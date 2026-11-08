"""Reuse sealed native evidence and execute only exact newly bound readings."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import threading
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.source_reading_units import POLICY,VIEWS
from extent_common import HERE,ROOT,authenticate,committed,helpers,prior_snapshots,read,require,runtime,save,sha
from extent_metrics import measurements,aggregate
from prepare_extents import flatten

BINDING=HERE/'native-binding-v1.json'


def source_inputs(commit):
    plan,_,_,guard=authenticate(commit);preparation=read(ROOT/'preparation.json')
    require(preparation['status']=='complete' and preparation['plan_commit']==commit and preparation['plan_sha256']==sha(HERE/'plan-v1.json'),'preparation_binding')
    for name,digest in preparation['artifacts'].items():require(sha(ROOT/name)==digest,'prepared_artifact')
    source=read(ROOT/'source-extents.json')['rows'];requests=read(ROOT/'requests.json')
    require(len(source)==len({r['parent_original_row_sha256'] for r in source})==335
        and all(set(r['views'])==set(VIEWS) for r in source),'source_population')
    expected={}
    for parent,_,view in flatten(source):
        lineage=view['lineage'];row=view['input']
        require(view['lineage_sha256']==canonical_json_hash(lineage) and lineage['parent_original_row_sha256']==parent
            and lineage['policy_sha256']==canonical_json_hash(POLICY) and lineage['training_eligible'] is False
            and lineage['independent_gold_eligible'] is False and lineage['independent_evaluation_eligible'] is False,'source_lineage')
        require(lineage['candidate_input_sha256']==(canonical_json_hash(row) if row is not None else None),'source_input_hash')
        if row is not None:
            require(view['status']=='source_extent_diagnostic_ready' and not lineage['pending_reasons']
                and row['reading']==view['hypothesis']['reading'] and row['target']==view['hypothesis']['target']
                and row['left_context']==view['hypothesis']['left_context'] and 1<=len(row['reading'])<=128 and 1<=len(row['target'])<=256
                and row['candidate_request_id']=='growth-reading-'+canonical_json_hash(row['reading']),'source_request_bounds')
            expected[row['candidate_request_id']]=dict(stable_id=row['candidate_request_id'],reading=row['reading'])
    require(requests['all_requests']==[expected[k] for k in sorted(expected)] and len(expected)<=1005,'source_requests')
    identity=runtime(plan);prior=prior_snapshots(identity);old=set(prior)
    require(requests['reused_request_ids']==sorted(old) and old<=set(expected)
        and requests['new_requests']==[expected[k] for k in sorted(set(expected)-old)],'request_reuse_partition')
    return plan,source,requests,guard,identity,prior


def seal(commit):
    plan,_,requests,guard,_,_=source_inputs(commit)
    bound=dict(kind='source_extent_native_binding',version=1,plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),attempt=ROOT.as_posix(),
        artifacts={(ROOT/name).as_posix():sha(ROOT/name) for name in ('preparation.json','source-extents.json','requests.json','raw-overlap.json')},
        parents=335,view_slots=1005,new_requests=len(requests['new_requests']),reused_requests=264,native=plan['native'],
        automatic_retries=0,training_admission=False,gold_admission=False,final_test=False)
    require(guard.blocked==0,'forbidden_read');save(BINDING,bound)
    return dict(status='native_binding_sealed',new_requests=bound['new_requests'],reused_requests=264,binding_sha256=sha(BINDING))


def bound_inputs(commit):
    bound=json.loads(committed(BINDING,commit));require(bound['attempt']==ROOT.as_posix(),'native_attempt')
    plan,source,requests,guard,identity,prior=source_inputs(bound['plan_commit'])
    require(bound['native']==plan['native'] and bound['plan_sha256']==sha(HERE/'plan-v1.json') and bound['new_requests']==len(requests['new_requests']),'native_plan')
    for path,digest in bound['artifacts'].items():require(sha(path)==digest,'native_bound_artifact')
    return plan,source,requests,guard,identity,prior


def run(commit):
    plan,source,request_set,guard,identity,snapshots=bound_inputs(commit);requests=request_set['new_requests']
    executor,validator,check=helpers();native=plan['native'];target=ROOT/'candidates';target.mkdir(exist_ok=False)
    save(ROOT/'native-request-reservation.json',dict(binding_commit=commit,binding_sha256=sha(BINDING),new_requests=len(requests),reused_requests=264,automatic_retries=0))
    started=time.monotonic();output_bytes=0;lock=threading.Lock();attempts=[];stop=None
    def validate(directory,raw,current_identity):
        nonlocal output_bytes
        with lock:
            output_bytes+=(directory/'output.jsonl').stat().st_size
            require(output_bytes<=native['maximum_output_bytes'],'native_output_limit')
        return validator.validate_result(directory,raw,current_identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0,len(requests),2):
            remaining=native['total_timeout_seconds']-(time.monotonic()-started)
            if remaining<=0:stop='run_timeout';break
            futures={pool.submit(executor.execute_request,target/f'request-{i:04d}',i,requests[i],identity,
                Path(native['executable']),Path(native['dictionary']),validate,min(native['request_timeout_seconds'],remaining)):i
                for i in range(offset,min(offset+2,len(requests)))}
            for future in as_completed(futures):
                index=futures[future];terminal=None
                try:
                    terminal,_=future.result();outcome,record=check(target/f'request-{index:04d}',requests[index],terminal,identity,validator)
                except Exception as error:outcome=dict(status='unexpected_failure',error_type=type(error).__name__);record=None
                attempts.append(dict(index=index,terminal=terminal,outcome=outcome))
                if record is not None:snapshots[requests[index]['stable_id']]=record
                if outcome['status'] not in ('complete','candidate_count_rejected','output_contract_rejected'):stop='unexpected_request_failure'
            if offset%50==0 or stop:print(json.dumps(dict(stage='native',attempted=len(attempts),new_requests=len(requests),available_snapshots=len(snapshots))),flush=True)
            if stop:break
    attempts.sort(key=lambda r:r['index']);by_index={r['index']:r['outcome']['status'] for r in attempts}
    states={key:'complete' for key in request_set['reused_request_ids']}
    states.update({r['stable_id']:by_index.get(i,'not_attempted') for i,r in enumerate(requests)})
    execution=dict(binding_commit=commit,attempts=attempts,new_requests=len(requests),reused_requests=264,
        not_attempted=len(requests)-len(attempts),stop_reason=stop,elapsed_seconds=round(time.monotonic()-started,3),
        accepted_output_bytes=output_bytes,new_request_outcomes=dict(Counter(by_index.values())),all_request_outcomes=dict(Counter(states.values())),automatic_retries=0)
    save(ROOT/'native-execution.json',execution)
    rows=measurements(source,snapshots,states);save(ROOT/'measurements.json',dict(rows=rows));result=aggregate(rows)
    runtime(plan);require(guard.blocked==0,'forbidden_read')
    report=dict(status='complete' if stop is None else 'incomplete',binding_commit=commit,
        execution_sha256=sha(ROOT/'native-execution.json'),measurements_sha256=sha(ROOT/'measurements.json'),
        new_requests=len(requests),reused_requests=264,new_request_outcomes=execution['new_request_outcomes'],all_request_outcomes=execution['all_request_outcomes'],
        census=result,elapsed_seconds=round(time.monotonic()-started,3),forbidden_data_reads=guard.blocked,
        accuracy_improvement_demonstrated=False,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'native-report.json',report);require(stop is None,'native_incomplete')
    return dict(status=report['status'],new_requests=len(requests),request_outcomes=report['new_request_outcomes'],
        source_presence={name:r['source_presence'] for name,r in result['views'].items()})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','native'));parser.add_argument('--commit',required=True);args=parser.parse_args()
    try:result=seal(args.commit) if args.stage=='seal' else run(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('source_extent_'):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
