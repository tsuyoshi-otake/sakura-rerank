"""Read only the proven source scope and reauthenticate candidate bytes."""
import json
from pathlib import Path
import sys

sys.path.insert(0,"research/issue-49-consumed-contrast")
try:
    import audit_common as origin
    import forward_batches as forward
    import verify_audit as candidate_verifier
finally:
    sys.path.pop(0)

ROOT=Path("data/generated/issue-33-consumed-numeric-v1")
PLAN=Path("research/issue-33-consumed-numeric/plan-v1.json")
POLICY=Path("research/issue-33-consumed-numeric/weak-teacher-policy-v1.md")
PLAN_COMMIT="049622b96da83a4007714ad7acf372ce5ae849f6"
boundary,read_json,save,sha=origin.boundary,origin.read_json,origin.save,origin.sha


def load_inputs():
    plan=json.loads(boundary.committed(PLAN,PLAN_COMMIT))
    boundary.committed(POLICY,PLAN_COMMIT)
    for path,digest in plan["inputs"].items():
        if sha(path)!=digest:
            raise ValueError("consumed_numeric_bound_input_changed")
    execution=read_json(forward.ROOT/"execution.json")
    _,identity,targets,components,_,requests=forward.authenticate(execution["binding_commit"])
    report=read_json(forward.ROOT/"report.json")
    verification=read_json(forward.ROOT/"verification.json")
    if (verification["status"]!="passed" or verification["report_sha256"]!=sha(forward.ROOT/"report.json")
            or verification["script_sha256"]!=sha("research/issue-49-consumed-contrast/verify_audit.py")):
        raise ValueError("consumed_numeric_upstream_verification_missing")
    evidence=read_json(forward.ROOT/"candidate-evidence.json")
    if sha(forward.ROOT/"candidate-evidence.json")!=report["evidence_sha256"]:
        raise ValueError("consumed_numeric_candidate_evidence_changed")
    supported={r["stable_id"] for r in evidence if r["evidence"]["eligible"]}
    if (len(evidence)!=len(targets) or {r["stable_id"] for r in evidence}!={r["stable_id"] for r in targets}
            or len(supported)!=plan["population"]["candidate_supported"]):
        raise ValueError("consumed_numeric_upstream_denominator_differs")
    selected=sorted((r for r in targets if r["stable_id"] in supported),key=lambda r:r["stable_id"])
    print(json.dumps(dict(stage="authenticate_numeric_source_candidates",rows=len(selected),source_scope=len(targets))),flush=True)
    snapshots=candidate_verifier.snapshots(targets,identity,execution,requests)
    wanted={r["candidate_request_id"] for r in selected}
    snapshots={key:value for key,value in snapshots.items() if key in wanted}
    if set(snapshots)!=wanted:
        raise ValueError("consumed_numeric_snapshot_coverage_missing")
    source_report=read_json(origin.source.ROOT/"report.json")
    receipts={r["stable_id"]:r for r in origin.source.read_rows(source_report["artifacts"]["consumption"]) if r["stable_id"] in supported}
    if set(receipts)!=supported or {r["stable_id"] for r in selected}!=supported:
        raise ValueError("consumed_numeric_origin_coverage_missing")
    return plan,selected,{key:components[key] for key in supported},receipts,snapshots
