"""Publish verified aggregate extent evidence, never source texts or identities."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from extent_common import HERE,ROOT,read,require,save,sha


def publish():
    plan=read(HERE/'plan-v1.json');preparation=read(ROOT/'preparation.json');native=read(ROOT/'native-report.json')
    proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    require(proof['status']=='passed' and proof['preparation_sha256']==sha(ROOT/'preparation.json') and proof['native_report_sha256']==sha(ROOT/'native-report.json')
        and native['status']=='complete','publication_proof')
    require(tests==dict(tests=890,successful=True,failures=0,errors=0,skipped=0),'publication_tests')
    for stage in ('prepare','native','verify','tests'):require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','publication_terminal')
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'bound_artifact_changed')
    for name,digest in preparation['artifacts'].items():require(sha(ROOT/name)==digest,'prepared_artifact')
    require(native['execution_sha256']==sha(ROOT/'native-execution.json') and native['measurements_sha256']==sha(ROOT/'measurements.json'),'native_artifact')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/source_reading_units.py'),Path('tests/test_source_reading_units.py')]:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import');static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    previous=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(previous.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','original_integrity')
    models=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:require(sha(model['path'])==model['sha256'],'old_checkpoint_changed')
    report=dict(kind='original_source_extent_report',version=1,status='verified_changed_input_diagnostic_not_gold',issue=31,parent_issue=1,
        related_issues=[32,33,34,35],plan_sha256=sha(HERE/'plan-v1.json'),native_binding_sha256=sha(HERE/'native-binding-v1.json'),
        preparation=preparation,native=native,verification=proof,tests=tests,static_checks=static,original_integrity=integrity,old_checkpoints_unchanged=len(models),
        reference_runtime=plan['native'],policy=plan['policy'],
        interpretation=[
            'Every one of335 parents receives all three predefined source-only hypotheses. The prior305 Top32 misses are a conditional reporting group, never a selection filter for new source reconstruction.',
            'Expanded source surface and continuous reading are different converter inputs; extent-only presence is not same-input accuracy, a ranker rescue or evidence of intended IME boundaries.',
            'Original1-character readings remain outside the unchanged2..32 preparation reading bound even when permitted by the existing native diagnostic contract. Native truncation/rejection and preparation bounds remain explicit.',
            'Only exact original annotations and literal kana supply readings. No modernization, unknown-Kanji guess, annotation split, clipping, accepted-surface normalization or Gold admission.',
            'All variants inherit source/component and consumption history. Direct matches and new IDs do not prove complete exposure closure or independent evaluation eligibility.'],
        scope=dict(owner='src/sakura_rerank/data/source_reading_units.py',state='immutable source hypotheses, lineage and separately bound native outcomes',
            expansion='Changing an input extent changes target, reading, source prefix and numeric identity; paired candidate/exposure accounting is necessary to interpret the hypothesis.',
            future_reading='The extent API/tests, original-source gate and pinned native contract suffice for another fixed source-unit diagnostic; no need to reopen earlier full-corpus audits.'),
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,gold_requirements=plan['gold_requirements'],
        original_labels_changed=0,new_fits=0,model_inferences=0,human_reviews=0,ai_linguistic_reviews=0,training_admission=False,gold_admission=False,
        threshold_selection=False,calibration=False,final_test=False,production_change=False,release_eligible=False)
    path=Path('reports/issue-31-source-extents-v1.json');save(path,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(path),tests=tests['tests'],static_files=len(static),new_requests=native['new_requests'])))


if __name__=='__main__':publish()
