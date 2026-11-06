"""Frozen source-only comparison scope and authenticated prior request reuse."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.source_reading_units import POLICY

sys.path.insert(0,'research/issue-31-reading-rebuild')
try:
    import rebuild_common as repair
    import prepare_rebuild as original_preparation
    import native_rebuild as original_native
    import rebuild_metrics as original_metrics
finally:sys.path.pop(0)

HERE=Path('research/issue-31-source-extents')
_attempt=os.environ.get('SAKURA_EXTENT_ATTEMPT','attempt-01')
if not re.fullmatch('attempt-0[1-8]',_attempt):raise ValueError('source_extent_attempt_bound')
ROOT=Path('data/generated/issue-31-source-extents-v1')/_attempt
PRIOR=Path('data/generated/issue-31-reading-rebuild-v1/attempt-01')
reading=repair.previous
read,sha,committed,runtime=repair.read,repair.sha,repair.committed,repair.runtime
parents,helpers=original_preparation.parents,original_native.helpers
measure,summary=original_metrics.measure,original_metrics.summary


def require(condition,code):
    if not condition:raise ValueError('source_extent_'+code)


def save(path,value):
    raw=canonical_json_bytes(value)+b'\n';require(len(raw)<=256*1024*1024,'artifact_byte_bound')
    with Path(path).open('xb') as stream:stream.write(raw)


def freeze():
    previous=read(repair.HERE/'plan-v1.json');inputs=dict(previous['inputs']);code=dict(previous['code'])
    paths=[repair.HERE/'plan-v1.json',repair.HERE/'native-binding-v1.json',Path('reports/issue-31-reading-rebuild-v1.json')]
    paths.extend(PRIOR/name for name in ('preparation.json','rebuilds.json','requests.json','raw-overlap.json','native-execution.json','native-report.json','measurements.json','verification.json'))
    inputs.update({p.as_posix():sha(p) for p in paths})
    scripts=sorted(HERE.glob('*.py'))+[Path(p) for p in ('src/sakura_rerank/data/source_reading_units.py','tests/test_source_reading_units.py',
        'src/sakura_rerank/data/tatoeba_input_units.py','src/sakura_rerank/data/tatoeba_source.py','src/sakura_rerank/data/input_boundary.py')]
    code.update({p.as_posix():sha(p) for p in scripts})
    native=dict(previous['native']);native['maximum_unique_requests']=1005
    native['current_sakura_input_head']=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'dirty_sakura_input')
    plan=dict(kind='original_source_extent_diagnostic',version=1,issue=31,parent_issue=1,prior_commit='6dcc281da684ad2a92f5bf856cb98660af441fcd',
        inputs=inputs,code=code,parents=335,view_slots=1005,policy=POLICY,native=native,
        selection='All335 original-reading conflicts, including17 held by preparation reading length. Never select only candidate misses for new source reconstruction.',
        views=dict(original_ruby='Same exact original annotation extent.',literal_suffix='Anchor ruby plus maximal immediately following unannotated literal kana; never cross another annotation.',
            supported_run='Maximal adjacent sequence of complete phonetic ruby spans and literal kana containing the anchor. Unknown readings, unsupported annotation and punctuation/space stop the run; boundaries are not certified words.'),
        native_permission='Existing1..128 reading/1..256 target diagnostic bounds, unchanged18-segment validation. Separately commit exact requests before execution, reuse all264 bound prior snapshots, and attempt each new reading once.',
        training_policy='Original2..32 reading,1..32 target,8..64 prefix conditions remain unchanged and separately counted. No variant, even one within all bounds, is admitted to training or Gold.',
        comparison='All335 parent views plus the fixed305 previously measured Top32 misses. Report exclusive measured/unmeasured pair states; expanded targets/readings are different inputs, not same-input accuracy or ranker rescues.',
        source_policy='No inferred readings, modernization, NFKC, partial annotation, clipping or filling unknown Kanji. Preserve full source/component ancestry; right source text becomes only an explicit expanded target, never a model-context feature.',
        exposure='Compare derived raw and numeric inputs with the bound current75000 and14304 historical actual inputs. Preserve old component bridges; direct matches do not certify full closure or independence.',
        cost='At most1005 view requests before reuse,2 native workers,30seconds/request,900seconds total; two source passes, full tests. No downloads, builds, GPU or model calls.',
        new_fits=0,model_inferences=0,original_labels_changed=0,gold_admission=False,training_admission=False,
        calibration=False,final_test=False,threshold_selection=False,production_change=False,worktrees_created=0,safety_limit=.0025,
        gold_requirements=previous['gold_requirements'])
    runtime(plan);save(HERE/'plan-v1.json',plan)
    return dict(status='plan_frozen',inputs=len(inputs),code_files=len(code),parents=335,view_slots=1005)


def authenticate(commit):
    plan=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'bound_artifact_changed')
    for path in plan['code']:committed(path,commit)
    registry=read(reading.previous.REGISTRY);selection={r['work_id']:r for r in read(reading.previous.GROWTH/'aozora-selection.json')}
    require(len(registry)==len({r['work_id'] for r in registry})==546 and all(selection[r['work_id']]['partition']=='train' for r in registry),'train_registry')
    allowed=list(plan['inputs'])
    for row in registry:
        require(re.fullmatch('[0-9]+',row['work_id']),'source_path')
        allowed.extend(reading.previous.GROWTH/'aozora-download'/(row['work_id']+suffix) for suffix in ('.json','.zip'))
    for i in range(264):allowed.extend(PRIOR/'candidates'/f'request-{i:04d}'/name for name in ('input.jsonl','identity.json','output.jsonl','native-report.json','execution.json','stdout.log','stderr.log'))
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:from experiment_fit_contract import TrainingReadGuard
    finally:sys.path.pop(0)
    guard=TrainingReadGuard(Path.cwd(),allowed,ROOT);sys.addaudithook(guard)
    return plan,registry,selection,guard


def prior_snapshots(identity):
    requests=read(PRIOR/'requests.json')['requests'];execution=read(PRIOR/'native-execution.json');report=read(PRIOR/'native-report.json')
    require(report['status']=='complete' and report['execution_sha256']==sha(PRIOR/'native-execution.json')
        and len(requests)==264 and [a['index'] for a in execution['attempts']]==list(range(264)),'prior_native_binding')
    _,validator,check=helpers();snapshots={}
    for attempt in execution['attempts']:
        index=attempt['index'];directory=PRIOR/'candidates'/f'request-{index:04d}';receipt=read(directory/'execution.json')
        require(receipt['index']==index and receipt['stable_id']==requests[index]['stable_id'] and receipt['status']==attempt['terminal']['status']=='complete'
            and read(directory/'identity.json')==identity,'prior_native_identity')
        outcome,record=check(directory,requests[index],attempt['terminal'],identity,validator)
        require(outcome==attempt['outcome']==dict(status='complete') and record is not None,'prior_native_output')
        snapshots[requests[index]['stable_id']]=record
    require(len(snapshots)==264,'prior_request_uniqueness')
    return snapshots
