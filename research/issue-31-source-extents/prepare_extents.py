"""Recover every fixed parent and derive all views before any new native call."""
import argparse
from collections import Counter,defaultdict
import json
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.source_reading_units import VIEWS,build
from extent_common import HERE,ROOT,PRIOR,authenticate,freeze,parents,reading,read,require,save,sha


def flatten(rows):
    return [(r['parent_original_row_sha256'],name,r['views'][name]) for r in rows for name in VIEWS]


def run(commit):
    started=time.monotonic();_,registry,selection,guard=authenticate(commit)
    cohort,origins,indices,decisions=parents();previous={r['lineage']['parent_original_row_sha256']:r for r in read(PRIOR/'rebuilds.json')['rows']}
    values={}
    for row,source,paragraph in reading.source_records([cohort[i] for i in indices],[origins[i] for i in indices],registry,selection):
        key=source['original_row_sha256'];require(key not in values,'duplicate_parent')
        value=build(row,source,paragraph,decisions[key],parent_dictionary_only=True)
        require(value['parent_rebuild_sha256']==canonical_json_hash(previous[key]),'parent_repair_replay')
        values[key]=value
    require(set(values)==set(previous)==set(decisions) and len(values)==335,'complete_parent_identity')
    rows=[values[k] for k in sorted(values)];views=flatten(rows);requests={}
    by_input,by_label=defaultdict(list),defaultdict(list)
    for i,record in enumerate(cohort):
        row=record['encoder_input'];by_input[canonical_json_hash([row['left_context'],row['reading']])].append(i)
        by_label[canonical_json_hash([row['left_context'],row['reading'],row['target']])].append(i)
    overlaps=[]
    for parent,name,view in views:
        row=view['input']
        if row is None:continue
        requests[row['candidate_request_id']]=dict(stable_id=row['candidate_request_id'],reading=row['reading'])
        match=by_input.get(canonical_json_hash([row['left_context'],row['reading']]),[])
        overlaps.append(dict(parent_original_row_sha256=parent,view=name,input_sha256=canonical_json_hash(row),current_input_rows=match,
            current_same_target_rows=by_label.get(canonical_json_hash([row['left_context'],row['reading'],row['target']]),[]),
            matching_parent_components=sorted({cohort[i]['encoder_input']['component_id'] for i in match})))
    prior=read(PRIOR/'requests.json')['requests'];old={r['stable_id'] for r in prior}
    require(old<=set(requests) and all(requests[r['stable_id']]==r for r in prior),'prior_requests_retained')
    new=[requests[k] for k in sorted(set(requests)-old)];all_requests=[requests[k] for k in sorted(requests)]
    require(len(all_requests)<=1005 and len(views)==1005,'request_population_bound')
    save(ROOT/'source-extents.json',dict(rows=rows));save(ROOT/'raw-overlap.json',dict(rows=overlaps))
    save(ROOT/'requests.json',dict(all_requests=all_requests,new_requests=new,reused_request_ids=sorted(old)))
    census={}
    for name in VIEWS:
        group=[v for _,n,v in views if n==name]
        census[name]=dict(parents=len(group),status_counts=dict(Counter(v['status'] for v in group)),expanded_rows=sum(v['expanded'] for v in group),
            within_preparation_bounds=sum(v['within_preparation_bounds'] for v in group),
            pending_reasons=dict(Counter(reason for v in group for reason in v['lineage']['pending_reasons'])),
            left_stops=dict(Counter(v['left_stop'] for v in group)),right_stops=dict(Counter(v['right_stop'] for v in group)),
            current_raw_input_match_rows=sum(bool(v['current_input_rows']) for v in overlaps if v['view']==name))
    require(guard.blocked==0,'forbidden_read')
    report=dict(status='complete',plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),parents=335,view_slots=1005,
        source=census,unique_requests=len(all_requests),new_requests=len(new),reused_requests=len(old),
        artifacts={name:sha(ROOT/name) for name in ('source-extents.json','raw-overlap.json','requests.json')},
        elapsed_seconds=round(time.monotonic()-started,3),forbidden_data_reads=guard.blocked,
        original_labels_changed=0,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'preparation.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','prepare'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=freeze() if args.stage=='plan' else run(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('source_extent_'):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
