"""Rebuild all bound parent conflicts, preserving lineage and consumed identity."""
import argparse
from collections import Counter,defaultdict
import json
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.source_reading_gate import prepare,load_prepared
from sakura_rerank.data.source_reading_rebuild import rebuild
from rebuild_common import HERE,ROOT,PARENT,previous,authenticate,freeze,read,require,save,sha


def parents():
    bound=read(PARENT/'preparation.json')
    pool=load_prepared(PARENT/'pool',bound['pool_manifest_sha256'],purpose='candidate_generation')
    require(pool['manifest']['input_rows']==75000 and pool['manifest']['pending_rows']==915,'parent_population')
    chosen={d['source']['original_row_sha256']:d for d in pool['decisions'] if d['terminal']=='pending_reading_conflict'}
    expected={r['original_row_sha256'] for r in read(previous.PRIOR/'repair-proposals.json')['rows']}
    require(set(chosen)==expected and len(chosen)==335,'parent_repair_identity')
    cohort,origins=previous.population()
    indices=[i for i,r in enumerate(cohort) if r['origin']['original_row_sha256'] in chosen]
    require(len(indices)==335 and all(cohort[i]['origin']['group']=='dictionary' and cohort[i]['encoder_input']['corpus']=='aozora' for i in indices),'selected_parent_scope')
    return cohort,origins,indices,chosen


def run(commit):
    started=time.monotonic();plan,registry,selection,guard=authenticate(commit)
    cohort,origins,indices,decisions=parents()
    results={};paragraphs={}
    for row,source,paragraph in previous.source_records([cohort[i] for i in indices],[origins[i] for i in indices],registry,selection):
        key=source['original_row_sha256']
        require(key not in results,'duplicate_parent')
        result=rebuild(row,source,paragraph,decisions[key],parent_dictionary_only=True)
        results[key]=result
        if result['input'] is not None:paragraphs[key]=paragraph
    require(set(results)==set(decisions),'all_parents_recovered')
    ordered=[results[key] for key in sorted(results)]
    usable=[r for r in ordered if r['status']=='rebuilt_source_ready']
    if usable:
        prepare([(r['input'],r['source'],paragraphs[r['lineage']['parent_original_row_sha256']]) for r in usable],ROOT/'pool',
                source_binding_sha256=sha(HERE/'plan-v1.json'),expected_rows=len(usable))
        pool_hash=sha(ROOT/'pool/manifest.json')
        checked=load_prepared(ROOT/'pool',pool_hash,purpose='candidate_generation')
        require([r['input'] for r in checked['rows']]==[r['input'] for r in usable],'strict_child_consumer')
    else:pool_hash=None
    by_input,by_label=defaultdict(list),defaultdict(list)
    for i,row in enumerate(cohort):
        value=row['encoder_input']
        by_input[canonical_json_hash([value['left_context'],value['reading']])].append(i)
        by_label[canonical_json_hash([value['left_context'],value['reading'],value['target']])].append(i)
    requests={};overlap=[]
    for result in usable:
        row=result['input'];requests[row['candidate_request_id']]=dict(stable_id=row['candidate_request_id'],reading=row['reading'])
        match=by_input.get(canonical_json_hash([row['left_context'],row['reading']]),[])
        exact=by_label.get(canonical_json_hash([row['left_context'],row['reading'],row['target']]),[])
        overlap.append(dict(child_input_sha256=canonical_json_hash(row),current_input_rows=match,current_same_target_rows=exact,
                            matching_parent_components=sorted({cohort[i]['encoder_input']['component_id'] for i in match})))
    save(ROOT/'rebuilds.json',dict(rows=ordered))
    save(ROOT/'raw-overlap.json',dict(rows=overlap))
    save(ROOT/'requests.json',dict(requests=[requests[key] for key in sorted(requests)]))
    require(guard.blocked==0,'forbidden_read')
    result=dict(status='complete',plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),parents=335,
        outcomes=dict(Counter(r['status'] for r in ordered)),rebuilt_rows=len(usable),requests=len(requests),pool_manifest_sha256=pool_hash,
        current_raw_input_match_rows=sum(bool(r['current_input_rows']) for r in overlap),
        current_exact_input_and_target_match_rows=sum(bool(r['current_same_target_rows']) for r in overlap),
        artifacts={name:sha(ROOT/name) for name in ('rebuilds.json','raw-overlap.json','requests.json')},
        elapsed_seconds=round(time.monotonic()-started,3),forbidden_data_reads=guard.blocked,
        original_labels_changed=0,training_admission=False,gold_admission=False,native_calls=0,final_test=False)
    save(ROOT/'preparation.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','prepare'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=freeze() if args.stage=='plan' else run(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith(('reading_rebuild_','source_reading_','conflict_')):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
