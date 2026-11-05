"""Build and independently verify the two fixed weak-reconstruction cohorts."""
from collections import Counter,defaultdict
import hashlib
import io
import json
import os
import re
import sys
import time

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,LABEL_FIELDS,chain_entry,schema,validate_arrays,verify_chain
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.corpus_v5 import _publish_directory_atomically
from sakura_rerank.data.growth_numeric import encode
from comparison_common import ROOT,HERE,PLAN,authenticate,implementation,rows,read,save,sha
from prepare_cohorts import SCOPE_ROOT,SCOPE_PLAN

sys.path.insert(0,'research/issue-33-consumed-numeric')
try:
    import verify_cache as separate_encoder
finally:
    sys.path.pop(0)

RUN_ROOT=ROOT/'numeric-r2'
OUTPUT=RUN_ROOT/'cache'
CODE=(HERE/'prepare_numeric.py',HERE/'comparison_common.py',HERE/'reserve_plan.py',
      'src/sakura_rerank/data/corpus_v5.py')


def projection(snapshot):
    candidates=[dict(surface=c['surface'],local_cost=c['local_cost'],source_category=c['source_category'],
        segments=[dict(source_category=s['source_category']) for s in c['segments']])
        for c in snapshot['candidate_snapshots']['training_top32']['candidates']]
    return dict(candidate_snapshots=dict(training_top32=dict(candidates=candidates),production_top6=dict(candidates=candidates[:6])))


def duplicates(indices,input_hashes,label_hashes,components):
    counts=Counter(input_hashes[i] for i in indices);labels=defaultdict(set);groups=defaultdict(set)
    for i in indices:
        labels[input_hashes[i]].add(label_hashes[i]);groups[input_hashes[i]].add(components[i])
    return dict(unique_inputs=len(counts),duplicate_groups=sum(v>1 for v in counts.values()),
        duplicate_rows=sum(v for v in counts.values() if v>1),surplus_rows=sum(v-1 for v in counts.values()),
        conflicting_label_groups=sum(len(v)>1 for v in labels.values()),cross_component_groups=sum(len(v)>1 for v in groups.values()))


def profile(indices,records,snapshots):
    readings=defaultdict(Counter);by_corpus=Counter();lengths=Counter();top1=0
    for i in indices:
        row=records[i]['encoder_input'];readings[row['reading']][row['target']]+=1;by_corpus[row['corpus']]+=1
        lengths[str(len(row['reading']))]+=1
        top1+=snapshots[row['candidate_request_id']]['candidate_snapshots']['production_top6']['candidates'][0]['surface']==row['target']
    return dict(rows=len(indices),source_counts=dict(by_corpus),readings=len(readings),reading_length_counts=dict(lengths),
        multi_form_readings=sum(len(v)>1 for v in readings.values()),multi_form_rows=sum(sum(v.values()) for v in readings.values() if len(v)>1),
        source_top1_rows=top1,in_sample_reading_majority_matches=sum(max(v.values()) for v in readings.values()),
        interpretation='Training-source descriptive statistics only, never model accuracy or unique IME correctness.')


