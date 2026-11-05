"""Prespecified CPU-only export parity and 10,000-run research benchmarks."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import time

# Must precede importing Torch/ORT; this process never uses a GPU.
os.environ["CUDA_VISIBLE_DEVICES"]="-1"
os.environ["OMP_NUM_THREADS"]="1"
os.environ["MKL_NUM_THREADS"]="1"
os.environ["OPENBLAS_NUM_THREADS"]="1"

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from evaluate_models import bound_evaluation,context_arrays
from model_common import ROOT,reference,build,sha
from feasibility import boundary


def run(evaluation_commit,implementation_commit):
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    path=Path(__file__).resolve().relative_to(Path.cwd())
    boundary.committed(path,implementation_commit)
    _,bound=bound_evaluation(evaluation_commit)
    if platform.system()!="Windows" or torch.cuda.is_available():raise ValueError("windows_cpu_only_benchmark_required")
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    harness=reference()
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    score_receipt=json.loads((ROOT/"scores/execution.json").read_bytes())
    if sha(ROOT/"scores/all.npz")!=score_receipt["scores_sha256"]:raise ValueError("score_parity_reference_changed")
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
    conditions=json.loads((ROOT/"model-conditions.json").read_bytes())
    chosen=[model for model in bound["models"] if model.get("seed")==20260814]
    if [m["architecture"] for m in chosen]!=["c2","context_initialized"]:raise ValueError("benchmark_seed_or_architectures_changed")
    prior=ROOT/"cpu-benchmark/report.json"
    prior_report=json.loads(prior.read_bytes())
    if prior_report["status"]!="failed" or prior_report["models"][0]["measured"]!=0:
        raise ValueError("preserved_first_export_failure_required")
    output=ROOT/"cpu-benchmark-r2";output.mkdir(exist_ok=False)
    receipt=dict(kind="context_architecture_cpu_benchmark",status="failed",implementation_commit=implementation_commit,
        evaluation_commit=evaluation_commit,script_sha256=sha(__file__),gpu_disabled=True,
        environment=dict(python=platform.python_version(),torch=torch.__version__,onnx=onnx.__version__,onnxruntime=ort.__version__,
                         platform=platform.platform(),processor=platform.processor()),
        batch=1,intra_op_threads=1,inter_op_threads=1,warmup=200,measured_per_model=10000,models=[],production_eligible=False,
        adapter_revision=2,prior_failed_report_sha256=sha(prior),
        revision_reason="The legacy exporter treats a list as one positional argument; pass the eight tensors as a tuple. No model, input, metric or timing condition changed.")
    start=time.monotonic()
    try:
        for item in chosen:
            directory=output/item["name"];directory.mkdir()
            result=dict(model=item["name"],architecture=item["architecture"],status="failed",measured=0,failures=0)
            model_start=time.monotonic()
            try:
                model=build(harness,item["architecture"]).eval()
                model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
                inputs,_=harness._tensors(arrays,arrays["features"],np.array([0]),torch.device("cpu"))
                onnx_path=directory/"model-fp32.onnx"
                names=list(harness.INPUT_NAMES)
                torch.onnx.export(model,tuple(inputs),onnx_path,input_names=names,output_names=["scores"],
                    dynamic_axes={name:{0:"batch"} for name in (*names,"scores")},opset_version=18,dynamo=False,do_constant_folding=True)
                onnx.checker.check_model(onnx.load(onnx_path))
                options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
                options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                session=ort.InferenceSession(str(onnx_path),sess_options=options,providers=["CPUExecutionProvider"])
                if session.get_providers()!=["CPUExecutionProvider"]:raise ValueError("unexpected_execution_provider")
                parity={};latency_feeds=None
                for context in conditions["contexts"]:
                    modified=context_arrays(arrays,conditions,context)
                    feeds=[{name:modified[name][i:i+1] for name in names} for i in range(len(arrays["gold"]))]
                    actual=np.concatenate([session.run(["scores"],feed)[0] for feed in feeds])
                    expected=scores[context+"/"+item["name"]]
                    if not np.isfinite(actual).all():raise ValueError("nonfinite_export_scores")
                    parity[context]=dict(rows=len(actual),maximum_absolute_difference=float(np.max(np.abs(actual-expected))),
                        winner_mismatches=int((actual.argmax(axis=1)!=expected.argmax(axis=1)).sum()),
                        allclose=bool(np.allclose(actual,expected,atol=1e-5,rtol=1e-5)))
                    if not parity[context]["allclose"] or parity[context]["winner_mismatches"]:raise ValueError("export_score_or_winner_parity_failed")
                    if context=="intact":latency_feeds=feeds
                for i in range(200):session.run(["scores"],latency_feeds[i%len(latency_feeds)])
                times=np.empty(10000,dtype=np.int64);errors=Counter()
                for i in range(10000):
                    if time.monotonic()-model_start>180:raise TimeoutError("benchmark_wall_time_bound")
                    tick=time.perf_counter_ns()
                    try:session.run(["scores"],latency_feeds[i%len(latency_feeds)])
                    except Exception as error:errors[type(error).__name__]+=1
                    times[i]=time.perf_counter_ns()-tick
                    result["measured"]=i+1
                np.save(directory/"latencies-ns.npy",times,allow_pickle=False)
                milliseconds=times/1_000_000.0
                quantiles=np.quantile(milliseconds,[.5,.95,.99],method="linear")
                result.update(status="complete" if not errors else "complete_with_failures",failures=sum(errors.values()),
                    error_types=dict(errors),onnx_sha256=sha(onnx_path),onnx_bytes=onnx_path.stat().st_size,parity=parity,
                    p50_ms=float(quantiles[0]),p95_ms=float(quantiles[1]),p99_ms=float(quantiles[2]),maximum_ms=float(milliseconds.max()),
                    latency_samples_sha256=sha(directory/"latencies-ns.npy"),
                    latency_limits_passed=not errors and quantiles[1]<=2.0 and quantiles[2]<=5.0)
                del session,model,latency_feeds,feeds
            except Exception as error:
                result["error_type"]=type(error).__name__;raise
            finally:
                result["elapsed_seconds"]=round(time.monotonic()-model_start,3)
                result["unattempted_measured_runs"]=10000-result["measured"]
                write_once(directory/"report.json",canonical_json_bytes(result)+b"\n")
                receipt["models"].append(result)
            print(json.dumps({k:result[k] for k in ("model","measured","failures","p50_ms","p95_ms","p99_ms","latency_limits_passed")}),flush=True)
        bound_evaluation(evaluation_commit)
        receipt["status"]="complete"
    except Exception as error:
        receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(output/"report.json",canonical_json_bytes(receipt)+b"\n")
        write_once(Path("reports/issue-40-context-cpu-r2.json"),canonical_json_bytes(receipt)+b"\n")
    return dict(status=receipt["status"],models=len(receipt["models"]),elapsed_seconds=receipt["elapsed_seconds"])


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--evaluation-commit",required=True);parser.add_argument("--implementation-commit",required=True)
    args=parser.parse_args();print(json.dumps(run(args.evaluation_commit,args.implementation_commit)))
