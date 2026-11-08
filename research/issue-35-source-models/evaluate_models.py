"""Score sealed fixed models against source reconstruction, never Gold admission."""
from collections import Counter
import hashlib
import json

import numpy as np

from sakura_rerank.evaluation_metrics import EvaluationCase,EvaluationRun,evaluate_runs
from sakura_rerank.evaluation_statistics import paired_component_bootstrap,wilson95
from model35_common import ROOT,read,save,sha
from run_models import bound_inputs
from source_score_outcomes import fixed_observation


def sealed_predictions():
    seal=read(ROOT/'outputs-seal.json');report=read(ROOT/'inference-report.json')
    if seal['inference_report_sha256']!=sha(ROOT/'inference-report.json') or seal['models']!=report['models']:
        raise ValueError('source_models_output_seal_changed')
    bound,plan,_=bound_inputs(report['binding_commit']);outputs={};states={}
    if [m['name'] for m in report['models']]!=[m['name'] for m in bound['models']]:raise ValueError('source_models_output_family_changed')
    for model in report['models']:
        name=model['name']
        for suffix,key in (('scores.npz','scores_sha256'),('terminals.json','terminals_sha256'),('timings.npz','timings_sha256')):
            if sha(ROOT/(name+'-'+suffix))!=model[key]:raise ValueError('source_models_sealed_output_changed')
        with np.load(ROOT/(name+'-scores.npz'),allow_pickle=False) as archive:outputs[name]=archive['scores']
        states[name]=read(ROOT/(name+'-terminals.json'))['states']
        if outputs[name].shape!=(bound['quality_inputs'],6) or len(states[name])!=bound['quality_inputs']:
            raise ValueError('source_models_sealed_count')
    return plan,report,outputs,states


def observations(cases,plan,outputs,states):
    runs={}
    models={m['name']:m for m in plan['models']}
    for variant in plan['variants']:
        name=variant.split('-')[0];threshold=models[name]['published_gate_tau'] if variant.endswith('published-gate') else None
        runs[variant]={}
        for row in cases:
            index=row['tensor_index']
            key=hashlib.sha256(row['stable_id'].encode()).hexdigest()
            runs[variant][key]=fixed_observation(outputs[name][index],states[name][index],min(6,len(row['candidates'])),threshold)
    return runs


def chosen_surface(row,observation):
    index=observation.ranking[0] if observation.status=='applied' else 0
    return row['candidates'][index]


def sentence_metrics(document,run_observations,plan):
    cases={c['stable_id']:c for c in document['cases']};names=plan['variants'];complete=[];source_statuses=Counter()
    for slot in document['slots']:
        source_statuses[slot['status']]+=1
        if slot['status']!='native_measured':continue
        rows=[cases[key] for key in slot['input_ids']]
        components={r['component'] for r in rows}
        if not rows or len(components)!=1:raise ValueError('source_models_sentence_component_contract')
        baseline=all(row['candidates'][0]==row['target'] for row in rows)
        result=dict(slot=slot['slot'],component=next(iter(components)),baseline=baseline,models={})
        for name in names:
            selected=[chosen_surface(row,run_observations[name][hashlib.sha256(row['stable_id'].encode()).hexdigest()]) for row in rows]
            result['models'][name]=dict(correct=all(surface==row['target'] for surface,row in zip(selected,rows)),
                changed=any(surface!=row['candidates'][0] for surface,row in zip(selected,rows)))
        complete.append(result)
    n=len(complete);base=sum(r['baseline'] for r in complete);errors=n-base;reports={};vectors=[];ratios={}
    for row in complete:
        vector=[1,int(row['baseline'])]
        for name in names:
            correct=row['models'][name]['correct'];vector.extend((int(correct),int(row['baseline'] and not correct)))
        for left,right in plan['comparisons']:
            a=row['models'][left]['correct'];b=row['baseline'] if right=='baseline' else row['models'][right]['correct']
            vector.append(int(a)-int(b))
        vectors.append(vector)
    for index,name in enumerate(names):
        correct=rescue=harm=wrong=changed=0
        for row in complete:
            out=row['models'][name];correct+=out['correct'];changed+=out['changed']
            rescue+=not row['baseline'] and out['correct'];harm+=row['baseline'] and not out['correct']
            wrong+=not row['baseline'] and not out['correct'] and out['changed']
        if changed!=rescue+harm+wrong or correct!=base+rescue-harm:raise ValueError('source_models_sentence_reconciliation')
        reports[name]=dict(measured_sentences=n,source_matching=correct,match_gained=rescue,match_lost=harm,
            change_failure=harm+wrong,wrong_to_different_wrong=wrong,changed=changed,
            precision=rescue/changed if changed else None,recall=rescue/errors if errors else None,
            application_to_mismatched_sources=(rescue+wrong)/errors if errors else None,
            match_fraction_among_measured=correct/n,match_fraction_wilson95_row_assumption=wilson95(correct,n),
            full1000_identification_bounds=[correct/1000,(correct+1000-n)/1000],baseline_gain=(rescue-harm)/n)
        ratios[name+'-source-match']=(2+2*index,0);ratios[name+'-match-loss']=(3+2*index,1)
    for index,(left,right) in enumerate(plan['comparisons']):ratios[left+'__vs__'+right]=(2+2*len(names)+index,0)
    intervals=paired_component_bootstrap([r['component'] for r in complete],vectors,ratios,
        replicates=plan['statistics']['bootstrap_replicates'],seed=plan['statistics']['seed'])
    return dict(reserved_sentences=1000,source_statuses=dict(source_statuses),measured_sentences=n,
        baseline_source_matching=base,baseline_source_mismatching=errors,models=reports,conditional_component_intervals=intervals,
        bounds_are_not_confidence_intervals=True,unknown_sentences=1000-n,independent_accuracy=None,gold_quality=None)


