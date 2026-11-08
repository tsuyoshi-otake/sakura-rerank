"""Check source bytes, literal annotation positions and every supplement link."""
from collections import Counter, defaultdict
import hashlib
import json
import re
import zipfile

from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.growth_corpus import SEED
from recover_ruby import ROOT, PLAN, SOURCE_ROOT, TRAIN_PATH, CAPACITY_ROOT, read_json, rows, save, sha


def run():
    report = read_json(ROOT / "report.json")
    plan = read_json(PLAN)
    if sha(PLAN) != report["plan_sha256"]:
        raise ValueError("ruby_verifier_plan_changed")
    for path, expected in {**plan["sources"], **report["implementation"]}.items():
        if sha(path) != expected:
            raise ValueError("ruby_verifier_source_changed")
    for name, expected in report["artifacts"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("ruby_verifier_artifact_changed")
    by_id = {r["stable_id"]: r for r in rows(TRAIN_PATH) if r["corpus"] == "aozora"}
    previous = read_json(CAPACITY_ROOT / "evidence-manifest.json")["last_record_sha256"]
    grouped, counts, observed_ids = defaultdict(list), Counter(), []
    for index, entry in enumerate(rows(ROOT / "evidence.jsonl")):
        digest = entry.pop("record_sha256")
        row = by_id[entry["stable_id"]]
        if (entry["index"] != index or entry["previous_record_sha256"] != previous
                or canonical_json_hash(entry) != digest or entry["source_row_sha256"] != canonical_json_hash(row)):
            raise ValueError("ruby_verifier_chain_differs")
        previous = digest
        observed_ids.append(entry["stable_id"])
        counts[entry["state"]] += 1
        grouped[row["source_id"]].append(entry)
    ledger = read_json(ROOT / "evidence-manifest.json")
    if (observed_ids != sorted(by_id) or len(observed_ids) != ledger["rows"]
            or previous != ledger["last_record_sha256"] or dict(counts) != report["states"]):
        raise ValueError("ruby_verifier_population_or_tail_differs")
    checked_spans = checked_readings = 0
    for receipt in read_json(ROOT / "source-receipts.json"):
        archive_path = SOURCE_ROOT / "aozora-download" / (receipt["work_id"] + ".zip")
        if sha(archive_path) != receipt["archive_sha256"]:
            raise ValueError("ruby_verifier_archive_changed")
        with zipfile.ZipFile(archive_path) as archive:
            raw = archive.read(archive.infolist()[0])
        if hashlib.sha256(raw).hexdigest() != receipt["decoded_sha256"]:
            raise ValueError("ruby_verifier_decoded_source_changed")
        lines = raw.decode("cp932").splitlines()
        for entry in grouped[receipt["work_id"]]:
            if entry["state"] == "span_not_recovered":
                continue
            row = by_id[entry["stable_id"]]
            source_line = lines[entry["source_line_number"]]
            clean = re.sub(r"《[^《》]*》", "", source_line.strip()).replace("｜", "")
            start, end = entry["paragraph_start"], entry["paragraph_end"]
            key = canonical_json_hash([SEED, "aozora", row["source_id"], row["source_revision"],
                entry["paragraph_index"], entry["sentence_index"], entry["sentence_start"], entry["sentence_end"], row["target"]])
            if (text_sha256(source_line) != entry["source_line_sha256"]
                    or text_sha256(clean) != row["source"]["paragraph_hash"]
                    or clean[start:end] != row["target"]
                    or clean[max(0, start - 64):start] != row["left_context"]
                    or "growth-" + key != entry["stable_id"]):
                raise ValueError("ruby_verifier_literal_source_position_differs")
            checked_spans += 1
            if entry["state"].startswith("exact_ruby_"):
                matches = []
                line = source_line.strip()
                for match in re.finditer(r"《([^《》]*)》", line):
                    prefix = line[:match.start()]
                    stripped_prefix = re.sub(r"《[^《》]*》", "", prefix).replace("｜", "")
                    if len(stripped_prefix) == end and prefix.endswith(row["target"]):
                        matches.append(match.group(1))
                if len(matches) != 1 or text_sha256(matches[0]) != entry["annotations"][0]["reading_sha256"]:
                    raise ValueError("ruby_verifier_literal_annotation_differs")
                annotation = matches[0]
                phonetic = "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in annotation)
                valid = (1 <= len(annotation) <= 32 and annotation not in ("ママ", "まま")
                         and all("ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヶ" or c == "ー" for c in annotation))
                expected = ("exact_ruby_reading_match" if phonetic == row["reading"] else "exact_ruby_reading_disagreement") if valid else "exact_ruby_nonphonetic_or_out_of_bounds"
                if entry["state"] != expected:
                    raise ValueError("ruby_verifier_reading_comparison_differs")
                checked_readings += 1
    if checked_spans != report["spans_recovered"]:
        raise ValueError("ruby_verifier_span_denominator_differs")
    result = dict(kind="ruby_evidence_verification", status="passed", rows=len(by_id),
        source_spans_independently_checked=checked_spans, exact_annotations_independently_checked=checked_readings,
        full_hash_chain_and_external_tail_checked=True, states=dict(counts),
        report_sha256=sha(ROOT / "report.json"), verifier_sha256=sha(__file__),
        gold_certified=False, final_test_used=False)
    save(ROOT / "verification.json", result)
    save("reports/issue-48-ruby-verification-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
