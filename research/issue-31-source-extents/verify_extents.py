"""Independent source extent, numeric and paired-census replay; no native retry."""
import argparse
from collections import Counter,defaultdict
import json
import re
import sys
import time
import unicodedata
import unittest

import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,tensor_hash
from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_hash,text_sha256
from sakura_rerank.data.source_reading_units import POLICY,VIEWS
from sakura_rerank.source_model_inputs import encode_snapshot
from extent_common import ROOT,PRIOR,reading,repair,parents,helpers,read,require,save,sha
from extent_metrics import aggregate
from native_extents import bound_inputs
from prepare_extents import flatten


def replay_source(row,source,paragraph,decision,parent_deriver):
    parent=parent_deriver(row,source,paragraph,decision);parent_sha=canonical_json_hash(parent)
    text=paragraph['text'];covered=bytearray(len(text));atoms=[]
    projection=str.maketrans({chr(n):chr(n-96) for n in range(0x30a1,0x30f7)})
    for span in paragraph['spans']:
        a,b=span['start'],span['end'];covered[a:b]=b'\1'*(b-a)
        valid=(b>a and span['kind']!='unresolved_base' and re.fullmatch('[ぁ-ゖァ-ヶー]{1,32}',span['reading'])
            and span['reading'] not in ('ママ','まま'))
        atoms.append(dict(start=a,end=b,reading=span['reading'].translate(projection) if valid else None,
            origin='original_ruby' if valid else 'unresolved_annotation'))
    for i,c in enumerate(text):
        if covered[i]:continue
        phonetic=re.fullmatch('[ぁ-ゖァ-ヶー]',c) is not None
        origin='literal_kana' if phonetic else 'literal_boundary' if unicodedata.category(c)[0] in 'PSZ' or c.isspace() else 'unannotated_reading'
        atoms.append(dict(start=i,end=i+1,reading=c.translate(projection) if phonetic else None,origin=origin))
    atoms.sort(key=lambda a:(a['start'],a['end']))
    anchors=[i for i,a in enumerate(atoms) if (a['start'],a['end'],a['origin'])==(source['start'],source['end'],'original_ruby')]
    require(len(anchors)==1,'replay_anchor');anchor=anchors[0];blocks=[];block=[]
    for i,atom in enumerate(atoms):
        if atom['reading'] is None:
            if block:blocks.append(block);block=[]
        else:block.append(i)
    if block:blocks.append(block)
    full=next(block for block in blocks if anchor in block)
    suffix=[anchor]
    for i in range(anchor+1,len(atoms)):
        if atoms[i]['origin']!='literal_kana':break
        suffix.append(i)
    indices=dict(original_ruby=[anchor],literal_suffix=suffix,supported_run=full);views={}
    for name,selected in indices.items():
        parts=[atoms[i] for i in selected];a,b=parts[0]['start'],parts[-1]['end']
        observed=''.join(p['reading'] for p in parts);target=text[a:b];prefix=text[max(0,a-64):a]
        changed=(a,b)!=(source['start'],source['end']);reasons=[]
        if len(observed)==0 or len(observed)>128:reasons.append('native_reading_bound')
        if len(target)==0 or len(target)>256:reasons.append('native_surface_bound')
        if changed and paragraph['flags']['orphan_marker']:reasons.append('annotation_parse_uncertainty')
        status='pending_source_extent' if reasons else 'source_extent_diagnostic_ready'
        limits=dict(reading=2<=len(observed)<=32,target=1<=len(target)<=32,prefix=8<=len(prefix)<=64)
        lineage=dict(kind='original_source_extent_hypothesis',version=1,view=name,policy_sha256=canonical_json_hash(POLICY),
            parent_original_row_sha256=source['original_row_sha256'],parent_rebuild_sha256=parent_sha,
            parent_input_sha256=canonical_json_hash(row),parent_source_sha256=canonical_json_hash(source),parent_component_sha256=canonical_json_hash(row['component_id']),
            source_evidence_sha256=canonical_json_hash([source,paragraph]),start=a,end=b,reading_sha256=text_sha256(observed),target_sha256=text_sha256(target),
            prefix_sha256=text_sha256(prefix),parts_sha256=canonical_json_hash(parts),status=status,pending_reasons=reasons,
            training_eligible=False,independent_gold_eligible=False,independent_evaluation_eligible=False)
        child=None
        if not reasons:
            child=dict(stable_id='source-extent-'+canonical_json_hash(lineage),component_id=row['component_id'],corpus=row['corpus'],
                left_context=prefix,reading=observed,target=target,candidate_request_id='growth-reading-'+canonical_json_hash(observed))
        lineage['candidate_input_sha256']=canonical_json_hash(child) if child is not None else None
        low,high=selected[0],selected[-1]+1
        views[name]=dict(status=status,lineage=lineage,lineage_sha256=canonical_json_hash(lineage),input=child,
            hypothesis=dict(start=a,end=b,reading=observed,target=target,left_context=prefix,parts=parts),expanded=changed,
            added_left_characters=source['start']-a,added_right_characters=b-source['end'],
            left_stop='source_start' if low==0 else atoms[low-1]['origin'],right_stop='source_end' if high==len(atoms) else atoms[high]['origin'],
            preparation_bounds=limits,within_preparation_bounds=all(limits.values()),grammatical_boundary_verified=False,ime_gold=False)
    return dict(parent_original_row_sha256=source['original_row_sha256'],parent_rebuild_sha256=parent_sha,views=views)


