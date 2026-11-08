"""Post-observation backend diagnosis; fixed checkpoints and original scores stay intact."""
import json
import os
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.growth_metrics import observe
from evaluate_models import bound_evaluation,context_arrays
from model_common import ROOT,reference,build,sha

EVALUATION_COMMIT="a4af7e05fcbac9f4561f5f988b503f62d31859bf"


def run():
    import numpy as np
    import torch
    _,bound=bound_evaluation(EVALUATION_COMMIT)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    harness=reference();harness.seed_everything(20261105)
    settings_before=dict(cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
                         cuda_matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32,
                         float32_matmul_precision=torch.get_float32_matmul_precision())
    torch.backends.cudnn.allow_tf32=False
    torch.backends.cuda.matmul.allow_tf32=False
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as p:arrays={k:np.array(p[k]) for k in p.files}
    execution=json.loads((ROOT/"scores/execution.json").read_bytes())
    if sha(ROOT/"scores/all.npz")!=execution["scores_sha256"]:raise ValueError("original_scores_changed")
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as p:original={k:np.array(p[k]) for k in p.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    output=ROOT/"numerical-audit";output.mkdir(exist_ok=False)
    cpu_scores,strict_scores,comparisons={},{},[]
    for item in bound["models"]:
        model=build(harness,item["architecture"]).eval()
        model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
        for context in conditions["contexts"]:
            modified=context_arrays(arrays,conditions,context)
            key=context+"/"+item["name"]
            cpu_scores[key]=harness.score_rows(model,modified,modified["features"],np.arange(len(arrays["gold"])))
        model=model.to("cuda:0")
        for context in conditions["contexts"]:
            modified=context_arrays(arrays,conditions,context)
            key=context+"/"+item["name"]
            strict=harness.score_rows(model,modified,modified["features"],np.arange(len(arrays["gold"])))
            strict_scores[key]=strict;cpu=cpu_scores[key];gpu=original[key]
            row=dict(model=item["name"],context=context,
                default_gpu_vs_cpu_max_abs=float(np.abs(gpu-cpu).max()),strict_gpu_vs_cpu_max_abs=float(np.abs(strict-cpu).max()),
                strict_gpu_cpu_allclose=bool(np.allclose(strict,cpu,atol=1e-5,rtol=1e-5)),outcomes={})
            for gate in ("ungated","gated"):
                old=observe(arrays,gpu,gate);now=observe(arrays,cpu,gate);precise=observe(arrays,strict,gate)
                row["outcomes"][gate]=dict(default_to_cpu_winner_changes=int((old["predicted"]!=now["predicted"]).sum()),
                    strict_to_cpu_winner_changes=int((precise["predicted"]!=now["predicted"]).sum()),
                    default_to_cpu_source_correct_changes=int((old["correct"]!=now["correct"]).sum()),
                    default_to_cpu_application_changes=int((old["changed"]!=now["changed"]).sum()))
            comparisons.append(row)
        del model;torch.cuda.empty_cache()
        print(json.dumps(dict(stage="numerical_backend_audit",model=item["name"])),flush=True)
    np.savez_compressed(output/"cpu-scores.npz",**cpu_scores)
    np.savez_compressed(output/"strict-gpu-scores.npz",**strict_scores)
    result=dict(kind="context_model_backend_diagnosis",post_observation_diagnostic=True,
        original_gpu_scores_sha256=execution["scores_sha256"],script_sha256=sha(__file__),
        cpu_scores_sha256=sha(output/"cpu-scores.npz"),strict_gpu_scores_sha256=sha(output/"strict-gpu-scores.npz"),
        settings_before=settings_before,settings_after=dict(cudnn_allow_tf32=False,cuda_matmul_allow_tf32=False),
        comparisons=comparisons,all_strict_gpu_cpu_scores_close=all(r["strict_gpu_cpu_allclose"] for r in comparisons),
        all_original_source_outcomes_unchanged=all(o["default_to_cpu_source_correct_changes"]==0 and o["default_to_cpu_application_changes"]==0 for r in comparisons for o in r["outcomes"].values()),
        models_retrained=0,thresholds_changed=False,original_results_replaced=False,safety_threshold=.0025)
    for path in (output/"report.json",Path("reports/issue-40-context-numerical-audit-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return dict(settings_before=settings_before,all_strict_gpu_cpu_scores_close=result["all_strict_gpu_cpu_scores_close"],
                all_original_source_outcomes_unchanged=result["all_original_source_outcomes_unchanged"],
                maximum_default_gpu_cpu_difference=max(r["default_gpu_vs_cpu_max_abs"] for r in comparisons),
                maximum_strict_gpu_cpu_difference=max(r["strict_gpu_vs_cpu_max_abs"] for r in comparisons))


if __name__=="__main__":print(json.dumps(run()))
