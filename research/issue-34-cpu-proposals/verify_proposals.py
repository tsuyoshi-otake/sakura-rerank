"""Independent projections, graph/heap folds, CPU replay and scalar recounts."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from proposal_common import CACHE,HERE,LINEAGE,OOF,ROOT,INPUT_NAMES,committed,input_arrays,read,save,sha
from run_cpu import bound


def require(value,code):
    if not value:raise ValueError('proposal_verification_'+code)


def encoded(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()


def checksum(value):return hashlib.sha256(encoded(value)).hexdigest()


def row_hash(arrays,index):
    digest=hashlib.sha256()
    for key in INPUT_NAMES:
        value=np.asarray(arrays[key][index]);digest.update(encoded([key,value.dtype.str,list(value.shape)]));digest.update(value.tobytes(order='C'))
    return digest.hexdigest()


def verify_projections(spec):
    # Reuse the already committed independent DFS+heap implementation, not the producer's DSU/min allocation.
    committed(Path('research/issue-34-oof-design/verify_oof.py'),'7e04d6d3651fc9f3525c2c7ed6a7eca2c22e8e71')
    sys.path.insert(0,'research/issue-34-oof-design')
    try:from verify_oof import graph_components,independently_allocate
    finally:sys.path.pop(0)
    prep=read(ROOT/'preparation.json');manifest=read(CACHE/'manifest.json');identities=read(OOF/'training-identities.json')
    base=read(OOF/'folds.json')['union'];records=identities['rows'];indices=read(CACHE/'cohort-indices.json')
    original=input_arrays(CACHE/'arrays.npz',manifest['artifacts']['arrays.npz'])
    previous='0'*64;origin_ids=[]
    with (CACHE/'row-receipts.jsonl').open('rb') as stream:
        for i,raw in enumerate(stream):
            row=json.loads(raw);origin=row['origin'];require(row['index']==i and row['previous_sha256']==previous,'chain_order')
            previous=checksum({k:v for k,v in row.items() if k!='record_sha256'});require(previous==row['record_sha256'],'chain_hash')
            require(row_hash(original,i)==row['input_tensor_sha256']==records[i]['numeric_input_key'],'original_input')
            require(records[i]['row_key']==hashlib.sha256(('gate-oof-row-v1\n'+origin['group']+'\n'+origin['stable_id']).encode()).hexdigest(),'identity_join')
            origin_ids.append(origin['stable_id'])
    require(len(origin_ids)==75000 and len(set(origin_ids))==75000 and previous==manifest['row_chain_head'] and checksum(origin_ids)==manifest['source_order_sha256'],'chain_population')
    historical=read(LINEAGE/'historical-numeric.json');old={role:{r['numeric'] for r in historical if r['split']==role} for role in ('train','dev')}
    old_union=old['train']|old['dev']
    findings={};elements=0
    for condition in spec['conditions']:
        arrays=input_arrays(ROOT/(condition+'-inputs.npz'),spec['inputs'][condition+'-inputs.npz'],prepared=True)
        for key in INPUT_NAMES:
            expected=np.zeros_like(original[key]) if condition=='empty' and key in ('context_ids','context_lengths') else original[key]
            require(arrays[key].dtype==expected.dtype and np.array_equal(arrays[key],expected),'projection_elements');elements+=arrays[key].size
        hashes=[row_hash(arrays,i) for i in range(75000)];meta=read(ROOT/(condition+'-metadata.json'))
        require(hashes==meta['numeric_hashes'],'all_projected_hashes')
        projected=[dict(r,component_key=base['row_component'][r['row_key']],numeric_input_key=hashes[i]) for i,r in enumerate(records)]
        components=graph_components(projected);union=independently_allocate(projected,components)
        require(union==meta['union'],'union_folds')
        for arm,positions in indices.items():
            require(independently_allocate([projected[i] for i in positions],components)==meta['arms'][arm],'arm_folds')
        matched={role:{components[records[i]['row_key']] for i,value in enumerate(hashes) if value in keys} for role,keys in old.items()}
        require({role:sorted(values) for role,values in matched.items()}==meta['historical_match_components'],'historical_components')
        connected=matched['train']|matched['dev'];observed=prep['conditions'][condition]
        direct={role:sum(value in keys for value in hashes) for role,keys in old.items()}
        count=sum(components[r['row_key']] in connected for r in records)
        require(direct==observed['direct_historical_numeric_matches'] and count==observed['history_connected_rows'] and len(connected)==observed['history_connected_components'],'historical_counts')
        provenance=observed['recorded_provenance']
        require(provenance['lineage_complete'] and provenance['known_models_visited']==22 and not provenance['missing_models']
            and provenance['fit_overlap_components']==len(matched['train']) and provenance['selection_overlap_components']==len(connected)
            and provenance['oof_eligible']==(not connected),'projected_ancestry_counts')
        require(len(set(hashes))==observed['unique_numeric_inputs'],'projected_unique_count')
        findings[condition]=dict(rows=75000,components=len(set(components.values())),fold_populations_verified=3,
            unique_inputs=len(set(hashes)),direct_historical_matches=direct,direct_union_historical_matches=sum(value in old_union for value in hashes),
            history_connected_rows=count,history_unconnected_rows=75000-count,fold_sizes=union['fold_sizes'])
    return dict(input_elements_verified=elements,receipt_rows=75000,conditions=findings)


def replay_cpu(spec):
    import onnxruntime as ort
    os.environ['CUDA_VISIBLE_DEVICES']='';require(ort.__version__=='1.23.2','runtime_version')
    raw=Path(spec['model']['path']).read_bytes();require(hashlib.sha256(raw).hexdigest()==spec['model']['sha256'],'loaded_model')
    records=[];started=time.monotonic()
    for condition in spec['conditions']:
        arrays=input_arrays(ROOT/(condition+'-inputs.npz'),spec['inputs'][condition+'-inputs.npz'],prepared=True)
        with np.load(ROOT/(condition+'-scores.npz'),allow_pickle=False) as archive:saved=archive['scores'];states=archive['states']
        require(saved.shape==(75000,6) and saved.dtype==np.float32 and np.isfinite(saved).all() and np.all(states==1),'complete_saved_scores')
        options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        session=ort.InferenceSession(raw,sess_options=options,providers=['CPUExecutionProvider']);require(session.get_providers()==['CPUExecutionProvider'],'cpu_provider')
        for i in range(75000):
            require(time.monotonic()-started<1800,'cpu_replay_deadline')
            # Construct the eight feed arrays directly, without the inference adapter.
            feed={name:np.ascontiguousarray(arrays[name][i:i+1]) for name in INPUT_NAMES}
            result=session.run(['scores'],feed)[0]
            require(result.shape==(1,6) and result.dtype==np.float32 and np.array_equal(result[0],saved[i]),'full_cpu_bitwise_replay')
            if (i+1)%25000==0:print(json.dumps(dict(stage='cpu_replay',condition=condition,rows=i+1)),flush=True)
        del session;records.append(dict(condition=condition,rows=75000,bitwise_equal=True,provider='CPUExecutionProvider',batch=1,intra_op_threads=1,inter_op_threads=1))
    return dict(conditions=records,elapsed_seconds=round(time.monotonic()-started,3),total_rows=150000)


def scalar_metrics(scores,arrays,indexes,gated):
    c=Counter();ranks=[0]*6;margins=[]
    for i in indexes:
        i=int(i);active=[j for j in range(6) if arrays['candidate_mask'][i,j]]
        winner=max(active,key=lambda j:float(scores[i,j]));margin=np.float32(scores[i,winner]-scores[i,0])
        if gated and not margin>np.float32(1.7):winner=0
        before=bool(arrays['correct_mask'][i,0]);after=bool(arrays['correct_mask'][i,winner]);changed=not bool(arrays['baseline_equivalent'][i,winner])
        c['correct']+=after;c['baseline_correct']+=before;c['rescue']+=not before and after;c['harm']+=before and not after
        c['wrong_to_wrong']+=not before and not after and changed;c['changed']+=changed;ranks[winner]+=1
        alternatives=[j for j in active if not arrays['baseline_equivalent'][i,j]]
        if alternatives:margins.append(np.float32(max(scores[i,j] for j in alternatives)-scores[i,0]))
    n=len(indexes);errors=n-c['baseline_correct']
    def rate(a,b):return None if b==0 else a/b
    return dict(rows=n,**{k:c[k] for k in ('correct','baseline_correct','rescue','harm','wrong_to_wrong','changed')},failed_inference=0,
        correction_failure=c['harm']+c['wrong_to_wrong'],source_correct_rate=rate(c['correct'],n),precision=rate(c['rescue'],c['changed']),
        recall=rate(c['rescue'],errors),coverage=rate(c['changed'],n),harm_rate=rate(c['harm'],c['baseline_correct']),
        error_application=rate(c['rescue']+c['wrong_to_wrong'],errors),winner_rank_counts=ranks,proposed_change_margin_rows=len(margins),
        proposed_change_margin_quantiles=None if not margins else np.quantile(np.asarray(margins,np.float32),[.1,.5,.9]).tolist())


def scalar_ceiling(hashes,correct,indexes,expected):
    counts=defaultdict(lambda:[0]*6);sizes=Counter();patterns=defaultdict(set)
    for i in indexes:
        key=hashes[i];sizes[key]+=1;patterns[key].add(tuple(bool(v) for v in correct[i]))
        for j in range(6):counts[key][j]+=int(correct[i,j])
    loss={key:sizes[key]-max(values) for key,values in counts.items()};n=len(indexes)
    observed=dict(rows=n,unique_inputs=len(sizes),duplicate_groups=sum(v>1 for v in sizes.values()),duplicate_excess=n-len(sizes),
        label_variation_groups=sum(len(v)>1 for v in patterns.values()),incompatible_label_groups=sum(v>0 for v in loss.values()),
        rows_in_incompatible_groups=sum(sizes[key] for key,value in loss.items() if value),unavoidable_source_mismatches=sum(loss.values()),
        maximum_source_matches=n-sum(loss.values()),empirical_source_match_ceiling=None if not n else (n-sum(loss.values()))/n)
    require(all(expected[key]==value for key,value in observed.items()),'scalar_ceiling')


def verify_analysis(spec):
    report=read(ROOT/'analysis.json');inference=read(ROOT/'inference.json');indices=read(CACHE/'cohort-indices.json');records=read(OOF/'training-identities.json')['rows']
    with np.load(CACHE/'arrays.npz',allow_pickle=False) as archive:arrays={key:archive[key] for key in ('candidate_mask','correct_mask','baseline_equivalent')}
    population_checks=ceiling_checks=0
    a,b=set(indices['dictionary']),set(indices['annotation'])
    for condition in spec['conditions']:
        meta=read(ROOT/(condition+'-metadata.json'));groups=dict(union=list(range(75000)),common_wikipedia=sorted(a&b),dictionary_aozora=sorted(a-b),annotation_aozora=sorted(b-a))
        for arm,positions in indices.items():
            groups[arm]=positions
            for fold in range(5):groups[arm+'/fold-'+str(fold)]=[i for i in positions if meta['arms'][arm]['row_fold'][records[i]['row_key']]==fold]
        with np.load(ROOT/(condition+'-scores.npz'),allow_pickle=False) as archive:scores=archive['scores']
        for label,gated in (('ungated',False),('published_L_gt_1p7',True)):
            require(set(groups)==set(report['results'][condition]['metrics'][label]),'metric_population_names')
            for name,positions in groups.items():
                require(scalar_metrics(scores,arrays,positions,gated)==report['results'][condition]['metrics'][label][name],'scalar_outcomes');population_checks+=1
        for name,positions in groups.items():
            scalar_ceiling(meta['numeric_hashes'],arrays['correct_mask'],positions,report['results'][condition]['input_label_limits'][name]);ceiling_checks+=1
        with np.load(ROOT/(condition+'-timings.npz'),allow_pickle=False) as archive:times=archive['milliseconds']
        measured=next(r for r in inference['conditions'] if r['condition']==condition)
        require(len(times)==10000 and np.isfinite(times).all() and np.all(times>0),'timing_denominator')
        require({key:float(np.quantile(times,q)) for key,q in (('p50',.5),('p95',.95),('p99',.99))}==measured['latency_ms'],'timing_quantiles')
    return dict(metric_populations=population_checks,ceiling_populations=ceiling_checks,timing_samples=20000)


def verify(commit):
    committed(HERE/'verify_proposals.py',commit);save(ROOT/'verification-reservation.json',dict(code_commit=commit))
    inference=read(ROOT/'inference.json');spec=bound(inference['binding_commit']);seal=read(ROOT/'outputs-seal.json')
    require(inference['status']=='complete' and seal['inference_sha256']==sha(ROOT/'inference.json'),'sealed_outputs')
    for row in inference['conditions']:
        require(sha(ROOT/(row['condition']+'-scores.npz'))==row['scores_sha256'] and sha(ROOT/(row['condition']+'-timings.npz'))==row['timings_sha256'],'inference_artifacts')
    projection=verify_projections(spec);replay=replay_cpu(spec);metrics=verify_analysis(spec)
    old=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(old.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','old_integrity')
    checkpoints=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in checkpoints:require(sha(model['path'])==model['sha256'],'old_checkpoint')
    result=dict(status='passed',code_commit=commit,projections=projection,replay=replay,metrics=metrics,original_integrity=integrity,
        old_checkpoints_unchanged=len(checkpoints),preparation_sha256=sha(ROOT/'preparation.json'),inference_sha256=sha(ROOT/'inference.json'),
        analysis_sha256=sha(ROOT/'analysis.json'),new_fits=0,threshold_selection=False,calibration=False,final_test=False)
    save(ROOT/'verification.json',result);print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);verify(parser.parse_args().commit)
