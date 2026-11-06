"""Complete indexed lexical census, retaining native/model interpretation limits."""
import argparse
from collections import Counter
import json
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.jawiki_preprocess import load_dictionary_inputs
from sakura_rerank.data.lexical_cover import Lexicon,TargetSubstrings
from sakura_rerank.data.tier_a import validate_dictionary_index_manifest
from lexical_common import HERE,ROOT,INDEX,MANIFEST,VIEWS,authenticate,freeze,pairs,require,save,sha


def dictionary(targets,*,independent=False):
    require(INDEX.stat().st_size<=64*1024*1024,'dictionary_file_bound')
    records,manifest=load_dictionary_inputs(INDEX,MANIFEST);verified=validate_dictionary_index_manifest(manifest,records)
    require(verified['record_count']==368341 and verified['content_sha256']==sha(INDEX),'dictionary_verified_identity')
    if independent:
        buckets={}
        for target in set(targets):
            for i in range(len(target)):
                buckets.setdefault(target[i],set()).add(target)
                if i+1<len(target):buckets.setdefault(target[i:i+2],set()).add(target)
        selected=[r for r in records if any(r['surface'] in t for t in buckets.get(r['surface'][:2],()))]
        states=None
    else:
        index=TargetSubstrings(targets);selected=[r for r in records if index.contains(r['surface'])];states=len(index.edges)
    return selected,dict(index_rows=len(records),relevant_rows=len(selected),relevant_index_sha256=canonical_json_hash(selected),
        substring_states=states,manifest_sha256=sha(MANIFEST),index_sha256=sha(INDEX),compiled_sha256=verified['dictionary_sha256'])


def classify(row):
    if row['condition']=='dictionary_control':return 'dictionary_reading_control'
    present=row['native_presence']['32'];cover=row['dictionary_plus_literal']['status']
    if cover=='work_bound':return 'lexical_work_bound'
    if present:return 'native_present_index_cover' if cover=='covered' else 'native_present_outside_index_model'
    if row['exact_pair']:return 'native_missing_exact_entry'
    if cover=='covered':return 'native_missing_composed_index_cover'
    return 'native_missing_no_index_cover'


def summarize(rows):
    result={}
    for condition in ('dictionary_control',*VIEWS):
        group=[r for r in rows if r['condition']==condition]
        require(len(group)==335,'condition_denominator')
        result[condition]=dict(rows=len(group),surface_indexed_rows=sum(r['surface_indexed'] for r in group),exact_pair_rows=sum(r['exact_pair'] for r in group),
            dictionary_only=dict(Counter(r['dictionary_only']['status'] for r in group)),
            dictionary_plus_literal=dict(Counter(r['dictionary_plus_literal']['status'] for r in group)),
            terminal_counts=dict(Counter(classify(r) for r in group)),
            minimum_cover_units=dict(Counter(str(r['dictionary_plus_literal']['minimum_units']) for r in group if r['dictionary_plus_literal']['status']=='covered')),
            indexed_reading_counts=dict(Counter(str(r['indexed_readings_count']) for r in group)),
            native_source_presence=None if condition=='dictionary_control' else {str(k):sum(r['native_presence'][str(k)] for r in group) for k in (1,5,6,10,32)})
    return result


def run(commit):
    started=time.monotonic();plan,guard=authenticate(commit);inputs=pairs()
    selected,metadata=dictionary([r['target'] for r in inputs]);lexicon=Lexicon(selected);rows=[]
    for pair in inputs:
        indexed=lexicon.readings.get(pair['target'],())
        value={k:v for k,v in pair.items() if k not in ('target','reading')}
        value.update(pair_sha256=canonical_json_hash(pair),target_sha256=canonical_json_hash(pair['target']),reading_sha256=canonical_json_hash(pair['reading']),
            surface_indexed=bool(indexed),indexed_readings_count=len(indexed),indexed_readings_sha256=canonical_json_hash(indexed),exact_pair=pair['reading'] in indexed,
            dictionary_only=lexicon.cover(pair['target'],pair['reading']),dictionary_plus_literal=lexicon.cover(pair['target'],pair['reading'],literal_kana=True))
        rows.append(value)
    require(all(r['exact_pair'] and r['indexed_readings_count']==1 for r in rows if r['condition']=='dictionary_control'),'dictionary_control_identity')
    save(ROOT/'pairs.json',dict(rows=inputs));save(ROOT/'relevant-lexicon.json',dict(rows=selected));save(ROOT/'lexical-rows.json',dict(rows=rows))
    require(guard.blocked==0,'forbidden_read')
    report=dict(status='complete',plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),pairs=1340,source_views=1005,controls=335,
        dictionary=metadata,census=summarize(rows),artifacts={name:sha(ROOT/name) for name in ('pairs.json','relevant-lexicon.json','lexical-rows.json')},
        elapsed_seconds=round(time.monotonic()-started,3),forbidden_data_reads=guard.blocked,original_labels_changed=0,
        model_inferences=0,native_requests=0,training_admission=False,gold_admission=False,final_test=False,safety_limit=plan['safety_limit'])
    save(ROOT/'analysis.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','analyze'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=freeze() if args.stage=='plan' else run(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith(('lexical_audit_','lexical_cover_')):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
