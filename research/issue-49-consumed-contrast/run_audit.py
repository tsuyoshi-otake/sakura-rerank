"""Frozen source/contrast preparation and separately bound native acquisition."""
from collections import Counter, defaultdict
import hashlib
import json
import subprocess
import sys
import time

from sakura_rerank.data.annotation_contrast import boundary_observation, profile
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.consumed_source import unit_key, verify_consumption
from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from audit_common import (ROOT, PLAN, PLAN_COMMIT, BINDING, source, boundary, read_json, save, sha,
                          scope, identity, prior_evidence, write_rows, read_rows)

sys.path.insert(0, "research")
try:
    from reference_execution import execute_requests
finally:
    sys.path.pop(0)

CODE = ("src/sakura_rerank/data/annotation_contrast.py", "research/issue-49-consumed-contrast/audit_common.py",
        "research/issue-49-consumed-contrast/run_audit.py")


def prepare():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    plan, targets, components, receipts, units = scope()
    grouped = defaultdict(list)
    for row in targets:
        grouped[row["source_id"]].append(row)
    observations = {}
    _, sources, selection = source.source_identity()
    print(json.dumps(dict(stage="original_source_boundary_observations", rows=len(targets))), flush=True)
    for receipt in sources:
        work = selection[receipt["work_id"]]
        raw = source.read_work(receipt, work)
        if hashlib.sha256(raw).hexdigest() != receipt["decoded_sha256"]:
            raise ValueError("consumed_contrast_source_revision_changed")
        paragraphs, _ = paragraphs_with_ruby(raw)
        for row in grouped.get(work["work_id"], ()):
            pi = row["paragraph_index"]
            paragraph = paragraphs[pi]
            verified = verify_consumption(row, units[unit_key(row["source"])], paragraph,
                work_id=work["work_id"], author_id=work["author_id"], revision=receipt["decoded_sha256"],
                paragraph_index=pi, consumer="source_verification")
            if verified != receipts[row["stable_id"]]:
                raise ValueError("consumed_contrast_original_receipt_changed")
            observations[row["stable_id"]] = boundary_observation(row, paragraph["text"])
    if set(observations) != set(receipts):
        raise ValueError("consumed_contrast_source_observation_missing")
    source_profile, witnesses = profile(targets, components, observations)
    print(json.dumps(dict(stage="authenticate_existing_candidate_receipts", rows=len(targets))), flush=True)
    proof, reused_authentication = prior_evidence(targets)
    known, missing, requested = [], {}, {}
    for row in targets:
        request_id = row["candidate_request_id"]
        request = dict(stable_id=request_id, reading=row["reading"])
        requested[request_id] = request
        evidence = proof[(request_id, row["target"])]
        if evidence["status"] == "acquisition_missing":
            missing[request_id] = request
        else:
            known.append(dict(stable_id=row["stable_id"], evidence=evidence))
    if any(r["candidate_request_id"] in missing and proof[(r["candidate_request_id"], r["target"])]["status"] != "acquisition_missing" for r in targets):
        raise ValueError("consumed_contrast_partial_reading_reuse")
    artifacts = dict(observations=write_rows("boundary-observations", (observations[k] for k in sorted(observations))),
                     reused=write_rows("reused-evidence", sorted(known, key=lambda r: r["stable_id"])))
    save(ROOT / "source-witnesses.json", witnesses)
    artifacts["witnesses"] = dict(path="source-witnesses.json", sha256=sha(ROOT / "source-witnesses.json"))
    new = [missing[k] for k in sorted(missing)]
    write_once(ROOT / "new-requests.jsonl", b"".join(canonical_json_bytes(r)+b"\n" for r in new))
    blocked = len(new) > plan["native"]["max_new_requests"]
    result = dict(kind="consumed_contrast_preparation", status="native_budget_blocked" if blocked else "ready_for_bound_acquisition",
        source_profile=source_profile, original_provisional_targets=plan["population"]["original_provisional_targets"],
        original_annotation_slots=plan["population"]["original_annotation_slots"], verified_source_inputs=len(observations),
        unique_readings=len(requested), new_requests=len(new), reused_readings=len(requested)-len(new), reused_rows=len(known),
        artifacts=artifacts, requests_sha256=sha(ROOT / "new-requests.jsonl"), prior_candidate_authentication=reused_authentication,
        plan_commit=PLAN_COMMIT, plan_sha256=sha(PLAN), implementation={p: sha(p) for p in CODE}, preparation_commit=head,
        model_fits=0, model_inferences=0, final_test_used=False, gold_certified=False, training_labels_admitted=0)
    save(ROOT / "preparation.json", result)
    save("reports/issue-49-consumed-preparation-v1.json", result)
    if not blocked:
        bound = dict(kind="consumed_contrast_forward_binding", preparation_sha256=sha(ROOT / "preparation.json"),
            plan_sha256=sha(PLAN), requests_sha256=sha(ROOT / "new-requests.jsonl"), requests=len(new),
            identity_sha256=sha(boundary.IDENTITY), implementation={p: sha(p) for p in CODE},
            execution=dict(concurrency=2, request_timeout_seconds=30, total_timeout_seconds=900))
        save(ROOT / "forward-binding.json", bound)
        save(BINDING, bound)
    return {k: result[k] for k in ("status", "verified_source_inputs", "unique_readings", "new_requests", "reused_readings")}


