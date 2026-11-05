"""Three fixed LM runs and six paired downstream fits without evaluation access."""
import argparse
import json
import os
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

from sakura_rerank.language_pretraining import encoder_parameters,next_character_logits
from language_common import ROOT,PRIOR_ROOT,TRAIN_ROOT,context_model,read_json,save,sha
from fit_contract import authenticate,BINDING


def forbid_evaluation_access(event,args):
    if event!="open" or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
    path=os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
    protected=[ROOT/"cache",ROOT/"source",ROOT/"candidates",PRIOR_ROOT/"cache",PRIOR_ROOT/"source",PRIOR_ROOT/"candidates"]
    files=[ROOT/"forward-targets.jsonl",ROOT/"selected.jsonl",ROOT/"pool.jsonl",TRAIN_ROOT/"cache/evaluation.npz",TRAIN_ROOT/"cache/evaluation-metadata.jsonl"]
    if any(path==os.path.normcase(os.path.abspath(p)) or path.startswith(os.path.normcase(os.path.abspath(p))+os.sep) for p in protected+files):
        raise PermissionError("evaluation_input_open_forbidden_in_training")


def checkpoint(torch,model,optimizer,directory,metadata):
    state={k:v.detach().cpu() for k,v in model.state_dict().items()}
    if not all(torch.isfinite(v).all() for v in state.values()):raise ValueError("nonfinite_language_weights")
    path=directory/"model.pt";torch.save(dict(state_dict=state,**metadata),directory/"model.partial.pt")
    (directory/"model.partial.pt").rename(path)
    torch.save(optimizer.state_dict(),directory/"optimizer.partial.pt");(directory/"optimizer.partial.pt").rename(directory/"optimizer.pt")
    return sha(path),sha(directory/"optimizer.pt")


def train_lm(torch,harness,growth,initial,arrays,recipe,seed,directory,commit,run_start):
    receipt=dict(kind="causal_character_pretraining",status="failed",seed=seed,steps=0,fit_commit=commit,scorer_unchanged=False)
    start=time.monotonic();losses=[]
    try:
        harness.seed_everything(seed);model=harness.build_model("C2");model.load_state_dict(initial,strict=True);model=model.to("cuda:0").train()
        parameters=encoder_parameters(model);optimizer=torch.optim.AdamW(parameters,lr=recipe["learning_rate"],weight_decay=recipe["weight_decay"])
        import numpy as np
        indices=np.arange(len(arrays["next_ids"]),dtype=np.int64)
        for step,batch in enumerate(growth.batches(indices,seed,recipe["batch_size"],recipe["updates"]),1):
            if time.monotonic()-start>recipe["maximum_seconds_per_seed"] or time.monotonic()-run_start>recipe["maximum_total_gpu_seconds"]:
                raise TimeoutError("registered_language_time_budget")
            ids=torch.as_tensor(arrays["context_ids"][batch].astype(np.int64),device="cuda:0")
            lengths=torch.as_tensor(arrays["context_lengths"][batch].astype(np.int64),device="cuda:0")
            target=torch.as_tensor(arrays["next_ids"][batch].astype(np.int64),device="cuda:0")
            optimizer.zero_grad(set_to_none=True);loss=torch.nn.functional.cross_entropy(next_character_logits(model,ids,lengths),target)
            if not torch.isfinite(loss):raise ValueError("nonfinite_language_loss")
            loss.backward();norm=torch.nn.utils.clip_grad_norm_(parameters,recipe["gradient_clip_norm"])
            if not torch.isfinite(norm):raise ValueError("nonfinite_language_gradient")
            optimizer.step();losses.append(float(loss.detach().cpu()));receipt["steps"]=step
            if step%200==0:print(json.dumps(dict(stage="language_pretraining",seed=seed,step=step,elapsed_seconds=round(time.monotonic()-start,1))),flush=True)
        if not all(torch.equal(value.detach().cpu(),initial[key]) for key,value in model.state_dict().items() if key.startswith("scorer.")):
            raise ValueError("language_pretraining_changed_scorer")
        model_sha,optimizer_sha=checkpoint(torch,model,optimizer,directory,dict(seed=seed,stage="pretraining",steps=step))
        receipt.update(status="complete",checkpoint_sha256=model_sha,optimizer_sha256=optimizer_sha,scorer_unchanged=True,
            first100_loss=sum(losses[:100])/100,last100_loss=sum(losses[-100:])/100,examples=step*recipe["batch_size"])
        save(directory/"losses.json",losses)
        del model,optimizer,ids,lengths,target,loss;torch.cuda.empty_cache()
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3);save(directory/"execution.json",receipt)
    return receipt


