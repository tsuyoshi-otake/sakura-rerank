"""Publish only verified aggregate source-repair evidence."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from rebuild_common import HERE,ROOT,read,require,save,sha


def publish():
    preparation=read(ROOT/'preparation.json');native=read(ROOT/'native-report.json')
    proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json');plan=read(HERE/'plan-v1.json')
    require(proof['status']=='passed' and proof['preparation_sha256']==sha(ROOT/'preparation.json')
        and proof['native_report_sha256']==sha(ROOT/'native-report.json') and native['status']=='complete','publication_proof')
    require(tests==dict(tests=867,successful=True,failures=0,errors=0,skipped=0),'publication_tests')
    for stage in ('prepare','native','verify','tests'):require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','publication_terminal')
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'immutable_input_or_code')
    for name,digest in preparation['artifacts'].items():require(sha(ROOT/name)==digest,'prepared_artifact')
    require(native['measurements_sha256']==sha(ROOT/'measurements.json') and native['execution_sha256']==sha(ROOT/'native-execution.json'),'native_artifact')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/source_reading_rebuild.py'),Path('tests/test_source_reading_rebuild.py')]:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
            for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import');static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    completed=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(completed.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','original_integrity')
    models=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:require(sha(model['path'])==model['sha256'],'checkpoint_unchanged')
    result=dict(kind='original_reading_rebuild_report',version=1,status='verified_source_reconstruction_not_gold',issue=31,parent_issue=1,
        related_issues=[32,33,34,35],plan_sha256=sha(HERE/'plan-v1.json'),native_binding_sha256=sha(HERE/'native-binding-v1.json'),
        preparation=preparation,native=native,verification=proof,tests=tests,static_checks=static,
        original_integrity=integrity,old_checkpoints_unchanged=len(models),reference_runtime=plan['native'],
        interpretation=[
            'All335 exact original-reading contradictions remain in the denominator. New identities change only derived reading/request identity; original target, source prefix and component ancestry remain.',
            'Literal original-source presence in validated native candidates is not contextual Japanese correctness, intended IME-unit correctness or adopted model accuracy.',
            'Exact original annotation readings retain historical kana and author notation. No guessed modernization, surface normalization, candidate-contract relaxation or repair of580 uncertain annotations.',
            'Direct current/historical input matches are exposure evidence, not a complete independence proof. Preserve old component bridges and recompute full closure before any future fitting; new IDs do not create new evaluation data.'],
        scope=dict(owner='src/sakura_rerank/data/source_reading_rebuild.py',state='new immutable child pool, parent lineage and native receipts',
            expansion='Candidate re-execution and input exposure are necessary because changing a reading changes both request identity and model input equality.',
            future_reading='Use rebuild API/tests plus source gate and bound native contract; no need to reopen the earlier75000-row source audit for ordinary reconstruction.'),
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,gold_requirements=plan['gold_requirements'],
        new_fits=0,model_inferences=0,original_labels_changed=0,human_reviews=0,ai_linguistic_reviews=0,
        training_admission=False,gold_admission=False,threshold_selection=False,calibration=False,final_test=False,
        production_change=False,release_eligible=False)
    path=Path('reports/issue-31-reading-rebuild-v1.json');save(path,result)
    print(json.dumps(dict(status=result['status'],report_sha256=sha(path),tests=tests['tests'],census=native['census'],static_files=len(static))))


if __name__=='__main__':publish()
