"""Version-2 operational binding; source and label policy remain version 1."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import time

from sakura_rerank.data.annotation_contrast import profile
from sakura_rerank.data.contrast_capacity import candidate_evidence
from audit_common import ROOT as PREPARED, boundary, read_json, save, sha, scope, identity, read_rows
from batch_execution import execute_batches

ROOT = PREPARED / "batched-forward-v2"
PLAN = Path("research/issue-49-consumed-contrast/plan-v2.json")
PLAN_COMMIT = "9a684fb2c5ac82dea9be1f1db8b6283344ec22e2"
BINDING = Path("manifests/consumed-contrast-forward-v2.json")
CODE = ("research/issue-49-consumed-contrast/batch_execution.py", "research/issue-49-consumed-contrast/forward_batches.py")


def inputs():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, digest in plan["inputs"].items():
        if sha(path) != digest:
            raise ValueError("consumed_batch_bound_input_changed")
    _, targets, components, _, _ = scope()
    prepared = read_json(PREPARED / "preparation.json")
    requests = [json.loads(line) for line in (PREPARED / "new-requests.jsonl").read_bytes().splitlines()]
    if (len(requests) != plan["population"]["new_readings"] or len(targets) != plan["population"]["targets"]
            or requests != sorted(requests, key=lambda r: r["stable_id"])):
        raise ValueError("consumed_batch_complete_population_changed")
    return targets, components, prepared, requests


def prepare():
    targets, _, _, requests = inputs()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    bound = dict(kind="consumed_contrast_batched_binding", targets=len(targets), requests=len(requests),
        batches=(len(requests)+99)//100, requests_sha256=sha(PREPARED / "new-requests.jsonl"),
        preparation_sha256=sha(PREPARED / "preparation.json"), plan_sha256=sha(PLAN), plan_commit=PLAN_COMMIT,
        identity_sha256=sha(boundary.IDENTITY), implementation={p: sha(p) for p in CODE}, preparation_commit=head,
        batch_size=100, concurrency=1, batch_timeout_seconds=30, total_timeout_seconds=900, retries=0)
    ROOT.mkdir(exist_ok=False)
    save(ROOT / "binding.json", bound)
    save(BINDING, bound)
    return {k: bound[k] for k in ("targets", "requests", "batches", "concurrency", "total_timeout_seconds")}


def authenticate(commit):
    bound = json.loads(boundary.committed(BINDING, commit))
    if (bound != read_json(ROOT / "binding.json") or sha(PLAN) != bound["plan_sha256"]
            or sha(PREPARED / "preparation.json") != bound["preparation_sha256"]
            or sha(PREPARED / "new-requests.jsonl") != bound["requests_sha256"]
            or sha(boundary.IDENTITY) != bound["identity_sha256"]):
        raise ValueError("consumed_batch_binding_changed")
    for path, digest in bound["implementation"].items():
        if sha(path) != digest:
            raise ValueError("consumed_batch_code_changed")
    targets, components, prepared, requests = inputs()
    if len(requests) != bound["requests"] or len(targets) != bound["targets"]:
        raise ValueError("consumed_batch_binding_population_changed")
    return bound, identity(), targets, components, prepared, requests


def execute(commit):
    bound, identity_value, targets, components, prepared, requests = authenticate(commit)
    execution, measured = execute_batches(requests, ROOT / "candidates", identity_value, boundary.BINARY, boundary.DICTIONARY,
        boundary.native.validate_result, total_timeout=bound["total_timeout_seconds"],
        progress=lambda done, total: print(json.dumps(dict(stage="consumed_candidate_batches", done=done, total=total)), flush=True))
    execution.update(binding_commit=commit, binding_sha256=sha(BINDING))
    save(ROOT / "execution.json", execution)
    authenticate(commit)
    known = {r["stable_id"]: r["evidence"] for r in read_rows(prepared["artifacts"]["reused"])}
    observations = {r["stable_id"]: r for r in read_rows(prepared["artifacts"]["observations"])}
    evidence, counts, presence, supported = [], Counter(), Counter(), []
    for row in targets:
        observed = known.get(row["stable_id"])
        if observed is None:
            observed = candidate_evidence(row["target"], measured.get(row["candidate_request_id"]))
        evidence.append(dict(stable_id=row["stable_id"], candidate_request_id=row["candidate_request_id"], evidence=observed))
        counts[observed["status"]] += 1
        presence.update(k for k, found in observed["presence"].items() if found)
        if observed["eligible"]:
            supported.append(row)
    supported_profile, witnesses = profile(supported, components, observations)
    save(ROOT / "candidate-evidence.json", sorted(evidence, key=lambda r: r["stable_id"]))
    save(ROOT / "supported-witnesses.json", witnesses)
    report = dict(kind="consumed_annotation_candidate_contrasts", status="complete" if not counts["acquisition_missing"] else "complete_with_unmeasured_targets",
        targets=len(targets), source_exact_presence={str(k): presence[str(k)] for k in (1,5,6,10,32)}, candidate_statuses=dict(counts),
        source_profile=prepared["source_profile"], candidate_supported_profile=supported_profile,
        original_provisional_targets=prepared["original_provisional_targets"], original_annotation_slots=prepared["original_annotation_slots"],
        unique_readings=prepared["unique_readings"], new_requests=prepared["new_requests"], reused_readings=prepared["reused_readings"],
        native_request_outcomes=execution["request_outcomes"], native_batch_outcomes=dict(Counter(a["status"] for a in execution["attempts"])),
        not_attempted_requests=execution["not_attempted"], evidence_sha256=sha(ROOT / "candidate-evidence.json"),
        witnesses_sha256=sha(ROOT / "supported-witnesses.json"), execution_sha256=sha(ROOT / "execution.json"),
        preparation_sha256=sha(PREPARED / "preparation.json"), binding_sha256=sha(BINDING), binding_commit=commit,
        model_fits=0, model_inferences=0, final_test_used=False, gold_certified=False, training_labels_admitted=0, safety_threshold=.0025,
        interpretation="Conditional source-annotation reconstruction, not Gold or IME accuracy. Boundary flags never reject or certify labels. Conservative quartets are lower bounds, not maximum semantic contrast capacity.")
    save(ROOT / "report.json", report)
    save("reports/issue-49-consumed-contrasts-v2.json", report)
    return {k: report[k] for k in ("status", "targets", "source_exact_presence", "candidate_statuses", "native_request_outcomes", "not_attempted_requests")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "execute"))
    parser.add_argument("--binding-commit")
    args = parser.parse_args()
    if args.stage == "execute" and not args.binding_commit:
        parser.error("execute requires a committed binding")
    if args.stage == "prepare":
        print(json.dumps(prepare()))
    else:
        terminal = ROOT / "stage-execution.json"
        if terminal.exists():
            raise ValueError("consumed_batch_stage_already_terminal")
        started = time.monotonic()
        try:
            result = execute(args.binding_commit)
        except Exception as error:
            save(terminal, dict(status="failed", error_type=type(error).__name__, elapsed_seconds=round(time.monotonic()-started,3)))
            print(json.dumps(dict(status="failed", error_type=type(error).__name__)), flush=True)
            raise SystemExit(1) from None
        save(terminal, dict(status="complete", elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(result))
