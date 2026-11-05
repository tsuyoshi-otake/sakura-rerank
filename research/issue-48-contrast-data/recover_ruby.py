"""Append original ruby/span evidence for admitted train rows, without relabeling."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import time
import zipfile

from sakura_rerank.data.aozora_ruby_evidence import recover_rows
from sakura_rerank.data.contrast_capacity import witnesses
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from audit_capacity import ROOT as CAPACITY_ROOT, LANGUAGE_ROOT, boundary, read_json, rows, save, sha

ROOT = CAPACITY_ROOT / "ruby-v1"
PLAN = Path("research/issue-48-contrast-data/ruby-plan-v1.json")
PLAN_COMMIT = "fd36ffca6865537b50d975a9387ddd2536a662a9"
SOURCE_ROOT = Path("data/generated/issue-33-data-growth-v1")
TRAIN_PATH = LANGUAGE_ROOT / "lm-admitted-fragments.jsonl"
IMPLEMENTATION = ("research/issue-48-contrast-data/recover_ruby.py", "src/sakura_rerank/data/aozora_ruby_evidence.py")


def write_supplement(records, parent_tail):
    destination, temporary = ROOT / "evidence.jsonl", ROOT / "evidence.pending"
    created = False
    previous = parent_tail
    try:
        with temporary.open("xb") as stream:
            created = True
            for index, item in enumerate(records):
                record = dict(item, index=index, previous_record_sha256=previous)
                previous = canonical_json_hash(record)
                record["record_sha256"] = previous
                stream.write(canonical_json_bytes(record) + b"\n")
        if destination.exists():
            if sha(destination) != sha(temporary):
                raise ValueError("ruby_immutable_supplement_differs")
        else:
            temporary.rename(destination)
        return dict(rows=len(records), sha256=sha(destination), parent_evidence_tail=parent_tail,
                    last_record_sha256=previous)
    finally:
        if created and temporary.exists():
            temporary.unlink()


def run():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in IMPLEMENTATION:
        boundary.committed(path, head)
    for path, expected in plan["sources"].items():
        if sha(path) != expected:
            raise ValueError("ruby_bound_source_changed")
    downloads = read_json(SOURCE_ROOT / "aozora-download/execution.json")
    old_binding = json.loads(boundary.committed("manifests/data-growth-source-reservations-v1.json", downloads["source_reservation_commit"]))
    if (downloads["status"] != "complete"
            or sha(SOURCE_ROOT / "aozora-selection.json") != old_binding["aozora_selection_sha256"]):
        raise ValueError("ruby_original_reservation_changed")
    origin_plan = json.loads(boundary.committed("research/issue-33-data-growth/plan-v1.json", old_binding["plan_commit"]))
    selected = [r for r in rows(TRAIN_PATH) if r["corpus"] == "aozora"]
    by_id = {r["stable_id"]: r for r in selected}
    works = defaultdict(list)
    for row in selected:
        if row["population"] != "train":
            raise ValueError("ruby_evaluation_row_forbidden")
        works[row["source_id"]].append(row)
    reserved = {r["work_id"]: r for r in read_json(SOURCE_ROOT / "aozora-selection.json")}
    if not 1 <= len(works) <= plan["bounds"]["works"]:
        raise ValueError("ruby_work_population_bound")
    evidence, source_receipts = [], []
    counts, parser_counts, total_bytes = Counter(), Counter(), 0
    for work_id in sorted(works):
        work = reserved[work_id]
        receipt_path = SOURCE_ROOT / "aozora-download" / (work_id + ".json")
        receipt = read_json(receipt_path)
        archive_path = receipt_path.with_suffix(".zip")
        if (work["partition"] != "train" or receipt["status"] != "downloaded"
                or any(receipt[k] != value for k, value in work.items())
                or archive_path.stat().st_size != receipt["bytes"] or sha(archive_path) != receipt["sha256"]):
            raise ValueError("ruby_work_receipt_or_partition_changed")
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if (len(entries) != 1 or entries[0].is_dir() or not entries[0].filename.endswith(".txt")
                    or entries[0].file_size > plan["bounds"]["decoded_bytes_per_work"]):
                raise ValueError("ruby_archive_contract_differs")
            raw = archive.read(entries[0])
        if len(works[work_id]) > origin_plan["aozora"]["max_targets_per_work"]:
            raise ValueError("ruby_original_target_bound_changed")
        recovered, parsed = recover_rows(raw, works[work_id])
        if recovered != recover_rows(raw, works[work_id][::-1])[0]:
            raise ValueError("ruby_source_order_replay_differs")
        evidence.extend(recovered)
        counts.update(r["state"] for r in recovered)
        parser_counts.update(parsed["ruby_counts"])
        total_bytes += len(raw)
        source_receipts.append(dict(work_id=work_id, target_rows=len(recovered), decoded_bytes=len(raw),
            decoded_sha256=hashlib.sha256(raw).hexdigest(), archive_sha256=sha(archive_path),
            acquisition_receipt_sha256=sha(receipt_path), paragraph_count=parsed["paragraphs"]))
    evidence.sort(key=lambda r: r["stable_id"])
    if len(evidence) != len(selected) or set(r["stable_id"] for r in evidence) != set(by_id):
        raise ValueError("ruby_target_denominator_differs")
    # All candidates were already authenticated in the parent feasibility unit.
    candidate_supported = set()
    for item in rows(CAPACITY_ROOT / "evidence.jsonl"):
        if item["candidate"]["eligible"]:
            candidate_supported.add(item["stable_id"])
    matched_ids = {r["stable_id"] for r in evidence if r["state"] == "exact_ruby_reading_match"}
    supported_ids = matched_ids & candidate_supported
    components = read_json(LANGUAGE_ROOT / "lm-source-relations.json")["components"]
    original_history = read_json(CAPACITY_ROOT / "history-replay.json")
    if sha(LANGUAGE_ROOT / "lm-source-relations.json") != original_history["relation_sha256"]:
        raise ValueError("ruby_component_binding_changed")
    supported_rows = [by_id[s] for s in sorted(supported_ids)]
    groups, group_counts = witnesses(supported_rows, components, independent_components=True)
    selection = read_json(CAPACITY_ROOT / "selection-identities.json")
    if sha(CAPACITY_ROOT / "selection-identities.json") != read_json(CAPACITY_ROOT / "report.json")["artifacts"]["selection-identities.json"]:
        raise ValueError("ruby_parent_selection_changed")
    reserved_ids = {s for group in selection["reserved_quartets"] for s in group["stable_ids"]}
    reserved_states = Counter(r["state"] for r in evidence if r["stable_id"] in reserved_ids)
    parent = read_json(CAPACITY_ROOT / "evidence-manifest.json")
    supplement = write_supplement(evidence, parent["last_record_sha256"])
    save(ROOT / "evidence-manifest.json", supplement)
    save(ROOT / "source-receipts.json", source_receipts)
    save(ROOT / "annotation-matching-quartets.json", groups)
    result = dict(kind="original_ruby_evidence_recovery", status="complete_quality_unresolved", rows=len(selected),
        works=len(works), decoded_source_bytes=total_bytes, states=dict(counts),
        spans_recovered=len(evidence) - counts["span_not_recovered"],
        reading_matched_rows=len(matched_ids), reading_matched_candidate_supported_rows=len(supported_ids),
        annotation_matching_four_component_quartets=len(groups), quartet_selector_counts=group_counts,
        reserved_contrast_aozora_rows=sum(reserved_states.values()), reserved_contrast_states=dict(reserved_states),
        reserved_contrast_whole_quartets_with_all_four_readings_supported=sum(
            set(g["stable_ids"]) <= supported_ids for g in selection["reserved_quartets"]),
        parser_counts=dict(parser_counts), exact_frozen_cleaner_parity=True, all_rows_reverse_replayed=True,
        plan_commit=PLAN_COMMIT, plan_sha256=sha(PLAN), execution_commit=head,
        implementation={p: sha(p) for p in IMPLEMENTATION},
        artifacts={name: sha(ROOT / name) for name in ("evidence.jsonl", "evidence-manifest.json", "source-receipts.json", "annotation-matching-quartets.json")},
        parent_report_sha256=sha(CAPACITY_ROOT / "report.json"), model_fits=0, model_inferences=0,
        original_data_mutations=0, evaluation_source_files_read=0, gold_certified=False, final_test_used=False,
        unresolved_axes=["ime_input_boundary", "meaning_and_usage", "orthographic_intent"],
        interpretation="Exact recovered source scope and original kana annotation agreement only; disagreements are evidence conflicts, and partial ruby is never assigned to target substrings.")
    save(ROOT / "report.json", result)
    save("reports/issue-48-ruby-evidence-v1.json", result)
    return {k: result[k] for k in ("status", "rows", "works", "spans_recovered", "states", "reading_matched_candidate_supported_rows",
        "annotation_matching_four_component_quartets", "reserved_contrast_aozora_rows", "reserved_contrast_states",
        "reserved_contrast_whole_quartets_with_all_four_readings_supported")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", choices=("initial", "replay"), required=True)
    attempt = parser.parse_args().attempt
    ROOT.mkdir(exist_ok=True)
    receipt_path = ROOT / ("execution-" + attempt + ".json")
    if receipt_path.exists():
        raise SystemExit("immutable_ruby_execution_already_exists")
    started = time.monotonic()
    try:
        summary = run()
    except Exception as error:
        receipt = dict(status="failed", error_type=type(error).__name__, elapsed_seconds=round(time.monotonic() - started, 3))
        save(receipt_path, receipt)
        print(json.dumps(receipt))
        raise SystemExit(1) from None
    else:
        save(receipt_path, dict(status="complete", report_sha256=sha(ROOT / "report.json"),
                               elapsed_seconds=round(time.monotonic() - started, 3)))
        print(json.dumps(summary))
