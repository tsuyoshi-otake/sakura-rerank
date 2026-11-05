"""Append a CPU score readout; preserve the original GPU experiment unchanged."""
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.evaluation_statistics import paired_component_bootstrap
from sakura_rerank.growth_metrics import observe,summarize
from evaluate_models import bound_evaluation,cluster_ids,uncertainty
from model_common import ROOT,sha


def run():
    import numpy as np
    commit="a4af7e05fcbac9f4561f5f988b503f62d31859bf"
    plan,bound=bound_evaluation(commit)
    original_path=Path("reports/issue-40-context-models-v1.json")
    original=json.loads(original_path.read_bytes())
    numerical=json.loads((ROOT/"numerical-audit/report.json").read_bytes())
    if original["scores_sha256"]!=numerical["original_gpu_scores_sha256"] or sha(ROOT/"numerical-audit/cpu-scores.npz")!=numerical["cpu_scores_sha256"]:
        raise ValueError("backend_score_binding_differs")
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    with np.load(ROOT/"numerical-audit/cpu-scores.npz",allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    targets=[json.loads(line) for line in (ROOT/"forward-targets.jsonl").read_bytes().splitlines()]
    if set(scores)!={context+"/"+model["name"] for context in conditions["contexts"] for model in bound["models"]}:
        raise ValueError("cpu_score_population_differs")
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
        baseline=observations[f"ungated/intact/c2-s{seed}"]["correct"]
        conditioned=observations[f"ungated/intact/context_initialized-s{seed}"]["correct"]
        difference=conditioned[main].astype(int)-baseline[main].astype(int)
        interval=paired_component_bootstrap(clusters["main"],np.stack((difference,np.ones(len(main),dtype=int)),axis=1).tolist(),
            {"accuracy_difference":(0,1)},replicates=2000,seed=20261105)
        primary.append(dict(seed=seed,main_difference=float(difference.mean()),main_net_rows=int(difference.sum()),
            main_paired_ci95=interval["ratios"]["accuracy_difference"]["ci95"],component_count=interval["component_count"],
            supported_contrast_net_rows=int(conditioned[supported].sum()-baseline[supported].sum())))
    mean=sum(p["main_difference"] for p in primary)/3
    advance=(all(p["main_difference"]>=0 for p in primary) and mean>0
             and all(p["main_paired_ci95"] is not None and p["main_paired_ci95"][0]>0 for p in primary)
             and sum(p["supported_contrast_net_rows"]>0 for p in primary)>=2)
    context_changes={}
    for model in bound["models"]:
        for gate in ("ungated","gated"):
            intact=observations[gate+"/intact/"+model["name"]]
            context_changes[gate+"/"+model["name"]]={}
            for context in ("empty","shuffled"):
                altered=observations[gate+"/"+context+"/"+model["name"]]
                context_changes[gate+"/"+model["name"]][context]={name:dict(
                    changed_winners=int((altered["predicted"][indexes]!=intact["predicted"][indexes]).sum()),
                    source_correct_difference=int(altered["correct"][indexes].sum()-intact["correct"][indexes].sum()))
                    for name,indexes in conditions["populations"].items()}
    changed=[]
    for key,populations in metrics.items():
        for population,point in populations.items():
            before=original["metrics"][key][population]
            fields=("correct","rescue","harm","wrong_to_wrong","changed")
            delta={field:point[field]-before[field] for field in fields if point[field]!=before[field]}
            if delta:changed.append(dict(model_condition=key,population=population,deltas=delta))
    result=dict(original,kind="context_conditioned_cpu_research_comparison",inference_backend="PyTorch CPU FP32",
        scores_sha256=numerical["cpu_scores_sha256"],metrics=metrics,context_changes=context_changes,
        primary_comparisons=primary,primary_mean_difference=mean,conditioned_structure_advances=advance,
        next_research_structure="context_initialized" if advance else "c2",
        original_gpu_report_sha256=sha(original_path),numerical_audit_sha256=sha(ROOT/"numerical-audit/report.json"),
        script_sha256=sha(__file__),backend_metric_changes=changed,
        structure_decision_unchanged=advance==original["conditioned_structure_advances"],
        original_gpu_results_replaced=False,post_observation_backend_audit=True,
        verification_note="Recompute all counts and intervals from CPU scores for the same fixed checkpoints and populations. Preserve original GPU scores/results. No retraining, selection, gate or tolerance adjustment.")
    for path in (ROOT/"model-report-cpu.json",Path("reports/issue-40-context-models-cpu-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return dict(primary_comparisons=primary,primary_mean_difference=mean,conditioned_structure_advances=advance,
                structure_decision_unchanged=result["structure_decision_unchanged"],backend_metric_changes=changed)


if __name__=="__main__":print(json.dumps(run()))
