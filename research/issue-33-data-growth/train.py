"""Nine fixed-budget adaptations; development tensors never enter this process."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from extend_wiki import ROOT,bound_plan
from prepare_sources import sha

PLAN_COMMIT="1ca3fb4ff9670d1cd12f21e4d87f6bb975248415"
FIT_BINDING=Path("manifests/data-growth-fit-binding-v2.json")
H21=Path("data/generated/issue-21-retrain/run.py")
H21_SHA="d0e24a57ccf9d5a1aa5fc3c9de0b3ff4ef8124bd15c126fc47c9c3bfbf55216d"


def harness():
    for path in (H21,Path("research/issue-21-retrain/run.py")):
        if sha(path)!=H21_SHA:raise ValueError("fixed_model_implementation_changed")
    spec=importlib.util.spec_from_file_location("growth_h21",H21)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def authenticate_fit(commit):
    if len(commit)!=40 or any(c not in "0123456789abcdef" for c in commit):raise ValueError("full_fit_commit_required")
    raw=subprocess.check_output(["git","show",commit+":"+FIT_BINDING.as_posix()],timeout=30)
    if raw!=FIT_BINDING.read_bytes():raise ValueError("fit_binding_changed")
    binding=json.loads(raw)
    for artifact in binding["artifacts"]:
        if sha(Path(artifact["path"]))!=artifact["sha256"]:raise ValueError("fit_artifact_changed")
    plan,plan_sha=bound_plan(PLAN_COMMIT)
    if plan_sha!=binding["plan_sha256"]:raise ValueError("fit_plan_changed")
    return binding,plan


def batches(indices,seed,batch_size,steps):
    import numpy as np
    import torch
    generator=torch.Generator(device="cpu").manual_seed(seed)
    pending=np.empty(0,dtype=np.int64)
    for _ in range(steps):
        while len(pending)<batch_size:
            pending=np.concatenate((pending,indices[torch.randperm(len(indices),generator=generator).numpy()]))
        yield pending[:batch_size]
        pending=pending[batch_size:]


def run(commit):
    import numpy as np
    import torch
    binding,plan=authenticate_fit(commit)
    environment=dict(torch=torch.__version__,numpy=np.__version__,python=__import__("sys").version.split()[0])
    if environment!=binding["environment"]:raise ValueError("frozen_training_environment_changed")
    if not torch.cuda.is_available():raise ValueError("registered_cuda_environment_required")
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    h21=harness();recipe=plan["training"]
    with np.load(ROOT/"cache/train.npz",allow_pickle=False) as cache:arrays={k:np.array(cache[k]) for k in cache.files}
    cohorts=json.loads((ROOT/"cache/cohorts.json").read_bytes())
    initial=torch.load(recipe["initial_checkpoint"],map_location="cpu",weights_only=True)["state_dict"]
    output=ROOT/"training";output.mkdir(exist_ok=False)
    run_receipt=dict(kind="growth_training_execution",status="failed",fit_commit=commit,
        fit_binding_sha256=hashlib.sha256(FIT_BINDING.read_bytes()).hexdigest(),environment=environment,
        gpu=torch.cuda.get_device_name(0),development_arrays_loaded=False,models=[],gold_certified=False)
    start=time.monotonic()
    try:
        for cohort in ("wiki_small","wiki_large","mixed"):
            indices=np.asarray(cohorts[cohort],dtype=np.int64)
            expected=12516 if cohort=="wiki_small" else 50000
            if len(indices)!=expected or len(set(indices.tolist()))!=expected or np.any(arrays["gold"][indices]<0):
                raise ValueError("training_cohort_contract_differs")
            for seed in recipe["seeds"]:
                name=f"{cohort}-s{seed}"
                directory=output/name;directory.mkdir()
                receipt=dict(kind="growth_fit",status="failed",cohort=cohort,seed=seed,steps=0,
                    initial_checkpoint_sha256=recipe["initial_checkpoint_sha256"],fit_commit=commit)
                fit_start=time.monotonic();losses=[]
                try:
                    h21.seed_everything(seed)
                    model=h21.build_model("C2")
                    model.load_state_dict(initial,strict=True)
                    if not all(torch.equal(model.state_dict()[key],value) for key,value in initial.items()):raise ValueError("initial_weights_differ")
                    model=model.to("cuda:0");model.train()
                    optimizer=torch.optim.AdamW(model.parameters(),lr=recipe["learning_rate"],weight_decay=recipe["weight_decay"])
                    for step,batch in enumerate(batches(indices,seed,recipe["batch_size"],recipe["updates_per_fit"]),1):
                        if time.monotonic()-fit_start>1800:raise TimeoutError("fit_wall_time_bound")
                        inputs,target=h21._tensors(arrays,arrays["features"],batch,torch.device("cuda:0"))
                        optimizer.zero_grad(set_to_none=True)
                        loss=h21.loss_fn(model(*inputs),target,inputs[-1],"C2")
                        if not torch.isfinite(loss):raise ValueError("non_finite_training_loss")
                        loss.backward()
                        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),recipe["gradient_clip_norm"])
                        if not torch.isfinite(norm):raise ValueError("non_finite_training_gradient")
                        optimizer.step()
                        losses.append(float(loss.detach().cpu()));receipt["steps"]=step
                        if step%100==0:print(json.dumps(dict(stage="fit",cohort=cohort,seed=seed,step=step,elapsed_seconds=round(time.monotonic()-fit_start,1))),flush=True)
                    state={key:value.detach().cpu() for key,value in model.state_dict().items()}
                    if not all(torch.isfinite(value).all() for value in state.values()):raise ValueError("non_finite_final_weights")
                    temporary=directory/"model.partial.pt"
                    torch.save(dict(state_dict=state,cohort=cohort,seed=seed,updates=receipt["steps"]),temporary)
                    temporary.rename(directory/"model.pt")
                    receipt.update(status="complete",checkpoint_sha256=sha(directory/"model.pt"),
                        examples=receipt["steps"]*recipe["batch_size"],mean_loss=sum(losses)/len(losses),last_100_loss=sum(losses[-100:])/100)
                    write_once(directory/"losses.json",canonical_json_bytes(losses)+b"\n")
                    del state,model,optimizer,inputs,target,loss
                    torch.cuda.empty_cache()
                except Exception as error:
                    receipt["error_type"]=type(error).__name__
                    raise
                finally:
                    receipt["elapsed_seconds"]=round(time.monotonic()-fit_start,3)
                    write_once(directory/"execution.json",canonical_json_bytes(receipt)+b"\n")
                run_receipt["models"].append(dict(name=name,checkpoint_sha256=receipt["checkpoint_sha256"],execution_sha256=sha(directory/"execution.json")))
        if len(run_receipt["models"])!=9:raise ValueError("incomplete_fixed_fit_population")
        run_receipt["status"]="complete"
        return run_receipt
    except Exception as error:
        run_receipt["error_type"]=type(error).__name__
        raise
    finally:
        run_receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(output/"execution.json",canonical_json_bytes(run_receipt)+b"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--fit-commit",required=True)
    print(canonical_json_bytes(run(parser.parse_args().fit_commit)).decode("utf-8"))