def authenticate(commit):
    bound = json.loads(boundary.committed(BINDING, commit))
    if (bound != read_json(ROOT / "forward-binding.json") or sha(PLAN) != bound["plan_sha256"]
            or sha(ROOT / "preparation.json") != bound["preparation_sha256"]
            or sha(ROOT / "new-requests.jsonl") != bound["requests_sha256"]):
        raise ValueError("consumed_contrast_forward_binding_changed")
    for path, digest in bound["implementation"].items():
        if sha(path) != digest:
            raise ValueError("consumed_contrast_forward_code_changed")
    plan, targets, components, _, _ = scope()
    prepared = read_json(ROOT / "preparation.json")
    requests = [json.loads(line) for line in (ROOT / "new-requests.jsonl").read_bytes().splitlines()]
    if len(requests) != bound["requests"] or len(requests) > plan["native"]["max_new_requests"]:
        raise ValueError("consumed_contrast_request_bound")
    return bound, identity(), targets, components, prepared, requests


def execute(commit):
    bound, identity_value, targets, components, prepared, requests = authenticate(commit)
    execution, measured = execute_requests(requests, ROOT / "candidates", identity_value, boundary.BINARY, boundary.DICTIONARY,
        boundary.native.validate_result, concurrency=2, request_timeout=30, total_timeout=900,
        progress=lambda done, total: print(json.dumps(dict(stage="consumed_candidates", done=done, total=total)), flush=True))
    execution.update(binding_commit=commit, binding_sha256=sha(BINDING))
    save(ROOT / "forward-execution.json", execution)
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
    artifact = write_rows("candidate-evidence", sorted(evidence, key=lambda r: r["stable_id"]))
    save(ROOT / "supported-witnesses.json", witnesses)
    report = dict(kind="consumed_annotation_candidate_contrasts", status="complete" if not counts["acquisition_missing"] else "complete_with_unmeasured_targets",
        targets=len(targets), source_exact_presence={str(k): presence[str(k)] for k in (1,5,6,10,32)}, candidate_statuses=dict(counts),
        source_profile=prepared["source_profile"], candidate_supported_profile=supported_profile,
        original_provisional_targets=prepared["original_provisional_targets"], original_annotation_slots=prepared["original_annotation_slots"],
        unique_readings=prepared["unique_readings"], new_requests=prepared["new_requests"], reused_readings=prepared["reused_readings"],
        native_outcomes=dict(Counter(a["status"] for a in execution["attempts"])), not_attempted_requests=execution["not_attempted"],
        evidence=artifact, witnesses_sha256=sha(ROOT / "supported-witnesses.json"), execution_sha256=sha(ROOT / "forward-execution.json"),
        preparation_sha256=sha(ROOT / "preparation.json"), binding_sha256=sha(BINDING), binding_commit=commit,
        model_fits=0, model_inferences=0, final_test_used=False, gold_certified=False, training_labels_admitted=0, safety_threshold=.0025,
        interpretation="Conditional source-annotation reconstruction, not Gold or IME accuracy. Boundary flags do not reject or certify labels. Conservative quartets are witnessed lower bounds, not maximum semantic contrast capacity.")
    save(ROOT / "report.json", report)
    save("reports/issue-49-consumed-contrasts-v1.json", report)
    return {k: report[k] for k in ("status", "targets", "source_exact_presence", "candidate_statuses", "native_outcomes", "not_attempted_requests")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "execute"))
    parser.add_argument("--binding-commit")
    args = parser.parse_args()
    if args.stage == "execute" and not args.binding_commit:
        parser.error("execute requires a committed binding")
    ROOT.mkdir(parents=True, exist_ok=True)
    terminal = ROOT / (args.stage + "-execution.json")
    if terminal.exists():
        raise ValueError("consumed_contrast_stage_already_terminal")
    started = time.monotonic()
    try:
        output = prepare() if args.stage == "prepare" else execute(args.binding_commit)
    except Exception as error:
        save(terminal, dict(status="failed", error_type=type(error).__name__, elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(dict(status="failed", error_type=type(error).__name__)), flush=True)
        raise SystemExit(1) from None
    save(terminal, dict(status="complete", elapsed_seconds=round(time.monotonic()-started,3)))
    print(json.dumps(output), flush=True)
