"""Scalar metric recount, paired-difference replay and CPU sample verification."""
import json
import sys

import numpy as np

from sakura_rerank.evaluation_statistics import paired_component_bootstrap
from language_common import ROOT,PRIOR_ROOT,context_model,cluster_ids,boundary,read_json,rows,save,sha
from evaluate_language import bound_evaluation

EVALUATION_COMMIT="853f23028355aa0cd6c8ce336493725b674ab52f"


def run():
    plan,bound=bound_evaluation(EVALUATION_COMMIT)
    # This verifier's scalar path predates #41 and does not call observe/summarize.
    sys.path.insert(0,"research/issue-40-context-contrast")
    try:scalar=boundary.load_script("language_independent_scalar_recount","research/issue-40-context-contrast/verify_results.py")
    finally:sys.path.pop(0)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
    report=read_json(ROOT/"model-report.json");conditions=read_json(ROOT/"conditions.json")
    if sha(ROOT/"scores/all.npz")!=report["scores_sha256"]:raise ValueError("language_scores_changed")
    expected={context+"/"+m["name"] for context in conditions["contexts"] for m in bound["models"]}
    if set(scores)!=expected or len(scores)!=21:raise ValueError("language_score_population_incomplete")
    checks=0;rates=0;by_condition={}
    for key,values in scores.items():
        for gate in ("ungated","gated"):
            for name,indexes in conditions["populations"].items():
                actual=scalar.recount(arrays,values,indexes,gate=="gated");recorded=report["metrics"][gate+"/"+key][name]
                if any(recorded[k]!=v for k,v in actual.items()):raise ValueError("language_scalar_recount_differs")
                n=actual["rows"];c=actual;errors=c["baseline_errors"]
                for metric,num,den in (("accuracy",c["correct"],n),("baseline_accuracy",c["baseline_correct"],n),
                        ("precision",c["rescue"],c["changed"]),("recall",c["rescue"],errors),("application",c["changed"],n),
                        ("application_to_error",c["rescue"]+c["wrong_to_wrong"],errors),("harm_rate",c["harm"],c["baseline_correct"])):
                    scalar.verify_rate(recorded[metric],num,den);rates+=1
                if recorded["baseline_gain"]!=(c["rescue"]-c["harm"])/n:raise ValueError("language_baseline_gain_differs")
                checks+=1;by_condition[(gate,key,name)]=actual
    targets=list(rows(ROOT/"forward-targets.jsonl"));main=conditions["populations"]["main"]
    clusters=cluster_ids(targets,main,False);primary=[]
    for before in report["primary_comparisons"]:
        seed=before["seed"];delta=[]
        for i in main:
            off=scalar.recount(arrays,scores[f"intact/lm_off-s{seed}"],[i],False)["correct"]
            on=scalar.recount(arrays,scores[f"intact/lm_on-s{seed}"],[i],False)["correct"]
            delta.append([on-off,1])
        interval=paired_component_bootstrap(clusters,delta,{"accuracy_difference":(0,1)},replicates=2000,seed=20261105)
        count=sum(d[0] for d in delta)
        supported=by_condition[("ungated",f"intact/lm_on-s{seed}","contrast_supported")]["correct"]-by_condition[("ungated",f"intact/lm_off-s{seed}","contrast_supported")]["correct"]
        after=dict(seed=seed,main_net_rows=count,main_difference=count/len(main),main_paired_ci95=interval["ratios"]["accuracy_difference"]["ci95"],
            component_count=interval["component_count"],supported_contrast_net_rows=supported)
        if after!=before:raise ValueError("primary_paired_interval_replay_differs")
        primary.append(after)
    advance=(all(p["main_net_rows"]>=0 for p in primary) and sum(p["main_net_rows"] for p in primary)>0
             and all(p["main_paired_ci95"] is not None and p["main_paired_ci95"][0]>0 for p in primary)
             and sum(p["supported_contrast_net_rows"]>0 for p in primary)>=2
             and read_json(ROOT/"scores/execution.json")["status"]=="complete")
    if advance!=report["pretraining_advances"] or report["safety_threshold"]!=.0025 or report["gold_certified"] or report["final_test_used"]:
        raise ValueError("registered_decision_or_safety_changed")
    benchmark=read_json(ROOT/"cpu-benchmark/report.json")
    if (benchmark["status"]!="complete" or benchmark["unattempted_models"] or len(benchmark["models"])!=2
            or not benchmark["gpu_disabled"] or benchmark["recipe"]!=plan["cpu_benchmark"]):raise ValueError("language_cpu_contract_differs")
    for model in benchmark["models"]:
        directory=ROOT/"cpu-benchmark"/model["model"]
        if model["status"]!="complete" or model["measured"]!=10000 or model["failures"] or model["unattempted_runs"]:raise ValueError("cpu_run_population_differs")
        if sha(directory/"latencies-ns.npy")!=model["latency_samples_sha256"] or sha(directory/"model-fp32.onnx")!=model["onnx_sha256"]:raise ValueError("cpu_artifact_changed")
        times=np.load(directory/"latencies-ns.npy",allow_pickle=False)
        if times.shape!=(10000,) or np.any(times<=0):raise ValueError("cpu_samples_differ")
        q=np.quantile(times/1_000_000,[.5,.95,.99],method="linear")
        if [model[k] for k in ("p50_ms","p95_ms","p99_ms")]!=q.tolist():raise ValueError("cpu_quantile_recount_differs")
        if model["latency_limits_passed"]!=bool(q[1]<=2 and q[2]<=5):raise ValueError("cpu_latency_threshold_changed")
        for parity in model["parity"].values():
            if parity["rows"]!=len(arrays["gold"]) or not parity["allclose"] or parity["winner_mismatches"]:raise ValueError("cpu_parity_failed")
    # Recheck actual tensor identities, not only the fit's self-report.
    import torch
    context_model.authenticate("2f3c86640d5509aeb9c619485f8607c59eb8e373")
    original=torch.load(plan["downstream"]["initial_checkpoint"],map_location="cpu",weights_only=True)["state_dict"]
    controls=[]
    for seed in plan["downstream"]["seeds"]:
        off=torch.load(ROOT/"models"/f"lm_off-s{seed}"/"model.pt",map_location="cpu",weights_only=True)["state_dict"]
        prior=torch.load(PRIOR_ROOT/"models"/f"c2-s{seed}"/"model.pt",map_location="cpu",weights_only=True)["state_dict"]
        lm=torch.load(ROOT/"pretrained"/f"s{seed}"/"model.pt",map_location="cpu",weights_only=True)["state_dict"]
        if set(off)!=set(prior) or not all(torch.equal(off[k],prior[k]) for k in off):raise ValueError("control_tensor_recount_differs")
        if set(lm)!=set(original) or not all(torch.equal(lm[k],original[k]) for k in original if k.startswith("scorer.")):
            raise ValueError("pretraining_scorer_or_parameters_changed")
        controls.append(dict(seed=seed,control_tensor_equal=True,pretraining_scorer_unchanged=True))
    result=dict(kind="language_results_independent_verification",status="passed",scalar_metric_populations=checks,rate_and_wilson_checks=rates,
        primary_intervals_replayed=3,primary_comparisons=primary,registered_advancement=advance,cpu_measured_runs=20000,cpu_winner_mismatches=0,
        control_tensor_checks=controls,script_sha256=sha(__file__),report_sha256=sha(ROOT/"model-report.json"),
        benchmark_sha256=sha(ROOT/"cpu-benchmark/report.json"),gold_certified=False,final_test_used=False,safety_threshold=.0025,
        prior_verification_sha256=sha(ROOT/"result-verification.json"),revision_reason="Independent replay after removing an unused import; no model, metric or criterion change.")
    save(ROOT/"result-verification-r2.json",result);save("reports/issue-41-language-result-verification-r2.json",result)
    return {k:result[k] for k in ("status","scalar_metric_populations","rate_and_wilson_checks","primary_intervals_replayed","registered_advancement","cpu_measured_runs")}


if __name__=="__main__":print(json.dumps(run()))
