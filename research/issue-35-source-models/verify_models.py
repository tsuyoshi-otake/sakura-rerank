"""Directly reproduce feeds, CPU scores and source-only statistics without fitting."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from model35_common import HERE,ROOT,SOURCE,committed,read,save,sha
from prepare_models import authenticated_snapshots
from run_models import bound_inputs,cpu_session


def require(condition,code):
    if not condition:raise ValueError('source_models_verify_'+code)


def near(actual,expected):
    if actual is None or expected is None:require(actual is expected,'undefined_statistic')
    else:require(np.allclose(actual,expected,rtol=0,atol=2e-12),'numeric_statistic')


def wilson(success,total):
    if not total:return None
    z=1.959963984540054;denominator=total+z*z
    center=(success+z*z/2)/denominator
    spread=z*math.sqrt(success*(1-success/total)+z*z/4)/denominator
    return [max(0,center-spread),min(1,center+spread)]


def binomial_upper(success,total,alpha):
    if success==total:return 1.0
    low,high=0.0,1.0
    for _ in range(64):
        p=(low+high)/2
        cdf=math.fsum(math.comb(total,k)*p**k*(1-p)**(total-k) for k in range(success+1))
        if cdf>alpha:low=p
        else:high=p
    return (low+high)/2


def scalar_feed(snapshot):
    reading=snapshot['reading'];cs=snapshot['candidate_snapshots']['production_top6']['candidates']
    encode=lambda s:[(ord(c)*2654435761)%13311+1 for c in s[:32]]+[0]*max(0,32-len(s))
    costs=[float(c['local_cost']) for c in cs];low=min(costs);span=max(max(costs)-low,1.0)
    features=[]
    for i,c in enumerate(cs):
        surface=c['surface'];common=0
        for a,b in zip(reading,surface):
            if a!=b:break
            common+=1
        features.append([-(costs[i]-low)/span,-i/5,min(len(c['segments']),8)/8,len(surface)/32,
            common/max(len(reading),len(surface),1),float(c['source_category']=='system_dictionary'),
            -math.log1p((costs[i]-low)/1000)])
    padded=6-len(cs)
    return dict(context_ids=np.zeros(64,dtype=np.int64),context_lengths=np.int64(0),
        reading_ids=np.array(encode(reading),dtype=np.int64),reading_lengths=np.int64(min(len(reading),32)),
        candidate_ids=np.array([encode(c['surface']) for c in cs]+[[0]*32]*padded,dtype=np.int64),
        candidate_lengths=np.array([min(len(c['surface']),32) for c in cs]+[0]*padded,dtype=np.int64),
        features=np.array(features+[[0.0]*7]*padded,dtype=np.float32),
        candidate_mask=np.array([True]*len(cs)+[False]*padded,dtype=np.bool_))


def verify_inputs(arrays,document):
    snapshots=authenticated_snapshots();index=read(ROOT/'input-index.json');identities=index['request_ids']
    require(identities==sorted(snapshots) and len(identities)==1221,'request_alignment')
    elements=0;profile_counts=Counter();collisions=truncated_surfaces=reading_overflow=0
    for i,key in enumerate(identities):
        snapshot=snapshots[key];expected=scalar_feed(snapshot)
        require(set(expected)==set(arrays),'feed_fields')
        for name,value in expected.items():
            require(value.dtype==arrays[name][i].dtype and np.array_equal(value,arrays[name][i]),'scalar_feed')
            elements+=value.size
        cs=snapshot['candidate_snapshots']['production_top6']['candidates'];profile=index['profiles'][key]
        profile_counts[len(cs)]+=1;overflow=len(snapshot['reading'])>32;reading_overflow+=overflow
        st=sum(len(c['surface'])>32 for c in cs);truncated_surfaces+=st
        same=hashed=0
        for left in range(len(cs)):
            for right in range(left+1,len(cs)):
                a,b=cs[left]['surface'],cs[right]['surface']
                if a!=b and expected['candidate_lengths'][left]==expected['candidate_lengths'][right] and np.array_equal(expected['candidate_ids'][left],expected['candidate_ids'][right]):
                    if a[:32]==b[:32]:same+=1
                    else:hashed+=1
        collisions+=same+hashed
        require(profile==dict(candidate_count=len(cs),reading_characters=len(snapshot['reading']),reading_truncated=overflow,
            surface_truncations=st,any_truncation=overflow or bool(st),encoded_surface_collision_pairs=same+hashed,
            same_prefix_collision_pairs=same,hash_collision_pairs=hashed,empty_observed_session_context=True),'profile')
    source=read(SOURCE/'consumed-slots.json')['rows'];relations=read(SOURCE/'source-relations-v2.json')
    positions={key:i for i,key in enumerate(identities)};expected_cases=[];expected_slots=[]
    for row in source:
        status='source_unresolved' if not row['inputs'] else 'native_unmeasured' if any(p['request_id'] not in snapshots for p in row['inputs']) else 'native_measured'
        expected_slots.append(dict(slot=row['slot'],status=status,stratum=row['stratum'],input_ids=[p['stable_id'] for p in row['inputs']]))
        for part in row['inputs']:
            if part['request_id'] not in snapshots:continue
            expected_cases.append(dict(stable_id=part['stable_id'],slot=row['slot'],request_id=part['request_id'],tensor_index=positions[part['request_id']],
                component=relations['components'][part['stable_id']],historically_related=part['stable_id'] in relations['excluded'],
                stratum=row['stratum'],target=part['target'],candidates=[c['surface'] for c in snapshots[part['request_id']]['candidate_snapshots']['training_top32']['candidates']],
                prefix_truncated=index['profiles'][part['request_id']]['any_truncation']))
    require(document['cases']==expected_cases and document['slots']==expected_slots,'source_population')
    require([s['slot'] for s in expected_slots]==list(range(1000)),'all_slots')
    return dict(authenticated_native_requests=1230,scalar_verified_inputs=len(identities),scalar_tensor_elements=elements,
        source_slots=len(expected_slots),source_part_cases=len(expected_cases),candidate_counts=dict(profile_counts),
        reading_overflow=reading_overflow,surface_overflow=truncated_surfaces,encoded_surface_collisions=collisions)


def replay(bound,arrays):
    os.environ['CUDA_VISIBLE_DEVICES']='';report=read(ROOT/'inference-report.json');seal=read(ROOT/'outputs-seal.json')
    require(seal['inference_report_sha256']==sha(ROOT/'inference-report.json') and seal['models']==report['models'],'output_seal')
    scores={};counts=[]
    for model,record in zip(bound['models'],report['models'],strict=True):
        name=model['name'];require(name==record['name'],'model_order')
        for suffix,field in [('scores.npz','scores_sha256'),('terminals.json','terminals_sha256'),('timings.npz','timings_sha256')]:
            require(sha(ROOT/(name+'-'+suffix))==record[field],'output_hash')
        with np.load(ROOT/(name+'-scores.npz'),allow_pickle=False) as archive:scores[name]=archive['scores']
        require(scores[name].shape==(1221,6) and scores[name].dtype==np.float32 and np.isfinite(scores[name]).all(),'scores')
        require(read(ROOT/(name+'-terminals.json'))['states']==['complete']*1221,'terminals')
        session=cpu_session(model)
        for i in range(bound['direct_verification_replay_per_model']):
            feed={key:np.ascontiguousarray(value[i:i+1]) for key,value in arrays.items()}
            feed['features']=np.ascontiguousarray(feed['features'][:,:,:model['feature_dim']])
            actual=session.run(['scores'],feed)[0]
            require(actual.shape==(1,6) and np.array_equal(actual[0],scores[name][i]),'exact_cpu_replay')
        del session
        with np.load(ROOT/(name+'-timings.npz'),allow_pickle=False) as archive:times=archive['milliseconds']
        require(len(times)==10000 and np.isfinite(times).all() and (times>0).all(),'timing_runs')
        ordered=sorted(float(t) for t in times)
        for label,q in [('p50',.5),('p95',.95),('p99',.99)]:
            position=(len(ordered)-1)*q;lo=math.floor(position);hi=math.ceil(position)
            near(record['timing_ms'][label],ordered[lo]+(ordered[hi]-ordered[lo])*(position-lo))
        require(record['warmup_calls']==200 and record['quality_calls']==1221 and record['benchmark_calls']==10000,'run_accounting')
        counts.append(dict(model=name,exact_score_rows=1221,timing_runs=10000))
    return scores,counts


def outcomes(cases,plan,scores):
    rows=[];models={m['name']:m for m in plan['models']}
    for case in cases:
        row=dict(component=case['component'],baseline=case['candidates'][0]==case['target'],models={},case=case)
        for name in plan['variants']:
            model=name.split('-')[0];values=[float(v) for v in scores[model][case['tensor_index']]]
            order=sorted(range(min(6,len(case['candidates']))),key=lambda i:(-values[i],i))
            applied=not name.endswith('published-gate') or order[0]!=0 and values[order[0]]-values[0]>models[model]['published_gate_tau']
            if not applied:order=list(range(len(order)))
            selected=case['candidates'][order[0]]
            rank=next((j+1 for j,i in enumerate(order) if case['candidates'][i]==case['target']),None)
            row['models'][name]=dict(correct=selected==case['target'],changed=selected!=case['candidates'][0],applied=applied,rank=rank)
        rows.append(row)
    return rows


def counts(rows,name):
    base=sum(r['baseline'] for r in rows);correct=rescue=harm=wrong=changes=0
    for row in rows:
        value=row['models'][name];c=value['correct'];d=value['changed'];b=row['baseline']
        correct+=c;rescue+=c and not b;harm+=b and not c;wrong+=not c and not b and d;changes+=d
    return dict(n=len(rows),base=base,error=len(rows)-base,correct=correct,rescue=rescue,harm=harm,wrong=wrong,changed=changes)


def independent_intervals(rows,plan,reported,sentences=False):
    # Build named sufficient statistics directly, not the evaluator's column vector.
    names=plan['variants'];components=sorted({r['component'] for r in rows});positions={k:i for i,k in enumerate(components)}
    terms={}
    for name in names:
        terms[name+('-source-match' if sentences else '-accuracy')]=([int(r['models'][name]['correct']) for r in rows],[1]*len(rows))
        terms[name+('-match-loss' if sentences else '-harm')]=([int(r['baseline'] and not r['models'][name]['correct']) for r in rows],[int(r['baseline']) for r in rows])
    for left,right in plan['comparisons']:
        terms[left+'__vs__'+right]=([int(r['models'][left]['correct'])-int(r['baseline'] if right=='baseline' else r['models'][right]['correct']) for r in rows],[1]*len(rows))
    keys=list(terms);aggregated=np.zeros((len(components),len(keys),2),dtype=np.int64)
    for j,key in enumerate(keys):
        for i,row in enumerate(rows):aggregated[positions[row['component']],j]+=np.array([terms[key][0][i],terms[key][1][i]])
    require(reported['component_count']==len(components) and reported['replicates']==10000 and reported['seed']==20261106,'bootstrap_metadata')
    rng=np.random.Generator(np.random.PCG64(20261106));samples={k:[] for k in keys};invalid=Counter()
    for offset in range(0,10000,32):
        draws=rng.multinomial(len(components),np.full(len(components),1/len(components)),size=min(32,10000-offset))
        # Exact integer sum with explicit per-component weights; no evaluator BLAS path.
        totals=(draws[:,:,None,None]*aggregated[None,:,:,:]).sum(axis=1)
        for j,key in enumerate(keys):
            for numerator,denominator in totals[:,j]:
                if denominator:samples[key].append(float(numerator/denominator))
                else:invalid[key]+=1
    for key,values in samples.items():
        result=reported['ratios'][key];require(result['invalid_replicates']==invalid[key],'bootstrap_undefined')
        require(result['degenerate']==(bool(values) and min(values)==max(values)),'bootstrap_degenerate')
        ordered=sorted(values)
        def quantile(q):
            x=(len(ordered)-1)*q;lo=math.floor(x);hi=math.ceil(x)
            return ordered[lo]+(ordered[hi]-ordered[lo])*(x-lo)
        near(result['ci95'],None if invalid[key] else [quantile(.025),quantile(.975)])
    return len(keys)


def verify_part_metrics(rows,plan,reported):
    checks=intervals=0
    for group,report in reported.items():
        chosen=[r for r in rows if group=='all' or group=='isolated_hypothesis' and not r['case']['historically_related']
            or group=='historically_related' and r['case']['historically_related']
            or group=='prefix_complete' and not r['case']['prefix_truncated'] or group=='prefix_truncated' and r['case']['prefix_truncated']
            or group in ('named_editor','no_editor') and r['case']['stratum']==group]
        n=len(chosen);base=sum(r['baseline'] for r in chosen)
        require(report['record_count']==n and report['baseline_correct']==base and report['baseline_errors']==n-base,'slice_denominators')
        for k,value in report['observed_candidate_oracle'].items():
            hit=sum(r['case']['target'] in r['case']['candidates'][:int(k)] for r in chosen)
            require(value['numerator']==hit and value['denominator']==n,'oracle');near(value['wilson_ci95_row_assumption'],wilson(hit,n))
        for name,model in report['models'].items():
            c=counts(chosen,name)
            expected=dict(correction_success=c['rescue'],correction_failure=c['harm']+c['wrong'],baseline_correct_destroyed=c['harm'],
                wrong_to_different_wrong=c['wrong'],effective_changes=c['changed'],gate_applied_count=sum(r['models'][name]['applied'] for r in chosen))
            require(all(model[k]==v for k,v in expected.items()),'point_counts')
            rates=dict(accuracy=(c['correct'],n),harm_rate=(c['harm'],base),overwrite_coverage=(c['changed'],n),
                application_to_error_targets=(c['rescue']+c['wrong'],n-base),correction_precision=(c['rescue'],c['changed']),correction_recall=(c['rescue'],n-base))
            for key,(num,den) in rates.items():
                value=model[key];require((value['numerator'],value['denominator'])==(num,den),'rate_counts')
                near(value['value'],num/den if den else None);near(value['wilson_ci95_row_assumption'],wilson(num,den))
            near(model['baseline_gain'],(c['rescue']-c['harm'])/n)
            if base:
                h=c['harm'];cp=model['harm_clopper_pearson95_row_assumption']
                near(cp['upper_one_sided'],binomial_upper(h,base,.05))
                near(cp['two_sided'],[1-binomial_upper(base-h,base,.025),binomial_upper(h,base,.025)])
            ranks=[r['models'][name]['rank'] for r in chosen]
            near(model['mrr_at_6'],math.fsum(1/r if r else 0 for r in ranks)/n)
            near(model['ndcg_at_6_first_correct_surface'],math.fsum(1/math.log2(r+1) if r else 0 for r in ranks)/n)
            checks+=1
        pvalues={}
        for key,pair in report['paired_comparisons'].items():
            left,right=pair['left'],pair['right'];a=b=0
            for row in chosen:
                l=row['models'][left]['correct'];r=row['baseline'] if right=='baseline' else row['models'][right]['correct']
                a+=l and not r;b+=r and not l
            require(pair['left_only_correct']==a and pair['right_only_correct']==b,'discordant_pairs')
            p=min(1,2*sum(math.comb(a+b,k) for k in range(min(a,b)+1))/2**(a+b))
            pvalues[key]=p;near(pair['mcnemar_exact_two_sided_p'],p);near(pair['accuracy_difference'],(a-b)/n)
        last=0.0
        for i,(key,p) in enumerate(sorted(pvalues.items(),key=lambda item:(item[1],item[0]))):
            last=max(last,min(1,(len(pvalues)-i)*p));near(report['paired_comparisons'][key]['holm_adjusted_p'],last)
        intervals+=independent_intervals(chosen,plan,report['paired_component_intervals'])
    return dict(model_slice_groups=checks,component_intervals=intervals)


def verify_sentences(rows,document,plan,reported):
    lookup={r['case']['stable_id']:r for r in rows};sentences=[]
    for slot in document['slots']:
        if slot['status']!='native_measured':continue
        parts=[lookup[k] for k in slot['input_ids']];components={r['component'] for r in parts}
        require(len(components)==1,'sentence_component')
        sentences.append(dict(component=next(iter(components)),baseline=all(p['baseline'] for p in parts),
            models={name:dict(correct=all(p['models'][name]['correct'] for p in parts),changed=any(p['models'][name]['changed'] for p in parts)) for name in plan['variants']}))
    require(len(sentences)==957 and reported['unknown_sentences']==43,'sentence_denominators')
    for name,m in reported['models'].items():
        c=counts(sentences,name);require(c['base']==reported['baseline_source_matching'],'sentence_baseline')
        expected=dict(source_matching=c['correct'],match_gained=c['rescue'],match_lost=c['harm'],change_failure=c['harm']+c['wrong'],wrong_to_different_wrong=c['wrong'],changed=c['changed'])
        require(all(m[k]==v for k,v in expected.items()),'sentence_counts')
        for key,num,den in [('precision',c['rescue'],c['changed']),('recall',c['rescue'],c['error']),('application_to_mismatched_sources',c['rescue']+c['wrong'],c['error']),('baseline_gain',c['rescue']-c['harm'],c['n']),('match_fraction_among_measured',c['correct'],c['n'])]:near(m[key],num/den if den else None)
        near(m['full1000_identification_bounds'],[c['correct']/1000,(c['correct']+43)/1000])
        near(m['match_fraction_wilson95_row_assumption'],wilson(c['correct'],c['n']))
    return dict(measured_sentences=len(sentences),model_groups=5,component_intervals=independent_intervals(sentences,plan,reported['conditional_component_intervals'],True))


def verify(commit):
    committed(HERE/'verify_models.py',commit)
    save(ROOT/'verification-reservation.json',dict(code_commit=commit,code_sha256=sha(HERE/'verify_models.py'),direct_replay_per_model=1221))
    inference=read(ROOT/'inference-report.json');bound,plan,arrays=bound_inputs(inference['binding_commit'])
    document=read(ROOT/'source-cases.json');input_result=verify_inputs(arrays,document)
    scores,replayed=replay(bound,arrays);rows=outcomes(document['cases'],plan,scores);evaluation=read(ROOT/'evaluation.json')
    require(evaluation['inference_report_sha256']==sha(ROOT/'inference-report.json') and evaluation['source_case_sha256']==sha(ROOT/'source-cases.json') and evaluation['outputs_seal_sha256']==sha(ROOT/'outputs-seal.json'),'evaluation_binding')
    parts=verify_part_metrics(rows,plan,evaluation['parts']);sentences=verify_sentences(rows,document,plan,evaluation['sentences'])
    binding=json.loads(committed(Path('research/issue-33-loss-balance/evaluation-binding-v1.json'),'5fcbb79afcf109391f75e6e880228c259d11f4a4'))
    for model in binding['models']:require(sha(model['path'])==model['sha256'],'old_checkpoint')
    old=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,timeout=120,check=True)
    history=json.loads(old.stdout.strip().splitlines()[-1]);require(history['status']=='passed','old_integrity')
    current=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(current==plan['current_sakura_input_head'] and not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'input_checkout')
    report=dict(status='passed',code_commit=commit,inputs=input_result,direct_cpu_replay=replayed,parts=parts,sentences=sentences,
        old_integrity=history,old_checkpoints_unchanged=len(binding['models']),evaluation_sha256=sha(ROOT/'evaluation.json'),
        inference_sha256=sha(ROOT/'inference-report.json'),sakura_input_head=current,sakura_input_clean=True,
        thresholds_changed=False,new_fits=0,gold_certified=False,final_test_used=False)
    save(ROOT/'verification.json',report);print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);verify(parser.parse_args().commit)