def verify(commit):
    started=time.monotonic();plan,source,request_set,guard,identity,snapshots=bound_inputs(commit)
    cohort,origins,indices,decisions=parents();registry=read(reading.previous.REGISTRY)
    selection={r['work_id']:r for r in read(reading.previous.GROWTH/'aozora-selection.json')};replayed={}
    parent_deriver=repair.load_script('extent_parent_verifier','research/issue-31-reading-rebuild/verify_rebuild.py').independent_child
    for row,origin,paragraph in reading.source_records([cohort[i] for i in indices],[origins[i] for i in indices],registry,selection):
        key=origin['original_row_sha256'];require(key not in replayed,'replay_duplicate')
        replayed[key]=replay_source(row,origin,paragraph,decisions[key],parent_deriver)
    require(source==[replayed[k] for k in sorted(replayed)] and len(replayed)==335,'source_extent_replay')
    raw,labels=defaultdict(list),defaultdict(list)
    for i,value in enumerate(cohort):
        row=value['encoder_input'];raw[(row['left_context'],row['reading'])].append(i)
        labels[(row['left_context'],row['reading'],row['target'])].append(i)
    overlap=[]
    for parent,name,view in flatten(source):
        row=view['input']
        if row is None:continue
        match=raw.get((row['left_context'],row['reading']),[])
        overlap.append(dict(parent_original_row_sha256=parent,view=name,input_sha256=canonical_json_hash(row),current_input_rows=match,
            current_same_target_rows=labels.get((row['left_context'],row['reading'],row['target']),[]),
            matching_parent_components=sorted({cohort[i]['encoder_input']['component_id'] for i in match})))
    require(overlap==read(ROOT/'raw-overlap.json')['rows'],'raw_overlap_replay')
    execution=read(ROOT/'native-execution.json');report=read(ROOT/'native-report.json');requests=request_set['new_requests']
    require(report['execution_sha256']==sha(ROOT/'native-execution.json') and report['measurements_sha256']==sha(ROOT/'measurements.json')
        and execution['not_attempted']==0 and execution['stop_reason'] is None,'native_results')
    require([r['index'] for r in execution['attempts']]==list(range(len(requests))),'complete_new_request_indices')
    states={k:'complete' for k in request_set['reused_request_ids']};_,validator,check=helpers();output_bytes=0
    for attempt in execution['attempts']:
        index=attempt['index'];directory=ROOT/'candidates'/f'request-{index:04d}';request=requests[index];receipt=read(directory/'execution.json')
        require(receipt['index']==attempt['terminal']['index']==index and receipt['stable_id']==request['stable_id']
            and receipt['status']==attempt['terminal']['status'] and read(directory/'identity.json')==identity,'native_receipt_identity')
        outcome,snapshot=check(directory,request,attempt['terminal'],identity,validator);require(outcome==attempt['outcome'],'native_terminal_replay')
        states[request['stable_id']]=outcome['status']
        if snapshot is not None:snapshots[request['stable_id']]=snapshot
        if (directory/'output.jsonl').exists():output_bytes+=(directory/'output.jsonl').stat().st_size
    require(output_bytes==execution['accepted_output_bytes']<=plan['native']['maximum_output_bytes'],'native_byte_bound')
    with (reading.previous.CACHE/'row-receipts.jsonl').open('rb') as stream:ledger=[json.loads(line) for line in stream]
    number_maps={}
    for condition in ('source','empty'):
        groups=defaultdict(list)
        for i,key in enumerate(read(repair.CPU/(condition+'-metadata.json'))['numeric_hashes']):groups[key].append(i)
        number_maps[condition]=groups
    history=defaultdict(list)
    for item in read(repair.HISTORICAL):history[item['numeric']].append(item)
    rows=read(ROOT/'measurements.json')['rows'];require(len(rows)==1005,'measured_slots')
    observed_presence={};measured=0;top={name:Counter({str(k):0 for k in (1,5,6,10,32)}) for name in VIEWS}
    for record,(parent,name,view) in zip(rows,flatten(source),strict=True):
        row=view['input'];require(record['parent_original_row_sha256']==parent and record['view']==name and record['lineage_sha256']==view['lineage_sha256']
            and record['child_input_sha256']==view['lineage']['candidate_input_sha256'] and record['expanded']==view['expanded']
            and record['within_preparation_bounds']==view['within_preparation_bounds'],'measurement_identity')
        snapshot=snapshots.get(row['candidate_request_id']) if row is not None else None
        expected_status=states[row['candidate_request_id']] if row is not None else view['status']
        require(record['status']==expected_status,'measured_terminal')
        require(record['candidate']==(candidate_evidence(row['target'],snapshot) if row is not None else None),'candidate_contract')
        if snapshot is None:
            require(record['numeric']=={},'unmeasured_no_numeric');observed_presence[(parent,name)]=None;continue
        measured+=1;candidates=snapshot['candidate_snapshots']['training_top32']['candidates'];presence={}
        for k in (1,5,6,10,32):
            present=row['target'] in [c['surface'] for c in candidates[:k]];presence[str(k)]=present;top[name][str(k)]+=present
        require(presence==record['candidate']['presence'],'literal_presence_recount');observed_presence[(parent,name)]=presence
        arrays,profile=encode_snapshot(snapshot);require(record['encoding_profile']==profile,'profile_replay')
        for condition in ('empty','source'):
            if condition=='source':
                prefix=row['left_context'][:64];arrays['context_ids'][0]=np.array([1+(ord(c)*2654435761)%13311 for c in prefix]+[0]*(64-len(prefix)),dtype=np.int64)
                arrays['context_lengths'][0]=len(prefix)
            digest=tensor_hash(arrays,0,MODEL_FIELDS);match=number_maps[condition].get(digest,[])
            require(record['numeric'][condition]==dict(input_sha256=digest,current_cache_rows=match,
                matching_parent_components=sorted({ledger[i]['origin']['component_id'] for i in match}),historical_matches=history.get(digest,[])),'numeric_exposure_replay')
    require(aggregate(rows)==report['census'],'aggregate_replay')
    for name in VIEWS:require(dict(top[name])==report['census']['views'][name]['source_presence'],'independent_topk')
    old=read(PRIOR/'measurements.json')['rows'];all_parents={r['parent_original_row_sha256'] for r in old}
    missing={r['parent_original_row_sha256'] for r in old if r['status']=='complete' and not r['candidate']['presence']['32']}
    categories={(True,True):'both_present',(True,False):'original_only',(False,True):'extent_only',(False,False):'neither_present',
        (None,None):'both_unmeasured',(None,True):'original_unmeasured',(None,False):'original_unmeasured',(True,None):'extent_unmeasured',(False,None):'extent_unmeasured'}
    for scope,selected in (('all335',all_parents),('old305_top32_missing',missing)):
        for name in VIEWS[1:]:
            for k in ('1','5','6','10','32'):
                count=Counter({key:0 for key in set(categories.values())})
                for parent in selected:
                    a,b=observed_presence[(parent,'original_ruby')],observed_presence[(parent,name)]
                    count[categories[(a[k] if a is not None else None,b[k] if b is not None else None)]]+=1
                require(dict(count)==report['census']['paired_source_presence'][scope][name][k]['counts'],'independent_pair_recount')
    require(Counter(states.values())==report['all_request_outcomes'] and guard.blocked==0,'request_census_or_forbidden_read')
    proof=dict(status='passed',binding_commit=commit,preparation_sha256=sha(ROOT/'preparation.json'),native_report_sha256=sha(ROOT/'native-report.json'),
        original_parents_verified=335,source_views_independently_verified=1005,raw_overlap_records_verified=len(overlap),prior_native_receipts_verified=264,
        new_native_receipts_verified=len(requests),numeric_rows_verified=measured,numeric_conditions=2,paired_censuses_independently_verified=20,
        source_presence_independent_recount={name:dict(top[name]) for name in VIEWS},elapsed_seconds=round(time.monotonic()-started,3),
        forbidden_data_reads=guard.blocked,native_retries=0,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'verification.json',proof);return proof


def tests():
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    value=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-tests.json',value);require(result.wasSuccessful() and not result.skipped,'full_tests_failed');return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('verify','tests'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=tests() if args.stage=='tests' else verify(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('source_extent_'):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
