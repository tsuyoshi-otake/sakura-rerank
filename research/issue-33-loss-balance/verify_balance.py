"""Recount saved predictions, shared-component intervals, provenance and CPU samples."""
import argparse
import ast
from collections import Counter
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import NormalDist
import subprocess
import sys

import numpy as np

from sakura_rerank.data.kwdlc_probe import blob_sha1
from balance_common import ROOT,boundary,read,rows,save,sha
from balance_fit_contract import authenticated_bytes
from evaluate_balance import bound_evaluation,evaluation_arrays,helpers


def assert_same(actual,expected,code):
    if actual!=expected:raise ValueError(code)


def scalar_observations(arrays,scores,gated):
    output=[]
    for i,values in enumerate(scores):
        valid=np.flatnonzero(arrays['candidate_mask'][i]).tolist()
        available=bool(valid);finite=bool(np.isfinite(values).all())
        prediction=0
        if available and finite:
            best=max(valid,key=lambda j:float(values[j]))
            if not gated or float(values[best]-values[0])>1.7:prediction=best
        base=bool(arrays['correct_mask'][i,0]);correct=bool(arrays['correct_mask'][i,prediction])
        changed=available and not bool(arrays['baseline_equivalent'][i,prediction])
        output.append(dict(baseline=base,correct=correct,changed=changed,available=available,
                           inference_failed=available and not finite,predicted=prediction))
    return output


def scalar_counts(observations,indexes):
    values=[observations[i] for i in indexes]
    n=len(values);base=sum(r['baseline'] for r in values);correct=sum(r['correct'] for r in values)
    rescue=sum(not r['baseline'] and r['correct'] for r in values)
    harm=sum(r['baseline'] and not r['correct'] for r in values)
    wrong=sum(not r['baseline'] and not r['correct'] and r['changed'] for r in values)
    changed=sum(r['changed'] for r in values)
    return dict(rows=n,baseline_correct=base,baseline_errors=n-base,correct=correct,rescue=rescue,harm=harm,
        wrong_to_wrong=wrong,correction_failure=harm+wrong,changed=changed,
        candidate_acquisition_failure=sum(not r['available'] for r in values),
        model_inference_failure=sum(r['inference_failed'] for r in values))


def independent_mean_interval(clusters,deltas):
    # Direct component sums with a three-seed denominator, not the producer's
    # repeated-row helper. Integer products stay exactly representable here.
    keys=sorted(set(clusters));position={key:i for i,key in enumerate(keys)}
    totals=np.zeros((len(keys),2),dtype=np.float64)
    for i,key in enumerate(clusters):
        totals[position[key],0]+=sum(int(delta[i]) for delta in deltas)
        totals[position[key],1]+=len(deltas)
    rng=np.random.Generator(np.random.PCG64(20261106));samples=[]
    for offset in range(0,2000,32):
        draws=rng.multinomial(len(keys),np.full(len(keys),1/len(keys)),size=min(32,2000-offset))
        values=draws@totals
        samples.extend((values[:,0]/values[:,1]).tolist())
    return np.quantile(samples,[.025,.975],method='linear').tolist()


def independent_wilson(successes,total):
    if not total:return None
    z=NormalDist().inv_cdf(.975);z2=z*z
    center=(successes+z2/2)/(total+z2)
    radius=z*math.sqrt(successes*(total-successes)/total+z2/4)/(total+z2)
    return [max(0.,center-radius),min(1.,center+radius)]


@lru_cache(maxsize=512)
def independent_exact(successes,total):
    if not total:return dict(two_sided=None,upper_one_sided=None)
    combinations=[math.comb(total,j) for j in range(total+1)]
    def upper(k,alpha):
        if k==total:return 1.
        low,high=0.,1.
        for _ in range(64):
            p=(low+high)/2
            cdf=math.fsum(combinations[j]*p**j*(1-p)**(total-j) for j in range(k+1))
            if cdf>alpha:low=p
            else:high=p
        return (low+high)/2
    return dict(two_sided=[1-upper(total-successes,.025),upper(successes,.025)],upper_one_sided=upper(successes,.05))


