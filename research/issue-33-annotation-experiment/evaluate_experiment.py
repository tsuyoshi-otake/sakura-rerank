"""Seal all six fits, then one CPU scoring pass and the prespecified comparison."""
import argparse
from collections import defaultdict
import io
import json
import os
import time

os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'

from sakura_rerank.evaluation_statistics import paired_component_bootstrap
from sakura_rerank.growth_metrics import observe,summarize
from experiment_common import ROOT,HERE,boundary,read,rows,save,sha
from experiment_fit_contract import authenticate_fit,authenticated_bytes,reference
from experiment_statistics import mean_seed_comparison

FIT_COMMIT='260c1b295a161282c3287194f0d058b4bb446b88'
BINDING=HERE/'evaluation-binding-v1.json'
HELPERS='research/issue-40-context-contrast/evaluate_models.py'


def helpers():
    return boundary.load_script('annotation_fixed_metric_helpers',HELPERS)


def seal():
    plan,fit=authenticate_fit(FIT_COMMIT,evaluation=True)
    training=read(ROOT/'training-execution.json')
    expected=[f'{arm}-s{seed}' for seed in plan['training']['seeds'] for arm in ('dictionary','annotation')]
    if (training['status']!='complete' or training['not_attempted_fits']
            or training['forbidden_data_read_attempts'] or training['evaluation_arrays_loaded']
            or [m['name'] for m in training['models']]!=expected):
        raise ValueError('all_six_fixed_fits_required')
    models=[dict(name='reference29',path=plan['training']['initial_checkpoint'],sha256=plan['training']['initial_checkpoint_sha256'])]
    for model in training['models']:
        path=ROOT/'models'/model['name']/'model.pt'
        if model['status']!='complete' or model['steps']!=500 or sha(path)!=model['checkpoint_sha256']:
            raise ValueError('fixed_model_checkpoint_incomplete')
        models.append(dict(name=model['name'],arm=model['arm'],seed=model['seed'],path=path.as_posix(),sha256=model['checkpoint_sha256']))
    paths=[HERE/'evaluate_experiment.py',HERE/'experiment_statistics.py',HELPERS,
           'src/sakura_rerank/growth_metrics.py','src/sakura_rerank/evaluation_statistics.py']
    bound=dict(kind='annotation_model_evaluation_binding',fit_commit=FIT_COMMIT,models=models,
        training_sha256=sha(ROOT/'training-execution.json'),conditions_sha256=sha(ROOT/'conditions.json'),
        code={str(p):sha(p) for p in paths},backend='CPU PyTorch float32, one thread',
        environment=fit['environment'],predictions_seen=False,gold_certified=False,final_test_used=False)
    save(BINDING,bound);save(ROOT/'evaluation-binding.json',bound)
    return dict(models=len(models),fits=6,predictions_seen=False)


def bound_evaluation(commit):
    plan,fit=authenticate_fit(FIT_COMMIT,evaluation=True)
    bound=json.loads(boundary.committed(BINDING,commit))
    if (bound!=read(ROOT/'evaluation-binding.json') or bound['training_sha256']!=sha(ROOT/'training-execution.json')
            or bound['conditions_sha256']!=sha(ROOT/'conditions.json')):
        raise ValueError('evaluation_binding_changed')
    for path,digest in bound['code'].items():
        if sha(path)!=digest:raise ValueError('evaluation_code_changed')
    for model in bound['models']:
        if sha(model['path'])!=model['sha256']:raise ValueError('evaluation_checkpoint_changed')
    return plan,fit,bound


def evaluation_arrays(fit):
    import numpy as np
    path=ROOT/'evaluation-cache/arrays.npz'
    raw=authenticated_bytes(path,fit['evaluation_artifacts'][path.as_posix()])
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved:
        return {key:np.array(saved[key]) for key in saved.files}


def infer(commit):
    import numpy as np
    import torch
    _,fit,bound=bound_evaluation(commit)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if torch.cuda.is_available():raise ValueError('cpu_only_inference_required')
    harness=reference(fit);arrays=evaluation_arrays(fit);conditions=read(ROOT/'conditions.json')
    modify=helpers().context_arrays
    output=ROOT/'scores';output.mkdir(exist_ok=False)
    scores={};started=time.monotonic()
    execution=dict(kind='annotation_cpu_inference',status='failed',evaluation_commit=commit,
        binding_sha256=sha(BINDING),backend=bound['backend'],rows=len(arrays['gold']),threads=1,gpu_disabled=True,conditions=[])
    try:
        for item in bound['models']:
            model=harness.build_model('C2').eval()
            model.load_state_dict(torch.load(io.BytesIO(authenticated_bytes(item['path'],item['sha256'])),
                                            map_location='cpu',weights_only=True)['state_dict'],strict=True)
            for context in conditions['contexts']:
                terminal=dict(model=item['name'],context=context,status='failed')
                key=context+'/'+item['name']
                try:
                    modified=modify(arrays,conditions,context);parts=[]
                    with torch.no_grad():
                        for offset in range(0,len(arrays['gold']),128):
                            if time.monotonic()-started>300:raise TimeoutError('inference_wall_deadline')
                            indexes=np.arange(offset,min(offset+128,len(arrays['gold'])))
                            inputs,_=harness._tensors(modified,modified['features'],indexes,torch.device('cpu'))
                            parts.append(model(*inputs).numpy())
                    scores[key]=np.concatenate(parts)
                    if scores[key].shape!=(len(arrays['gold']),6):raise ValueError('inference_score_shape')
                    terminal.update(status='complete',nonfinite_rows=int((~np.isfinite(scores[key]).all(axis=1)).sum()))
                except (RuntimeError,ValueError) as error:
                    scores[key]=np.full((len(arrays['gold']),6),np.nan,dtype=np.float32)
                    terminal.update(error_type=type(error).__name__,fallback_rows=len(arrays['gold']))
                finally:
                    execution['conditions'].append(terminal)
            del model
            print(json.dumps(dict(stage='annotation_cpu_inference',model=item['name'],conditions=3)),flush=True)
        with (output/'all.npz').open('xb') as stream:
            np.savez_compressed(stream,**scores);stream.flush();os.fsync(stream.fileno())
        bound_evaluation(commit)
        execution.update(status='complete' if all(r['status']=='complete' and not r.get('nonfinite_rows')
            for r in execution['conditions']) else 'complete_with_failures',scores_sha256=sha(output/'all.npz'))
    except Exception as error:
        execution['error_type']=type(error).__name__;raise
    finally:
        execution.update(elapsed_seconds=round(time.monotonic()-started,3),not_attempted_conditions=21-len(execution['conditions']))
        save(output/'execution.json',execution)
    return {k:execution[k] for k in ('status','elapsed_seconds','not_attempted_conditions')}


