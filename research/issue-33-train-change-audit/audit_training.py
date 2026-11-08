"""Hash-bound train-only diagnosis of fixed models, with no optimizer or new data."""
import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
sys.path.insert(0, 'research/issue-33-annotation-experiment')
try:
    from experiment_common import boundary, sha, save
    from experiment_fit_contract import authenticate_fit, authenticated_bytes, load_training, reference, TrainingReadGuard
finally:
    sys.path.pop(0)
from change_metrics import observations, paired, partitions, slices, summary

ROOT = Path('data/generated/issue-33-train-change-audit-v1')
HERE = Path('research/issue-33-train-change-audit')
PLAN_COMMIT = 'fb22fe20fd369281da6756fba5ade8c3fb6d8806'


def authenticate():
    plan = json.loads(boundary.committed(HERE/'plan-v1.json', PLAN_COMMIT))
    bound = plan['fit_binding']
    if sha(bound['path']) != bound['sha256']:
        raise ValueError('audit_fit_binding_changed')
    _, fit = authenticate_fit(bound['commit'])
    for path, digest in {**plan['training_artifacts'], **plan['prior_code']}.items():
        if sha(path) != digest:
            raise ValueError('audit_train_input_changed')
    if sha(plan['training_execution']['path']) != plan['training_execution']['sha256']:
        raise ValueError('audit_training_receipt_changed')
    for model in plan['models']:
        if sha(model['path']) != model['sha256']:
            raise ValueError('audit_fixed_checkpoint_changed')
    return plan, fit


def profile(arrays, groups, fit):
    from sakura_rerank.data.consumed_numeric import verify_chain
    ledger_path = next(p for p in fit['training_artifacts'] if p.endswith('/row-receipts.jsonl'))
    manifest_path = next(p for p in fit['training_artifacts'] if p.endswith('/manifest.json'))
    manifest = json.loads(authenticated_bytes(manifest_path, fit['training_artifacts'][manifest_path]))
    ledger = verify_chain(authenticated_bytes(ledger_path, fit['training_artifacts'][ledger_path]), 75000, manifest['row_chain_head'])
    result = {}
    for name, indexes in groups.items():
        records = [ledger[int(i)] for i in indexes]
        components = Counter(r['origin']['component_id'] for r in records)
        inputs = Counter(r['input_tensor_sha256'] for r in records)
        conflicts = {}
        for row in records:
            conflicts.setdefault(row['input_tensor_sha256'], set()).add(row['label_tensor_sha256'])
        result[name] = dict(rows=len(indexes), baseline_correct=int(arrays['correct_mask'][indexes, 0].sum()),
            baseline_errors=int((~arrays['correct_mask'][indexes, 0]).sum()),
            gold_rank_counts=Counter(map(int, arrays['gold'][indexes])),
            reading_lengths=Counter(map(int, arrays['reading_lengths'][indexes])),
            candidate_counts=Counter(map(int, arrays['candidate_mask'][indexes].sum(axis=1))),
            multiple_correct_candidates=int((arrays['correct_mask'][indexes].sum(axis=1)>1).sum()),
            baseline_equivalent_duplicates=int((arrays['baseline_equivalent'][indexes].sum(axis=1)>1).sum()),
            unique_components=len(components), largest_component=max(components.values()),
            input_duplicate_groups=sum(v>1 for v in inputs.values()), input_duplicate_excess=sum(v-1 for v in inputs.values()),
            input_label_conflict_groups=sum(len(v)>1 for v in conflicts.values()),
            reading_provenance=dict(Counter(r['origin']['reading_provenance'] for r in records)))
    return result


