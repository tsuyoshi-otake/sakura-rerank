"""Recount saved predictions, shared-component intervals, provenance and CPU samples."""
import argparse
from collections import Counter,defaultdict
import io
import json
import subprocess
import sys

import numpy as np

from sakura_rerank.data.kwdlc_probe import blob_sha1
from experiment_common import ROOT,PREPARATION_ROOT,read,rows,save,sha
from experiment_fit_contract import authenticated_bytes
from evaluate_experiment import bound_evaluation,evaluation_arrays,helpers


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
        totals[position[key],1]+=3
    rng=np.random.Generator(np.random.PCG64(20261105));samples=[]
    for offset in range(0,2000,32):
        draws=rng.multinomial(len(keys),np.full(len(keys),1/len(keys)),size=min(32,2000-offset))
        values=draws@totals
        samples.extend((values[:,0]/values[:,1]).tolist())
    return np.quantile(samples,[.025,.975],method='linear').tolist()


def verify(commit):
    plan,fit,bound=bound_evaluation(commit)
    report=read(ROOT/'model-report.json');execution=read(ROOT/'scores/execution.json')
    arrays=evaluation_arrays(fit)
    with np.load(io.BytesIO(authenticated_bytes(ROOT/'scores/all.npz',execution['scores_sha256'])),allow_pickle=False) as saved:
        scores={key:np.array(saved[key]) for key in saved.files}
    conditions=read(ROOT/'conditions.json');targets=list(rows(ROOT/'forward-targets.jsonl.gz'))
    scalar={};checked=0
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
            assert_same((counts['rescue']-counts['harm'])/counts['rows'],metrics[population]['baseline_gain'],'independent_baseline_gain')
            assert_same(sum(not arrays['correct_mask'][i].any() for i in indexes),metrics[population]['source_absent_top6'],'independent_candidate_absence')
            assert_same(sum(bool(arrays['correct_mask'][i].any()) and not observation[i]['correct'] for i in indexes),
                        metrics[population]['source_present_top6_but_not_correct'],'independent_ranking_failure')
            checked+=1
    main=conditions['populations']['main'];deltas=[]
    for seed in plan['training']['seeds']:
        a=scalar[f'ungated/intact/annotation-s{seed}'];d=scalar[f'ungated/intact/dictionary-s{seed}']
        deltas.append([int(a[i]['correct'])-int(d[i]['correct']) for i in main])
    clusters=helpers().cluster_ids(targets,main,False)
    mean=sum(sum(delta) for delta in deltas)/(3*len(main))
    ci=independent_mean_interval(clusters,deltas)
    assert_same(mean,report['primary_comparison']['mean_difference'],'independent_primary_mean')
    assert_same(ci,report['primary_comparison']['ci95'],'independent_primary_interval')
    advance=execution['status']=='complete' and all(sum(delta)>=0 for delta in deltas) and ci[0]>0
    assert_same(advance,report['primary_comparison']['advances'],'independent_advance_rule')

    # Prespecified contexts; length strata below are explicitly post-hoc,
    # descriptive only, and cannot authorize selection or word backfill.
    strata=defaultdict(list)
    for i in main:
        length=len(targets[i]['reading'])
        strata['2' if length==2 else '3-4' if length<=4 else '5-8' if length<=8 else '9-32'].append(i)
    diagnostic={}
    for length,indexes in sorted(strata.items()):
        diagnostic[length]=dict(rows=len(indexes),baseline_correct=sum(bool(arrays['correct_mask'][i,0]) for i in indexes),arms={})
        for arm in ('dictionary','annotation'):
            values=[scalar_counts(scalar[f'ungated/intact/{arm}-s{seed}'],indexes) for seed in plan['training']['seeds']]
            diagnostic[length]['arms'][arm]={key:[value[key] for value in values] for key in ('correct','rescue','harm','wrong_to_wrong')}
    diagnostic_report=dict(kind='annotation_experiment_posthoc_length_diagnostic',status='descriptive_only',
        selected_by_outcomes=False,predeclared_primary_changed=False,new_fits=0,
        use='Aggregate hypothesis generation only; no evaluation words/targets fed into training and no retuning on these 985 rows.',
        reading_length_strata=diagnostic,training_profiles=read(PREPARATION_ROOT/'numeric-r2/report.json')['profiles'],
        causal_interpretation='Extraction unit, lexical/domain distribution, reading length and label difficulty changed together. Their separate causal contributions remain unmeasured.')

    acquisition=read(ROOT/'acquisition.json');selection=read(plan['evaluation']['selection_path'])
    assert_same(acquisition['status'],'complete','complete_source_acquisition')
    assert_same(len(acquisition['attempts']),1000,'source_slot_count')
    for document,attempt in zip(selection['documents'],acquisition['attempts']):
        assert_same(document['document_id'],attempt['document_id'],'source_slot_identity')
        path=ROOT/'source'/(document['document_id']+'.knp');raw=authenticated_bytes(path,attempt['sha256'],1048576)
        assert_same((len(raw),blob_sha1(raw)),(document['bytes'],document['git_blob_sha1']),'original_source_blob')
    prep=read(ROOT/'preparation.json');cohort=read(ROOT/'cohort.json')
    for value,base in ((prep,ROOT/'prepared'),(cohort,ROOT/'cohort')):
        for artifact in value['artifacts'].values():assert_same(sha(base/artifact['path']),artifact['sha256'],'source_cohort_artifact')
        for path,digest in value['implementation'].items():assert_same(sha(path),digest,'source_cohort_implementation')
    assert_same(cohort['preparation_sha256'],sha(ROOT/'preparation.json'),'cohort_preparation_binding')
    assert_same(cohort['full_reverse_replay'],True,'full_reverse_graph_required')
    slots=list(rows(ROOT/'cohort/main-terminal.jsonl.gz'))
    assert_same(dict(Counter(s['status'] for s in slots)),cohort['main_statuses'],'full_main_slot_accounting')
    assert_same(len(slots),1000,'full_main_denominator')

    cpu=read(ROOT/'cpu-benchmark/report.json')
    assert_same(cpu['status'],'complete','complete_cpu_benchmark')
    assert_same([m['arm'] for m in cpu['models']],['dictionary','annotation'],'fixed_cpu_arms')
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
    result=dict(kind='annotation_experiment_result_verification',status='passed',scalar_metric_populations_checked=checked,
        score_conditions=len(scores),original_source_blobs_verified=1000,all_source_cohort_artifacts_verified=True,
        fixed_main_slots=1000,main_rows=len(main),shared_component_mean_recomputed=True,mean_difference=mean,ci95=ci,
        research_advances=advance,latency_samples_verified=20000,
        original_integrity=integrity,model_report_sha256=sha(ROOT/'model-report.json'),cpu_report_sha256=sha(ROOT/'cpu-benchmark/report.json'),
        source_report_sha256=sha(ROOT/'preparation.json'),cohort_report_sha256=sha(ROOT/'cohort.json'),
        training_report_sha256=sha(ROOT/'training-execution.json'),candidate_report_sha256=sha(ROOT/'candidate-report.json'),
        script_sha256=sha(__file__),gold_certified=False,final_test_used=False,production_adoption=False,
        verification_method='Direct Codex verification using saved scores, scalar per-row arithmetic and separate aggregated-component bootstrap; no external agent or human review.')
    save(ROOT/'length-diagnostic.json',diagnostic_report)
    save(ROOT/'verification.json',result)
    return {key:result[key] for key in ('status','scalar_metric_populations_checked','original_source_blobs_verified',
                                      'mean_difference','ci95','research_advances','latency_samples_verified')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evaluation-commit',required=True)
    print(json.dumps(verify(parser.parse_args().evaluation_commit)))
