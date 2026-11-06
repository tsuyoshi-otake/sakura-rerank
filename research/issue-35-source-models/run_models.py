"""CPU-only fixed-model observations and bounded, model-only timing."""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np

from sakura_rerank.source_model_inputs import INPUT_NAMES,model_feed
from model35_common import HERE,ROOT,authenticate,committed,read,save,sha

BINDING=HERE/'inference-binding-v1.json'


def seal():
    prep=read(ROOT/'preparation.json');plan=authenticate(prep['plan_commit'],prep['plan_file'])
    if prep['source_slots']!=1000 or prep['source_part_cases']!=1228 or prep['unique_numeric_inputs']!=1221:
        raise ValueError('source_models_prepared_population')
    files=[ROOT/name for name in ('preparation.json','model-inputs.npz','input-index.json','source-cases.json')]
    code=[HERE/'run_models.py',HERE/'source_score_outcomes.py','src/sakura_rerank/source_model_inputs.py',
          'tests/test_source_model_decisions.py']
    save(BINDING,dict(kind='fixed_source_models_inference_binding',plan_commit=prep['plan_commit'],plan_file=prep['plan_file'],
        inputs={str(p).replace('\\','/'):sha(p) for p in files},code={str(p).replace('\\','/'):sha(p) for p in code},
        models=plan['models'],quality_inputs=1221,quality_model_calls=3663,warmup_per_model=200,benchmark_per_model=10000,
        direct_verification_replay_per_model=1221,maximum_runtime_seconds=840,
        label_free_feed=True,fit_permission=False,threshold_selection=False,final_test=False))
    return dict(stage='inference_sealed',binding_sha256=sha(BINDING),model_calls=0)


def bound_inputs(commit):
    bound=json.loads(committed(BINDING,commit));plan=authenticate(bound['plan_commit'],bound['plan_file'])
    for path,digest in {**bound['inputs'],**bound['code']}.items():
        if sha(path)!=digest:raise ValueError('source_models_inference_binding_changed')
    for path in bound['code']:committed(path,commit)
    raw=(ROOT/'model-inputs.npz').read_bytes()
    if len(raw)>plan['execution']['maximum_input_bytes']:raise ValueError('source_models_input_byte_bound')
    with np.load(io.BytesIO(raw),allow_pickle=False) as archive:
        if set(archive.files)!=set(INPUT_NAMES):raise ValueError('source_models_forbidden_feed_fields')
        arrays={name:archive[name] for name in INPUT_NAMES}
    if len(arrays['reading_lengths'])!=bound['quality_inputs']:raise ValueError('source_models_input_count')
    return bound,plan,arrays


def cpu_session(model):
    import onnxruntime as ort
    raw=Path(model['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=model['sha256']:raise ValueError('source_models_loaded_bytes_changed')
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='':raise ValueError('source_models_gpu_not_disabled')
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
    options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    session=ort.InferenceSession(raw,sess_options=options,providers=['CPUExecutionProvider'])
    if session.get_providers()!=['CPUExecutionProvider']:raise ValueError('source_models_provider_changed')
    if [v.name for v in session.get_inputs()]!=list(INPUT_NAMES):raise ValueError('source_models_input_names')
    if session.get_inputs()[6].shape[-1]!=model['feature_dim']:raise ValueError('source_models_feature_width')
    return session


def checked_scores(value):
    if not isinstance(value,np.ndarray) or value.shape!=(1,6) or value.dtype!=np.float32 or not np.isfinite(value).all():
        raise ValueError('source_models_output_contract')
    return value[0]


def execute(commit):
    os.environ['CUDA_VISIBLE_DEVICES']=''
    bound,plan,arrays=bound_inputs(commit)
    save(ROOT/'inference-reservation.json',dict(binding_commit=commit,models=[m['name'] for m in bound['models']],
        quality_inputs=bound['quality_inputs'],threshold_selection=False,final_test=False))
    start=time.monotonic();records=[]
    for model in bound['models']:
        count=bound['quality_inputs'];scores=np.full((count,6),np.nan,dtype=np.float32)
        states=['unavailable']*count;warmup=0;quality_calls=0;times=[];error_type=None
        try:
            session=cpu_session(model)
            feeds=[model_feed(arrays,i,model['feature_dim']) for i in range(count)]
            for index in range(bound['warmup_per_model']):
                if time.monotonic()-start>bound['maximum_runtime_seconds']:raise TimeoutError('source_models_deadline')
                checked_scores(session.run(['scores'],feeds[index%count])[0]);warmup+=1
            for index,feed in enumerate(feeds):
                if time.monotonic()-start>bound['maximum_runtime_seconds']:break
                quality_calls+=1
                try:scores[index]=checked_scores(session.run(['scores'],feed)[0]);states[index]='complete'
                except Exception as error:
                    states[index]='error';error_type=type(error).__name__;break
            if all(status=='complete' for status in states):
                for index in range(bound['benchmark_per_model']):
                    if time.monotonic()-start>bound['maximum_runtime_seconds']:break
                    begin=time.perf_counter_ns();output=session.run(['scores'],feeds[index%count])[0];elapsed=time.perf_counter_ns()-begin
                    checked_scores(output);times.append(elapsed/1_000_000)
            del session
        except Exception as error:error_type=type(error).__name__
        with (ROOT/(model['name']+'-scores.npz')).open('xb') as stream:np.savez(stream,scores=scores)
        with (ROOT/(model['name']+'-timings.npz')).open('xb') as stream:np.savez(stream,milliseconds=np.asarray(times,dtype=np.float64))
        save(ROOT/(model['name']+'-terminals.json'),dict(states=states))
        timing=None if not times else {key:float(np.quantile(times,q,method='linear')) for key,q in (('p50',.5),('p95',.95),('p99',.99))}
        item=dict(name=model['name'],sha256=model['sha256'],quality_outcomes=dict(Counter(states)),
            quality_calls=quality_calls,warmup_calls=warmup,benchmark_calls=len(times),timing_ms=timing,
            benchmark_complete=len(times)==10000,quality_complete=all(status=='complete' for status in states),error_type=error_type,
            scores_sha256=sha(ROOT/(model['name']+'-scores.npz')),terminals_sha256=sha(ROOT/(model['name']+'-terminals.json')),
            timings_sha256=sha(ROOT/(model['name']+'-timings.npz')))
        records.append(item);print(json.dumps(dict(stage='fixed_model_complete',**item)),flush=True)
    bound_inputs(commit)
    report=dict(status='complete' if all(r['quality_complete'] and r['benchmark_complete'] for r in records) else 'incomplete',
        binding_commit=commit,models=records,all_outputs_sealed_before_evaluation=True,provider='CPUExecutionProvider',
        gpu_disabled=True,batch=1,intra_op_threads=1,inter_op_threads=1,elapsed_seconds=round(time.monotonic()-start,3),
        model_fit_calls=0,source_labels_in_model_feed=0,native_calls=0,final_test=False)
    save(ROOT/'inference-report.json',report)
    save(ROOT/'outputs-seal.json',dict(inference_report_sha256=sha(ROOT/'inference-report.json'),models=records,source_scores_not_yet_evaluated=True))
    return dict(status=report['status'],models=len(records),quality_calls=sum(r['quality_calls'] for r in records),
        benchmark_calls=sum(r['benchmark_calls'] for r in records),elapsed_seconds=report['elapsed_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit')
    args=parser.parse_args();print(json.dumps(seal() if args.stage=='seal' else execute(args.commit)))
