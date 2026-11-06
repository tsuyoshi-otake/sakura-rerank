"""CPU-only, label-free fixed-selector inference with complete row accounting."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from sakura_rerank.source_model_inputs import model_feed
from proposal_common import HERE,ROOT,INPUT_NAMES,authenticate,committed,guard_summary,input_arrays,install_read_guard,read,save,sha

BINDING=HERE/'inference-binding-v1.json'


def seal():
    prep=read(ROOT/'preparation.json');plan=authenticate(prep['plan_commit'])
    if prep['status']!='complete' or prep['forbidden_data_reads'] or prep['labels_decoded']:
        raise ValueError('proposal_preparation_incomplete')
    for name,digest in prep['artifacts'].items():
        if sha(ROOT/name)!=digest:raise ValueError('proposal_prepared_artifact_changed')
    save(BINDING,dict(kind='fixed_selector_cpu_inference_binding',plan_commit=prep['plan_commit'],
        preparation_sha256=sha(ROOT/'preparation.json'),inputs=prep['artifacts'],model=plan['model'],cpu=plan['cpu'],
        conditions=plan['conditions'],rows=75000,code={p.as_posix():sha(p) for p in (HERE/'run_cpu.py',HERE/'proposal_common.py')},
        maximum_seconds=1800,new_fits=0,source_labels_in_feed=False,threshold_selection=False,calibration=False,final_test=False))
    return dict(stage='inference_bound',binding_sha256=sha(BINDING),model_calls=0)


def bound(commit):
    spec=json.loads(committed(BINDING,commit));plan=authenticate(spec['plan_commit'])
    if spec['preparation_sha256']!=sha(ROOT/'preparation.json') or spec['model']!=plan['model']:
        raise ValueError('proposal_inference_preparation_changed')
    for name,digest in spec['inputs'].items():
        if sha(ROOT/name)!=digest:raise ValueError('proposal_inference_input_changed')
    for path,digest in spec['code'].items():
        if sha(path)!=digest:raise ValueError('proposal_inference_code_changed')
        committed(path,commit)
    return spec


def session_for(model):
    import onnxruntime as ort
    if ort.__version__!='1.23.2' or os.environ.get('CUDA_VISIBLE_DEVICES')!='':
        raise ValueError('proposal_cpu_environment')
    raw=Path(model['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=model['sha256']:raise ValueError('proposal_loaded_model_changed')
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    session=ort.InferenceSession(raw,sess_options=options,providers=['CPUExecutionProvider'])
    if session.get_providers()!=['CPUExecutionProvider'] or [x.name for x in session.get_inputs()]!=list(INPUT_NAMES) or session.get_inputs()[6].shape[-1]!=7:
        raise ValueError('proposal_session_contract')
    return session


def checked(value):
    if not isinstance(value,np.ndarray) or value.shape!=(1,6) or value.dtype!=np.float32 or not np.isfinite(value).all():
        raise ValueError('proposal_score_contract')
    return value[0]


def execute(commit):
    os.environ['CUDA_VISIBLE_DEVICES']='';spec=bound(commit)
    save(ROOT/'inference-reservation.json',dict(binding_commit=commit,rows=75000,conditions=spec['conditions'],labels_decoded=0))
    guard=install_read_guard([spec['model']['path']]);started=time.monotonic();outcomes=[]
    terminal=dict(status='failed',binding_commit=commit,conditions=outcomes)
    try:
        for condition in spec['conditions']:
            scores=np.full((75000,6),np.nan,np.float32);states=np.zeros(75000,np.uint8);times=[];warmups=0;calls=0;error_type=None;session=None
            try:
                arrays=input_arrays(ROOT/(condition+'-inputs.npz'),spec['inputs'][condition+'-inputs.npz'],prepared=True)
                session=session_for(spec['model'])
                def deadline():
                    if time.monotonic()-started>spec['maximum_seconds']:raise TimeoutError('proposal_inference_deadline')
                for i in range(spec['cpu']['warmup_per_condition']):
                    deadline();checked(session.run(['scores'],model_feed(arrays,i,7))[0]);warmups+=1
                for i in range(75000):
                    deadline();calls+=1
                    try:scores[i]=checked(session.run(['scores'],model_feed(arrays,i,7))[0]);states[i]=1
                    except Exception:states[i]=2;raise
                    if (i+1)%25000==0:print(json.dumps(dict(stage='cpu_proposals',condition=condition,rows_completed=i+1)),flush=True)
                for i in range(spec['cpu']['benchmark_per_condition']):
                    deadline();feed=model_feed(arrays,i,7);begin=time.perf_counter_ns();value=session.run(['scores'],feed)[0]
                    times.append((time.perf_counter_ns()-begin)/1_000_000);checked(value)
            except Exception as error:error_type=type(error).__name__
            finally:
                if session is not None:del session
            with (ROOT/(condition+'-scores.npz')).open('xb') as stream:np.savez_compressed(stream,scores=scores,states=states)
            with (ROOT/(condition+'-timings.npz')).open('xb') as stream:np.savez(stream,milliseconds=np.asarray(times,np.float64))
            counts=Counter(map(int,states));complete=counts[1]==75000 and len(times)==10000 and error_type is None
            record=dict(condition=condition,status='complete' if complete else 'incomplete',quality_calls=calls,warmup_calls=warmups,benchmark_calls=len(times),
                completed=counts[1],failed=counts[2],unattempted=counts[0],error_type=error_type,
                latency_ms=None if not times else {key:float(np.quantile(times,q)) for key,q in (('p50',.5),('p95',.95),('p99',.99))},
                scores_sha256=sha(ROOT/(condition+'-scores.npz')),timings_sha256=sha(ROOT/(condition+'-timings.npz')))
            outcomes.append(record)
        terminal['status']='complete' if all(r['status']=='complete' for r in outcomes) else 'incomplete'
    except Exception as error:terminal['error_type']=type(error).__name__;raise
    finally:
        terminal.update(provider='CPUExecutionProvider',gpu_disabled=True,batch=1,intra_op_threads=1,inter_op_threads=1,
            source_labels_decoded=0,new_fits=0,threshold_selection=False,final_test=False,elapsed_seconds=round(time.monotonic()-started,3),**guard_summary(guard))
        save(ROOT/'inference.json',terminal)
    save(ROOT/'outputs-seal.json',dict(status=terminal['status'],inference_sha256=sha(ROOT/'inference.json'),conditions=outcomes,labels_not_yet_decoded=True))
    return dict(status=terminal['status'],quality_calls=sum(r['quality_calls'] for r in outcomes),benchmark_calls=sum(r['benchmark_calls'] for r in outcomes),elapsed_seconds=terminal['elapsed_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit');args=parser.parse_args()
    result=seal() if args.stage=='seal' else execute(args.commit);print(json.dumps(result))
    if result.get('status') not in (None,'complete'):raise SystemExit(1)
