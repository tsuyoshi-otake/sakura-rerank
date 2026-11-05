"""Independent scalar recount of every backend, condition, gate and population."""
import json
import math
from pathlib import Path

import numpy as np

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from evaluate_models import bound_evaluation
from model_common import ROOT,sha

EVALUATION_COMMIT="a4af7e05fcbac9f4561f5f988b503f62d31859bf"


def recount(arrays,scores,indexes,gated):
    counts=dict(rows=len(indexes),baseline_correct=0,correct=0,rescue=0,harm=0,
                wrong_to_wrong=0,changed=0,candidate_acquisition_failure=0,
                model_inference_failure=0,source_absent_top6=0,source_present_top6_but_not_correct=0)
    for i in indexes:
        valid=[j for j in range(6) if arrays["candidate_mask"][i,j]]
        finite=all(math.isfinite(float(s)) for s in scores[i])
        winner=max(valid,key=lambda j:float(scores[i,j])) if valid and finite else 0
        if gated and valid and finite and float(scores[i,winner]-scores[i,0])<=1.7:winner=0
        base=bool(arrays["correct_mask"][i,0]);correct=bool(arrays["correct_mask"][i,winner])
        changed=bool(valid) and not bool(arrays["baseline_equivalent"][i,winner])
        present=bool(any(arrays["correct_mask"][i]))
        values=dict(baseline_correct=base,correct=correct,rescue=not base and correct,harm=base and not correct,
            wrong_to_wrong=not base and not correct and changed,changed=changed,
            candidate_acquisition_failure=not valid,model_inference_failure=bool(valid) and not finite,
            source_absent_top6=not present,source_present_top6_but_not_correct=present and not correct)
        for key,value in values.items():counts[key]+=int(bool(value))
    counts["baseline_errors"]=counts["rows"]-counts["baseline_correct"]
    counts["correction_failure"]=counts["harm"]+counts["wrong_to_wrong"]
    return counts


def verify_rate(rate,numerator,denominator):
    if (rate["numerator"],rate["denominator"])!=(numerator,denominator):raise ValueError("rate_denominator_differs")
    expected=numerator/denominator if denominator else None
    if rate["value"]!=expected:raise ValueError("rate_value_differs")
    if denominator:
        z=1.959963984540054; center=(expected+z*z/(2*denominator))/(1+z*z/denominator)
        half=z*math.sqrt(expected*(1-expected)/denominator+z*z/(4*denominator*denominator))/(1+z*z/denominator)
        if not np.allclose(rate["wilson95_row_assumption"],[max(0,center-half),min(1,center+half)],atol=1e-12,rtol=0):
            raise ValueError("wilson_interval_differs")


