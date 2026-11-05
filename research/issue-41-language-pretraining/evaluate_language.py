"""One CPU inference pass after every checkpoint is sealed; all paired results."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import time

os.environ["CUDA_VISIBLE_DEVICES"]="-1"
os.environ["OMP_NUM_THREADS"]="1"
os.environ["MKL_NUM_THREADS"]="1"

from sakura_rerank.evaluation_statistics import paired_component_bootstrap
from sakura_rerank.growth_metrics import observe,summarize
from language_common import ROOT,context_model,context_arrays,cluster_ids,uncertainty,boundary,read_json,rows,save,sha
from fit_contract import authenticate

FIT_COMMIT="0f68712bfe665baa9fae6441e8f278fed828d021"
BINDING=Path("manifests/language-evaluation-v1.json")


def seal():
    plan,_=authenticate(FIT_COMMIT,evaluation=True);execution=read_json(ROOT/"training-execution.json")
    expected=[f"{mode}-s{seed}" for seed in plan["downstream"]["seeds"] for mode in ("lm_off","lm_on")]
    if (execution["status"]!="complete" or execution["unattempted_fits"] or execution["unattempted_pretraining_runs"]
            or [r["name"] for r in execution["models"]]!=expected):raise ValueError("all_language_fits_required")
    models=[dict(name="reference29",path=plan["downstream"]["initial_checkpoint"],sha256=plan["downstream"]["initial_checkpoint_sha256"])]
    for row in execution["models"]:
        directory=ROOT/"models"/row["name"]
        if row["status"]!="complete" or row["steps"]!=500 or sha(directory/"model.pt")!=row["checkpoint_sha256"]:raise ValueError("downstream_checkpoint_incomplete")
        if row["mode"]=="lm_off" and not row["prior_control_tensor_equal"]:raise ValueError("control_replay_missing")
        models.append(dict(name=row["name"],mode=row["mode"],seed=row["seed"],path=(directory/"model.pt").as_posix(),sha256=row["checkpoint_sha256"]))
    for row in execution["pretraining"]:
        if row["status"]!="complete" or row["steps"]!=2000 or not row["scorer_unchanged"]:raise ValueError("pretraining_contract_differs")
    bound=dict(kind="language_model_evaluation_binding",fit_commit=FIT_COMMIT,models=models,training_sha256=sha(ROOT/"training-execution.json"),
        conditions_sha256=sha(ROOT/"conditions.json"),script_sha256=sha(__file__),inference_backend="CPU PyTorch FP32 one thread",
        gold_certified=False,final_test_used=False,predictions_seen=False)
    save(BINDING,bound);save(ROOT/"evaluation-binding.json",bound);return dict(models=len(models),fits=6,pretraining_runs=3)


def bound_evaluation(commit):
    plan,_=authenticate(FIT_COMMIT,evaluation=True);bound=json.loads(boundary.committed(BINDING,commit))
    if (bound!=read_json(ROOT/"evaluation-binding.json") or bound["training_sha256"]!=sha(ROOT/"training-execution.json")
            or bound["conditions_sha256"]!=sha(ROOT/"conditions.json") or bound["script_sha256"]!=sha(__file__)):
        raise ValueError("language_evaluation_contract_changed")
    for model in bound["models"]:
        if sha(model["path"])!=model["sha256"]:raise ValueError("sealed_language_model_changed")
    return plan,bound


def infer(commit):
    import numpy as np
    import torch
    _,bound=bound_evaluation(commit)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if torch.cuda.is_available():raise ValueError("cpu_only_evaluation_required")
    harness=context_model.reference();conditions=read_json(ROOT/"conditions.json")
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    directory=ROOT/"scores";directory.mkdir(exist_ok=False);scores={};start=time.monotonic()
    receipt=dict(kind="language_cpu_inference",status="failed",evaluation_commit=commit,backend=bound["inference_backend"],
        evaluation_binding_sha256=sha(BINDING),conditions=[],rows=len(arrays["gold"]),threads=1,gpu_disabled=True)
    try:
        for item in bound["models"]:
            model=harness.build_model("C2").eval();model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
            for mode in conditions["contexts"]:
                terminal=dict(model=item["name"],context=mode,status="failed");label=mode+"/"+item["name"]
                try:
                    modified=context_arrays(arrays,conditions,mode);parts=[]
                    with torch.no_grad():
                        for offset in range(0,len(arrays["gold"]),128):
                            if time.monotonic()-start>300:raise TimeoutError("cpu_inference_time_bound")
                            indexes=np.arange(offset,min(offset+128,len(arrays["gold"])))
                            inputs,_=harness._tensors(modified,modified["features"],indexes,torch.device("cpu"))
                            parts.append(model(*inputs).numpy())
                    scores[label]=np.concatenate(parts)
                    if scores[label].shape!=(len(arrays["gold"]),6):raise ValueError("language_score_shape")
                    terminal.update(status="complete",nonfinite_rows=int((~np.isfinite(scores[label]).all(axis=1)).sum()))
                except (RuntimeError,ValueError) as error:
                    scores[label]=np.full((len(arrays["gold"]),6),np.nan,dtype=np.float32)
                    terminal.update(error_type=type(error).__name__,fallback_rows=len(arrays["gold"]))
                finally:receipt["conditions"].append(terminal)
            del model
            print(json.dumps(dict(stage="language_cpu_inference",model=item["name"],conditions=3)),flush=True)
        np.savez_compressed(directory/"all.npz",**scores);bound_evaluation(commit)
        receipt.update(status="complete" if all(r["status"]=="complete" and r.get("nonfinite_rows")==0 for r in receipt["conditions"]) else "complete_with_failures",
                       scores_sha256=sha(directory/"all.npz"))
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt.update(elapsed_seconds=round(time.monotonic()-start,3),unattempted_conditions=21-len(receipt["conditions"]))
        save(directory/"execution.json",receipt)
    return {k:receipt[k] for k in ("status","elapsed_seconds","unattempted_conditions")}


def report(commit):
    import numpy as np
    plan,bound=bound_evaluation(commit);execution=read_json(ROOT/"scores/execution.json")
    if execution["unattempted_conditions"] or sha(ROOT/"scores/all.npz")!=execution["scores_sha256"]:raise ValueError("all_bound_language_scores_required")
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
    conditions=read_json(ROOT/"conditions.json");targets=list(rows(ROOT/"forward-targets.jsonl"))
    expected={context+"/"+m["name"] for context in conditions["contexts"] for m in bound["models"]}
    if set(scores)!=expected:raise ValueError("model_context_population_differs")
    clusters={name:cluster_ids(targets,indexes,name!="main") for name,indexes in conditions["populations"].items()}
    observations={};metrics={}
    for label,values in scores.items():
        for gate in ("ungated","gated"):
            key=gate+"/"+label;observation=observe(arrays,values,gate);observations[key]=observation;metrics[key]={}
            for name,indexes in conditions["populations"].items():
                value=summarize(observation,indexes);value["paired_source_component_intervals"]=uncertainty(observation,indexes,clusters[name])
                value["source_absent_top6"]=int((~arrays["correct_mask"][indexes].any(axis=1)).sum())
                value["source_present_top6_but_not_correct"]=int((arrays["correct_mask"][indexes].any(axis=1) & ~observation["correct"][indexes]).sum())
                metrics[key][name]=value
    main=conditions["populations"]["main"];supported=conditions["populations"]["contrast_supported"];primary=[]
    for seed in plan["downstream"]["seeds"]:
        control=observations[f"ungated/intact/lm_off-s{seed}"]["correct"];treated=observations[f"ungated/intact/lm_on-s{seed}"]["correct"]
        delta=treated[main].astype(int)-control[main].astype(int)
        interval=paired_component_bootstrap(clusters["main"],np.stack((delta,np.ones(len(main),dtype=int)),axis=1).tolist(),
            {"accuracy_difference":(0,1)},replicates=2000,seed=20261105)
        primary.append(dict(seed=seed,main_net_rows=int(delta.sum()),main_difference=float(delta.mean()),
            main_paired_ci95=interval["ratios"]["accuracy_difference"]["ci95"],component_count=interval["component_count"],
            supported_contrast_net_rows=int(treated[supported].sum()-control[supported].sum())))
    mean=sum(r["main_difference"] for r in primary)/3
    advance=(execution["status"]=="complete" and all(r["main_difference"]>=0 for r in primary) and mean>0
             and all(r["main_paired_ci95"] is not None and r["main_paired_ci95"][0]>0 for r in primary)
             and sum(r["supported_contrast_net_rows"]>0 for r in primary)>=2)
    changes=defaultdict(dict)
    for model in bound["models"]:
        for gate in ("ungated","gated"):
            original=observations[gate+"/intact/"+model["name"]]
            for mode in ("empty","shuffled"):
                altered=observations[gate+"/"+mode+"/"+model["name"]]
                changes[gate+"/"+model["name"]][mode]={name:dict(changed_winners=int((altered["predicted"][indexes]!=original["predicted"][indexes]).sum()),
                    source_correct_difference=int(altered["correct"][indexes].sum()-original["correct"][indexes].sum())) for name,indexes in conditions["populations"].items()}
    result=dict(kind="paired_character_pretraining_research",fit_commit=FIT_COMMIT,evaluation_commit=commit,
        evaluation_binding_sha256=sha(BINDING),scores_sha256=execution["scores_sha256"],inference_backend=execution["backend"],
        metrics=metrics,primary_comparisons=primary,primary_mean_difference=mean,pretraining_advances=advance,
        context_changes=dict(changes),source_population_sizes={k:len(v) for k,v in conditions["populations"].items()},
        source_cluster_counts={k:len(set(v)) for k,v in clusters.items()},model_fits=6,pretraining_runs=3,
        safety_threshold=.0025,gold_certified=False,independent_human_ime_gold=0,final_test_used=False,production_adoption=False,
        uncertainty_scope="Exploratory exact source-form agreement under the preregistered cohort and source/contrast component bootstrap; neither IME intent nor population independence is certified.")
    save(ROOT/"model-report.json",result);save("reports/issue-41-language-models-v1.json",result)
    return {k:result[k] for k in ("primary_comparisons","primary_mean_difference","pretraining_advances")}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("seal","infer","report"));parser.add_argument("--evaluation-commit")
    args=parser.parse_args();print(json.dumps(seal() if args.stage=="seal" else (infer(args.evaluation_commit) if args.stage=="infer" else report(args.evaluation_commit))))
