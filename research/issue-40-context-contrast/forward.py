"""Bind and measure the fixed cohort; numerical arrays remain research-only."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.growth_numeric import encode
from sakura_rerank.data.input_boundary import request_id
from sakura_rerank.data.kwdlc_probe import write_once
from acquire import ROOT,sha
from feasibility import boundary

PLAN=Path("research/issue-40-context-contrast/forward_plan.json")
BINDING=Path("manifests/context-contrast-forward-v1.json")
COHORT=Path("manifests/context-contrast-cohort-v1.json")


def prepare():
    plan=json.loads(PLAN.read_bytes())
    if sha(COHORT)!=plan["cohort_binding_sha256"]:raise ValueError("cohort_changed_before_forward")
    verification=json.loads((ROOT/"verification.json").read_bytes())
    if verification["status"]!="pass" or verification["cohort_binding_sha256"]!=sha(COHORT):raise ValueError("cohort_verification_required")
    cohort=json.loads(COHORT.read_bytes())
    if sha(ROOT/"selected.jsonl")!=cohort["artifacts"]["selected"]:raise ValueError("selected_targets_changed")
    boundary.authenticate_input(plan["prior_boundary_input_commit"])
    known={json.loads(line)["stable_id"] for line in (boundary.ROOT/"requests.jsonl").read_bytes().splitlines()}
    targets=[dict(json.loads(line)) for line in (ROOT/"selected.jsonl").read_bytes().splitlines()]
    requests={}
    for row in targets:
        key=request_id(row["reading"])
        row.update(candidate_request_id=key,component_id=row["source_component"],corpus="kwdlc")
        requests[key]=dict(stable_id=key,reading=row["reading"])
    requests=[requests[key] for key in sorted(requests)]
    new=[row for row in requests if row["stable_id"] not in known]
    for name,rows in (("forward-targets",targets),("requests",requests),("new-requests",new)):
        write_once(ROOT/(name+".jsonl"),boundary.jsonl(rows))
    code=("research/reference_execution.py","research/issue-40-context-contrast/forward.py",
          "src/sakura_rerank/data/growth_numeric.py","src/sakura_rerank/research_tiny.py")
    result=dict(kind="context_contrast_forward_binding",plan_sha256=sha(PLAN),cohort_binding_sha256=sha(COHORT),
        verification_sha256=sha(ROOT/"verification.json"),targets=len(targets),requests=len(requests),
        new_requests=len(new),reused_requests=len(requests)-len(new),
        artifacts={name:sha(ROOT/(name+".jsonl")) for name in ("forward-targets","requests","new-requests")},
        code={path:sha(path) for path in code},model_predictions=0,model_fits=0,gold_certified=False)
    for path in (ROOT/"forward-binding.json",BINDING):write_once(path,canonical_json_bytes(result)+b"\n")
    return result


def authenticate(commit):
    bound=json.loads(boundary.committed(BINDING,commit))
    boundary.committed(PLAN,commit)
    if sha(COHORT)!=bound["cohort_binding_sha256"] or sha(PLAN)!=bound["plan_sha256"]:raise ValueError("forward_plan_or_cohort_changed")
    for name,expected in bound["artifacts"].items():
        if sha(ROOT/(name+".jsonl"))!=expected:raise ValueError("forward_input_changed")
    for path,expected in bound["code"].items():
        if sha(path)!=expected:raise ValueError("forward_code_changed")
    return bound


def previous_snapshots(identity):
    # Revalidate all prior boundary evidence without rerunning its converter.
    report=json.loads(boundary.committed("reports/issue-31-input-boundary-v1.json","189064cef30cf708ceea169d6bcdefea6e517bbb"))
    previous=boundary.ROOT/"isolated-r2"
    if sha(previous/"execution.json")!=report["artifacts"]["isolated_execution_sha256"]:raise ValueError("prior_execution_changed")
    records=boundary.load_old_snapshots(identity)
    for attempt in json.loads((previous/"execution.json").read_bytes())["attempts"]:
        if attempt["status"]!="complete":continue
        directory=previous/"candidates"/f"request-{attempt['index']:04d}"
        if sha(directory/"execution.json")!=attempt["execution_sha256"]:raise ValueError("prior_request_receipt_changed")
        receipt=json.loads((directory/"execution.json").read_bytes())
        if sha(directory/"output.jsonl")!=receipt["output_sha256"]:raise ValueError("prior_snapshot_changed")
        record=boundary.native.validate_result(directory,(directory/"input.jsonl").read_bytes(),identity)[0]
        records[record["stable_id"]]=record
    return records


def execute(commit):
    import numpy as np
    bound=authenticate(commit);plan=json.loads(PLAN.read_bytes());identity=boundary.identity()
    records=previous_snapshots(identity)
    targets=[json.loads(line) for line in (ROOT/"forward-targets.jsonl").read_bytes().splitlines()]
    new=[json.loads(line) for line in (ROOT/"new-requests.jsonl").read_bytes().splitlines()]
    executor=boundary.load_script("context_reference_execution","research/reference_execution.py")
    receipt,measured=executor.execute_requests(new,ROOT/"candidates",identity,boundary.BINARY,boundary.DICTIONARY,
        boundary.native.validate_result,concurrency=plan["execution"]["concurrency"],
        request_timeout=plan["execution"]["request_timeout_seconds"],total_timeout=plan["execution"]["total_timeout_seconds"],
        progress=lambda done,total:print(json.dumps(dict(stage="context_candidates",processed=done,total=total)),flush=True))
    receipt.update(input_commit=commit,input_binding_sha256=sha(BINDING),new_requests=len(new),
                   outcomes=dict(Counter(a["status"] for a in receipt["attempts"])))
    write_once(ROOT/"forward-execution.json",canonical_json_bytes(receipt)+b"\n")
    boundary.identity();authenticate(commit)
    records.update(measured)
    arrays,metadata=encode(targets,records)
    cache=ROOT/"cache";cache.mkdir(exist_ok=False)
    np.savez_compressed(cache/"evaluation.npz",**arrays)
    write_once(cache/"metadata.json",canonical_json_bytes(metadata)+b"\n")
    grouped=defaultdict(list);main=[]
    for row,meta in zip(targets,metadata):
        if "main" in row["roles"]:main.append(meta)
        if "contrast" in row["roles"]:grouped[row["contrast_group"]].append(meta)
    supported={key for key,rows in grouped.items() if all(m["source_exact_presence"]["6"] for m in rows)}
    main_measured=sum(m["acquisition_status"]=="complete" for m in main)
    ready=main_measured>=500 and len(supported)>=25 and receipt["stop_reason"] is None
    result=dict(kind="context_contrast_candidate_report",input_commit=commit,input_binding_sha256=sha(BINDING),
        status="ready_for_model_plan" if ready else "insufficient_do_not_train",targets=len(targets),main_rows=len(main),main_measured=main_measured,
        contrast_groups=len(grouped),both_targets_in_top6_groups=len(supported),both_targets_in_top6_rows=4*len(supported),
        source_exact_counts={role:{str(k):sum(m["source_exact_presence"][str(k)] for m in rows) for k in (1,5,6,10,32)}
                             for role,rows in (("main",main),("all_selected",metadata))},
        failed_targets=sum(m["acquisition_status"]!="complete" for m in metadata),
        candidate_surfaces_truncated=sum(m["candidate_surfaces_truncated"] for m in metadata),
        converter_outcomes=receipt["outcomes"],new_requests=len(new),reused_requests=bound["reused_requests"],
        cache_sha256=sha(cache/"evaluation.npz"),metadata_sha256=sha(cache/"metadata.json"),
        execution_sha256=sha(ROOT/"forward-execution.json"),model_fits=0,model_predictions=0,gold_certified=False,final_test=False,safety_threshold=.0025)
    write_once(ROOT/"candidate-report.json",canonical_json_bytes(result)+b"\n")
    write_once(Path("reports/issue-40-context-candidates-v1.json"),canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("prepare","execute"));parser.add_argument("--input-commit")
    args=parser.parse_args();r=prepare() if args.stage=="prepare" else execute(args.input_commit)
    print(json.dumps({k:r[k] for k in ("status","targets","requests","new_requests","reused_requests","main_measured","both_targets_in_top6_groups","failed_targets") if k in r}))
