"""Bind original evaluation requests, reuse authenticated candidates, verify all tensors."""
import argparse
from collections import Counter
import io
import json
import os

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.corpus_v5 import _publish_directory_atomically
from sakura_rerank.data.growth_numeric import encode
from sakura_rerank.data.input_boundary import request_id
from experiment_common import ROOT,HERE,EXECUTION_PLAN,authenticate,boundary,preparation,read,rows,save,sha,write_rows,jsonl
from cohort import EXECUTION_COMMIT
from numeric_verifier import verify_saved

BINDING=HERE/'candidate-binding-v1.json'


def previous_snapshots(targets):
    prior=preparation.prior
    execution=read(prior.forward.ROOT/'execution.json')
    _,identity,_,_,_,requests=prior.forward.authenticate(execution['binding_commit'])
    snapshots=prior.candidate_verifier.snapshots(targets,identity,execution,requests)
    for row in targets:
        found=snapshots.get(row['candidate_request_id'])
        if found is not None and found['reading']!=row['reading']:
            raise ValueError('evaluation_previous_reading_join')
    return identity,snapshots


def prepare():
    authenticate(EXECUTION_COMMIT)
    cohort=read(ROOT/'cohort.json')
    if cohort['status']!='ready' or not cohort['full_reverse_replay']:
        raise ValueError('evaluation_ready_cohort_required')
    for artifact in cohort['artifacts'].values():
        if sha(ROOT/'cohort'/artifact['path'])!=artifact['sha256']:
            raise ValueError('evaluation_selection_changed')
    targets=[];requests={}
    for row in rows(ROOT/'cohort/selected.jsonl.gz'):
        key=request_id(row['reading'])
        targets.append(dict(row,candidate_request_id=key,component_id=row['source_component'],corpus='kwdlc'))
        requests[key]=dict(stable_id=key,reading=row['reading'])
    identity,known=previous_snapshots(targets)
    requested=[requests[k] for k in sorted(requests)]
    new=[row for row in requested if row['stable_id'] not in known]
    artifacts={name:write_rows(ROOT/(name+'.jsonl.gz'),values) for name,values in
        (('forward-targets',targets),('requests',requested),('new-requests',new))}
    paths=[HERE/'candidates.py',HERE/'numeric_verifier.py',HERE/'experiment_common.py',
           'research/reference_execution.py','src/sakura_rerank/data/growth_numeric.py',
           'research/issue-49-consumed-contrast/verify_audit.py']
    bound=dict(kind='annotation_evaluation_candidate_binding',cohort_sha256=sha(ROOT/'cohort.json'),
        execution_plan_sha256=sha(EXECUTION_PLAN),artifacts=artifacts,targets=len(targets),requests=len(requested),
        new_requests=len(new),reused_requests=len(requested)-len(new),known_snapshot_hashes=canonical_json_hash(known),
        identity_sha256=canonical_json_hash(identity),code={str(p):sha(p) for p in paths},
        execution=dict(concurrency=2,request_timeout_seconds=30,total_timeout_seconds=900),
        readiness='At least 500 fixed main rows; zero unexpected/unattempted requests. Rejected counts remain fallback rows. No contrast minimum.',
        model_fits=0,model_predictions=0,final_test_used=False,gold_certified=False)
    save(BINDING,bound);save(ROOT/'candidate-binding.json',bound)
    return {k:bound[k] for k in ('targets','requests','new_requests','reused_requests')}


def bound_inputs(commit):
    authenticate(EXECUTION_COMMIT)
    bound=json.loads(boundary.committed(BINDING,commit))
    if bound!=read(ROOT/'candidate-binding.json') or bound['cohort_sha256']!=sha(ROOT/'cohort.json'):
        raise ValueError('evaluation_candidate_binding_changed')
    for path,digest in bound['code'].items():
        if sha(path)!=digest:raise ValueError('evaluation_candidate_code_changed')
    for artifact in bound['artifacts'].values():
        if sha(ROOT/artifact['path'])!=artifact['sha256']:raise ValueError('evaluation_candidate_input_changed')
    targets=list(rows(ROOT/'forward-targets.jsonl.gz'))
    identity,known=previous_snapshots(targets)
    if (canonical_json_hash(identity)!=bound['identity_sha256']
            or canonical_json_hash(known)!=bound['known_snapshot_hashes']):
        raise ValueError('evaluation_native_identity_changed')
    return bound,targets,identity,known,list(rows(ROOT/'new-requests.jsonl.gz'))


