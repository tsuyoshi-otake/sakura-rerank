"""Immutable candidate acquisition for the new #41 evaluation cohort."""
import argparse
from collections import Counter,defaultdict
import json

from sakura_rerank.data.growth_numeric import encode
from sakura_rerank.data.input_boundary import request_id
from sakura_rerank.data.kwdlc_probe import write_once
from language_common import ROOT,PRIOR_ROOT,PLAN,boundary,context_forward,read_json,rows,save,sha,jsonl

BINDING="manifests/language-forward-v1.json"


def load_completed(root,requests,execution,identity):
    records={}
    if len(requests)!=len(execution["attempts"]):raise ValueError("candidate_attempt_count_changed")
    for index,(request,attempt) in enumerate(zip(requests,execution["attempts"])):
        if attempt["index"]!=index:raise ValueError("candidate_attempt_order_changed")
        if attempt["status"]!="complete":continue
        directory=root/"candidates"/f"request-{index:04d}"
        if sha(directory/"execution.json")!=attempt["execution_sha256"]:raise ValueError("candidate_receipt_changed")
        receipt=read_json(directory/"execution.json")
        if (sha(directory/"output.jsonl")!=receipt["output_sha256"] or (directory/"input.jsonl").read_bytes()!=jsonl([request])
                or read_json(directory/"identity.json")!=identity):raise ValueError("candidate_input_or_output_changed")
        record=boundary.native.validate_result(directory,(directory/"input.jsonl").read_bytes(),identity)[0]
        records[record["stable_id"]]=record
    return records


def prior_snapshots():
    identity=boundary.identity();records=context_forward.previous_snapshots(identity)
    context_forward.authenticate("33ec9735932bc29cadf863e7a4637072efa60bf1")
    previous=read_json(PRIOR_ROOT/"candidate-report.json")
    if sha(PRIOR_ROOT/"forward-execution.json")!=previous["execution_sha256"]:raise ValueError("prior_candidate_execution_changed")
    records.update(load_completed(PRIOR_ROOT,list(rows(PRIOR_ROOT/"new-requests.jsonl")),read_json(PRIOR_ROOT/"forward-execution.json"),identity))
    return identity,records


def prepare():
    cohort=read_json(ROOT/"cohort.json");verification=read_json(ROOT/"cohort-verification.json")
    if cohort["status"]!="ready" or verification["status"]!="passed" or verification["cohort_sha256"]!=sha(ROOT/"cohort.json"):
        raise ValueError("verified_ready_source_cohort_required")
    if sha(ROOT/"selected.jsonl")!=cohort["artifacts"]["selected"]:raise ValueError("source_selection_changed")
    identity,known=prior_snapshots();targets=[];requests={}
    for row in rows(ROOT/"selected.jsonl"):
        key=request_id(row["reading"])
        targets.append(dict(row,candidate_request_id=key,component_id=row["source_component"],corpus="kwdlc"))
        requests[key]=dict(stable_id=key,reading=row["reading"])
    requested=[requests[k] for k in sorted(requests)];new=[r for r in requested if r["stable_id"] not in known]
    for name,data in (("forward-targets",targets),("requests",requested),("new-requests",new)):write_once(ROOT/(name+".jsonl"),jsonl(data))
    bound=dict(kind="language_evaluation_candidate_binding",cohort_sha256=sha(ROOT/"cohort.json"),plan_sha256=sha(PLAN),
        targets=len(targets),requests=len(requested),new_requests=len(new),reused_requests=len(requested)-len(new),
        artifacts={name:sha(ROOT/(name+".jsonl")) for name in ("forward-targets","requests","new-requests")},
        code={p:sha(p) for p in ("research/issue-41-language-pretraining/forward_candidates.py","research/reference_execution.py","src/sakura_rerank/data/growth_numeric.py")},
        execution=dict(concurrency=2,request_timeout_seconds=30,total_timeout_seconds=900),
        identity_sha256=sha("manifests/reference-probe-identity-v1.json"),model_predictions=0,model_fits=0)
    if not identity:raise ValueError("reference_identity_missing")
    save(ROOT/"forward-binding.json",bound);save(BINDING,bound)
    return {k:bound[k] for k in ("targets","requests","new_requests","reused_requests")}


