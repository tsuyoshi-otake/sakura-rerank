"""One bound inference pass for all registered models and context conditions."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.evaluation_statistics import paired_component_bootstrap
from sakura_rerank.growth_metrics import observe,summarize
from model_common import ROOT,authenticate,reference,build,sha
from feasibility import boundary

FIT_COMMIT="2f3c86640d5509aeb9c619485f8607c59eb8e373"
EVALUATION_BINDING=Path("manifests/context-model-evaluation-v1.json")


def seal():
    plan,_=authenticate(FIT_COMMIT)
    execution=json.loads((ROOT/"training-execution.json").read_bytes())
    expected=[f"{arch}-s{seed}" for seed in plan["training"]["seeds"] for arch in plan["architectures"]]
    if (execution["status"]!="complete" or execution["not_attempted_fits"]!=0
            or [r["name"] for r in execution["models"]]!=expected):raise ValueError("all_six_completed_fits_required")
    models=[dict(name="reference29",architecture="c2",path=plan["training"]["initial_checkpoint"],sha256=plan["training"]["initial_checkpoint_sha256"])]
    for row in execution["models"]:
        directory=ROOT/"models"/row["name"]
        if sha(directory/"execution.json")!=row["execution_sha256"] or sha(directory/"model.pt")!=row["checkpoint_sha256"]:
            raise ValueError("completed_model_artifact_changed")
        receipt=json.loads((directory/"execution.json").read_bytes())
        if receipt["status"]!="complete" or receipt["steps"]!=500 or not receipt["empty_context_initial_parity"]:
            raise ValueError("model_receipt_contract_differs")
        models.append(dict(name=row["name"],architecture=receipt["architecture"],seed=receipt["seed"],
                           path=str(directory/"model.pt").replace("\\","/"),sha256=row["checkpoint_sha256"]))
    result=dict(kind="context_model_evaluation_binding",fit_commit=FIT_COMMIT,training_receipt_sha256=sha(ROOT/"training-execution.json"),
                model_conditions_sha256=sha(ROOT/"model-conditions.json"),models=models,script_sha256=sha(__file__),
                model_predictions_seen=False,model_fits=6,gold_certified=False,final_test=False)
    for path in (EVALUATION_BINDING,ROOT/"evaluation-binding.json"):write_once(path,canonical_json_bytes(result)+b"\n")
    return dict(models=len(models),fits=6)


def bound_evaluation(commit):
    plan,_=authenticate(FIT_COMMIT)
    raw=boundary.committed(EVALUATION_BINDING,commit)
    if raw!=(ROOT/"evaluation-binding.json").read_bytes():raise ValueError("evaluation_binding_copy_differs")
    bound=json.loads(raw)
    if (bound["training_receipt_sha256"]!=sha(ROOT/"training-execution.json")
            or bound["model_conditions_sha256"]!=sha(ROOT/"model-conditions.json")
            or bound["script_sha256"]!=sha(__file__)):raise ValueError("evaluation_implementation_or_inputs_changed")
    for model in bound["models"]:
        if sha(model["path"])!=model["sha256"]:raise ValueError("bound_model_changed")
    return plan,bound


def context_arrays(arrays,conditions,mode):
    import numpy as np
    result=dict(arrays)
    if mode=="empty":
        result["context_ids"]=np.zeros_like(arrays["context_ids"])
        result["context_lengths"]=np.zeros_like(arrays["context_lengths"])
    elif mode=="shuffled":
        result["context_ids"]=arrays["context_ids"][conditions["shuffle"]]
        result["context_lengths"]=arrays["context_lengths"][conditions["shuffle"]]
    elif mode!="intact":raise ValueError("unknown_registered_context_condition")
    return result


def infer(commit):
    import numpy as np
    import torch
    plan,bound=bound_evaluation(commit)
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    harness=reference();harness.seed_everything(20261105)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as cache:arrays={k:np.array(cache[k]) for k in cache.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    output=ROOT/"scores";output.mkdir(exist_ok=False)
    receipt=dict(kind="context_model_inference",status="failed",evaluation_commit=commit,
        evaluation_binding_sha256=sha(EVALUATION_BINDING),batches=[],device="cuda:0",rows=len(arrays["gold"]),
        model_conditions_sha256=sha(ROOT/"model-conditions.json"),final_test=False,gold_certified=False)
    start=time.monotonic();scores={}
    try:
        for item in bound["models"]:
            model=build(harness,item["architecture"])
            model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
            model=model.to("cuda:0").eval()
            for mode in conditions["contexts"]:
                label=mode+"/"+item["name"]
                part=dict(model=item["name"],context=mode,status="failed")
                try:
                    modified=context_arrays(arrays,conditions,mode)
                    value=harness.score_rows(model,modified,modified["features"],np.arange(len(arrays["gold"])))
                    if value.shape!=(len(arrays["gold"]),6):raise ValueError("model_score_shape_differs")
                    scores[label]=value
                    part.update(status="complete",nonfinite_rows=int((~np.isfinite(value).all(axis=1)).sum()))
                except (RuntimeError,ValueError) as error:
                    scores[label]=np.full((len(arrays["gold"]),6),np.nan,dtype=np.float32)
                    part.update(error_type=type(error).__name__,fallback_rows=len(arrays["gold"]))
                receipt["batches"].append(part)
            del model;torch.cuda.empty_cache()
            print(json.dumps(dict(stage="context_inference",model=item["name"],conditions=3)),flush=True)
        np.savez_compressed(output/"all.npz",**scores)
        bound_evaluation(commit)
        receipt.update(status="complete" if all(b["status"]=="complete" and b["nonfinite_rows"]==0 for b in receipt["batches"]) else "complete_with_failures",
                       scores_sha256=sha(output/"all.npz"))
    except Exception as error:
        receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        receipt["unattempted_conditions"]=21-len(receipt["batches"])
        write_once(output/"execution.json",canonical_json_bytes(receipt)+b"\n")
    return dict(status=receipt["status"],conditions=len(receipt["batches"]),elapsed_seconds=receipt["elapsed_seconds"])


def cluster_ids(targets,indexes,contrast):
    # Union source and contrast groups rather than treating repeated lexical
    # contexts as independent observations. No labels/scores enter clustering.
    parent=list(range(len(indexes)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    known={}
    for local,index in enumerate(indexes):
        row=targets[index]
        keys=["source:"+row["source_component"]]
        if contrast:keys.append("contrast:"+row["contrast_group"])
        for key in keys:
            if key in known:parent[find(local)]=find(known[key])
            else:known[key]=local
    members=defaultdict(list)
    for local,index in enumerate(indexes):members[find(local)].append(targets[index]["stable_id"])
    names={root:canonical_json_hash(sorted(ids)) for root,ids in members.items()}
    return [names[find(i)] for i in range(len(indexes))]


def uncertainty(observation,indexes,clusters):
    import numpy as np
    correct=observation["correct"][indexes];base=observation["baseline"][indexes];changed=observation["changed"][indexes]
    rescue=~base & correct;harm=base & ~correct
    values=np.stack((correct,base,rescue,harm,changed,~base,np.ones(len(indexes),dtype=bool),
                     correct.astype(int)-base.astype(int),changed & ~base),axis=1).astype(int).tolist()
    ratios=dict(accuracy=(0,6),baseline_gain=(7,6),precision=(2,4),recall=(2,5),application=(4,6),harm_rate=(3,1),application_to_error=(8,5))
    return paired_component_bootstrap(clusters,values,ratios,replicates=2000,seed=20261105)


def report(commit):
    import numpy as np
    plan,bound=bound_evaluation(commit)
    execution=json.loads((ROOT/"scores/execution.json").read_bytes())
    if execution["status"] not in ("complete","complete_with_failures") or execution["unattempted_conditions"]!=0 or sha(ROOT/"scores/all.npz")!=execution["scores_sha256"]:
        raise ValueError("complete_bound_scores_required")
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as cache:arrays={k:np.array(cache[k]) for k in cache.files}
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as cache:scores={k:np.array(cache[k]) for k in cache.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    targets=[json.loads(line) for line in (ROOT/"forward-targets.jsonl").read_bytes().splitlines()]
    expected={mode+"/"+model["name"] for mode in conditions["contexts"] for model in bound["models"]}
    if set(scores)!=expected:raise ValueError("score_model_condition_population_differs")
    clusters={name:cluster_ids(targets,indexes,name!="main") for name,indexes in conditions["populations"].items()}
    observations={};metrics={}
    for label,value in scores.items():
        for gate in ("ungated","gated"):
            key=gate+"/"+label;observation=observe(arrays,value,gate);observations[key]=observation
            metrics[key]={}
            for name,indexes in conditions["populations"].items():
                point=summarize(observation,indexes)
                point["paired_source_component_intervals"]=uncertainty(observation,indexes,clusters[name])
                point["source_present_top6_but_not_correct"]=int((arrays["correct_mask"][indexes].any(axis=1) & ~observation["correct"][indexes]).sum())
                point["source_absent_top6"]=int((~arrays["correct_mask"][indexes].any(axis=1)).sum())
                metrics[key][name]=point
    primary=[];main=conditions["populations"]["main"];supported=conditions["populations"]["contrast_supported"]
    for seed in plan["training"]["seeds"]:
        base=observations[f"ungated/intact/c2-s{seed}"]["correct"]
        conditional=observations[f"ungated/intact/context_initialized-s{seed}"]["correct"]
        difference=conditional[main].astype(int)-base[main].astype(int)
        interval=paired_component_bootstrap(clusters["main"],np.stack((difference,np.ones(len(main),dtype=int)),axis=1).tolist(),
            {"accuracy_difference":(0,1)},replicates=2000,seed=20261105)
        primary.append(dict(seed=seed,main_difference=float(difference.mean()),main_net_rows=int(difference.sum()),
            main_paired_ci95=interval["ratios"]["accuracy_difference"]["ci95"],component_count=interval["component_count"],
            supported_contrast_net_rows=int(conditional[supported].sum()-base[supported].sum())))
    mean=sum(p["main_difference"] for p in primary)/3
    advance=(all(p["main_difference"]>=0 for p in primary) and mean>0
             and all(p["main_paired_ci95"] is not None and p["main_paired_ci95"][0]>0 for p in primary)
             and sum(p["supported_contrast_net_rows"]>0 for p in primary)>=2
             and execution["status"]=="complete")
    context_changes={}
    for model in bound["models"]:
        for gate in ("ungated","gated"):
            original=observations[gate+"/intact/"+model["name"]]
            context_changes[gate+"/"+model["name"]]={}
            for mode in ("empty","shuffled"):
                altered=observations[gate+"/"+mode+"/"+model["name"]]
                context_changes[gate+"/"+model["name"]][mode]={name:dict(
                    changed_winners=int((altered["predicted"][indexes]!=original["predicted"][indexes]).sum()),
                    source_correct_difference=int(altered["correct"][indexes].sum()-original["correct"][indexes].sum()))
                    for name,indexes in conditions["populations"].items()}
    result=dict(kind="context_conditioned_research_comparison",fit_commit=FIT_COMMIT,evaluation_commit=commit,
        evaluation_binding_sha256=sha(EVALUATION_BINDING),scores_sha256=execution["scores_sha256"],
        inference_receipt_sha256=sha(ROOT/"scores/execution.json"),model_fits=6,metrics=metrics,
        primary_comparisons=primary,primary_mean_difference=mean,context_changes=context_changes,
        conditioned_structure_advances=advance,next_research_structure="context_initialized" if advance else "c2",
        comparison_family="Three primary seed-paired main comparisons; all reported, no best-seed selection",
        source_population_sizes={name:len(indexes) for name,indexes in conditions["populations"].items()},
        source_cluster_counts={name:len(set(ids)) for name,ids in clusters.items()},
        safety_threshold=.0025,gold_certified=False,independent_human_ime_gold=0,final_test_used=False,
        production_adoption=False,
        uncertainty_scope="Exploratory original-source agreement under the fixed source/contrast sampling and component bootstrap. Label validity and general IME population independence are not certified; zero observed harm would still be insufficient at this sample size.")
    for path in (ROOT/"model-report.json",Path("reports/issue-40-context-models-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return dict(primary_comparisons=primary,primary_mean_difference=mean,conditioned_structure_advances=advance,next_research_structure=result["next_research_structure"])


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("seal","infer","report"));parser.add_argument("--evaluation-commit")
    args=parser.parse_args();r=seal() if args.stage=="seal" else infer(args.evaluation_commit) if args.stage=="infer" else report(args.evaluation_commit)
    print(json.dumps(r))
