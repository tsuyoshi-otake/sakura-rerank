"""Publish only verified aggregate lexical evidence and its limitations."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from lexical_common import HERE,ROOT,read,require,save,sha


def publish():
    plan=read(HERE/'plan-v1.json');analysis=read(ROOT/'analysis.json');proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    require(proof['status']=='passed' and proof['analysis_sha256']==sha(ROOT/'analysis.json') and analysis['status']=='complete','publication_proof')
    require(tests==dict(tests=911,successful=True,failures=0,errors=0,skipped=0),'publication_tests')
    for stage in ('analyze','verify','tests'):require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','publication_terminal')
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'immutable_input_or_code')
    for name,digest in analysis['artifacts'].items():require(sha(ROOT/name)==digest,'analysis_artifact')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/lexical_cover.py'),Path('tests/test_lexical_cover.py')]:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import');static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    previous=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(previous.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','original_integrity')
    models=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:require(sha(model['path'])==model['sha256'],'checkpoint_unchanged')
    report=dict(kind='exact_indexed_lexical_coverage_report',version=1,status='verified_lexical_diagnostic_not_gold',issue=31,parent_issue=1,
        related_issues=[32,33,34,35],plan_sha256=sha(HERE/'plan-v1.json'),analysis=analysis,verification=proof,tests=tests,static_checks=static,
        original_integrity=integrity,old_checkpoints_unchanged=len(models),dictionary=plan['dictionary'],current_sakura_input_head=plan['current_sakura_input_head'],
        interpretation=[
            'All335 parent controls and1005 source views remain. Indexed direct/concatenated cover is an exact-string property, not contextual Japanese or IME-intent correctness.',
            'The graph omits POS connectivity, costs, beam/search behavior and other native generators. A missing graph cover is absence from this index model, not a proof that the full converter cannot produce a target.',
            'Native-positive examples outside the simplified graph model remain explicit. Lexical units and their character offsets are not native segment counts or UTF-8 byte offsets.',
            'Literal kana copying is separate from exact dictionary-only composition. Neither mode modernizes historical readings, guesses unknown-Kanji pronunciations, normalizes surfaces or admits labels.',
            'Previously verified native observations are reused through committed report/private artifact hashes; no new converter/model call or independent evaluation occurred.'],
        scope=dict(owner='src/sakura_rerank/data/lexical_cover.py',state='new immutable1340-pair census and exact graph witnesses',
            expansion='Whole-surface lookup cannot separate missing entries from valid token composition. Full target/reading cover and a separate native-observation join are necessary.',
            future_reading='Use the lexical-cover API/contracts and bound source/measurement artifact contract; prior extraction/native orchestration internals are not required for another lexical diagnostic.'),
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,gold_requirements=plan['gold_requirements'],
        native_requests=0,model_inferences=0,new_fits=0,original_labels_changed=0,human_reviews=0,ai_linguistic_reviews=0,
        training_admission=False,gold_admission=False,threshold_selection=False,calibration=False,final_test=False,production_change=False,release_eligible=False)
    path=Path('reports/issue-31-lexical-coverage-v1.json');save(path,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(path),tests=tests['tests'],static_files=len(static),census=analysis['census'])))


if __name__=='__main__':publish()
