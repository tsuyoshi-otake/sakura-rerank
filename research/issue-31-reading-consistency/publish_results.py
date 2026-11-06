"""Publish verified behavior and aggregate preparation results only."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from reading_common import HERE,ROOT,read,require,save,sha


def publish():
    preparation=read(ROOT/'preparation.json');proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    require(proof['status']=='passed' and proof['preparation_sha256']==sha(ROOT/'preparation.json')
            and proof['pool_manifest_sha256']==sha(ROOT/'pool/manifest.json'),'publication_proof')
    require(tests==dict(tests=849,successful=True,failures=0,errors=0,skipped=0),'publication_tests')
    for stage in ('prepare','verify','tests'):require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','publication_terminal')
    plan=read(HERE/'plan-v1.json')
    require(preparation['plan_sha256']==sha(HERE/'plan-v1.json'),'publication_plan')
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'immutable_input_or_code')
    manifest=read(ROOT/'pool/manifest.json')
    for name,value in manifest['artifacts'].items():require(sha(ROOT/'pool'/name)==value['sha256'],'pool_artifact')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/source_reading_gate.py'),Path('tests/test_source_reading_gate.py')]:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
                for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import')
        static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    old=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(old.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','legacy_integrity')
    models=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:require(sha(model['path'])==model['sha256'],'model_unchanged')
    report=dict(kind='source_reading_consistency_implementation_report',status='verified_preparation_guard_no_training_admission',
        issue=31,parent_issue=1,related_issues=[32,33,34,35],plan_sha256=sha(HERE/'plan-v1.json'),execution_commit=preparation['code_commit'],
        preparation=preparation,verification=proof,pool_manifest=manifest,tests=tests,static_checks=static,
        original_integrity=integrity,old_checkpoints_unchanged=len(models),
        behavior_changes=[
            'New preparation recomputes original annotation evidence from authenticated exact source extents before writing each row; no caller-provided classification is trusted.',
            'All335 known source-reading conflicts and580 uncertain annotation cases are pending and cannot reach the authenticated candidate/numeric consumer.',
            'Missing annotation is pending by default. This explicitly bound compatibility run preserves48518 dictionary-only weak examples without promoting them;25567 examples agree with original annotation.',
            'The complete75000-row decision chain remains. Prepared payload contains74085 original inputs unchanged; pending rows remain consumed history and are not independent evaluation candidates.',
            'Staging is validated with the same strict consumer before a new directory is published. Corruption, row insertion, admission-flag escalation, unsupported purpose, incomplete inputs and destination overwrite fail closed.'],
        scope_notes=dict(original_extractors_unchanged=True,legacy_experiments_reproducible=True,new_preparation_only=True,
            scope_expansion='A detection-only helper would permit downstream bypass; transactional publication and authenticated consumer were required to enforce the boundary.',
            changed_behavior_owner='src/sakura_rerank/data/source_reading_gate.py',
            state_owner='new immutable pool manifest and complete hash-chained decisions',
            future_reading='Use the gate API/tests and immutable source binding; original parser internals and prior diagnostic calculations need not be re-read for normal consumers.'),
        remaining_work=[
            'Rebuild separately identified source-reading contradictions from exact original full annotations under new identities, preserving old parents and complete history. Do not guess missing readings or automatically fix the580 uncertain cases.',
            'A new research fit requires a separate bound recipe and fresh evaluation source; the915-row change alters source composition and is not a fair accuracy comparison by itself.',
            'Independent Gold quality, calibration, one-use final Test and production Gates A/B remain unsatisfied; these source checks cannot supply human or independent linguistic certification.'],
        expected_effect='Known contradictory/uncertain source readings are blocked in new preparation. No adopted accuracy lift is measured.',
        measured_cost_seconds=dict(preparation=preparation['elapsed_seconds'],verification=proof['elapsed_seconds']),
        adopted_accuracy_record=0.9072,accuracy_improvement_demonstrated=False,safety_limit=0.0025,
        gold_requirements=plan['gold_requirements'],new_fits=0,model_inferences=0,native_requests=0,original_labels_changed=0,
        training_admission=False,gold_admission=False,threshold_selection=False,calibration=False,final_test=False,production_change=False,release_eligible=False)
    path=Path('reports/issue-31-reading-consistency-v1.json');save(path,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(path),tests=849,pending_rows=915,old_conflicts_held=335,static_files=len(static))))


if __name__=='__main__':publish()