def report(commit):
    import numpy as np
    plan,fit,bound=bound_evaluation(commit);execution=read(ROOT/'scores/execution.json')
    if execution['not_attempted_conditions'] or sha(ROOT/'scores/all.npz')!=execution['scores_sha256']:
        raise ValueError('all_fixed_inference_conditions_required')
    arrays=evaluation_arrays(fit)
    raw=authenticated_bytes(ROOT/'scores/all.npz',execution['scores_sha256'])
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved:scores={key:np.array(saved[key]) for key in saved.files}
    conditions=read(ROOT/'conditions.json');targets=list(rows(ROOT/'forward-targets.jsonl.gz'));metric=helpers()
    expected={context+'/'+m['name'] for context in conditions['contexts'] for m in bound['models']}
    if set(scores)!=expected:raise ValueError('fixed_inference_population_changed')
    clusters={name:metric.cluster_ids(targets,indexes,name!='main') for name,indexes in conditions['populations'].items()}
    observations={};metrics={}
    for label,values in scores.items():
        for gate in ('ungated','gated'):
            key=gate+'/'+label;observation=observe(arrays,values,gate);observations[key]=observation;metrics[key]={}
            for name,indexes in conditions['populations'].items():
                if not indexes:
                    metrics[key][name]=dict(rows=0,status='empty_population_not_measured');continue
                value=summarize(observation,indexes)
                value['paired_source_component_intervals']=metric.uncertainty(observation,indexes,clusters[name])
                value['source_absent_top6']=int((~arrays['correct_mask'][indexes].any(axis=1)).sum())
                value['source_present_top6_but_not_correct']=int((arrays['correct_mask'][indexes].any(axis=1)&~observation['correct'][indexes]).sum())
                metrics[key][name]=value
    main=conditions['populations']['main'];supported=conditions['populations']['contrast_supported']
    differences=[];per_seed=[]
    for seed in plan['training']['seeds']:
        control=observations[f'ungated/intact/dictionary-s{seed}']['correct']
        treated=observations[f'ungated/intact/annotation-s{seed}']['correct']
        delta=treated[main].astype(int)-control[main].astype(int);differences.append(delta)
        interval=paired_component_bootstrap(clusters['main'],np.stack((delta,np.ones(len(main),dtype=int)),axis=1).tolist(),
            {'accuracy_difference':(0,1)},replicates=2000,seed=20261105)
        per_seed.append(dict(seed=seed,main_net_rows=int(delta.sum()),main_difference=float(delta.mean()),
            main_paired_ci95=interval['ratios']['accuracy_difference']['ci95'],
            supported_contrast_net_rows=int(treated[supported].sum()-control[supported].sum())))
    primary=mean_seed_comparison(clusters['main'],differences,inference_complete=execution['status']=='complete')
    changes=defaultdict(dict)
    for model in bound['models']:
        for gate in ('ungated','gated'):
            original=observations[gate+'/intact/'+model['name']]
            for context in ('empty','shuffled'):
                changed=observations[gate+'/'+context+'/'+model['name']]
                changes[gate+'/'+model['name']][context]={name:dict(
                    changed_winners=int((changed['predicted'][indexes]!=original['predicted'][indexes]).sum()),
                    source_correct_difference=int(changed['correct'][indexes].sum()-original['correct'][indexes].sum()))
                    for name,indexes in conditions['populations'].items()}
    result=dict(kind='paired_annotation_recipe_research',fit_commit=FIT_COMMIT,evaluation_commit=commit,
        binding_sha256=sha(BINDING),scores_sha256=execution['scores_sha256'],inference_backend=bound['backend'],
        metrics=metrics,primary_comparison=primary,per_seed_descriptive_comparisons=per_seed,context_changes=dict(changes),
        population_sizes={key:len(value) for key,value in conditions['populations'].items()},
        source_component_counts={key:len(set(value)) for key,value in clusters.items()},
        reserved_main_slots=1000,main_terminal_counts=read(ROOT/'cohort.json')['main_statuses'],
        model_fits=6,safety_threshold=.0025,gold_certified=False,independent_human_ime_gold=0,final_test_used=False,
        production_adoption=False,uncertainty_scope='Conditional source-form agreement on the fixed research cohort; source/contrast component dependence retained, not certified IME intent or independent Gold.')
    save(ROOT/'model-report.json',result)
    return dict(primary_comparison=primary,per_seed_comparisons=per_seed)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','infer','report'));parser.add_argument('--evaluation-commit')
    args=parser.parse_args()
    print(json.dumps(seal() if args.stage=='seal' else dict(infer=infer,report=report)[args.stage](args.evaluation_commit)))