def authenticate(commit):
    bound=json.loads(boundary.committed(BINDING,commit))
    if bound!=read_json(ROOT/"forward-binding.json") or bound["cohort_sha256"]!=sha(ROOT/"cohort.json") or bound["plan_sha256"]!=sha(PLAN):
        raise ValueError("language_forward_binding_changed")
    for name,expected in bound["artifacts"].items():
        if sha(ROOT/(name+".jsonl"))!=expected:raise ValueError("language_forward_input_changed")
    for path,expected in bound["code"].items():
        if sha(path)!=expected:raise ValueError("language_forward_code_changed")
    return bound


def execute(commit):
    import numpy as np
    bound=authenticate(commit);identity,records=prior_snapshots();new=list(rows(ROOT/"new-requests.jsonl"))
    executor=boundary.load_script("language_reference_execution","research/reference_execution.py")
    execution,measured=executor.execute_requests(new,ROOT/"candidates",identity,boundary.BINARY,boundary.DICTIONARY,
        boundary.native.validate_result,concurrency=2,request_timeout=30,total_timeout=900,
        progress=lambda done,total:print(json.dumps(dict(stage="language_candidates",processed=done,total=total)),flush=True))
    execution.update(input_commit=commit,binding_sha256=sha(BINDING));save(ROOT/"forward-execution.json",execution)
    authenticate(commit);records.update(measured);targets=list(rows(ROOT/"forward-targets.jsonl"));arrays,metadata=encode(targets,records)
    cache=ROOT/"cache";cache.mkdir(exist_ok=False);np.savez_compressed(cache/"evaluation.npz",**arrays);save(cache/"metadata.json",metadata)
    main=[m for r,m in zip(targets,metadata) if "main" in r["roles"]];groups=defaultdict(list)
    for row,meta in zip(targets,metadata):
        if "contrast" in row["roles"]:groups[row["contrast_group"]].append(meta)
    supported=sum(all(m["source_exact_presence"]["6"] for m in group) for group in groups.values())
    result=dict(kind="language_evaluation_candidates",status="ready" if len(main)>=500 and supported>=25 and execution["not_attempted"]==0 else "insufficient_do_not_train",
        input_commit=commit,targets=len(targets),main_rows=len(main),contrast_groups=len(groups),supported_groups=supported,
        source_exact_counts={name:{str(k):sum(m["source_exact_presence"][str(k)] for m in part) for k in (1,5,6,10,32)} for name,part in (("main",main),("all",metadata))},
        failed_targets=sum(m["acquisition_status"]!="complete" for m in metadata),candidate_surface_truncations=sum(m["candidate_surfaces_truncated"] for m in metadata),
        new_requests=len(new),reused_requests=bound["reused_requests"],outcomes=dict(Counter(a["status"] for a in execution["attempts"])),
        execution_sha256=sha(ROOT/"forward-execution.json"),cache_sha256=sha(cache/"evaluation.npz"),metadata_sha256=sha(cache/"metadata.json"),
        model_predictions=0,gold_certified=False,final_test_used=False)
    save(ROOT/"candidate-report.json",result);save("reports/issue-41-language-candidates-v1.json",result)
    return {k:result[k] for k in ("status","targets","main_rows","supported_groups","failed_targets","outcomes")}


def verify(commit):
    import numpy as np
    authenticate(commit);identity,records=prior_snapshots();report=read_json(ROOT/"candidate-report.json")
    if sha(ROOT/"forward-execution.json")!=report["execution_sha256"]:raise ValueError("language_execution_changed")
    records.update(load_completed(ROOT,list(rows(ROOT/"new-requests.jsonl")),read_json(ROOT/"forward-execution.json"),identity))
    arrays,metadata=encode(list(rows(ROOT/"forward-targets.jsonl")),records)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:
        if set(arrays)!=set(saved.files) or any(not np.array_equal(saved[k],v) for k,v in arrays.items()):raise ValueError("language_numeric_replay_differs")
    if metadata!=read_json(ROOT/"cache/metadata.json"):raise ValueError("language_metadata_replay_differs")
    result=dict(status="passed",targets=len(metadata),candidate_report_sha256=sha(ROOT/"candidate-report.json"),cache_sha256=sha(ROOT/"cache/evaluation.npz"),full_native_reauthentication=True)
    save(ROOT/"forward-verification.json",result);return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("prepare","execute","verify"));parser.add_argument("--input-commit")
    args=parser.parse_args();print(json.dumps(prepare() if args.stage=="prepare" else (execute(args.input_commit) if args.stage=="execute" else verify(args.input_commit))))
