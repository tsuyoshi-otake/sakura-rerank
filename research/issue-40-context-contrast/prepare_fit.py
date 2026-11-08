"""Audit saved candidates/numerical tensors and freeze all prediction conditions."""
from collections import defaultdict
import json

from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.growth_numeric import encode
from sakura_rerank.data.kwdlc_probe import write_once
from feasibility import boundary
from forward import authenticate as authenticate_forward,previous_snapshots
from model_common import ROOT,TRAIN_ROOT,PLAN,BINDING,growth_training,sha


def run():
    import numpy as np
    plan=json.loads(PLAN.read_bytes())
    report=json.loads((ROOT/"candidate-report.json").read_bytes())
    for path,expected in ((ROOT/"candidate-report.json",plan["candidate_report_sha256"]),
                          (ROOT/"cache/evaluation.npz",plan["evaluation_cache_sha256"]),
                          (ROOT/"cache/metadata.json",plan["evaluation_metadata_sha256"])):
        if sha(path)!=expected:raise ValueError("model_preregistered_candidate_evidence_changed")
    if report["status"]!="ready_for_model_plan" or report["failed_targets"]!=0:raise ValueError("model_candidate_readiness_not_met")
    authenticate_forward(plan["forward_input_commit"])
    identity=boundary.identity();records=previous_snapshots(identity)
    requests=[json.loads(line) for line in (ROOT/"new-requests.jsonl").read_bytes().splitlines()]
    execution=json.loads((ROOT/"forward-execution.json").read_bytes())
    if sha(ROOT/"forward-execution.json")!=report["execution_sha256"] or execution["stop_reason"] is not None or execution["not_attempted"]!=0:
        raise ValueError("completed_candidate_execution_required")
    if [a["index"] for a in execution["attempts"]]!=list(range(len(requests))):raise ValueError("request_terminal_accounting_differs")
    for attempt,request in zip(execution["attempts"],requests):
        directory=ROOT/"candidates"/f"request-{attempt['index']:04d}"
        if attempt["status"]!="complete" or sha(directory/"execution.json")!=attempt["execution_sha256"]:
            raise ValueError("candidate_terminal_evidence_differs")
        receipt=json.loads((directory/"execution.json").read_bytes())
        if (sha(directory/"output.jsonl")!=receipt["output_sha256"]
                or (directory/"input.jsonl").read_bytes()!=boundary.jsonl([request])
                or json.loads((directory/"identity.json").read_bytes())!=identity):
            raise ValueError("candidate_request_or_output_changed")
        record=boundary.native.validate_result(directory,(directory/"input.jsonl").read_bytes(),identity)[0]
        records[record["stable_id"]]=record
    targets=[json.loads(line) for line in (ROOT/"forward-targets.jsonl").read_bytes().splitlines()]
    arrays,metadata=encode(targets,records)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:
        if set(saved.files)!=set(arrays) or any(not np.array_equal(saved[key],value) for key,value in arrays.items()):
            raise ValueError("numerical_cache_replay_differs")
    if canonical_json_bytes(metadata)+b"\n"!=(ROOT/"cache/metadata.json").read_bytes():raise ValueError("metadata_replay_differs")
    counts={role:{str(k):0 for k in (1,5,6,10,32)} for role in ("main","all_selected")}
    groups=defaultdict(list);main=[]
    for i,row in enumerate(targets):
        candidates=records[row["candidate_request_id"]]["candidate_snapshots"]["training_top32"]["candidates"]
        if "main" in row["roles"]:main.append(i)
        if "contrast" in row["roles"]:groups[row["contrast_group"]].append(i)
        for role in (["main","all_selected"] if "main" in row["roles"] else ["all_selected"]):
            for k in (1,5,6,10,32):counts[role][str(k)]+=any(c["surface"]==row["target"] for c in candidates[:k])
    if counts!=report["source_exact_counts"]:raise ValueError("independent_candidate_counts_differ")
    supported=[key for key,indexes in groups.items() if all(arrays["correct_mask"][i].any() for i in indexes)]
    populations=dict(main=main,contrast_all=sorted(i for indexes in groups.values() for i in indexes),
        contrast_supported=sorted(i for key in supported for i in groups[key]))
    if len(main)!=991 or len(groups)!=61 or len(supported)!=53:raise ValueError("fixed_model_population_differs")
    strata=defaultdict(list)
    for i,row in enumerate(targets):
        length=len(row["left_context"])
        strata[("main" in row["roles"],0 if length<16 else 1 if length<32 else 2)].append(i)
    permutation=list(range(len(targets)));singleton_rows=0
    for indexes in strata.values():
        ordered=sorted(indexes,key=lambda i:canonical_json_hash([20261105,"shuffle",targets[i]["stable_id"]]))
        if len(ordered)==1:singleton_rows+=1
        for i,j in zip(ordered,ordered[1:]+ordered[:1]):permutation[i]=j
    if sorted(permutation)!=list(range(len(targets))):raise ValueError("context_permutation_not_bijective")
    conditions=dict(populations=populations,shuffle=permutation,singleton_shuffle_rows=singleton_rows,
        contexts=["intact","empty","shuffled"],target_ids_sha256=canonical_json_hash([r["stable_id"] for r in targets]))
    write_once(ROOT/"model-conditions.json",canonical_json_bytes(conditions)+b"\n")
    growth=growth_training();prior,_=growth.authenticate_fit(plan["training"]["prior_fit_binding_commit"])
    paths=[str(ROOT/relative) for relative in ("cohort-binding.json","forward-binding.json","candidate-report.json",
        "forward-targets.jsonl","cache/evaluation.npz","cache/metadata.json","model-conditions.json")]
    paths += [str(TRAIN_ROOT/relative) for relative in ("cache/train.npz","cache/cohorts.json")]
    paths += [plan["training"]["initial_checkpoint"],"manifests/data-growth-fit-binding-v2.json",
        "src/sakura_rerank/context_conditioned.py","research/issue-40-context-contrast/model_common.py",
        "research/issue-40-context-contrast/fit_models.py","research/issue-40-context-contrast/prepare_fit.py",
        "src/sakura_rerank/growth_metrics.py","src/sakura_rerank/evaluation_statistics.py"]
    binding=dict(kind="paired_context_fit_binding",plan_sha256=sha(PLAN),artifacts={path:sha(path) for path in paths},
        environment=prior["environment"],training_rows=50000,evaluation_rows=1215,
        evaluation_population_sizes={k:len(v) for k,v in populations.items()},singleton_shuffle_rows=singleton_rows,
        scalar_candidate_recount=True,numerical_replay_equal=True,all_new_snapshots_authenticated=len(requests),
        model_fits_started=False,model_predictions_seen=False,gold_certified=False,final_test=False,safety_threshold=.0025)
    for path in (BINDING,ROOT/"model-fit-binding.json"):write_once(path,canonical_json_bytes(binding)+b"\n")
    return binding


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("training_rows","evaluation_rows","evaluation_population_sizes","all_new_snapshots_authenticated","singleton_shuffle_rows")}))