def verify_training_replay(plan,fit):
    from balance_fit_contract import TRAIN_CACHE
    training=read(ROOT/'training-execution.json')
    path=TRAIN_CACHE/'cohort-indices.json'
    cohorts=json.loads(authenticated_bytes(path,fit['training_artifacts'][path.as_posix()]))
    original=Path('research/issue-33-annotation-experiment/train_models.py')
    tree=ast.parse(authenticated_bytes(original,plan['inputs'][original.as_posix()]))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='batches')
    namespace={};exec(compile(ast.Module(body=[function],type_ignores=[]),str(original),'exec'),namespace)
    exposures=[]
    for model in training['models']:
        digest=hashlib.sha256();rows_seen=0
        for batch in namespace['batches'](np.asarray(cohorts['annotation'],dtype=np.int64),model['seed'],256,500):
            digest.update(batch.astype('<i8',copy=False).tobytes());rows_seen+=len(batch)
        assert_same((digest.hexdigest(),rows_seen),(model['exposure_order_sha256'],128000),'control_exposure_order')
        exposures.append(dict(seed=model['seed'],rows_seen=rows_seen,identical_control_order=True))
    path=TRAIN_CACHE/'arrays.npz'
    with np.load(io.BytesIO(authenticated_bytes(path,fit['training_artifacts'][path.as_posix()])),allow_pickle=False) as saved:
        baseline=np.array(saved['correct_mask'])[:,0]
    path=ROOT/'training-weights.npy'
    weights=np.load(io.BytesIO(authenticated_bytes(path,fit['training_artifacts'][path.as_posix()])),allow_pickle=False)
    common=set(cohorts['dictionary'])&set(cohorts['annotation'])
    dictionary=set(cohorts['dictionary'])-common;annotation=set(cohorts['annotation'])-common
    d=sum(bool(baseline[i]) for i in dictionary);a=sum(bool(baseline[i]) for i in annotation)
    assert_same((len(common),len(dictionary),len(annotation),d,a),(25000,25000,25000,18776,12830),'weight_source_counts')
    for i in range(75000):
        expected=np.float32(d/a if baseline[i] else (25000-d)/(25000-a)) if i in annotation else np.float32(1)
        assert_same(weights[i],expected,'independent_per_row_loss_weight')
    assert_same(training['forbidden_data_read_attempts'],0,'fit_read_guard')
    assert_same(training['evaluation_arrays_loaded'],False,'no_fit_evaluation_read')
    return dict(weights_checked=75000,control_exposure_replays=exposures,
        source_correct_counts=dict(dictionary=d,annotation=a),forbidden_data_reads=0)


