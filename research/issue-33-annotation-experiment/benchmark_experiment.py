"""Fixed-seed CPU export parity and 10,000 batch-one calls for each arm."""
import argparse
from collections import Counter
import io
import json
import os
import platform
import time

os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'

from experiment_common import ROOT,HERE,boundary,read,save,sha
from experiment_fit_contract import authenticated_bytes,reference
from evaluate_experiment import bound_evaluation,evaluation_arrays,helpers


def run(evaluation_commit,implementation_commit):
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    boundary.committed(HERE/'benchmark_experiment.py',implementation_commit)
    plan,fit,bound=bound_evaluation(evaluation_commit)
    if platform.system()!='Windows' or torch.cuda.is_available():
        raise ValueError('windows_cpu_only_benchmark_required')
    if (onnx.__version__!='1.19.1' or ort.__version__!='1.23.2'
            or torch.__version__!=fit['environment']['torch'] or np.__version__!=fit['environment']['numpy']):
        raise ValueError('fixed_cpu_environment_changed')
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    harness=reference(fit);arrays=evaluation_arrays(fit);conditions=read(ROOT/'conditions.json')
    score_execution=read(ROOT/'scores/execution.json')
    if score_execution['status']!='complete':raise ValueError('complete_cpu_reference_required')
    raw=authenticated_bytes(ROOT/'scores/all.npz',score_execution['scores_sha256'])
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved:scores={key:np.array(saved[key]) for key in saved.files}
    chosen=[model for model in bound['models'] if model.get('seed')==plan['cpu_benchmark']['seed']]
    if [m['arm'] for m in chosen]!=['dictionary','annotation']:
        raise ValueError('prespecified_benchmark_arms_changed')
    modify=helpers().context_arrays
    output=ROOT/'cpu-benchmark';output.mkdir(exist_ok=False)
    report=dict(kind='annotation_recipe_cpu_benchmark',status='failed',evaluation_commit=evaluation_commit,
        implementation_commit=implementation_commit,script_sha256=sha(__file__),gpu_disabled=True,
        backend='CPUExecutionProvider only',batch=1,intra_op_threads=1,inter_op_threads=1,
        warmup=200,runs_per_arm=10000,models=[],production_eligible=False,
        scores_sha256=score_execution['scores_sha256'],environment=dict(python=platform.python_version(),
        torch=torch.__version__,onnx=onnx.__version__,onnxruntime=ort.__version__,numpy=np.__version__,platform=platform.platform()))
    started=time.monotonic()
    try:
        for item in chosen:
            directory=output/item['name'];directory.mkdir()
            result=dict(model=item['name'],arm=item['arm'],seed=item['seed'],status='failed',measured=0,failures=0,parity={})
            tick=time.monotonic();times=None;session=None
            try:
                model=harness.build_model('C2').eval()
                state=torch.load(io.BytesIO(authenticated_bytes(item['path'],item['sha256'])),map_location='cpu',weights_only=True)['state_dict']
                model.load_state_dict(state,strict=True)
                inputs,_=harness._tensors(arrays,arrays['features'],np.asarray([0]),torch.device('cpu'))
                path=directory/'model-fp32.onnx';names=list(harness.INPUT_NAMES)
                torch.onnx.export(model,tuple(inputs),path,input_names=names,output_names=['scores'],
                    dynamic_axes={name:{0:'batch'} for name in (*names,'scores')},opset_version=18,dynamo=False,do_constant_folding=True)
                onnx.checker.check_model(onnx.load(path))
                options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
                options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
                if session.get_providers()!=['CPUExecutionProvider']:raise ValueError('unexpected_cpu_provider')
                latency_feeds=None
                for context in conditions['contexts']:
                    modified=modify(arrays,conditions,context)
                    feeds=[{name:modified[name][i:i+1] for name in names} for i in range(len(arrays['gold']))]
                    actual=np.concatenate([session.run(['scores'],feed)[0] for feed in feeds])
                    expected=scores[context+'/'+item['name']]
                    parity=dict(rows=len(actual),maximum_absolute_difference=float(np.max(np.abs(actual-expected))),
                        winner_mismatches=int((actual.argmax(axis=1)!=expected.argmax(axis=1)).sum()),
                        allclose=bool(np.allclose(actual,expected,atol=1e-5,rtol=1e-5)))
                    result['parity'][context]=parity
                    if not np.isfinite(actual).all() or not parity['allclose'] or parity['winner_mismatches']:
                        raise ValueError('export_score_or_winner_parity_failed')
                    if context=='intact':latency_feeds=feeds
                for i in range(200):session.run(['scores'],latency_feeds[i%len(latency_feeds)])
                times=np.empty(10000,dtype=np.int64);errors=Counter()
                for i in range(10000):
                    if time.monotonic()-tick>180:raise TimeoutError('cpu_benchmark_wall_deadline')
                    call=time.perf_counter_ns()
                    try:session.run(['scores'],latency_feeds[i%len(latency_feeds)])
                    except Exception as error:errors[type(error).__name__]+=1
                    times[i]=time.perf_counter_ns()-call
                    result['measured']=i+1;result['failures']=sum(errors.values())
                milliseconds=times/1_000_000.
                p50,p95,p99=np.quantile(milliseconds,[.5,.95,.99],method='linear')
                result.update(status='complete' if not errors else 'complete_with_failures',error_types=dict(errors),
                    p50_ms=float(p50),p95_ms=float(p95),p99_ms=float(p99),maximum_ms=float(milliseconds.max()),
                    latency_limits_passed=bool(not errors and p95<=2 and p99<=5),onnx_sha256=sha(path),onnx_bytes=path.stat().st_size)
            except Exception as error:
                result['error_type']=type(error).__name__;raise
            finally:
                if times is not None:
                    with (directory/'latencies-ns.npy').open('xb') as stream:np.save(stream,times[:result['measured']],allow_pickle=False)
                    result['latency_samples_sha256']=sha(directory/'latencies-ns.npy')
                result.update(elapsed_seconds=round(time.monotonic()-tick,3),not_attempted_runs=10000-result['measured'])
                save(directory/'report.json',result);report['models'].append(result)
                if session is not None:del session
            print(json.dumps({key:result[key] for key in ('model','measured','failures','p95_ms','p99_ms','latency_limits_passed')}),flush=True)
        bound_evaluation(evaluation_commit)
        report['status']='complete' if all(m['status']=='complete' and m['latency_limits_passed'] for m in report['models']) else 'complete_with_limit_failures'
    except Exception as error:
        report['error_type']=type(error).__name__;raise
    finally:
        report.update(elapsed_seconds=round(time.monotonic()-started,3),not_attempted_models=2-len(report['models']))
        save(output/'report.json',report)
    return {key:report[key] for key in ('status','elapsed_seconds','not_attempted_models')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evaluation-commit',required=True);parser.add_argument('--implementation-commit',required=True)
    args=parser.parse_args();print(json.dumps(run(args.evaluation_commit,args.implementation_commit)))
