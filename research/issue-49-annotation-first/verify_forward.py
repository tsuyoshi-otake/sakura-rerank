"""Independent source-presence recount from authenticated native snapshots."""
from collections import Counter
import json

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.reference_probe import validate_probe_records
from annotation_common import ROOT, TRAIN_ROOT, boundary, read_json, rows, save, sha
from forward_annotations import authenticate, BINDING

BINDING_COMMIT = "c715fa1a6006208effcdaaac50395cb7e68c5b18"


def run():
    bound, identity, selected = authenticate(BINDING_COMMIT)
    execution = read_json(ROOT / "forward-execution.json")
    report = read_json(ROOT / "candidate-report.json")
    if (sha(ROOT / "forward-execution.json") != report["execution_sha256"]
            or sha(ROOT / "candidate-evidence.json") != report["evidence_sha256"]):
        raise ValueError("annotation_forward_evidence_changed")
    reused = read_json(ROOT / "reused-evidence.json")
    wanted = {r["candidate_request_id"] for r in reused}
    prior_plan = json.loads(boundary.committed("research/issue-48-contrast-data/plan-v2.json", "986f77208b4cabf5b308fb114602cf15faf2a380"))
    prior = read_json(TRAIN_ROOT / "candidates/execution.json")
    if sha(TRAIN_ROOT / "candidates/execution.json") != prior_plan["candidate_receipt"]["sha256"]:
        raise ValueError("annotation_prior_receipt_changed")
    original_binding = json.loads(boundary.committed("manifests/data-growth-input-reservations-v2.json", prior["input_commit"]))
    if sha(TRAIN_ROOT / "isolation/requests.jsonl") != original_binding["requests_sha256"]:
        raise ValueError("annotation_prior_requests_changed")
    original_requests = list(rows(TRAIN_ROOT / "isolation/requests.jsonl"))
    snapshots = {}
    for offset in range(0, len(original_requests), 100):
        batch = original_requests[offset:offset + 100]
        if not wanted & {r["stable_id"] for r in batch}:
            continue
        directory = TRAIN_ROOT / "candidates" / f"batch-{offset // 100:05d}"
        if sha(directory / "execution.json") != prior["batches"][offset // 100]["execution_sha256"]:
            raise ValueError("annotation_prior_batch_changed")
        receipt = read_json(directory / "execution.json")
        if receipt["status"] != "complete" or sha(directory / "output.jsonl") != receipt["output_sha256"]:
            raise ValueError("annotation_prior_snapshot_changed")
        for record in validate_probe_records((directory / "output.jsonl").read_bytes(), batch, identity):
            if record["stable_id"] in wanted:
                snapshots[record["stable_id"]] = record
    if set(snapshots) != wanted:
        raise ValueError("annotation_reuse_coverage_differs")
    requests = list(rows(ROOT / "new-requests.jsonl"))
    attempts = {a["index"]: a for a in execution["attempts"]}
    if len(attempts) != len(execution["attempts"]) or len(attempts) + execution["not_attempted"] != len(requests):
        raise ValueError("annotation_native_terminal_accounting")
    for index, attempt in attempts.items():
        if attempt["status"] != "complete":
            continue
        directory = ROOT / "candidates" / f"request-{index:04d}"
        if sha(directory / "execution.json") != attempt["execution_sha256"]:
            raise ValueError("annotation_new_receipt_changed")
        receipt = read_json(directory / "execution.json")
        raw = canonical_json_bytes(requests[index]) + b"\n"
        if ((directory / "input.jsonl").read_bytes() != raw
                or sha(directory / "output.jsonl") != receipt["output_sha256"]):
            raise ValueError("annotation_new_snapshot_changed")
        native = boundary.native.validate_result(directory, raw, identity)[0]
        snapshots[native["stable_id"]] = native
    evidence = {r["stable_id"]: r["evidence"] for r in read_json(ROOT / "candidate-evidence.json")}
    counts, supported = Counter(), set()
    missing = 0
    for row in selected:
        snapshot = snapshots.get(row["candidate_request_id"])
        if snapshot is None:
            missing += 1
            observed = {str(k): False for k in (1, 5, 6, 10, 32)}
            eligible = False
        else:
            candidates = snapshot["candidate_snapshots"]["training_top32"]["candidates"]
            observed = {str(k): row["target"] in [c["surface"] for c in candidates[:k]] for k in (1, 5, 6, 10, 32)}
            positive = [c for c in candidates[:6] if c["surface"] == row["target"]]
            eligible = (len(candidates[:6]) >= 2 and len(positive) == 1
                and all(s["source_category"] == "system_dictionary" for s in positive[0]["segments"])
                and all(len(c["surface"]) <= 32 for c in candidates[:6]) and len(row["target"]) <= 32)
        if observed != evidence[row["stable_id"]]["presence"] or eligible != evidence[row["stable_id"]]["eligible"]:
            raise ValueError("annotation_independent_candidate_recount_differs")
        counts.update(k for k, yes in observed.items() if yes)
        if eligible:
            supported.add(row["stable_id"])
    if (dict(counts) != report["source_exact_presence"] or len(supported) != report["supported_rows"]
            or len(selected) != report["forwarded_denominator"] or missing != report["candidate_statuses"].get("acquisition_missing", 0)):
        raise ValueError("annotation_candidate_denominator_differs")
    result = dict(kind="annotation_forward_verification", status="passed", target_rows=len(selected),
        native_snapshots_reauthenticated=len(snapshots), source_presence_recount=dict(counts),
        supported_rows=len(supported), failed_or_unmeasured_target_rows=missing,
        original_slots=report["full_annotation_slots"], report_sha256=sha(ROOT / "candidate-report.json"),
        binding_sha256=sha(BINDING), script_sha256=sha(__file__), model_fits=0, gold_certified=False, final_test_used=False)
    save(ROOT / "candidate-verification.json", result)
    save("reports/issue-49-annotation-candidate-verification-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
