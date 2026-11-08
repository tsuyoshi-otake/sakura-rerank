"""Commit exact requests before one bounded native attempt per reading."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import threading
import time

from sakura_rerank.data.source_reading_gate import load_prepared
from rebuild_common import HERE,ROOT,authenticate,committed,load_script,read,require,runtime,save,sha
from rebuild_metrics import measure,summary

BINDING=HERE/'native-binding-v1.json'


def helpers():
    executor=load_script('reading_rebuild_executor','research/reference_execution.py')
    validator=load_script('reading_rebuild_validator','research/issue-31-quality/run_reference_probe.py')
    sys.path.insert(0,'research/issue-35-source-units')
    try:from resume_native import checked_result
    finally:sys.path.pop(0)
    return executor,validator,checked_result


def source_inputs(plan_commit):
    plan,_,_,guard=authenticate(plan_commit)
    preparation=read(ROOT/'preparation.json')
    require(preparation['status']=='complete' and preparation['plan_commit']==plan_commit
        and preparation['plan_sha256']==sha(HERE/'plan-v1.json'),'preparation_binding')
    for name,digest in preparation['artifacts'].items():require(sha(ROOT/name)==digest,'prepared_artifact')
    repairs=read(ROOT/'rebuilds.json')['rows'];requests=read(ROOT/'requests.json')['requests']
    require(len(repairs)==335 and len(requests)==preparation['requests']<=335,'native_population')
    expected={r['input']['candidate_request_id']:dict(stable_id=r['input']['candidate_request_id'],reading=r['input']['reading'])
        for r in repairs if r['input'] is not None}
    require(requests==[expected[key] for key in sorted(expected)],'native_request_derivation')
    if preparation['pool_manifest_sha256']:
        pool=load_prepared(ROOT/'pool',preparation['pool_manifest_sha256'],purpose='candidate_generation')
        require([r['input'] for r in pool['rows']]==[r['input'] for r in repairs if r['input'] is not None],'native_consumer')
    return plan,preparation,repairs,requests,guard


def seal(commit):
    plan,preparation,_,requests,guard=source_inputs(commit)
    runtime(plan)
    paths=[ROOT/name for name in ('preparation.json','rebuilds.json','requests.json','raw-overlap.json')]
    if preparation['pool_manifest_sha256']:paths.extend(ROOT/'pool'/name for name in ('manifest.json','decisions.jsonl.gz','prepared-rows.jsonl.gz'))
    bound=dict(kind='original_reading_native_binding',version=1,plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),
        attempt=ROOT.as_posix(),artifacts={p.as_posix():sha(p) for p in paths},requests=len(requests),parents=335,
        native=plan['native'],automatic_retries=0,unchanged_segment_bound=18,forbidden_data_reads=guard.blocked,
        model_inferences=0,new_fits=0,training_admission=False,gold_admission=False,final_test=False)
    require(guard.blocked==0,'forbidden_read');save(BINDING,bound)
    return dict(status='native_binding_sealed',requests=len(requests),binding_sha256=sha(BINDING))


def bound_inputs(commit):
    bound=json.loads(committed(BINDING,commit))
    require(bound['attempt']==ROOT.as_posix(),'native_attempt_binding')
    plan,preparation,repairs,requests,guard=source_inputs(bound['plan_commit'])
    require(bound['plan_sha256']==sha(HERE/'plan-v1.json') and bound['native']==plan['native'] and bound['requests']==len(requests),'native_plan_binding')
    for path,digest in bound['artifacts'].items():require(sha(path)==digest,'native_bound_artifact')
    return plan,preparation,repairs,requests,guard,runtime(plan)


def run(commit):
    plan,_,repairs,requests,guard,identity=bound_inputs(commit)
    executor,validator,checked_result=helpers();native=plan['native'];target=ROOT/'candidates'
    target.mkdir(exist_ok=False)
    save(ROOT/'native-request-reservation.json',dict(binding_commit=commit,binding_sha256=sha(BINDING),requests=len(requests),automatic_retries=0))
    started=time.monotonic();accepted_bytes=0;lock=threading.Lock();attempts=[];snapshots={};stop=None
    def validate(directory,raw,runtime_identity):
        nonlocal accepted_bytes
        with lock:
            accepted_bytes+=(directory/'output.jsonl').stat().st_size
            require(accepted_bytes<=native['maximum_output_bytes'],'native_output_limit')
        return validator.validate_result(directory,raw,runtime_identity)
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
                    terminal,_=future.result()
                    result,record=checked_result(target/f'request-{index:04d}',requests[index],terminal,identity,validator)
                except Exception as error:result=dict(status='unexpected_failure',error_type=type(error).__name__);record=None
                attempts.append(dict(index=index,terminal=terminal,outcome=result))
                if record is not None:snapshots[requests[index]['stable_id']]=record
                if result['status'] not in ('complete','candidate_count_rejected','output_contract_rejected'):stop='unexpected_request_failure'
            if offset%50==0 or stop:print(json.dumps(dict(stage='native',attempted=len(attempts),requested=len(requests),measured=len(snapshots))),flush=True)
            if stop:break
    attempts.sort(key=lambda r:r['index']);attempted={r['index']:r['outcome']['status'] for r in attempts}
    states={request['stable_id']:attempted.get(i,'not_attempted') for i,request in enumerate(requests)}
    execution=dict(binding_commit=commit,binding_sha256=sha(BINDING),attempts=attempts,not_attempted=len(requests)-len(attempts),
        stop_reason=stop,elapsed_seconds=round(time.monotonic()-started,3),accepted_output_bytes=accepted_bytes,
        request_outcomes=dict(Counter(states.values())),automatic_retries=0)
    save(ROOT/'native-execution.json',execution)
    rows=measure(repairs,snapshots,states);save(ROOT/'measurements.json',dict(rows=rows))
    runtime(plan);require(guard.blocked==0,'forbidden_read')
    report=dict(status='complete' if stop is None else 'incomplete',binding_commit=commit,native_requests=len(requests),
        native_attempted=len(attempts),native_measured=len(snapshots),request_outcomes=execution['request_outcomes'],
        census=summary(rows),execution_sha256=sha(ROOT/'native-execution.json'),measurements_sha256=sha(ROOT/'measurements.json'),
        elapsed_seconds=round(time.monotonic()-started,3),forbidden_data_reads=guard.blocked,automatic_retries=0,
        accuracy_improvement_demonstrated=False,original_labels_changed=0,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'native-report.json',report);require(stop is None,'native_incomplete')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','native'));parser.add_argument('--commit',required=True);args=parser.parse_args()
    try:result=seal(args.commit) if args.stage=='seal' else run(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('reading_rebuild_'):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