def run():
    plan,bound=bound_evaluation(EVALUATION_COMMIT)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    checks=0;rate_checks=0;artifacts={};primary=[]
    for score_path,report_path in ((ROOT/"scores/all.npz",Path("reports/issue-40-context-models-v1.json")),
            (ROOT/"numerical-audit/cpu-scores.npz",Path("reports/issue-40-context-models-cpu-v1.json"))):
        report=json.loads(report_path.read_bytes())
        if sha(score_path)!=report["scores_sha256"]:raise ValueError("score_hash_changed")
        with np.load(score_path,allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
        expected={mode+"/"+m["name"] for mode in conditions["contexts"] for m in bound["models"]}
        if set(scores)!=expected or len(scores)!=21:raise ValueError("missing_score_condition")
        for label,values in scores.items():
            for gate in ("ungated","gated"):
                for population,indexes in conditions["populations"].items():
                    actual=recount(arrays,values,indexes,gate=="gated")
                    recorded=report["metrics"][gate+"/"+label][population]
                    for key,value in actual.items():
                        if recorded[key]!=value:raise ValueError("scalar_metric_recount_differs:"+key)
                    c=actual;n=c["rows"];errors=c["baseline_errors"]
                    for key,num,den in (("accuracy",c["correct"],n),("baseline_accuracy",c["baseline_correct"],n),
                            ("precision",c["rescue"],c["changed"]),("recall",c["rescue"],errors),
                            ("application",c["changed"],n),("application_to_error",c["rescue"]+c["wrong_to_wrong"],errors),
                            ("harm_rate",c["harm"],c["baseline_correct"])):
                        verify_rate(recorded[key],num,den);rate_checks+=1
                    if recorded["baseline_gain"]!=(c["rescue"]-c["harm"])/n:raise ValueError("gain_differs")
                    if c["correct"]!=c["baseline_correct"]+c["rescue"]-c["harm"]:raise ValueError("count_identity_differs")
                    checks+=1
        for comparison in report["primary_comparisons"]:
            seed=comparison["seed"];prefix="ungated/intact/"
            delta=report["metrics"][prefix+f"context_initialized-s{seed}"]["main"]["correct"]-report["metrics"][prefix+f"c2-s{seed}"]["main"]["correct"]
            if comparison["main_net_rows"]!=delta or comparison["main_difference"]!=delta/991:raise ValueError("primary_difference_differs")
        advance=(all(r["main_net_rows"]>=0 for r in report["primary_comparisons"])
                 and sum(r["main_net_rows"] for r in report["primary_comparisons"])>0
                 and all(r["main_paired_ci95"][0]>0 for r in report["primary_comparisons"])
                 and sum(r["supported_contrast_net_rows"]>0 for r in report["primary_comparisons"])>=2)
        if advance or report["conditioned_structure_advances"] or report["next_research_structure"]!="c2":raise ValueError("registered_structure_decision_differs")
        if report["safety_threshold"]!=.0025 or report["gold_certified"] or report["final_test_used"] or report["production_adoption"]:
            raise ValueError("quality_safety_scope_changed")
        artifacts[str(score_path)]=sha(score_path);artifacts[str(report_path)]=sha(report_path)
        primary.append(dict(report=str(report_path),net_rows=[r["main_net_rows"] for r in report["primary_comparisons"]],advance=False))
    benchmark=json.loads((ROOT/"cpu-benchmark-r4/report.json").read_bytes())
    if (benchmark["status"]!="complete" or len(benchmark["models"])!=2 or not benchmark["gpu_disabled"]
            or [benchmark[k] for k in ("batch","intra_op_threads","inter_op_threads","warmup","measured_per_model")]!=[1,1,1,200,10000]):
        raise ValueError("cpu_contract_differs")
    for model in benchmark["models"]:
        directory=ROOT/"cpu-benchmark-r4"/model["model"]
        if model["status"]!="complete" or model["measured"]!=10000 or model["failures"] or model["unattempted_measured_runs"]:raise ValueError("cpu_population_differs")
        for filename,key in (("model-fp32.onnx","onnx_sha256"),("latencies-ns.npy","latency_samples_sha256")):
            if sha(directory/filename)!=model[key]:raise ValueError("cpu_artifact_changed")
        times=np.load(directory/"latencies-ns.npy",allow_pickle=False)
        if times.shape!=(10000,) or np.any(times<=0):raise ValueError("cpu_samples_differ")
        quantiles=np.quantile(times/1_000_000,[.5,.95,.99],method="linear")
        if [model[k] for k in ("p50_ms","p95_ms","p99_ms")]!=quantiles.tolist():raise ValueError("cpu_quantiles_differ")
        if not model["latency_limits_passed"] or quantiles[1]>2 or quantiles[2]>5:raise ValueError("cpu_limits_failed")
        for parity in model["parity"].values():
            if parity["rows"]!=1215 or not parity["allclose"] or parity["winner_mismatches"]:raise ValueError("cpu_parity_failed")
    failures=[]
    for directory in ("cpu-benchmark","cpu-benchmark-r2","cpu-benchmark-r3"):
        path=ROOT/directory/"report.json";saved=json.loads(path.read_bytes())
        if saved["status"]!="failed":raise ValueError("prior_failed_attempt_replaced")
        failures.append(dict(path=str(path),sha256=sha(path),error_type=saved["error_type"]))
    r3_samples=ROOT/"cpu-benchmark-r3/c2-s20260814/latencies-ns.npy"
    if np.load(r3_samples,allow_pickle=False).shape!=(10000,):raise ValueError("failed_finalization_samples_lost")
    result=dict(kind="context_results_independent_verification",status="passed",scalar_metric_populations=checks,
        rate_and_wilson_checks=rate_checks,models=7,contexts=3,gates=2,populations=3,backends=2,
        bound_models_authenticated=len(bound["models"]),primary=primary,cpu_models=2,cpu_measured_runs=20000,
        cpu_winner_mismatches=0,failed_attempts_preserved=failures,
        failed_finalization_samples=dict(rows=10000,sha256=sha(r3_samples),used_for_final_benchmark=False),
        artifacts=artifacts,script_sha256=sha(__file__),gold_certified=False,final_test_used=False,safety_threshold=plan["safety_threshold"])
    for path in (ROOT/"result-verification.json",Path("reports/issue-40-context-result-verification-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return {k:result[k] for k in ("status","scalar_metric_populations","rate_and_wilson_checks","cpu_measured_runs")}


if __name__=="__main__":print(json.dumps(run()))
