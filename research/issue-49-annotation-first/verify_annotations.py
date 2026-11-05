"""Reproduce extraction and independently check every original target position."""
from collections import Counter
import hashlib
import json
import re

from sakura_rerank.data.annotation_first import extract_work
from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash, text_sha256
from annotation_common import (ROOT, authenticate, read_work, compressed_rows, history_and_original_train,
    read_json, rows, save, sha)
from prepare_annotations import verified_preparation


def verify_preparation():
    prep = verified_preparation()
    _, receipts, selection = authenticate()
    work_receipts = read_json(ROOT / "prepared/work-receipts.json")
    if sha(ROOT / "prepared/work-receipts.json") != prep["work_receipts_sha256"]:
        raise ValueError("annotation_work_receipts_changed")
    expected = {r["work_id"]: r for r in work_receipts}
    digests = {name: hashlib.sha256() for name in ("targets", "terminals", "coverage")}
    totals, terminals, types = Counter(), Counter(), Counter()
    checked = 0
    for receipt in receipts:
        work = selection[receipt["work_id"]]
        raw = read_work(receipt, work)
        target_rows, terminal_rows, coverage, _ = extract_work(raw, work["work_id"], work["author_id"], receipt["decoded_sha256"])
        if canonical_json_hash([target_rows, terminal_rows, coverage]) != expected[work["work_id"]]["content_sha256"]:
            raise ValueError("annotation_work_reproduction_differs")
        lines = raw.decode("cp932").splitlines()
        for row in target_rows:
            line = lines[row["source_line_number"]]
            stripped = line.strip()
            clean = re.sub(r"《[^《》]*》", "", stripped).replace("｜", "")
            start, end = row["paragraph_start"], row["paragraph_end"]
            annotations = list(re.finditer(r"《([^《》]*)》", stripped))
            match = annotations[row["annotation_index"]]
            prefix = re.sub(r"《[^《》]*》", "", stripped[:match.start()]).replace("｜", "")
            annotation = match.group(1)
            mapped = "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in annotation)
            identity = canonical_json_hash([row["source_id"], row["source_revision"], row["paragraph_index"],
                row["annotation_index"], start, end, row["target"], annotation])
            if (text_sha256(line) != row["source_line_sha256"] or text_sha256(clean) != row["source"]["paragraph_hash"]
                    or clean[start:end] != row["target"] or clean[max(0, start - 64):start] != row["left_context"]
                    or len(prefix) != end or annotation != row["raw_annotation_reading"] or mapped != row["reading"]
                    or "ruby-first-" + identity != row["stable_id"] or row["training_eligible"] is not False):
                raise ValueError("annotation_independent_position_or_reading_differs")
            checked += 1
            types[row["annotation_kind"]] += 1
        terminals.update(r["status"] for r in terminal_rows)
        for name, records in (("targets", target_rows), ("terminals", terminal_rows), ("coverage", coverage)):
            totals[name] += len(records)
            for row in records:
                digests[name].update(canonical_json_bytes(row) + b"\n")
    if (dict(totals) != prep["counts"] or dict(terminals) != prep["terminal_counts"]
            or {name: d.hexdigest() for name, d in digests.items()} != prep["content_sha256"]):
        raise ValueError("annotation_full_extraction_replay_differs")
    result = dict(kind="annotation_first_preparation_verification", status="passed", counts=dict(totals),
        independently_checked_source_positions_and_annotations=checked, annotation_types=dict(types),
        all_source_and_terminal_bytes_reproduced=True, preparation_sha256=sha(ROOT / "preparation.json"),
        script_sha256=sha(__file__), model_fits=0, gold_certified=False, final_test_used=False)
    save(ROOT / "preparation-verification.json", result)
    save("reports/issue-49-annotation-preparation-verification-v1.json", result)
    return result


def verify_isolation():
    verified_preparation()
    report = read_json(ROOT / "isolation.json")
    for name, expected in report["artifacts"].items():
        if sha(ROOT / "isolated" / name) != expected:
            raise ValueError("annotation_isolation_artifact_changed")
    historical, old_train, proof = history_and_original_train()
    if proof != report["historical"]:
        raise ValueError("annotation_verifier_history_differs")
    targets = list(compressed_rows(ROOT / "prepared/targets.jsonl.gz"))
    coverage = list(compressed_rows(ROOT / "prepared/coverage.jsonl.gz"))
    metadata = [dict(stable_id=r["stable_id"], population="train", source=r["source"],
                    input_hash=canonical_json_hash([r["left_context"], r["reading"]])) for r in targets]
    records = historical + old_train + coverage + metadata
    print(json.dumps(dict(stage="annotation_reverse_closure", nodes=len(records))), flush=True)
    excluded, components, audit = isolate_annotations(records[::-1])
    if (dict(excluded=excluded, components=components) != read_json(ROOT / "isolated/relations.json")
            or audit != report["audit"]):
        raise ValueError("annotation_reverse_closure_differs")
    expected = [dict(r, component_id=components[r["stable_id"]]) for r in targets if r["stable_id"] not in excluded]
    saved = list(compressed_rows(ROOT / "isolated/retained.jsonl.gz"))
    if expected != saved or len(expected) != report["retained_targets"]:
        raise ValueError("annotation_retained_population_differs")
    prior_admitted = {r["stable_id"] for r in rows("data/generated/issue-41-language-pretraining-v1/lm-admitted-fragments.jsonl")}
    newly_connected = sorted(prior_admitted & set(excluded))
    if newly_connected != read_json(ROOT / "isolated/newly-connected-old-train.json"):
        raise ValueError("annotation_old_train_delta_differs")
    result = dict(kind="annotation_source_isolation_verification", status="passed", nodes=len(records),
        reversed_full_relation_closure_equal=True, retained_targets=len(saved),
        previously_admitted_train_newly_connected=len(newly_connected),
        isolation_sha256=sha(ROOT / "isolation.json"), script_sha256=sha(__file__),
        model_fits=0, gold_certified=False, final_test_used=False)
    save(ROOT / "isolation-verification.json", result)
    save("reports/issue-49-annotation-isolation-verification-v1.json", result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "isolate"))
    stage = parser.parse_args().stage
    print(json.dumps(verify_preparation() if stage == "prepare" else verify_isolation()))