def run():
    import numpy as np
    started=time.monotonic();authenticate();head,code=implementation(CODE)
    cohort=read(SCOPE_ROOT/'report.json');execution=read(SCOPE_ROOT/'execution.json')
    if (execution['status']!='complete' or execution['report_sha256']!=sha(SCOPE_ROOT/'report.json')
            or cohort['status']!='ready_for_numeric_verification' or not cohort['reverse_replay_passed'] or not cohort['legacy_graph_byte_parity']
            or cohort['plan_sha256']!=sha(PLAN) or cohort['scope_plan_sha256']!=sha(SCOPE_PLAN)
            or cohort['source_verification_sha256']!=sha(ROOT/'source-verification.json')):
        raise ValueError('comparison_numeric_cohort_not_verified')
    for path,digest in cohort['implementation'].items():
        if sha(path)!=digest: raise ValueError('comparison_numeric_cohort_code_changed')
    for artifact in cohort['artifacts'].values():
        if sha(SCOPE_ROOT/'cohorts'/artifact['path'])!=artifact['sha256']:
            raise ValueError('comparison_numeric_cohort_artifact_changed')
    if sha(SCOPE_ROOT/'cohorts/identities.json')!=cohort['identities_sha256']:
        raise ValueError('comparison_numeric_selection_changed')
    if sha('research/issue-33-consumed-numeric/verify_cache.py')!=read('reports/issue-33-consumed-numeric-verification-v1.json')['script_sha256']:
        raise ValueError('comparison_numeric_reference_encoder_changed')
    records=list(rows(SCOPE_ROOT/'cohorts/rows.jsonl.gz'))
    snapshots={r['stable_id']:r for r in rows(SCOPE_ROOT/'cohorts/snapshots.jsonl.gz')}
    identities=read(SCOPE_ROOT/'cohorts/identities.json')
    position={r['encoder_input']['stable_id']:i for i,r in enumerate(records)}
    if len(records)!=75000 or len(position)!=len(records) or set(identities)!={'dictionary','annotation'}:
        raise ValueError('comparison_numeric_population')
    indices={name:[position[key] for key in keys] for name,keys in identities.items()}
    if (any(len(v)!=50000 or len(set(v))!=50000 for v in indices.values())
            or identities['dictionary'][:25000]!=identities['annotation'][:25000]):
        raise ValueError('comparison_numeric_arm_contract')
    expected_fields={'stable_id','component_id','corpus','left_context','reading','target','candidate_request_id'}
    for item in records:
        row=item['encoder_input'];origin=item['origin']
        if (set(row)!=expected_fields or origin['training_eligible'] is not False or origin['independent_gold_eligible'] is not False
                or origin['ime_quality']!='unresolved' or origin['label_task']!='original_source_reconstruction'):
            raise ValueError('comparison_numeric_projection_contract')
    projected={key:projection(value) for key,value in snapshots.items()}
    snapshot_hashes={key:canonical_json_hash(value) for key,value in snapshots.items()}
    policy_hash=sha(HERE/'policy-v1.md')
    arrays,_=encode([r['encoder_input'] for r in records],projected);validate_arrays(arrays,len(records))
    output=RUN_ROOT/'cache.partial';output.mkdir(exist_ok=False)
    with (output/'arrays.npz').open('xb') as stream:
        np.savez_compressed(stream,**arrays);stream.flush();os.fsync(stream.fileno())
    previous='0'*64;input_hashes=[];label_hashes=[];components=[];seals=[]
    with (output/'row-receipts.jsonl').open('xb') as stream:
        for i,item in enumerate(records):
            row=item['encoder_input'];request=row['candidate_request_id']
            seal=dict(item['origin'],stable_id=row['stable_id'],component_id=row['component_id'],
                policy_sha256=policy_hash,cohort_record_sha256=canonical_json_hash(item),
                snapshot_sha256=snapshot_hashes[request],projection_sha256=canonical_json_hash([row,projected[request]]))
            entry=chain_entry(i,previous,seal,arrays);previous=entry['record_sha256'];seals.append(seal)
            input_hashes.append(entry['input_tensor_sha256']);label_hashes.append(entry['label_tensor_sha256']);components.append(row['component_id'])
            stream.write(canonical_json_bytes(entry)+b'\n')
        stream.flush();os.fsync(stream.fileno())
    save(output/'cohort-indices.json',indices)
    audit={name:duplicates(value,input_hashes,label_hashes,components) for name,value in indices.items()}
    union_audit=duplicates(range(len(records)),input_hashes,label_hashes,components)
    profiles={name:profile(value,records,snapshots) for name,value in indices.items()}
    if any(v['source_counts']!={'jawiki':25000,'aozora':25000} for v in profiles.values()):
        raise ValueError('comparison_numeric_source_quotas')
    manifest=dict(kind='paired_weak_reconstruction_numeric_cache',status='prepared_unverified',rows=len(records),array_schema=schema(len(records)),
        plan_sha256=sha(PLAN),scope_plan_sha256=sha(SCOPE_PLAN),policy_sha256=policy_hash,cohort_report_sha256=sha(SCOPE_ROOT/'report.json'),
        source_order_sha256=canonical_json_hash([r['encoder_input']['stable_id'] for r in records]),
        artifacts={name:sha(output/name) for name in ('arrays.npz','row-receipts.jsonl','cohort-indices.json')},
        row_chain_head=previous,input_duplicates_per_arm=audit,union_input_duplicates=union_audit,profiles=profiles,raw_array_bytes=sum(a.nbytes for a in arrays.values()),
        compressed_array_bytes=(output/'arrays.npz').stat().st_size,independent_gold_eligible=False,training_eligible=False,
        consumer='numeric_verification_only_until_separate_committed_fit_binding',execution_commit=head,implementation=code)
    save(output/'manifest.json',manifest)
    array_count=len(arrays);element_count=sum(a.size for a in arrays.values())
    del arrays,projected,snapshot_hashes
    # Re-read retained authenticated bytes, then compare with separate source formulas.
    with (output/'arrays.npz').open('rb') as stream: raw=stream.read(512*1024*1024+1)
    if len(raw)>512*1024*1024 or hashlib.sha256(raw).hexdigest()!=manifest['artifacts']['arrays.npz']:
        raise ValueError('comparison_numeric_array_bytes')
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved: restored={name:np.array(saved[name]) for name in saved.files}
    validate_arrays(restored,len(records))
    ledger_raw=(output/'row-receipts.jsonl').read_bytes()
    if hashlib.sha256(ledger_raw).hexdigest()!=manifest['artifacts']['row-receipts.jsonl']:
        raise ValueError('comparison_numeric_ledger_bytes')
    chain=verify_chain(ledger_raw,len(records),previous)
    expected_input=[];expected_label=[]
    print(json.dumps(dict(stage='independent_mixed_numeric_reconstruction',rows=len(records))),flush=True)
    for i,item in enumerate(records):
        row=item['encoder_input'];expected=separate_encoder.original_encoding(row,snapshots[row['candidate_request_id']])
        for name,value in expected.items():
            if not np.array_equal(value,restored[name][i]) or value.tobytes()!=restored[name][i].tobytes():
                raise ValueError('comparison_numeric_complete_tensor_difference')
        if chain[i]['origin']!=seals[i]: raise ValueError('comparison_numeric_origin_chain')
        ih=separate_encoder.row_digest(expected,MODEL_FIELDS);lh=separate_encoder.row_digest(expected,LABEL_FIELDS)
        if ih!=chain[i]['input_tensor_sha256'] or lh!=chain[i]['label_tensor_sha256']:
            raise ValueError('comparison_numeric_independent_row_hash')
        expected_input.append(ih);expected_label.append(lh)
        if (i+1)%15000==0:
            print(json.dumps(dict(stage='independent_mixed_numeric_progress',rows_verified=i+1,total_rows=len(records),elapsed_seconds=round(time.monotonic()-started,1))),flush=True)
    independently={name:duplicates(value,expected_input,expected_label,components) for name,value in indices.items()}
    if independently!=audit or duplicates(range(len(records)),expected_input,expected_label,components)!=union_audit:
        raise ValueError('comparison_numeric_duplicate_recount')
    if read(output/'cohort-indices.json')!=indices or sha(output/'cohort-indices.json')!=manifest['artifacts']['cohort-indices.json']:
        raise ValueError('comparison_numeric_saved_indices')
    result=dict(kind='paired_weak_reconstruction_numeric_verification',status='passed',rows=len(records),rows_per_arm={k:len(v) for k,v in indices.items()},
        arrays_verified=array_count,tensor_elements_verified=element_count,bitwise_equal=True,row_chain_head=previous,
        input_duplicates_per_arm=audit,union_input_duplicates=union_audit,profiles=profiles,cache_manifest_sha256=sha(output/'manifest.json'),
        raw_array_bytes=manifest['raw_array_bytes'],compressed_array_bytes=manifest['compressed_array_bytes'],
        source_and_cohort_report_sha256=manifest['cohort_report_sha256'],reference_formula_sha256=sha('research/issue-33-consumed-numeric/verify_cache.py'),
        script_sha256=sha(__file__),elapsed_seconds=round(time.monotonic()-started,3),
        model_fits=0,model_inferences=0,new_native_requests=0,final_test_used=False,gold_certified=False,legacy_label_admissions=0,
        further_conditions='Fresh reserved research cohort readiness and a separate committed fit binding remain required; no training or production admission from this receipt.')
    save(output/'verification.json',result)
    _publish_directory_atomically(output,OUTPUT,immutable_message='comparison_numeric_destination_exists')
    save(RUN_ROOT/'report.json',result)
    return result


if __name__=='__main__':
    if RUN_ROOT.exists(): raise SystemExit('comparison_numeric_already_reserved')
    RUN_ROOT.mkdir()
    save(RUN_ROOT/'reservation.json',dict(plan_sha256=sha(PLAN),stage='paired_numeric_verification'))
    started=time.monotonic()
    try: result=run()
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[a-z_0-9]{3,120}',str(error)) else 'unclassified_error'
        save(RUN_ROOT/'execution.json',dict(status='failed',error_type=type(error).__name__,code=code,
            errno=getattr(error,'errno',None),winerror=getattr(error,'winerror',None),elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(dict(status='failed',error_type=type(error).__name__,code=code)),flush=True)
        raise SystemExit(1) from None
    save(RUN_ROOT/'execution.json',dict(status='complete',report_sha256=sha(RUN_ROOT/'report.json'),elapsed_seconds=round(time.monotonic()-started,3)))
    print(json.dumps({k:result[k] for k in ('status','rows','rows_per_arm','tensor_elements_verified','input_duplicates_per_arm','elapsed_seconds')}),flush=True)