def verify(commit):
    plan,fit,bound=bound_evaluation(commit)
    report=read(ROOT/'model-report.json');execution=read(ROOT/'scores/execution.json')
    arrays=evaluation_arrays(fit)
    with np.load(io.BytesIO(authenticated_bytes(ROOT/'scores/all.npz',execution['scores_sha256'])),allow_pickle=False) as saved:
        scores={key:np.array(saved[key]) for key in saved.files}
    conditions=read(ROOT/'conditions.json');targets=list(rows(ROOT/'forward-targets.jsonl.gz'))
    scalar={};checked=0;rate_intervals=0
    for key,metrics in report['metrics'].items():
        gate,context,model=key.split('/')
        observation=scalar_observations(arrays,scores[context+'/'+model],gate=='gated');scalar[key]=observation
        for population,indexes in conditions['populations'].items():
            if not indexes:continue
            counts=scalar_counts(observation,indexes)
            for name,value in counts.items():assert_same(value,metrics[population][name],'independent_metric_count')
            for name,numerator,denominator in (
                ('accuracy',counts['correct'],counts['rows']),('baseline_accuracy',counts['baseline_correct'],counts['rows']),
                ('precision',counts['rescue'],counts['changed']),('recall',counts['rescue'],counts['baseline_errors']),
                ('application',counts['changed'],counts['rows']),('harm_rate',counts['harm'],counts['baseline_correct']),
                ('application_to_error',sum(observation[i]['changed'] and not observation[i]['baseline'] for i in indexes),counts['baseline_errors'])):
                value=metrics[population][name]
                assert_same((numerator,denominator),(value['numerator'],value['denominator']),'independent_metric_denominator')
                assert_same(numerator/denominator if denominator else None,value['value'],'independent_metric_rate')
                expected=independent_wilson(numerator,denominator)
                if expected is None:assert_same(value['wilson95_row_assumption'],None,'empty_interval')
                else:np.testing.assert_allclose(value['wilson95_row_assumption'],expected,rtol=0,atol=1e-14)
                rate_intervals+=1
            exact=independent_exact(counts['harm'],counts['baseline_correct'])
            for field in ('two_sided','upper_one_sided'):
                if exact[field] is None:assert_same(metrics[population]['harm_exact95_row_assumption'][field],None,'empty_harm_interval')
                else:np.testing.assert_allclose(metrics[population]['harm_exact95_row_assumption'][field],exact[field],rtol=0,atol=1e-12)
            assert_same((counts['rescue']-counts['harm'])/counts['rows'],metrics[population]['baseline_gain'],'independent_baseline_gain')
            assert_same(sum(not arrays['correct_mask'][i].any() for i in indexes),metrics[population]['source_absent_top6'],'independent_candidate_absence')
            assert_same(sum(bool(arrays['correct_mask'][i].any()) and not observation[i]['correct'] for i in indexes),
                        metrics[population]['source_present_top6_but_not_correct'],'independent_ranking_failure')
            checked+=1
    main=conditions['populations']['main'];deltas=[]
    for seed in plan['training']['seeds']:
        a=scalar[f'ungated/intact/weighted-s{seed}'];d=scalar[f'ungated/intact/annotation-s{seed}']
        deltas.append([int(a[i]['correct'])-int(d[i]['correct']) for i in main])
    clusters=helpers().cluster_ids(targets,main,False)
    mean=sum(sum(delta) for delta in deltas)/(3*len(main))
    ci=independent_mean_interval(clusters,deltas)
    assert_same(mean,report['primary_comparison']['mean_difference'],'independent_primary_mean')
    assert_same(ci,report['primary_comparison']['ci95'],'independent_primary_interval')
    harms=[scalar_counts(scalar[f'ungated/intact/weighted-s{s}'],main)['harm']
        -scalar_counts(scalar[f'ungated/intact/annotation-s{s}'],main)['harm'] for s in plan['training']['seeds']]
    assert_same(harms,report['primary_comparison']['per_seed_harm_differences'],'independent_harm_changes')
    advance=execution['status']=='complete' and all(sum(delta)>=0 for delta in deltas) and ci[0]>0 and all(h<=0 for h in harms)
    assert_same(advance,report['primary_comparison']['advances'],'independent_advance_rule')
    for index,item in enumerate(report['per_seed_descriptive_comparisons']):
        assert_same(item['main_net_rows'],sum(deltas[index]),'independent_seed_gain')
        assert_same(item['main_harm_difference'],harms[index],'independent_seed_harm')
        assert_same(item['main_paired_ci95'],independent_mean_interval(clusters,[deltas[index]]),'independent_seed_interval')
    for model in bound['models']:
        u=scalar['ungated/intact/'+model['name']];g=scalar['gated/intact/'+model['name']]
        expected=dict(prevented_harms=sum(u[i]['baseline'] and not u[i]['correct'] and g[i]['correct'] for i in main),
            suppressed_rescues=sum(not u[i]['baseline'] and u[i]['correct'] and not g[i]['correct'] for i in main))
        assert_same(expected,report['gate_effects'][model['name']],'independent_gate_effects')
    training_replay=verify_training_replay(plan,fit)

    acquisition=read(ROOT/'acquisition.json');selection=read(plan['evaluation']['selection_path'])
    assert_same(acquisition['status'],'complete','complete_source_acquisition')
    assert_same(len(acquisition['attempts']),615,'source_slot_count')
    for document,attempt in zip(selection['documents'],acquisition['attempts']):
        assert_same(document['document_id'],attempt['document_id'],'source_slot_identity')
        path=ROOT/'source'/(document['document_id']+'.knp');raw=authenticated_bytes(path,attempt['sha256'],1048576)
        assert_same((len(raw),blob_sha1(raw)),(document['bytes'],document['git_blob_sha1']),'original_source_blob')
    prep=read(ROOT/'preparation.json');cohort=read(ROOT/'cohort.json')
    for value,base in ((prep,ROOT/'prepared'),(cohort,ROOT/'cohort')):
        for artifact in value['artifacts'].values():assert_same(sha(base/artifact['path']),artifact['sha256'],'source_cohort_artifact')
        for path,digest in value['code'].items():
            assert_same(sha(path),digest,'source_cohort_implementation')
            boundary.committed(path,value['code_commit'])
    assert_same(cohort['preparation_sha256'],sha(ROOT/'preparation.json'),'cohort_preparation_binding')
    assert_same(cohort['full_reverse_replay'],True,'full_reverse_graph_required')
    slots=list(rows(ROOT/'cohort/main-terminal.jsonl.gz'))
    assert_same(dict(Counter(s['status'] for s in slots)),cohort['main_statuses'],'full_main_slot_accounting')
    assert_same(len(slots),615,'full_main_denominator')

    cpu=read(ROOT/'cpu-benchmark/report.json')
    assert_same(cpu['status'],'complete','complete_cpu_benchmark')
    assert_same([m['arm'] for m in cpu['models']],['annotation','weighted'],'fixed_cpu_arms')
    for model in cpu['models']:
        assert_same(model['seed'],20260814,'fixed_cpu_seed')
        assert_same(sha(ROOT/'cpu-benchmark'/model['model']/'model-fp32.onnx'),model['onnx_sha256'],'cpu_export_artifact')
        path=ROOT/'cpu-benchmark'/model['model']/'latencies-ns.npy'
        raw=authenticated_bytes(path,model['latency_samples_sha256'])
        times=np.load(io.BytesIO(raw),allow_pickle=False)
        assert_same(times.shape,(10000,),'all_cpu_runs')
        for name,value in zip(('p50_ms','p95_ms','p99_ms'),np.quantile(times/1_000_000.,[.5,.95,.99],method='linear')):
            assert_same(float(value),model[name],'cpu_sample_quantile')
        assert_same(model['failures'],0,'cpu_run_failures')
        if any(not p['allclose'] or p['winner_mismatches'] for p in model['parity'].values()):
            raise ValueError('cpu_parity_contract')
    integrity=json.loads(subprocess.check_output([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],text=True,timeout=120))
    assert_same(integrity['status'],'passed','original_artifacts_unchanged')
    result=dict(kind='loss_balance_result_verification',status='passed',scalar_metric_populations_checked=checked,
        score_conditions=len(scores),original_source_blobs_verified=615,all_source_cohort_artifacts_verified=True,
        fixed_main_slots=615,main_rows=len(main),shared_component_mean_recomputed=True,mean_difference=mean,ci95=ci,
        research_advances=advance,latency_samples_verified=20000,rate_intervals_checked=rate_intervals,
        exact_harm_intervals_checked=checked,training_replay=training_replay,
        original_integrity=integrity,model_report_sha256=sha(ROOT/'model-report.json'),cpu_report_sha256=sha(ROOT/'cpu-benchmark/report.json'),
        source_report_sha256=sha(ROOT/'preparation.json'),cohort_report_sha256=sha(ROOT/'cohort.json'),
        training_report_sha256=sha(ROOT/'training-execution.json'),candidate_report_sha256=sha(ROOT/'candidate-report.json'),
        script_sha256=sha(__file__),gold_certified=False,final_test_used=False,production_adoption=False,
        verification_method='Direct Codex verification using saved scores, scalar per-row arithmetic and separate aggregated-component bootstrap; no external agent or human review.')
    save(ROOT/'verification.json',result)
    return {key:result[key] for key in ('status','scalar_metric_populations_checked','original_source_blobs_verified',
                                      'mean_difference','ci95','research_advances','latency_samples_verified')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evaluation-commit',required=True)
    print(json.dumps(verify(parser.parse_args().evaluation_commit)))