def infer():
    import numpy as np
    import torch
    plan, fit = authenticate()
    code_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=15).strip()
    code = [HERE/name for name in ('audit_training.py','change_metrics.py','run_stage.py','unit_checks.py')]
    for path in code:
        boundary.committed(path, code_commit)
    ROOT.mkdir(exist_ok=True)
    save(ROOT/'reservation.json', dict(plan_commit=PLAN_COMMIT, plan_sha256=sha(HERE/'plan-v1.json'),
         code_commit=code_commit, code={p.as_posix():sha(p) for p in code}, conditions=14, rows=75000))
    allowed = [*plan['training_artifacts'], *plan['prior_code'], *[m['path'] for m in plan['models']],
               'data/generated/issue-33-annotation-experiment-v1/fit-binding.json', plan['training_execution']['path']]
    guard = TrainingReadGuard(Path.cwd(), allowed, ROOT)
    sys.addaudithook(guard)
    started = time.monotonic()
    execution = dict(kind='train_only_change_inference', status='failed', code_commit=code_commit,
        plan_sha256=sha(HERE/'plan-v1.json'), conditions=[], new_fits=0, evaluation_arrays_loaded=False,
        all_results_fitted_training_only=True, environment=dict(python=sys.version.split()[0], torch=torch.__version__, numpy=np.__version__))
    scores = {}
    try:
        if execution['environment'] != fit['environment'] or not torch.cuda.is_available():
            raise ValueError('audit_pinned_cuda_environment_required')
        torch.set_num_threads(4); torch.set_num_interop_threads(1)
        torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
        torch.use_deterministic_algorithms(True)
        arrays, cohorts, _ = load_training(fit)
        groups = partitions(cohorts, len(arrays['gold']))
        save(ROOT/'profile.json', profile(arrays, groups, fit))
        harness = reference(fit)
        parity_indexes = np.arange(0,75000,257)
        for item in plan['models']:
            model = harness.build_model('C2').eval()
            model.load_state_dict(torch.load(io.BytesIO(authenticated_bytes(item['path'],item['sha256'])), map_location='cpu', weights_only=True)['state_dict'],strict=True)
            for context in plan['contexts']:
                key = context+'/'+item['name']
                terminal = dict(model=item['name'], context=context, status='failed', rows_completed=0)
                try:
                    modified = arrays if context=='intact' else {**arrays,'context_ids':np.zeros_like(arrays['context_ids']), 'context_lengths':np.zeros_like(arrays['context_lengths'])}
                    model.to('cpu')
                    with torch.inference_mode():
                        inputs,_ = harness._tensors(modified,modified['features'],parity_indexes,torch.device('cpu'))
                        cpu_scores=model(*inputs).numpy().copy()
                    model.to('cuda:0'); parts=[]
                    with torch.inference_mode():
                        for offset in range(0,75000,256):
                            if time.monotonic()-started>plan['limits']['stage_seconds']:
                                raise TimeoutError('audit_wall_deadline')
                            indexes=np.arange(offset,min(offset+256,75000))
                            inputs,_=harness._tensors(modified,modified['features'],indexes,torch.device('cuda:0'))
                            parts.append(model(*inputs).cpu().numpy());terminal['rows_completed']+=len(indexes)
                    value=np.concatenate(parts)
                    if value.shape!=(75000,6) or not np.isfinite(value).all():
                        raise ValueError('audit_nonfinite_or_incomplete_scores')
                    selected=value[parity_indexes]
                    terminal.update(status='complete',cpu_parity_rows=len(parity_indexes),
                        cpu_allclose=bool(np.allclose(selected,cpu_scores,atol=1e-5,rtol=1e-5)),
                        cpu_max_absolute_difference=float(np.abs(selected-cpu_scores).max()),
                        cpu_winner_mismatches=int((selected.argmax(axis=1)!=cpu_scores.argmax(axis=1)).sum()))
                    scores[key]=value
                except Exception as error:
                    terminal['error_type']=type(error).__name__;raise
                finally:
                    execution['conditions'].append(terminal)
                print(json.dumps(dict(model=item['name'],context=context,status=terminal['status'],rows=75000)),flush=True)
            del model
        authenticate()
        with (ROOT/'scores.npz').open('xb') as stream:np.savez_compressed(stream,**scores)
        execution.update(status='complete', scores_sha256=sha(ROOT/'scores.npz'),
            cpu_parity_passed=all(r['cpu_allclose'] and not r['cpu_winner_mismatches'] for r in execution['conditions']))
    except Exception as error:
        execution['error_type']=type(error).__name__;raise
    finally:
        execution.update(elapsed_seconds=round(time.monotonic()-started,3), not_attempted_conditions=14-len(execution['conditions']),
            forbidden_data_read_attempts=guard.blocked, observed_data_read_paths=sorted(p.relative_to(Path.cwd()).as_posix() for p in guard.observed))
        save(ROOT/'inference.json',execution)
    return {k:execution[k] for k in ('status','elapsed_seconds','cpu_parity_passed','not_attempted_conditions','forbidden_data_read_attempts')}


def report():
    import numpy as np
    plan,fit=authenticate()
    execution=json.loads((ROOT/'inference.json').read_text())
    if execution['status']!='complete' or execution['not_attempted_conditions'] or execution['forbidden_data_read_attempts'] or sha(ROOT/'scores.npz')!=execution['scores_sha256']:
        raise ValueError('audit_complete_scores_required')
    arrays,cohorts,_=load_training(fit); groups=partitions(cohorts,75000)
    populations=slices(groups,arrays['reading_lengths'])
    with np.load(io.BytesIO((ROOT/'scores.npz').read_bytes()),allow_pickle=False) as saved:
        scores={key:np.array(saved[key]) for key in saved.files}
    expected={c+'/'+m['name'] for c in plan['contexts'] for m in plan['models']}
    if set(scores)!=expected:raise ValueError('audit_all_model_conditions_required')
    results={}; observed={}; transitions={}
    for gate in plan['gates']:
        for key,value in scores.items():
            full=gate+'/'+key;obs=observations(value,arrays,gate!='ungated');observed[full]=obs
            results[full]={name:summary(obs,indexes) for name,indexes in populations.items()}
            transitions[full]={name:np.bincount(arrays['gold'][indexes]*6+obs['winner'][indexes],minlength=36).reshape(6,6).tolist() for name,indexes in groups.items()}
    paired_results={};context_results={}
    for gate in plan['gates']:
        for seed in (20260814,20261103,20261104):
            for context in plan['contexts']:
                prefix=gate+'/'+context+'/'
                paired_results[gate+'/'+context+'/'+str(seed)]={name:paired(observed[prefix+'dictionary-s'+str(seed)],observed[prefix+'annotation-s'+str(seed)],indexes) for name,indexes in groups.items()}
        for model in plan['models']:
            name=model['name']
            context_results[gate+'/'+name]={group:paired(observed[gate+'/intact/'+name],observed[gate+'/empty/'+name],indexes) for group,indexes in groups.items()}
    result=dict(kind='train_only_change_diagnostic',status='descriptive_fitted_training_only',
        inference_sha256=sha(ROOT/'inference.json'),scores_sha256=sha(ROOT/'scores.npz'),
        plan_sha256=sha(HERE/'plan-v1.json'),profile=json.loads((ROOT/'profile.json').read_text()),
        metrics=results,gold_rank_to_selected_rank=transitions,annotation_minus_dictionary=paired_results,
        empty_minus_intact=context_results,new_fits=0,independent_accuracy_estimated=False,
        calibration_performed=False,gold_certified=False,production_adoption=False,final_test_used=False,safety_threshold=.0025)
    save(ROOT/'report.json',result)
    return dict(status=result['status'],metric_populations=sum(len(v) for v in results.values()),new_fits=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['infer','report'])
    args=parser.parse_args();print(json.dumps(infer() if args.mode=='infer' else report()))