def completed_snapshots(new,execution,identity):
    result={}
    if [a['index'] for a in execution['attempts']]!=list(range(len(execution['attempts']))):
        raise ValueError('evaluation_native_attempt_order')
    for attempt,request in zip(execution['attempts'],new):
        directory=ROOT/'candidates'/f"request-{attempt['index']:04d}"
        if sha(directory/'execution.json')!=attempt['execution_sha256']:
            raise ValueError('evaluation_native_execution_changed')
        if (directory/'input.jsonl').read_bytes()!=jsonl([request]) or read(directory/'identity.json')!=identity:
            raise ValueError('evaluation_native_input_changed')
        if attempt['status']=='complete':
            receipt=read(directory/'execution.json')
            if sha(directory/'output.jsonl')!=receipt['output_sha256']:
                raise ValueError('evaluation_native_output_changed')
            record=boundary.native.validate_result(directory,(directory/'input.jsonl').read_bytes(),identity)[0]
            result[record['stable_id']]=record
        elif attempt['status']=='candidate_count_rejected':
            receipt=read(directory/'execution.json')
            if (receipt['exit_code']!=2 or (directory/'output.jsonl').exists()
                    or sha(directory/'stderr.log')!=receipt['stderr_sha256']):
                raise ValueError('evaluation_rejected_receipt_changed')
    return result


def execute(commit):
    import numpy as np
    bound,targets,identity,known,new=bound_inputs(commit)
    executor=boundary.load_script('annotation_reference_execution','research/reference_execution.py')
    execution,_=executor.execute_requests(new,ROOT/'candidates',identity,boundary.BINARY,boundary.DICTIONARY,
        boundary.native.validate_result,concurrency=2,request_timeout=30,total_timeout=900,
        progress=lambda done,total:print(json.dumps(dict(stage='annotation_candidates',processed=done,total=total)),flush=True))
    execution.update(binding_commit=commit,binding_sha256=sha(BINDING))
    save(ROOT/'candidate-execution.json',execution)
    known.update(completed_snapshots(new,execution,identity))
    arrays,metadata=encode(targets,known)
    staging=ROOT/'evaluation-cache.partial';staging.mkdir(exist_ok=False)
    with (staging/'arrays.npz').open('xb') as stream:
        np.savez_compressed(stream,**arrays);stream.flush();os.fsync(stream.fileno())
    save(staging/'metadata.json',metadata)
    raw=(staging/'arrays.npz').read_bytes()
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved:
        verification=verify_saved(targets,known,{key:np.array(saved[key]) for key in saved.files})
    main=[m for r,m in zip(targets,metadata) if 'main' in r['roles']]
    groups={r['contrast_group'] for r in targets if 'contrast' in r['roles']}
    supported=sum(all(m['source_exact_presence']['6'] for r,m in zip(targets,metadata)
        if r['contrast_group']==g) for g in groups)
    ready=len(main)>=500 and execution['not_attempted']==0 and execution['stop_reason'] is None
    report=dict(kind='annotation_experiment_candidates',status='ready' if ready else 'insufficient_do_not_train',
        binding_commit=commit,targets=len(targets),main_rows=len(main),contrast_groups=len(groups),supported_groups=supported,
        source_exact_counts={name:{str(k):sum(m['source_exact_presence'][str(k)] for m in part) for k in (1,5,6,10,32)}
            for name,part in (('main',main),('all',metadata))},
        failed_targets=sum(m['acquisition_status']!='complete' for m in metadata),
        candidate_surface_truncations=sum(m['candidate_surfaces_truncated'] for m in metadata),
        new_requests=len(new),reused_requests=bound['reused_requests'],
        outcomes=dict(Counter(a['status'] for a in execution['attempts'])),not_attempted=execution['not_attempted'],
        execution_sha256=sha(ROOT/'candidate-execution.json'),numeric_verification=verification,
        arrays_sha256=sha(staging/'arrays.npz'),metadata_sha256=sha(staging/'metadata.json'),
        model_fits=0,model_predictions=0,final_test_used=False,gold_certified=False)
    save(staging/'manifest.json',report)
    _publish_directory_atomically(staging,ROOT/'evaluation-cache',immutable_message='evaluation_cache_exists')
    save(ROOT/'candidate-report.json',report)
    return {k:report[k] for k in ('status','targets','main_rows','contrast_groups','supported_groups','failed_targets','outcomes','numeric_verification')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','execute'));parser.add_argument('--binding-commit')
    args=parser.parse_args()
    print(json.dumps(prepare() if args.stage=='prepare' else execute(args.binding_commit)))
