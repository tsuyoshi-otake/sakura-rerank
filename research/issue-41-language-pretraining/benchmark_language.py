"""Preregistered Windows CPU ONNX parity and timing for LM-on/off models."""
import argparse
from collections import Counter
import json
import os
import platform
import time

os.environ["CUDA_VISIBLE_DEVICES"]="-1"
os.environ["OMP_NUM_THREADS"]="1"
os.environ["MKL_NUM_THREADS"]="1"

from language_common import ROOT,context_model,context_arrays,read_json,save,sha,boundary
from evaluate_language import bound_evaluation


def run(evaluation_commit,implementation_commit):
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    boundary.committed("research/issue-41-language-pretraining/benchmark_language.py",implementation_commit)
    plan,bound=bound_evaluation(evaluation_commit);recipe=plan["cpu_benchmark"]
    if platform.system()!="Windows" or torch.cuda.is_available():raise ValueError("windows_cpu_only_benchmark")
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    with np.load(ROOT/"scores/all.npz",allow_pickle=False) as saved:scores={k:np.array(saved[k]) for k in saved.files}
    if sha(ROOT/"scores/all.npz")!=read_json(ROOT/"scores/execution.json")["scores_sha256"]:raise ValueError("cpu_reference_scores_changed")
    conditions=read_json(ROOT/"conditions.json");chosen=[m for m in bound["models"] if m.get("seed")==recipe["seed"]]
    if [m["mode"] for m in chosen]!=["lm_off","lm_on"]:raise ValueError("benchmark_models_changed")
    output=ROOT/"cpu-benchmark";output.mkdir(exist_ok=False);harness=context_model.reference();start=time.monotonic()
    receipt=dict(kind="language_cpu_benchmark",status="failed",models=[],implementation_commit=implementation_commit,evaluation_commit=evaluation_commit,
        script_sha256=sha(__file__),environment=dict(python=platform.python_version(),torch=torch.__version__,onnx=onnx.__version__,onnxruntime=ort.__version__,platform=platform.platform(),processor=platform.processor()),
        gpu_disabled=True,providers=["CPUExecutionProvider"],recipe=recipe,production_eligible=False)
    try:
        for item in chosen:
            directory=output/item["name"];directory.mkdir();model_start=time.monotonic()
            result=dict(model=item["name"],status="failed",measured=0,failures=0,parity={})
            try:
                model=harness.build_model("C2").eval();model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
                inputs,_=harness._tensors(arrays,arrays["features"],np.array([0]),torch.device("cpu"));names=list(harness.INPUT_NAMES)
                path=directory/"model-fp32.onnx"
                torch.onnx.export(model,tuple(inputs),path,input_names=names,output_names=["scores"],opset_version=18,dynamo=False,
                    dynamic_axes={name:{0:"batch"} for name in (*names,"scores")},do_constant_folding=True)
                onnx.checker.check_model(onnx.load(path))
                options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                session=ort.InferenceSession(str(path),sess_options=options,providers=["CPUExecutionProvider"])
                if session.get_providers()!=["CPUExecutionProvider"]:raise ValueError("unexpected_cpu_provider")
                intact_feeds=None
                for mode in conditions["contexts"]:
                    modified=context_arrays(arrays,conditions,mode)
                    feeds=[{name:modified[name][i:i+1] for name in names} for i in range(len(arrays["gold"]))]
                    actual=np.concatenate([session.run(["scores"],feed)[0] for feed in feeds]);expected=scores[mode+"/"+item["name"]]
                    parity=dict(rows=len(actual),max_absolute_difference=float(np.abs(actual-expected).max()),
                        allclose=bool(np.allclose(actual,expected,atol=recipe["atol"],rtol=recipe["rtol"])),
                        winner_mismatches=int((actual.argmax(axis=1)!=expected.argmax(axis=1)).sum()))
                    result["parity"][mode]=parity
                    if not np.isfinite(actual).all() or not parity["allclose"] or parity["winner_mismatches"]:raise ValueError("cpu_export_parity_failed")
                    if mode=="intact":intact_feeds=feeds
                for i in range(recipe["warmup"]):session.run(["scores"],intact_feeds[i%len(intact_feeds)])
                times=np.empty(recipe["runs"],dtype=np.int64);errors=Counter()
                for i in range(recipe["runs"]):
                    if time.monotonic()-model_start>180:raise TimeoutError("cpu_benchmark_time_bound")
                    tick=time.perf_counter_ns()
                    try:session.run(["scores"],intact_feeds[i%len(intact_feeds)])
                    except Exception as error:errors[type(error).__name__]+=1
                    times[i]=time.perf_counter_ns()-tick;result["measured"]=i+1
                np.save(directory/"latencies-ns.npy",times,allow_pickle=False);ms=times/1_000_000;q=np.quantile(ms,[.5,.95,.99],method="linear")
                result.update(status="complete" if not errors else "complete_with_failures",failures=sum(errors.values()),error_types=dict(errors),
                    p50_ms=float(q[0]),p95_ms=float(q[1]),p99_ms=float(q[2]),maximum_ms=float(ms.max()),
                    latency_limits_passed=bool(not errors and q[1]<=recipe["p95_ms_max"] and q[2]<=recipe["p99_ms_max"]),
                    onnx_sha256=sha(path),onnx_bytes=path.stat().st_size,latency_samples_sha256=sha(directory/"latencies-ns.npy"))
                del model,session,intact_feeds,feeds
            except Exception as error:result["error_type"]=type(error).__name__;raise
            finally:
                result.update(elapsed_seconds=round(time.monotonic()-model_start,3),unattempted_runs=recipe["runs"]-result["measured"])
                receipt["models"].append(result);save(directory/"report.json",result)
            print(json.dumps({k:result[k] for k in ("model","measured","failures","p95_ms","p99_ms","latency_limits_passed")}),flush=True)
        bound_evaluation(evaluation_commit);receipt["status"]="complete"
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt.update(elapsed_seconds=round(time.monotonic()-start,3),unattempted_models=2-len(receipt["models"]))
        save(output/"report.json",receipt);save("reports/issue-41-language-cpu-v1.json",receipt)
    return dict(status=receipt["status"],models=len(receipt["models"]),elapsed_seconds=receipt["elapsed_seconds"])


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--evaluation-commit",required=True);parser.add_argument("--implementation-commit",required=True)
    args=parser.parse_args();print(json.dumps(run(args.evaluation_commit,args.implementation_commit)))
