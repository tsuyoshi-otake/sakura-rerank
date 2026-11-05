"""Bound and measure full-reading candidates only after source isolation."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from sakura_rerank.data.contrast_capacity import candidate_evidence, witnesses
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import authenticate_identity
from annotation_common import ROOT, PLAN, boundary, read_json, compressed_rows, save, sha

sys.path.insert(0, "research/issue-48-contrast-data")
try:
    from audit_capacity import authenticate_candidates
finally:
    sys.path.pop(0)
sys.path.insert(0, "research")
try:
    from reference_execution import execute_requests
finally:
    sys.path.pop(0)

BINDING = Path("manifests/annotation-first-forward-v1.json")
CODE = ("research/issue-49-annotation-first/forward_annotations.py", "research/reference_execution.py",
        "research/issue-48-contrast-data/audit_capacity.py", "src/sakura_rerank/data/contrast_capacity.py",
        "src/sakura_rerank/data/reference_probe.py", "research/issue-31-quality/run_reference_probe.py")


def targets():
    isolation = read_json(ROOT / "isolation.json")
    for name, expected in isolation["artifacts"].items():
        if sha(ROOT / "isolated" / name) != expected:
            raise ValueError("annotation_forward_isolation_changed")
    result = list(compressed_rows(ROOT / "isolated/retained.jsonl.gz"))
    if len(result) != isolation["retained_targets"]:
        raise ValueError("annotation_forward_target_count_differs")
    return [dict(r, candidate_request_id="growth-reading-" + canonical_json_hash(r["reading"])) for r in result]


def prepare():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    selected = targets()
    verification = read_json(ROOT / "isolation-verification.json")
    if verification["status"] != "passed" or verification["isolation_sha256"] != sha(ROOT / "isolation.json"):
        raise ValueError("annotation_verified_isolation_required")
    prior_plan = json.loads(boundary.committed("research/issue-48-contrast-data/plan-v2.json",
                                              "986f77208b4cabf5b308fb114602cf15faf2a380"))
    proof, authentication = authenticate_candidates(selected, prior_plan)
    if authentication.get("failed_requests", 0):
        raise ValueError("annotation_prior_failure_is_not_new_request")
    known, requested, unknown = [], {}, {}
    for row in selected:
        request_id = row["candidate_request_id"]
        requested[request_id] = dict(stable_id=request_id, reading=row["reading"])
        observed = proof[(request_id, row["target"])]
        if observed["status"] == "acquisition_missing":
            unknown[request_id] = requested[request_id]
        else:
            known.append(dict(stable_id=row["stable_id"], candidate_request_id=request_id, evidence=observed))
    new = [unknown[k] for k in sorted(unknown)]
    if len(new) > read_json(PLAN)["bounds"]["native_new_requests"]:
        raise ValueError("annotation_new_request_budget_exceeded")
    if any(r["candidate_request_id"] in unknown for r in known):
        raise ValueError("annotation_reading_reuse_inconsistent")
    save(ROOT / "reused-evidence.json", known)
    write_once(ROOT / "new-requests.jsonl", b"".join(canonical_json_bytes(r) + b"\n" for r in new))
    bound = dict(kind="annotation_first_forward_binding", targets=len(selected), unique_readings=len(requested),
        new_requests=len(new), reused_readings=len(requested) - len(new), reused_target_rows=len(known),
        isolation_sha256=sha(ROOT / "isolation.json"), plan_sha256=sha(PLAN),
        artifacts={name: sha(ROOT / name) for name in ("reused-evidence.json", "new-requests.jsonl")},
        identity_sha256=sha(boundary.IDENTITY), implementation={p: sha(p) for p in CODE},
        prior_candidate_authentication=authentication, execution=dict(concurrency=2, request_timeout_seconds=30, total_timeout_seconds=900),
        preparation_commit=head, model_fits=0, gold_certified=False, final_test_used=False)
    save(ROOT / "forward-binding.json", bound)
    save(BINDING, bound)
    return {k: bound[k] for k in ("targets", "unique_readings", "new_requests", "reused_readings", "reused_target_rows")}


def authenticate(commit):
    bound = json.loads(boundary.committed(BINDING, commit))
    if bound != read_json(ROOT / "forward-binding.json") or bound["isolation_sha256"] != sha(ROOT / "isolation.json"):
        raise ValueError("annotation_forward_binding_changed")
    for name, expected in bound["artifacts"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("annotation_forward_input_changed")
    for path, expected in bound["implementation"].items():
        if sha(path) != expected:
            raise ValueError("annotation_forward_code_changed")
    identity = authenticate_identity(boundary.IDENTITY, bound["identity_sha256"], boundary.BINARY, boundary.DICTIONARY)
    selected = targets()
    if len(selected) != bound["targets"]:
        raise ValueError("annotation_forward_population_changed")
    return bound, identity, selected


def summarize(bound, selected, measured, execution):
    known = {r["stable_id"]: r["evidence"] for r in read_json(ROOT / "reused-evidence.json")}
    evidence, counts, presence = [], Counter(), Counter()
    for row in selected:
        observed = known.get(row["stable_id"])
        if observed is None:
            observed = candidate_evidence(row["target"], measured.get(row["candidate_request_id"]))
        evidence.append(dict(stable_id=row["stable_id"], candidate_request_id=row["candidate_request_id"], evidence=observed))
        counts[observed["status"]] += 1
        presence.update(k for k, found in observed["presence"].items() if found)
    supported = {r["stable_id"] for r in evidence if r["evidence"]["eligible"]}
    components = {r["stable_id"]: r["component_id"] for r in selected}
    groups, selector = witnesses([r for r in selected if r["stable_id"] in supported], components, independent_components=True)
    save(ROOT / "candidate-evidence.json", evidence)
    save(ROOT / "candidate-supported-quartets.json", groups)
    result = dict(kind="annotation_first_full_reading_candidates", status="complete" if not counts["acquisition_missing"] else "complete_with_unmeasured_targets",
        forwarded_denominator=len(selected), source_exact_presence=dict(presence), candidate_statuses=dict(counts),
        supported_rows=len(supported), supported_four_component_quartets=len(groups), quartet_selector_counts=selector,
        source_works=len({r["source_id"] for r in selected}), source_authors=len({r["author_id"] for r in selected}),
        source_components=len(set(components.values())), unique_readings=bound["unique_readings"],
        new_requests=bound["new_requests"], reused_readings=bound["reused_readings"],
        native_outcomes=dict(Counter(a["status"] for a in execution["attempts"])), not_attempted_requests=execution["not_attempted"],
        binding_sha256=sha(BINDING), execution_sha256=sha(ROOT / "forward-execution.json"),
        evidence_sha256=sha(ROOT / "candidate-evidence.json"), quartet_sha256=sha(ROOT / "candidate-supported-quartets.json"),
        full_annotation_slots=read_json(ROOT / "isolation.json")["annotation_slots"],
        fit_status="insufficient_fixed_source_budget_and_unresolved_quality" if len(supported) < 25000 else "requires_separate_quality_and_fit_plan",
        model_fits=0, gold_certified=False, final_test_used=False, safety_threshold=.0025,
        interpretation="Conditional source-exact candidate presence among history-isolated original-annotation targets, not Gold accuracy. All earlier extraction/isolation exclusions remain in separate full-population counts.")
    save(ROOT / "candidate-report.json", result)
    save("reports/issue-49-annotation-candidates-v1.json", result)
    return result


def execute(commit):
    bound, identity, selected = authenticate(commit)
    requests = [json.loads(line) for line in (ROOT / "new-requests.jsonl").read_bytes().splitlines()]
    execution, measured = execute_requests(requests, ROOT / "candidates", identity, boundary.BINARY, boundary.DICTIONARY,
        boundary.native.validate_result, concurrency=2, request_timeout=30, total_timeout=900,
        progress=lambda done, total: print(json.dumps(dict(stage="annotation_candidates", done=done, total=total)), flush=True))
    execution.update(binding_commit=commit, binding_sha256=sha(BINDING))
    save(ROOT / "forward-execution.json", execution)
    authenticate(commit)
    return summarize(bound, selected, measured, execution)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "execute"))
    parser.add_argument("--binding-commit")
    args = parser.parse_args()
    if args.stage == "execute" and not args.binding_commit:
        parser.error("execute requires a frozen binding commit")
    print(json.dumps(prepare() if args.stage == "prepare" else execute(args.binding_commit)))
