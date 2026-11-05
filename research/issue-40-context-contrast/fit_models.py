"""Six paired fixed-budget fits; never load evaluation arrays in this process."""
import argparse
import json
import os
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from model_common import ROOT,TRAIN_ROOT,authenticate,reference,build,growth_training,sha


def run(commit):
    import numpy as np
    import torch
    plan,bound=authenticate(commit);recipe=plan["training"]
    growth=growth_training();prior,_=growth.authenticate_fit(recipe["prior_fit_binding_commit"])
    environment=dict(torch=torch.__version__,numpy=np.__version__,python=__import__("sys").version.split()[0])
    if environment!=prior["environment"] or not torch.cuda.is_available():raise ValueError("fixed_training_environment_changed")
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    harness=reference()
    with np.load(TRAIN_ROOT/"cache/train.npz",allow_pickle=False) as cache:
        arrays={k:np.array(cache[k]) for k in cache.files}
    indices=np.asarray(json.loads((TRAIN_ROOT/"cache/cohorts.json").read_bytes())[recipe["cohort"]],dtype=np.int64)
    if len(indices)!=50000 or len(set(indices.tolist()))!=50000 or np.any(arrays["gold"][indices]<0):raise ValueError("fixed_training_population_differs")
    initial=torch.load(recipe["initial_checkpoint"],map_location="cpu",weights_only=True)["state_dict"]
    output=ROOT/"models";output.mkdir(exist_ok=False)
    run_receipt=dict(kind="paired_context_training",status="failed",fit_commit=commit,environment=environment,
        training_rows=len(indices),evaluation_arrays_loaded=False,kwdlc_training_rows=0,models=[],fits_planned=6)
    start=time.monotonic()
    try:
        for seed in recipe["seeds"]:
            for architecture in plan["architectures"]:
                name=f"{architecture}-s{seed}";directory=output/name;directory.mkdir()
                receipt=dict(kind="context_architecture_fit",status="failed",architecture=architecture,seed=seed,steps=0,
                    fit_commit=commit,initial_checkpoint_sha256=recipe["initial_checkpoint_sha256"])
                fit_start=time.monotonic();losses=[]
                try:
                    harness.seed_everything(seed)
                    model=build(harness,architecture)
                    model.load_state_dict(initial,strict=True)
                    if not all(torch.equal(value,model.state_dict()[key]) for key,value in initial.items()):raise ValueError("initial_mapping_differs")
                    control=harness.build_model("C2").eval();control.load_state_dict(initial,strict=True)
                    sample,_=harness._tensors(arrays,arrays["features"],indices[:2],torch.device("cpu"))
                    sample=list(sample);sample[0]=torch.zeros_like(sample[0]);sample[1]=torch.zeros_like(sample[1])
                    model.eval()
                    with torch.no_grad():torch.testing.assert_close(model(*sample),control(*sample),atol=1e-6,rtol=1e-6)
                    receipt["parameters"]=sum(p.numel() for p in model.parameters())
                    if receipt["parameters"]!=sum(p.numel() for p in control.parameters()):raise ValueError("parameter_count_changed")
                    receipt["empty_context_initial_parity"]=True
                    del control,sample
                    model=model.to("cuda:0");model.train()
                    optimizer=torch.optim.AdamW(model.parameters(),lr=recipe["learning_rate"],weight_decay=recipe["weight_decay"])
                    for step,batch in enumerate(growth.batches(indices,seed,recipe["batch_size"],recipe["updates_per_fit"]),1):
                        if time.monotonic()-fit_start>recipe["max_seconds_per_fit"]:raise TimeoutError("fit_time_bound")
                        inputs,target=harness._tensors(arrays,arrays["features"],batch,torch.device("cuda:0"))
                        optimizer.zero_grad(set_to_none=True)
                        loss=harness.loss_fn(model(*inputs),target,inputs[-1],"C2")
                        if not torch.isfinite(loss):raise ValueError("nonfinite_training_loss")
                        loss.backward()
                        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),recipe["gradient_clip_norm"])
                        if not torch.isfinite(norm):raise ValueError("nonfinite_training_gradient")
                        optimizer.step();losses.append(float(loss.detach().cpu()));receipt["steps"]=step
                        if step%100==0:print(json.dumps(dict(stage="context_fit",architecture=architecture,seed=seed,step=step)),flush=True)
                    state={key:value.detach().cpu() for key,value in model.state_dict().items()}
                    if not all(torch.isfinite(v).all() for v in state.values()):raise ValueError("nonfinite_checkpoint")
                    temporary=directory/"model.partial.pt"
                    torch.save(dict(state_dict=state,architecture=architecture,seed=seed,steps=step,fit_commit=commit),temporary)
                    temporary.rename(directory/"model.pt")
                    write_once(directory/"losses.json",canonical_json_bytes(losses)+b"\n")
                    receipt.update(status="complete",checkpoint_sha256=sha(directory/"model.pt"),examples=step*recipe["batch_size"],
                        mean_loss=sum(losses)/len(losses),last100_loss=sum(losses[-100:])/100)
                    del state,model,optimizer,inputs,target,loss
                    torch.cuda.empty_cache()
                except Exception as error:
                    receipt["error_type"]=type(error).__name__
                    raise
                finally:
                    receipt["elapsed_seconds"]=round(time.monotonic()-fit_start,3)
                    write_once(directory/"execution.json",canonical_json_bytes(receipt)+b"\n")
                    run_receipt["models"].append(dict(name=name,status=receipt["status"],execution_sha256=sha(directory/"execution.json"),checkpoint_sha256=receipt.get("checkpoint_sha256")))
        authenticate(commit)
        if len(run_receipt["models"])!=6:raise ValueError("fixed_fit_population_incomplete")
        run_receipt["status"]="complete"
    except Exception as error:
        run_receipt["error_type"]=type(error).__name__
        raise
    finally:
        run_receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        run_receipt["not_attempted_fits"]=6-len(run_receipt["models"])
        write_once(ROOT/"training-execution.json",canonical_json_bytes(run_receipt)+b"\n")
    return run_receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--fit-commit",required=True)
    r=run(parser.parse_args().fit_commit);print(json.dumps({k:r[k] for k in ("status","elapsed_seconds","not_attempted_fits")}))
