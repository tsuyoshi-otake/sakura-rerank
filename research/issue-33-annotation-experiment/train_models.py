"""Exactly six fixed-budget fits, with all evaluation-data reads denied."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')

from experiment_common import ROOT,HERE,TRAIN_CACHE,save,sha
from experiment_fit_contract import authenticate_fit,authenticated_bytes,load_training,reference,TrainingReadGuard


def batches(indices,seed,batch_size,steps):
    import numpy as np
    import torch
    generator=torch.Generator(device='cpu').manual_seed(seed)
    pending=np.empty(0,dtype=np.int64)
    for _ in range(steps):
        while len(pending)<batch_size:
            pending=np.concatenate((pending,indices[torch.randperm(len(indices),generator=generator).numpy()]))
        yield pending[:batch_size]
        pending=pending[batch_size:]


def run(commit):
    import numpy as np
    import torch
    plan,bound=authenticate_fit(commit)
    recipe=plan['training'];output=ROOT/'models'
    save(ROOT/'fit-reservation.json',dict(fit_commit=commit,binding_sha256=sha(HERE/'fit-binding-v1.json'),fits=6))
    environment=dict(python=sys.version.split()[0],torch=torch.__version__,numpy=np.__version__)
    if environment!=bound['environment'] or not torch.cuda.is_available():
        raise ValueError('fixed_fit_environment_changed')
    guard=TrainingReadGuard(Path.cwd(),[*bound['training_artifacts'],*bound['code'],ROOT/'fit-binding.json'],output)
    sys.addaudithook(guard)
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    harness=reference(bound)
    arrays,cohorts,cache=load_training(bound)
    checkpoint=authenticated_bytes(recipe['initial_checkpoint'],recipe['initial_checkpoint_sha256'])
    initial=torch.load(io.BytesIO(checkpoint),map_location='cpu',weights_only=True)['state_dict']
    output.mkdir(exist_ok=False)
    result=dict(kind='paired_annotation_training',status='failed',fit_commit=commit,environment=environment,
        union_rows=75000,rows_per_arm=50000,source_counts_per_arm=dict(jawiki=25000,aozora=25000),
        training_cache_sha256=bound['training_artifacts'][(TRAIN_CACHE/'manifest.json').as_posix()],
        row_chain_head=cache['row_chain_head'],tensor_rows_authenticated=75000,
        evaluation_arrays_loaded=False,evaluation_read_guard_enabled=True,kwdlc_training_rows=0,
        tf32=False,amp=False,models=[],fits_planned=6)
    started=time.monotonic()
    try:
        for seed in recipe['seeds']:
            for arm in ('dictionary','annotation'):
                name=f'{arm}-s{seed}';directory=output/name;directory.mkdir()
                receipt=dict(name=name,arm=arm,seed=seed,status='failed',steps=0,fit_commit=commit,
                    initial_checkpoint_sha256=recipe['initial_checkpoint_sha256'])
                tick=time.monotonic();losses=[]
                try:
                    harness.seed_everything(seed)
                    model=harness.build_model('C2');model.load_state_dict(initial,strict=True)
                    if not all(torch.equal(value,model.state_dict()[key]) for key,value in initial.items()):
                        raise ValueError('fit_initial_weights_changed')
                    receipt['parameters']=sum(p.numel() for p in model.parameters())
                    model=model.to('cuda:0').train()
                    optimizer=torch.optim.AdamW(model.parameters(),lr=recipe['learning_rate'],weight_decay=recipe['weight_decay'])
                    for step,batch in enumerate(batches(cohorts[arm],seed,recipe['batch_size'],recipe['updates_per_fit']),1):
                        if time.monotonic()-tick>recipe['max_seconds_per_fit']:
                            raise TimeoutError('fit_wall_deadline')
                        inputs,target=harness._tensors(arrays,arrays['features'],batch,torch.device('cuda:0'))
                        optimizer.zero_grad(set_to_none=True)
                        loss=harness.loss_fn(model(*inputs),target,inputs[-1],'C2')
                        if not torch.isfinite(loss):raise ValueError('nonfinite_fit_loss')
                        loss.backward()
                        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),recipe['gradient_clip_norm'])
                        if not torch.isfinite(norm):raise ValueError('nonfinite_fit_gradient')
                        optimizer.step();losses.append(float(loss.detach().cpu()));receipt['steps']=step
                        if step%100==0:print(json.dumps(dict(stage='annotation_fit',arm=arm,seed=seed,step=step)),flush=True)
                    state={key:value.detach().cpu() for key,value in model.state_dict().items()}
                    if not all(torch.isfinite(v).all() for v in state.values()):raise ValueError('nonfinite_fit_checkpoint')
                    path=directory/'model.pt'
                    with path.open('xb') as stream:
                        torch.save(dict(state_dict=state,arm=arm,seed=seed,steps=500,fit_commit=commit),stream)
                        stream.flush();os.fsync(stream.fileno())
                    save(directory/'losses.json',losses)
                    receipt.update(status='complete',checkpoint_sha256=sha(path),examples=500*256,
                        mean_loss=sum(losses)/len(losses),last100_loss=sum(losses[-100:])/100)
                    del model,optimizer,state,inputs,target,loss
                    torch.cuda.empty_cache()
                except Exception as error:
                    receipt['error_type']=type(error).__name__;raise
                finally:
                    receipt['elapsed_seconds']=round(time.monotonic()-tick,3)
                    save(directory/'execution.json',receipt);result['models'].append(receipt)
        authenticate_fit(commit)
        if len(result['models'])!=6:raise ValueError('fit_count_incomplete')
        result['status']='complete'
    except Exception as error:
        result['error_type']=type(error).__name__;raise
    finally:
        result.update(elapsed_seconds=round(time.monotonic()-started,3),not_attempted_fits=6-len(result['models']),
                      forbidden_data_read_attempts=guard.blocked,
                      observed_data_read_paths=sorted(p.relative_to(Path.cwd()).as_posix() for p in guard.observed))
        save(ROOT/'training-execution.json',result)
    return {key:result[key] for key in ('status','elapsed_seconds','not_attempted_fits','forbidden_data_read_attempts')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--fit-commit',required=True)
    print(json.dumps(run(parser.parse_args().fit_commit)))
