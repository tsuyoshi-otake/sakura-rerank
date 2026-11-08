"""Replay original sources and sealed native bytes without another native call."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import sys
import time
import unittest

import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS
from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash,text_sha256
from sakura_rerank.data.source_reading_rebuild import POLICY
from sakura_rerank.source_model_inputs import encode_snapshot
from native_rebuild import bound_inputs,helpers
from prepare_rebuild import parents
from rebuild_common import CPU,HISTORICAL,ROOT,previous,read,require,save,sha
from rebuild_metrics import summary


def independent_child(row,source,paragraph,decision):
    spans=[s for s in paragraph['spans'] if s['start']<source['end'] and source['start']<s['end']]
    require(len(spans)==1 and (spans[0]['start'],spans[0]['end'])==(source['start'],source['end']),'replay_exact_span')
    original=spans[0]['reading'];table=str.maketrans({chr(i):chr(i-96) for i in range(0x30a1,0x30f7)})
    reading=original.translate(table)
    require(reading!=row['reading'] and paragraph['text'][source['start']:source['end']]==row['target'],'replay_contradiction')
    base=dict(kind='source_annotation_rebuild_weak_supervision',version=1,policy_sha256=canonical_json_hash(POLICY),
        parent_input_sha256=canonical_json_hash(row),parent_source_sha256=canonical_json_hash(source),
        parent_original_row_sha256=source['original_row_sha256'],parent_decision_sha256=canonical_json_hash(decision),
        parent_component_sha256=canonical_json_hash(row['component_id']),original_annotation_reading_sha256=text_sha256(original),
        parent_reading_sha256=text_sha256(row['reading']),rebuilt_reading_sha256=text_sha256(reading),
        original_annotation_characters=len(original),rebuilt_reading_characters=len(reading),
        training_eligible=False,independent_gold_eligible=False,independent_evaluation_eligible=False)
    child=None;child_source=None
    if 2<=len(reading)<=32:
        child={**row,'stable_id':'reading-rebuild-'+canonical_json_hash(base),'reading':reading,
            'candidate_request_id':'growth-reading-'+canonical_json_hash(reading)}
        lineage={**base,'status':'rebuilt_source_ready','rebuilt_input_sha256':canonical_json_hash(child)}
        child_source={**source,'origin_kind':'original_ruby','original_row_sha256':canonical_json_hash(lineage)}
    else:lineage={**base,'status':'pending_rebuilt_reading_bounds','rebuilt_input_sha256':None}
    return dict(status=lineage['status'],lineage=lineage,lineage_sha256=canonical_json_hash(lineage),input=child,source=child_source)


def independent_numeric(arrays):
    digest=hashlib.sha256()
    for name in MODEL_FIELDS:
        value=np.array(arrays[name][0])
        digest.update(json.dumps([name,value.dtype.str,list(value.shape)],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def verify(commit):
    started=time.monotonic();plan,preparation,repairs,requests,guard,identity=bound_inputs(commit)
    cohort,origins,indices,decisions=parents();registry=read(previous.previous.REGISTRY)
    selection={r['work_id']:r for r in read(previous.previous.GROWTH/'aozora-selection.json')}
    replay={}
    for row,source,paragraph in previous.source_records([cohort[i] for i in indices],[origins[i] for i in indices],registry,selection):
        key=source['original_row_sha256'];require(key not in replay,'replay_duplicate')
        replay[key]=independent_child(row,source,paragraph,decisions[key])
    require(repairs==[replay[key] for key in sorted(replay)] and len(replay)==335,'all_source_lineages')
    raw=defaultdict(list);exact=defaultdict(list)
    for i,original in enumerate(cohort):
        value=original['encoder_input'];raw[(value['left_context'],value['reading'])].append(i)
        exact[(value['left_context'],value['reading'],value['target'])].append(i)
    overlaps=[]
    for repair in repairs:
        if repair['input'] is None:continue
        row=repair['input'];matches=raw.get((row['left_context'],row['reading']),[])
        overlaps.append(dict(child_input_sha256=canonical_json_hash(row),current_input_rows=matches,
            current_same_target_rows=exact.get((row['left_context'],row['reading'],row['target']),[]),
            matching_parent_components=sorted({cohort[i]['encoder_input']['component_id'] for i in matches})))
    require(overlaps==read(ROOT/'raw-overlap.json')['rows'],'raw_overlap_replay')
    execution=read(ROOT/'native-execution.json');native_report=read(ROOT/'native-report.json')
    require(native_report['execution_sha256']==sha(ROOT/'native-execution.json') and native_report['measurements_sha256']==sha(ROOT/'measurements.json'),'native_result_binding')
    attempts=execution['attempts'];require([r['index'] for r in attempts]==list(range(len(requests))) and execution['not_attempted']==0 and execution['stop_reason'] is None,'one_complete_request_attempt')
    _,validator,checked_result=helpers();snapshots={};states={};output_bytes=0
    for attempt in attempts:
        index=attempt['index'];request=requests[index];directory=ROOT/'candidates'/f'request-{index:04d}'
        receipt=read(directory/'execution.json');terminal=attempt['terminal']
        require(terminal['index']==receipt['index']==index and receipt['stable_id']==request['stable_id']
            and terminal['status']==receipt['status'] and (directory/'identity.json').read_bytes()==canonical_json_bytes(identity)+b'\n','native_identity_receipt')
        outcome,snapshot=checked_result(directory,request,terminal,identity,validator)
        require(outcome==attempt['outcome'],'native_terminal_replay')
        states[request['stable_id']]=outcome['status']
        if snapshot is not None:snapshots[request['stable_id']]=snapshot
        if (directory/'output.jsonl').exists():output_bytes+=(directory/'output.jsonl').stat().st_size
    require(output_bytes==execution['accepted_output_bytes']<=plan['native']['maximum_output_bytes'],'native_output_bytes')
    with (previous.previous.CACHE/'row-receipts.jsonl').open('rb') as stream:ledger=[json.loads(line) for line in stream]
    require(len(ledger)==75000,'old_cache_rows')
    number_maps={}
    for condition in ('source','empty'):
        groups=defaultdict(list)
        for i,digest in enumerate(read(CPU/(condition+'-metadata.json'))['numeric_hashes']):groups[digest].append(i)
        number_maps[condition]=groups
    history=defaultdict(list)
    for item in read(HISTORICAL):history[item['numeric']].append(item)
    rows=read(ROOT/'measurements.json')['rows'];require(len(rows)==335,'all_measured_parent_slots');presence=Counter({str(k):0 for k in (1,5,6,10,32)})
    for repair,observed in zip(repairs,rows,strict=True):
        row=repair['input'];require(observed['lineage_sha256']==repair['lineage_sha256'] and observed['parent_original_row_sha256']==repair['lineage']['parent_original_row_sha256']
            and observed['child_input_sha256']==repair['lineage']['rebuilt_input_sha256'],'measured_lineage')
        if row is None:
            require(observed['status']==repair['status'] and observed['candidate'] is None and observed['numeric']=={},'pending_no_snapshot');continue
        key=row['candidate_request_id'];snapshot=snapshots.get(key)
        require(observed['status']==states[key] and observed['candidate']==candidate_evidence(row['target'],snapshot),'candidate_contract_replay')
        if snapshot is None:
            require(observed['numeric']=={},'unmeasured_no_numeric');continue
        candidates=snapshot['candidate_snapshots']['training_top32']['candidates']
        for k in (1,5,6,10,32):
            present=any(c['surface']==row['target'] for c in candidates[:k]);presence[str(k)]+=present
            require(observed['candidate']['presence'][str(k)]==present,'literal_candidate_presence')
        arrays,profile=encode_snapshot(snapshot);require(observed['encoding_profile']==profile,'encoding_profile')
        for condition in ('empty','source'):
            if condition=='source':
                text=row['left_context'][:64];arrays['context_ids'][0]=[1+(ord(c)*2654435761)%13311 for c in text]+[0]*(64-len(text))
                arrays['context_lengths'][0]=len(text)
            digest=independent_numeric(arrays);matches=number_maps[condition].get(digest,[])
            expected=dict(input_sha256=digest,current_cache_rows=matches,
                matching_parent_components=sorted({ledger[i]['origin']['component_id'] for i in matches}),historical_matches=history.get(digest,[]))
            require(observed['numeric'][condition]==expected,'numeric_and_direct_exposure')
    require(dict(presence)==native_report['census']['source_presence'] and summary(rows)==native_report['census'],'complete_census')
    require(dict(Counter(states.values()))==execution['request_outcomes']==native_report['request_outcomes'],'native_request_census')
    require(guard.blocked==0,'forbidden_read')
    proof=dict(status='passed',binding_commit=commit,preparation_sha256=sha(ROOT/'preparation.json'),native_report_sha256=sha(ROOT/'native-report.json'),
        source_lineages_verified=335,strict_child_rows_verified=preparation['rebuilt_rows'],native_receipts_verified=len(attempts),
        snapshots_revalidated=len(snapshots),numeric_input_rows_verified=sum(r['status']=='complete' for r in rows),
        numeric_conditions=2,raw_duplicate_entries_verified=len(overlaps),forbidden_data_reads=guard.blocked,
        source_presence_independent_recount=dict(presence),elapsed_seconds=round(time.monotonic()-started,3),
        native_retries=0,original_labels_changed=0,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'verification.json',proof);return proof


def tests():
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    value=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-tests.json',value);require(result.wasSuccessful() and not result.skipped,'full_tests_failed');return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('verify','tests'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=tests() if args.stage=='tests' else verify(args.commit)
    except Exception as error:
        info=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('reading_rebuild_'):info['error_code']=str(error)
        print(json.dumps(info),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