def evaluate():
    plan,inference,outputs,states=sealed_predictions()
    save(ROOT/'evaluation-reservation.json',dict(inference_report_sha256=sha(ROOT/'inference-report.json'),
        outputs_seal_sha256=sha(ROOT/'outputs-seal.json'),variants=plan['variants'],threshold_selection=False,final_test=False))
    document=read(ROOT/'source-cases.json');cases=document['cases']
    if len(document['slots'])!=1000 or [s['slot'] for s in document['slots']]!=list(range(1000)):
        raise ValueError('source_models_full_slot_denominator')
    obs=observations(cases,plan,outputs,states);part_reports={}
    model_complete={m['name']:m['quality_complete'] for m in inference['models']}
    for group in plan['slices']:
        chosen=[r for r in cases if group=='all' or group=='isolated_hypothesis' and not r['historically_related']
            or group=='historically_related' and r['historically_related']
            or group=='prefix_complete' and not r['prefix_truncated'] or group=='prefix_truncated' and r['prefix_truncated']
            or group in ('named_editor','no_editor') and r['stratum']==group]
        if not chosen:part_reports[group]=dict(status='empty_prespecified_slice',record_count=0);continue
        evaluation_cases=[EvaluationCase(hashlib.sha256(r['stable_id'].encode()).hexdigest(),r['component'],tuple(r['candidates']),r['target']) for r in chosen]
        keys={c.case_key for c in evaluation_cases}
        runs={name:EvaluationRun({key:value for key,value in values.items() if key in keys},model_complete[name.split('-')[0]]) for name,values in obs.items()}
        part_reports[group]=evaluate_runs(evaluation_cases,runs,comparisons=[tuple(p) for p in plan['comparisons']],
            bootstrap_replicates=plan['statistics']['bootstrap_replicates'],bootstrap_seed=plan['statistics']['seed'])
        print(json.dumps(dict(stage='source_metrics',slice=group,cases=len(chosen))),flush=True)
    sentence=sentence_metrics(document,obs,plan)
    report=dict(kind='fixed_three_model_source_reconstruction',status='complete_source_research_only',
        inference_report_sha256=sha(ROOT/'inference-report.json'),outputs_seal_sha256=sha(ROOT/'outputs-seal.json'),
        source_case_sha256=sha(ROOT/'source-cases.json'),parts=part_reports,sentences=sentence,
        interval_scope=plan['statistics']['scope'],thresholds_fixed=True,models_trained=0,
        independent_accuracy=None,gold_quality=None,safety_gate_pass=False,release_eligible=False,final_test=False)
    save(ROOT/'evaluation.json',report)
    summary={name:{key:r[key] for key in ('record_count','correction_success','correction_failure','baseline_correct_destroyed','effective_changes','baseline_gain')}
        for name,r in part_reports['all']['models'].items()}
    print(json.dumps(dict(status=report['status'],all_part_baseline=part_reports['all']['baseline_correct'],models=summary)))


if __name__=='__main__':evaluate()
