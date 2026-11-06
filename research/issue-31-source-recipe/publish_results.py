"""Publish aggregate source recipe evidence without admitting a fit or Gold."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from recipe_common import HERE, ROOT, read, require, save, sha


def publish():
    plan = read(HERE/'plan-v1.json'); prep = read(ROOT/'preparation.json'); proof = read(ROOT/'verification.json')
    tests = read(ROOT/'full-tests.json'); targeted = read(ROOT/'targeted-tests.json')
    require(proof['status'] == 'passed' and proof['preparation_sha256'] == sha(ROOT/'preparation.json')
            and prep['recipe_sha256'] == proof['recipe_sha256'] == sha(ROOT/'recipe.json'), 'publication_proof')
    require(tests['successful'] and tests['tests'] == tests['expected'] == 911 + targeted['tests']
            and not (tests['failures'] or tests['errors'] or tests['skipped']) and targeted['successful'], 'publication_tests')
    for stage in ('targeted', 'prepare', 'verify', 'tests'): require(read(ROOT/(stage+'-terminal.json'))['status'] == 'complete', 'stage_terminal')
    for path, digest in {**plan['inputs'], **plan['code']}.items(): require(sha(path) == digest, 'bound_bytes_changed')
    static = []
    for path in sorted(HERE.glob('*.py')) + [Path('src/sakura_rerank/data/source_research_recipe.py'), Path('tests/test_source_research_recipe.py')]:
        tree = ast.parse(path.read_bytes()); compile(tree, str(path), 'exec'); names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        unused = [a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused, 'unused_import'); static.append(dict(path=path.as_posix(), sha256=sha(path), syntax_valid=True, unused_imports=[]))
    checked = subprocess.run([sys.executable, '-B', 'research/issue-33-data-growth/verify_integrity.py'], capture_output=True, text=True, check=True, timeout=120)
    integrity = json.loads(checked.stdout.strip().splitlines()[-1]); require(integrity['status'] == 'passed', 'original_integrity')
    models = read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models: require(sha(model['path']) == model['sha256'], 'old_checkpoint_changed')
    report = dict(kind='source_screened_research_recipe_report', version=1, issue=31, parent_issue=1, related_issues=[32,33,34,35],
        status='verified_recipe_preparation_not_fit_or_gold', plan_sha256=sha(HERE/'plan-v1.json'), preparation=prep, verification=proof,
        tests=tests, targeted_tests=targeted, static_checks=static, original_integrity=integrity, old_checkpoints_unchanged=len(models),
        current_sakura_input_head=plan['current_sakura_input_head'],
        interpretation=['Source tier is independent of the old extraction arm. Original annotation agreement remains weak source reconstruction, not Japanese or IME-intent certification.',
            'Only old cache indices are selected. All original identities, numeric hashes, components and excluded history remain; no new independent cohort or split is inferred.',
            'The cache is already selected for literal Top6 labels. Source Top1 counts describe training composition, not measured model accuracy or unfiltered candidate coverage.',
            'A fresh isolated research evaluation reservation and separately committed fit binding remain necessary. The previous KWDLC public-train reservation is exhausted.'],
        expected_effect=plan['expected_effect'], scope=dict(owner='src/sakura_rerank/data/source_research_recipe.py', state='immutable complete row decisions and unchanged cache-index selections',
            expansion='Source preparation and numeric cache have different orders. Their complete identity/provenance/tensor bindings must be joined before selection.',
            future_reading='Use the bound recipe reader and frozen index/census contract; original source parsing and native candidate generation need not be reopened for the same cache.'),
        adopted_accuracy_record=.9072, accuracy_improvement_demonstrated=False, safety_limit=.0025, gold_requirements=plan['gold_requirements'],
        new_fits=0, model_inferences=0, native_requests=0, original_labels_changed=0, human_reviews=0, ai_linguistic_reviews=0,
        training_admission=False, gold_admission=False, threshold_selection=False, calibration=False, final_test=False, production_change=False, release_eligible=False)
    path = Path('reports/issue-31-source-recipe-v1.json'); save(path, report)
    print(json.dumps(dict(status=report['status'], report_sha256=sha(path), summary=prep['summary'], baseline_source_counts=prep['baseline_source_counts'], tests=tests['tests'], static_files=len(static))))


if __name__ == '__main__':
    publish()