def train_ranker(torch,harness,growth,state,arrays,indices,recipe,seed,mode,directory,commit,run_start):
    receipt=dict(kind="paired_language_downstream_fit",status="failed",seed=seed,mode=mode,steps=0,fit_commit=commit)
    start=time.monotonic();losses=[]
    try:
        # Reset RNG and optimizer after LM so downstream sampling/dropout share
        # the same seed and budget with the no-LM control.
        harness.seed_everything(seed);model=harness.build_model("C2");model.load_state_dict(state,strict=True);model=model.to("cuda:0").train()
        optimizer=torch.optim.AdamW(model.parameters(),lr=recipe["learning_rate"],weight_decay=recipe["weight_decay"])
        for step,batch in enumerate(growth.batches(indices,seed,recipe["batch_size"],recipe["updates"]),1):
            if time.monotonic()-start>1800 or time.monotonic()-run_start>14400:raise TimeoutError("registered_downstream_time_budget")
            inputs,target=harness._tensors(arrays,arrays["features"],batch,torch.device("cuda:0"))
            optimizer.zero_grad(set_to_none=True);loss=harness.loss_fn(model(*inputs),target,inputs[-1],"C2")
            if not torch.isfinite(loss):raise ValueError("nonfinite_downstream_loss")
            loss.backward();norm=torch.nn.utils.clip_grad_norm_(model.parameters(),recipe["gradient_clip_norm"])
            if not torch.isfinite(norm):raise ValueError("nonfinite_downstream_gradient")
            optimizer.step();losses.append(float(loss.detach().cpu()));receipt["steps"]=step
        model_sha,optimizer_sha=checkpoint(torch,model,optimizer,directory,dict(seed=seed,mode=mode,steps=step))
        if mode=="lm_off":
            prior=torch.load(PRIOR_ROOT/"models"/f"c2-s{seed}"/"model.pt",map_location="cpu",weights_only=True)["state_dict"]
            same=all(torch.equal(value.detach().cpu(),prior[key]) for key,value in model.state_dict().items())
            if not same:raise ValueError("no_lm_control_does_not_reproduce")
            receipt["prior_control_tensor_equal"]=True
        receipt.update(status="complete",checkpoint_sha256=model_sha,optimizer_sha256=optimizer_sha,
            mean_loss=sum(losses)/len(losses),last100_loss=sum(losses[-100:])/100,examples=step*recipe["batch_size"])
        save(directory/"losses.json",losses);del model,optimizer,inputs,target,loss;torch.cuda.empty_cache()
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3);save(directory/"execution.json",receipt)
    return receipt


def run(commit):
    import numpy as np
    import torch
    sys.addaudithook(forbid_evaluation_access)
    plan,bound=authenticate(commit);environment=dict(python=sys.version.split()[0],torch=torch.__version__,numpy=np.__version__)
    if environment!=bound["environment"] or not torch.cuda.is_available():raise ValueError("fixed_language_environment_required")
    torch.set_num_threads(4);torch.set_num_interop_threads(1);harness=context_model.reference();growth=context_model.growth_training()
    recipe=plan["downstream"]
    with np.load(TRAIN_ROOT/"cache/train.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    with np.load(ROOT/"language-windows.npz",allow_pickle=False) as saved:language={k:np.array(saved[k]) for k in saved.files}
    indices=np.asarray(read_json(TRAIN_ROOT/"cache/cohorts.json")["mixed"],dtype=np.int64)
    if len(indices)!=50000 or len(set(indices.tolist()))!=50000 or np.any(arrays["gold"][indices]<0):raise ValueError("downstream_population_changed")
    initial=torch.load(recipe["initial_checkpoint"],map_location="cpu",weights_only=True)["state_dict"]
    (ROOT/"models").mkdir(exist_ok=False);(ROOT/"pretrained").mkdir(exist_ok=False)
    receipt=dict(kind="paired_language_training_execution",status="failed",fit_commit=commit,fit_binding_sha256=sha(BINDING),
        environment=environment,gpu=torch.cuda.get_device_name(0),models=[],pretraining=[],evaluation_open_guard=True,
        evaluation_arrays_loaded=False,kwdlc_training_rows=0,language_windows=len(language["next_ids"]),downstream_rows=50000)
    start=time.monotonic()
    try:
        for seed in recipe["seeds"]:
            directory=ROOT/"pretrained"/f"s{seed}";directory.mkdir()
            try:train_lm(torch,harness,growth,initial,language,plan["pretraining"],seed,directory,commit,start)
            finally:
                terminal=read_json(directory/"execution.json") if (directory/"execution.json").exists() else dict(status="failed_without_receipt",seed=seed)
                receipt["pretraining"].append(dict(name=f"s{seed}",**terminal))
            state=torch.load(directory/"model.pt",map_location="cpu",weights_only=True)["state_dict"]
            for mode in ("lm_off","lm_on"):
                name=f"{mode}-s{seed}";output=ROOT/"models"/name;output.mkdir()
                try:
                    trained=train_ranker(torch,harness,growth,initial if mode=="lm_off" else state,arrays,indices,recipe,seed,mode,output,commit,start)
                    print(json.dumps(dict(stage="language_downstream",model=name,status=trained["status"],elapsed_seconds=trained["elapsed_seconds"])),flush=True)
                finally:
                    terminal=read_json(output/"execution.json") if (output/"execution.json").exists() else dict(status="failed_without_receipt",seed=seed,mode=mode)
                    receipt["models"].append(dict(name=name,**terminal))
        authenticate(commit)
        if len(receipt["models"])!=6 or len(receipt["pretraining"])!=3:raise ValueError("incomplete_language_fit_population")
        receipt["status"]="complete"
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        receipt.update(elapsed_seconds=round(time.monotonic()-start,3),unattempted_fits=6-len(receipt["models"]),unattempted_pretraining_runs=3-len(receipt["pretraining"]))
        save(ROOT/"training-execution.json",receipt)
    return {k:receipt[k] for k in ("status","elapsed_seconds","unattempted_fits","unattempted_pretraining_runs")}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--fit-commit",required=True)
    print(json.dumps(run(parser.parse_args().fit_commit)))
