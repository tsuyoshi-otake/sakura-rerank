"""One bounded native attempt per reserved reading, with full rejection accounting."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import threading
import time

from sakura_rerank.data.input_boundary import score_view
from consume35_common import HERE, ROOT, authenticate, committed, load_script, read, save, sha

sys.path.insert(0,'research/issue-35-source-units')
try:
    from resume_native import checked_result
    from unit_native import runtime
finally:
    sys.path.pop(0)

BINDING=HERE/'native-binding-v1.json'
KS=(1,5,6,10,32)


def aggregate(rows,snapshots,excluded):
    groups=defaultdict(Counter)
    for row in rows:
        isolation=('no_input_hypothesis' if not row['inputs'] else
                   'historically_related' if any(p['stable_id'] in excluded for p in row['inputs']) else 'isolated_hypothesis')
        score=score_view(row['view'],snapshots) if row['view'] is not None else dict(status=row['status'])
        for group in ('all',row['stratum'],isolation):
            total=groups[group];total['slots']+=1;total[score['status']]+=1
            if score['status']=='measured':
                total['parts']+=score['parts']
                for k in KS:total['all_parts_at_'+str(k)]+=score['all_parts_present'][str(k)]
            for part in row['inputs']:
                if part['request_id'] not in snapshots:
                    total['unmeasured_parts']+=1;continue
                total['measured_parts']+=1
                surfaces=[p['surface'] for p in snapshots[part['request_id']]]
                for k in KS:total['parts_at_'+str(k)]+=part['target'] in surfaces[:k]
    return {key:dict(value) for key,value in groups.items()}


def seal(plan_commit):
    spec=authenticate(plan_commit);runtime(spec)
    prep=read(ROOT/'preparation.json');requests=read(ROOT/'requests.json')['requests']
    if len(requests)!=prep['requests'] or len(requests)>spec['native']['maximum_unique_requests']:
        raise ValueError('consumption_native_population_bound')
    inputs=[ROOT/name for name in ('preparation.json','consumed-slots.json','requests.json','history-report.json','source-relations.json')]
    code=[HERE/'native_consumption.py','research/reference_execution.py','research/issue-31-quality/run_reference_probe.py',
          'research/issue-35-source-units/resume_native.py','research/issue-35-source-units/unit_native.py',
          'research/issue-35-source-units/unit35_common.py','src/sakura_rerank/data/reference_probe.py',
          'src/sakura_rerank/data/research_exporter.py','src/sakura_rerank/data/contracts.py']
    save(BINDING,dict(kind='prospective_source_native_binding',plan_commit=plan_commit,
        requests=len(requests),slots=prep['slots'],maximum_output_bytes=512*1024*1024,
        inputs={str(p).replace('\\','/'):sha(p) for p in inputs},code={str(p).replace('\\','/'):sha(p) for p in code},
        existing_segment_bound=18,retries=0,model_predictions=0,gold_admission=0,final_test=False))
    return dict(stage='native_sealed',requests=len(requests),binding_sha256=sha(BINDING))


def bound_inputs(commit):
    bound=json.loads(committed(BINDING,commit));spec=authenticate(bound['plan_commit'])
    for path,digest in {**bound['inputs'],**bound['code']}.items():
        if sha(path)!=digest:raise ValueError('consumption_native_binding_changed')
    for path in bound['code']:committed(path,commit)
    return bound,spec,runtime(spec)


def run(commit):
    bound,spec,identity=bound_inputs(commit)
    requests=read(ROOT/'requests.json')['requests'];rows=read(ROOT/'consumed-slots.json')['rows']
    save(ROOT/'native-reservation.json',dict(binding_commit=commit,requests=len(requests),slots=len(rows),retries=0))
    executor=load_script('consume35_execution','research/reference_execution.py')
    validator=load_script('consume35_validator','research/issue-31-quality/run_reference_probe.py')
    target=ROOT/'candidates';target.mkdir(exist_ok=False)
    observed_bytes=0;lock=threading.Lock()
    def validate(directory,raw,runtime_identity):
        nonlocal observed_bytes
        with lock:
            observed_bytes+=(directory/'output.jsonl').stat().st_size
            if observed_bytes>bound['maximum_output_bytes']:raise ValueError('consumption_native_output_bound')
        return validator.validate_result(directory,raw,runtime_identity)
    start=time.monotonic();outcomes={};snapshots={};stop=None
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0,len(requests),2):
            remaining=spec['native']['total_timeout_seconds']-(time.monotonic()-start)
            if remaining<=0:stop='total_deadline';break
            futures={pool.submit(executor.execute_request,target/f'request-{i:04d}',i,requests[i],identity,
                Path(spec['native']['executable']),Path(spec['native']['dictionary']),validate,min(30,remaining)):i
                for i in range(offset,min(offset+2,len(requests)))}
            for future in as_completed(futures):
                index=futures[future]
                terminal=None
                try:
                    terminal,_=future.result()
                    result,record=checked_result(target/f'request-{index:04d}',requests[index],terminal,identity,validator)
                except Exception as error:
                    result=dict(status='unexpected_failure',error_type=type(error).__name__);record=None
                outcomes[index]=dict(index=index,terminal=terminal,**result)
                if record is not None:snapshots[record['stable_id']]=record
                if result['status'] not in ('complete','output_contract_rejected','candidate_count_rejected'):
                    stop='unexpected_request_failure'
            if offset%100==0 or stop:
                print(json.dumps(dict(stage='native',attempted=len(outcomes),total=len(requests))),flush=True)
            if stop:break
    ledger=[outcomes.get(i,dict(index=i,status='not_attempted')) for i in range(len(requests))]
    save(ROOT/'request-ledger.json',dict(rows=ledger,binding_commit=commit,stop_reason=stop))
    bound_inputs(commit)
    surfaces={key:r['candidate_snapshots']['training_top32']['candidates'] for key,r in snapshots.items()}
    report=dict(kind='prospective_source_native',status='complete_with_explicit_rejections' if not stop and len(outcomes)==len(requests) else 'incomplete',
        slots=len(rows),requests=len(requests),outcomes=dict(Counter(r['status'] for r in ledger)),
        native_calls=len(outcomes),retries=0,not_attempted=len(requests)-len(outcomes),stop_reason=stop,
        output_bytes=observed_bytes,elapsed_seconds=round(time.monotonic()-start,3),
        groups=aggregate(rows,surfaces,read(ROOT/'source-relations.json')['excluded']),
        request_ledger_sha256=sha(ROOT/'request-ledger.json'),binding_commit=commit,
        independent_accuracy=None,gold_quality=None,confidence_interval=None,
        interval_reason='Prospective source reconstruction with unresolved labels and shared lineage; not independent correctness.',
        model_fits=0,model_inference=0,gold_admission=0,calibration_admission=0,final_test=False)
    save(ROOT/'native-report.json',report)
    return {k:report[k] for k in ('status','slots','outcomes','not_attempted','groups','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit',required=True)
    args=parser.parse_args();print(json.dumps((seal if args.stage=='seal' else run)(args.commit)))
