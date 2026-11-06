"""Separate source/native bindings for deterministic original-reading repairs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.reference_probe import authenticate_identity

sys.path.insert(0,'research/issue-31-reading-consistency')
try:import reading_common as previous
finally:sys.path.pop(0)

HERE=Path('research/issue-31-reading-rebuild')
_attempt=os.environ.get('SAKURA_REBUILD_ATTEMPT','attempt-01')
if not re.fullmatch('attempt-0[1-8]',_attempt):raise ValueError('reading_rebuild_attempt_bound')
ROOT=Path('data/generated/issue-31-reading-rebuild-v1')/_attempt
PARENT=Path('data/generated/issue-31-reading-consistency-v1/attempt-01')
IDENTITY=Path('manifests/reference-probe-identity-v1.json')
HISTORICAL=Path('data/generated/issue-34-selector-lineage-v1/historical-numeric.json')
CPU=Path('data/generated/issue-34-cpu-proposals-v1')


def require(condition,code):
    if not condition:raise ValueError('reading_rebuild_'+code)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def committed(path,commit):return previous.previous.committed(path,commit)


def load_script(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def runtime(plan):
    native=plan['native']
    require(subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()==native['current_sakura_input_head']
            and not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'current_sakura_input_changed')
    return authenticate_identity(IDENTITY,native['runtime_identity_sha256'],Path(native['executable']),Path(native['dictionary']))


def freeze():
    old=read(previous.HERE/'plan-v1.json');inputs=dict(old['inputs']);code=dict(old['code'])
    native=dict(read('research/issue-35-source-consumption/plan-v1.json')['native'])
    native.update(maximum_unique_requests=335,maximum_output_bytes=128*1024*1024,
                  current_sakura_input_head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip())
    require(not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'dirty_sakura_input')
    for path in [previous.HERE/'plan-v1.json',Path('reports/issue-31-reading-consistency-v1.json'),
                 PARENT/'preparation.json',PARENT/'verification.json',PARENT/'pool/manifest.json',
                 PARENT/'pool/decisions.jsonl.gz',PARENT/'pool/prepared-rows.jsonl.gz',
                 HISTORICAL,CPU/'source-metadata.json',CPU/'empty-metadata.json',IDENTITY,Path(native['executable']),Path(native['dictionary'])]:
        inputs[path.as_posix()]=sha(path)
    paths=sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/source_reading_rebuild.py'),Path('tests/test_source_reading_rebuild.py')]
    paths.extend(Path(p) for p in ('research/reference_execution.py','research/issue-31-quality/run_reference_probe.py',
        'research/issue-35-source-units/resume_native.py','research/issue-35-source-units/unit_native.py','research/issue-35-source-units/unit35_common.py',
        'src/sakura_rerank/data/reference_probe.py','src/sakura_rerank/data/research_exporter.py','src/sakura_rerank/data/contrast_capacity.py',
        'src/sakura_rerank/data/consumed_numeric.py','src/sakura_rerank/source_model_inputs.py','src/sakura_rerank/research_tiny.py',
        'src/sakura_rerank/research_tiny_r2.py'))
    code.update({p.as_posix():sha(p) for p in paths})
    plan=dict(kind='original_annotation_reading_rebuild',version=1,issue=31,parent_issue=1,prior_commit='3b3be1e1d015293bdb83fd135d886e28bac25759',
        inputs=inputs,code=code,parent_population=75000,selected_parent_conflicts=335,other_uncertain_cases_not_rebuilt=580,
        selection='Every pending_reading_conflict from the bound parent pool, matched to exact original source evidence. No content- or model-based sampling.',
        repair='Copy the exact full original ruby reading using only fullwidth katakana-to-hiragana. Preserve surface, left prefix and component; assign new deterministic identity and parent lineage. Bounds2..32 unchanged.',
        parent_policy=dict(allow_dictionary_only=True),child_policy=dict(allow_dictionary_only=False),
        source_order='Sort repairs by parent original-row SHA after bounded source recovery. All335 parent outcomes remain, including unpreparable readings.',
        native=native,native_permission='Commit exact rebuilt request binding after source preparation and before any native call. One attempt per deduplicated reading; no retries or relaxed18-segment validator.',
        evidence='Top1/5/6/10/32 literal source presence and existing candidate-eligibility contract. Source reconstruction only, not independent accuracy.',
        exposure='Record raw duplicates within the75000 consumed rows and direct source/empty numeric matches to current inputs and14304 actual historical train/dev inputs. New identities confer no independence; full closure before any future fit remains required.',
        estimated_cost='At most335 unique native requests, concurrency2,30s/request and900s/run; two bounded source passes and complete tests. No downloads/builds/GPU fitting.',
        new_fits=0,model_inferences=0,original_labels_changed=0,training_admission=False,gold_admission=False,threshold_selection=False,
        calibration=False,final_test=False,production_edits=False,worktrees_created=0,safety_limit=0.0025,
        gold_requirements=dict(point_estimate=0.995,wilson95_lower=0.99,final_valid_minimum=3000))
    runtime(plan);save(HERE/'plan-v1.json',plan)
    return dict(status='plan_frozen',inputs=len(inputs),code_files=len(code),current_sakura_input_head=native['current_sakura_input_head'])


def authenticate(commit):
    plan=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'bound_artifact_changed')
    for path in plan['code']:committed(path,commit)
    registry=read(previous.previous.REGISTRY)
    selection={r['work_id']:r for r in read(previous.previous.GROWTH/'aozora-selection.json')}
    require(len(registry)==len({r['work_id'] for r in registry})==546 and all(selection[r['work_id']]['partition']=='train' for r in registry),'source_registry')
    allowed=list(plan['inputs'])
    for entry in registry:
        require(re.fullmatch('[0-9]+',entry['work_id']),'source_path')
        allowed.extend(previous.previous.GROWTH/'aozora-download'/(entry['work_id']+suffix) for suffix in ('.json','.zip'))
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:from experiment_fit_contract import TrainingReadGuard
    finally:sys.path.pop(0)
    guard=TrainingReadGuard(Path.cwd(),allowed,ROOT);sys.addaudithook(guard)
    return plan,registry,selection,guard
