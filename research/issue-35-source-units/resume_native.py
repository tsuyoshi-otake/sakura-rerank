"""Continue only unattempted requests; rejected contracts never yield candidates.

The first attempt and all of its bytes remain immutable. ContractError is a
terminal unmeasured diagnostic outcome, not permission to relax the validator.
All other failures stop scheduling. No attempted native request is retried.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import hashlib
from pathlib import Path
import threading
import time

from sakura_rerank.data.contracts import ContractError,MAX_CONVERTER_SEGMENTS,canonical_json_hash
from unit35_common import ROOT,HERE,committed,load_script,read,save,sha
from unit_native import aggregate_units,bound_inputs

CONTINUATION=HERE/'native-continuation-v1.json'


def unattempted_indices(total,attempts):
    ids=[r['index'] for r in attempts]
    if (type(total) is not int or not 1<=total<=1000 or len(ids)!=len(set(ids))
            or any(type(i) is not int or not 0<=i<total for i in ids)):
        raise ValueError('unit35_attempt_index_contract')
    seen=set(ids)
    return [i for i in range(total) if i not in seen]


def checked_result(directory,request,terminal,identity,validator):
    """Authenticate a terminal receipt; rejection is never a snapshot."""
    receipt=read(directory/'execution.json')
    if sha(directory/'execution.json')!=terminal['execution_sha256']:
        raise ValueError('unit35_request_receipt_changed')
    raw=(directory/'input.jsonl').read_bytes()
    if json.loads(raw)!=request or sha(directory/'input.jsonl')!=receipt['input_sha256']:
        raise ValueError('unit35_request_input_changed')
    if terminal['status']=='complete':
        if sha(directory/'output.jsonl')!=receipt['output_sha256']:raise ValueError('unit35_native_output_changed')
        return dict(status='complete'),validator.validate_result(directory,raw,identity)[0]
    if terminal['status']=='candidate_count_rejected':
        if (receipt['exit_code']!=2 or (directory/'output.jsonl').exists() or (directory/'native-report.json').exists()
                or sha(directory/'stderr.log')!=receipt['stderr_sha256']):raise ValueError('unit35_invalid_count_rejection')
        return dict(status='candidate_count_rejected'),None
    if terminal['status']=='failed' and receipt.get('exit_code')==0 and receipt.get('error_type')=='ContractError':
        try:validator.validate_result(directory,raw,identity)
        except ContractError as error:
            payload=read(directory/'output.jsonl')
            counts=[len(c['segments']) for c in payload['candidate_snapshots']['training_top32']['candidates']]
            return dict(status='output_contract_rejected',validation_error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
                observed_segment_counts=counts,segments_exceed_existing_bound=any(n>MAX_CONVERTER_SEGMENTS for n in counts),
                existing_segment_bound=MAX_CONVERTER_SEGMENTS,output_sha256=sha(directory/'output.jsonl')) ,None
        raise ValueError('unit35_expected_contract_rejection_not_reproduced')
    return dict(status=terminal['status'],error_type=receipt.get('error_type')),None


def run(commit):
    continuation=json.loads(committed(CONTINUATION,commit))
    for path,digest in continuation['code'].items():
        committed(path,commit)
        if sha(path)!=digest:raise ValueError('unit35_continuation_code_changed')
    bound,plan,identity=bound_inputs(continuation['original_binding_commit'])
    for path,digest in continuation['previous_artifacts'].items():
        if sha(path)!=digest:raise ValueError('unit35_previous_attempt_changed')
    requests=read(ROOT/'requests.json')['requests'];rows=read(ROOT/'source-units.json')['rows']
    original=read(ROOT/'native-execution.json')
    attempted={r['index'] for r in original['attempts']}
    remaining=unattempted_indices(len(requests),original['attempts'])
    if canonical_json_hash(remaining)!=continuation['unattempted_indices_sha256'] or len(remaining)!=continuation['unattempted_count']:
        raise ValueError('unit35_unattempted_population_changed')
    save(ROOT/'continuation-reservation.json',dict(binding_commit=commit,already_attempted=len(attempted),
        scheduled_only_unattempted=len(remaining),automatic_retries=0,original_report_sha256=sha(ROOT/'native-report.json')))
    executor=load_script('unit35_continue_execution','research/reference_execution.py')
    validator=load_script('unit35_continue_validator','research/issue-31-quality/run_reference_probe.py')
    snapshots={};outcomes={};validated_bytes=0;lock=threading.Lock()
    for attempt in original['attempts']:
        index=attempt['index'];directory=ROOT/'candidates'/f'request-{index:04d}'
        result,record=checked_result(directory,requests[index],attempt,identity,validator)
        if result['status'] not in ('complete','output_contract_rejected','candidate_count_rejected'):
            raise ValueError('unit35_prior_failure_not_classified')
        outcomes[index]=dict(index=index,origin='first_attempt',**result)
        if record is not None:snapshots[record['stable_id']]=record
        if (directory/'output.jsonl').exists():validated_bytes+=(directory/'output.jsonl').stat().st_size
    def validate(directory,raw,identity):
        nonlocal validated_bytes
        with lock:
            validated_bytes+=(directory/'output.jsonl').stat().st_size
            if validated_bytes>bound['maximum_validated_output_bytes']:raise ValueError('unit35_native_output_bound')
        return validator.validate_result(directory,raw,identity)
    target=ROOT/'continuation-candidates';target.mkdir(exist_ok=False)
    start=time.monotonic();stop_reason=None
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0,len(remaining),2):
            seconds=continuation['total_timeout_seconds']-(time.monotonic()-start)
            if seconds<=0:stop_reason='continuation_deadline';break
            futures={pool.submit(executor.execute_request,target/f'request-{i:04d}',i,requests[i],identity,
                Path(plan['native']['executable']),Path(plan['native']['dictionary']),validate,min(30,seconds)):i
                for i in remaining[offset:offset+2]}
            for future in as_completed(futures):
                index=futures[future]
                try:
                    terminal,_=future.result()
                    result,record=checked_result(target/f'request-{index:04d}',requests[index],terminal,identity,validator)
                except Exception as error:
                    result=dict(status='unexpected_failure',error_type=type(error).__name__);record=None
                outcomes[index]=dict(index=index,origin='continuation',**result)
                if record is not None:snapshots[record['stable_id']]=record
                if result['status'] not in ('complete','output_contract_rejected','candidate_count_rejected'):
                    stop_reason='unexpected_request_failure'
            if offset%100==0 or stop_reason:
                print(json.dumps(dict(stage='source_unit_continuation',terminal=len(outcomes),total=len(requests))),flush=True)
            if stop_reason:break
    # Every original request gets exactly one observation, including not scheduled.
    ledger=[outcomes.get(index,dict(index=index,origin='not_scheduled',status='not_attempted')) for index in range(len(requests))]
    save(ROOT/'request-ledger-v2.json',dict(requests=ledger,binding_commit=commit,stop_reason=stop_reason))
    bound_inputs(continuation['original_binding_commit'])
    surfaces={key:record['candidate_snapshots']['training_top32']['candidates'] for key,record in snapshots.items()}
    stats=aggregate_units(rows,surfaces);counts=Counter(r['status'] for r in ledger)
    report=dict(kind='source_unit_native_diagnostic_v2',status='complete_with_explicit_rejections' if len(outcomes)==len(requests) and stop_reason is None else 'incomplete',
        binding_commit=commit,slots=100,unique_requests=len(requests),native_calls_first_attempt=len(attempted),
        native_calls_continuation=len(outcomes)-len(attempted),native_requests_retried=0,measured_requests=len(snapshots),
        outcomes=dict(counts),not_attempted=counts['not_attempted'],stop_reason=stop_reason,
        output_bytes_observed=validated_bytes,existing_segment_bound=MAX_CONVERTER_SEGMENTS,
        rejected_over_segment_bound=sum(r.get('segments_exceed_existing_bound',False) for r in ledger),
        first_execution_sha256=sha(ROOT/'native-execution.json'),first_report_sha256=sha(ROOT/'native-report.json'),
        request_ledger_sha256=sha(ROOT/'request-ledger-v2.json'),continuation_elapsed_seconds=round(time.monotonic()-start,3),
        **stats,independent_accuracy=None,gold_quality=None,confidence_interval=None,
        interval_reason='Exposed source diagnostic with unresolved labels, dependent owners and failed observations; no independent accuracy claim.',
        fits=0,models_run=0,gold_admitted=0,calibration_admitted=0,final_test_used=False,legacy_contract_changed=False)
    save(ROOT/'native-report-v2.json',report)
    print(json.dumps({k:report[k] for k in ('status','outcomes','not_attempted','native_calls_first_attempt','native_calls_continuation','measured_requests','by_stratum_view')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binding-commit',required=True)
    run(parser.parse_args().binding_commit)
