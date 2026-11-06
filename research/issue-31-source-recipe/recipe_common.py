"""Authenticate only consumed training evidence for source recipe preparation."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.consumed_numeric import verify_chain
from sakura_rerank.data.source_reading_gate import load_prepared

sys.path.insert(0, 'research/issue-33-annotation-experiment')
try:
    import experiment_fit_contract as fit
finally:
    sys.path.pop(0)

HERE = Path('research/issue-31-source-recipe')
PLAN = HERE / 'plan-v2.json'
attempt = os.environ.get('SAKURA_RECIPE_ATTEMPT', 'attempt-01')
if not re.fullmatch('attempt-0[1-8]', attempt):
    raise ValueError('recipe_run_attempt_bound')
ROOT = Path('data/generated/issue-31-source-recipe-v1') / attempt
BASE = Path('data/generated/issue-33-annotation-comparison-v1/attempt-02')
COHORT = BASE / 'scope-v1/cohorts/rows.jsonl.gz'
CACHE = BASE / 'numeric-r2/cache'
NUMERIC = BASE / 'numeric-r2/report.json'
POOL = Path('data/generated/issue-31-reading-consistency-v1/attempt-01/pool')
SOURCE_REPORT = Path('reports/issue-31-reading-consistency-v1.json')
OLD_FIT = Path('research/issue-33-annotation-experiment/fit-binding-v1.json')


def require(value, code):
    if not value: raise ValueError('recipe_run_' + code)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    raw = canonical_json_bytes(value) + b'\n'
    require(len(raw) <= 128 * 1024 * 1024, 'output_bound')
    with Path(path).open('xb') as stream: stream.write(raw)


def committed(path, commit):
    require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit), 'commit_required')
    raw = subprocess.check_output(['git', 'show', commit + ':' + Path(path).as_posix()], timeout=30)
    require(raw == Path(path).read_bytes(), 'committed_bytes_changed')
    return raw


def freeze():
    import numpy as np
    paths = [COHORT, NUMERIC, SOURCE_REPORT, OLD_FIT]
    paths += [POOL / name for name in ('manifest.json', 'decisions.jsonl.gz', 'prepared-rows.jsonl.gz')]
    paths += [CACHE / name for name in ('manifest.json', 'row-receipts.jsonl', 'arrays.npz', 'cohort-indices.json')]
    failed_terminal = Path('data/generated/issue-31-source-recipe-v1/attempt-01/prepare-terminal.json')
    paths += [HERE/'plan-v1.json', failed_terminal]
    diagnosis = read('.codex/goal-loop/issue-31-source-recipe/origin-diagnosis.json')
    require(diagnosis['status'] == 'root_cause_verified' and diagnosis['rows'] == 75000
            and diagnosis['counts']['producer_contract_mapping_mismatch'] == 0, 'origin_mapping_diagnosis')
    source = read(SOURCE_REPORT)
    require(source['verification']['status'] == 'passed'
            and source['verification']['pool_manifest_sha256'] == sha(POOL/'manifest.json'), 'source_proof')
    numeric = read(NUMERIC)
    require(numeric['status'] == 'passed' and numeric['cache_manifest_sha256'] == sha(CACHE/'manifest.json'), 'numeric_proof')
    code = set(HERE.glob('*.py')) | {Path('src/sakura_rerank/data/source_research_recipe.py'), Path('tests/test_source_research_recipe.py')}
    workspace = Path.cwd().resolve()
    for module in list(sys.modules.values()):
        value = getattr(module, '__file__', None)
        if value:
            path = Path(value).resolve()
            if path.is_relative_to(workspace) and path.suffix == '.py':
                code.add(path.relative_to(workspace))
    head = subprocess.check_output(['git', '-C', '../sakura-input', 'rev-parse', 'HEAD'], text=True, timeout=30).strip()
    require(not subprocess.check_output(['git', '-C', '../sakura-input', 'status', '--porcelain'], timeout=30), 'dirty_sakura_input')
    plan = dict(kind='source_screened_research_recipe_plan', version=2, issue=31, parent_issue=1,
        created_at_utc=datetime.now(timezone.utc).isoformat(), parent_commit='ac526495f507d7708e45db385d9b7e0b7816e33e',
        inputs={p.as_posix(): sha(p) for p in paths}, code={p.as_posix(): sha(p) for p in sorted(code)},
        population_rows=75000, original_rows_per_arm=50000, allow_dictionary_only=True,
        preceding_failed_attempt=dict(attempt='attempt-01', commit='62de972858d53dd61478eb5f710a2614bec440ce',
            plan_sha256=sha(HERE/'plan-v1.json'), terminal_sha256=sha(failed_terminal),
            cause='Distinct documented origin enums were compared literally. All75000 original-row hashes and flags agree; the25000 annotation names require the exact original_ruby_annotation to original_ruby mapping.',
            trusted_recipe_published=False, policy_population_and_thresholds_unchanged=True),
        selection='Keep unchanged source-annotation matches and explicitly weak dictionary-only rows. Exclude every contradictory/uncertain source decision; do not repair or resample. Join by complete source input hash, preserving numeric order, original components and all excluded history.',
        metrics=['all original/selected/excluded rows by arm, source tier and reason', 'baseline-source-match counts before/after/excluded, descriptive training statistics only', 'full identity, receipt and numeric tensor joins'],
        candidate_scope='The existing consumed cache was already selected for literal Top6 labels. It cannot estimate unfiltered source candidate coverage.',
        evaluation_condition='No unused KWDLC public-train reservation remains. A fresh isolated research reservation and separately committed fit binding are required; this artifact grants neither.',
        expected_effect='Enforce source evidence at later fit-binding preparation and quantify which old arms actually change; no accuracy benefit assumed.',
        expected_cost='Two complete 75000-row source/cache joins and tensor checks, full tests; no downloads, native/model calls or fitting.',
        limits=dict(rows=100000, decoded_cohort_bytes=134217728, line_bytes=262144, output_bytes=134217728, stage_seconds=1800, concurrency=1, retries=0),
        current_sakura_input_head=head, current_sakura_input_clean=True, python=sys.version.split()[0], numpy=np.__version__,
        source_license_scope='Unchanged prior pinned source manifests; no new acquisition or raw-text redistribution.',
        new_fits=0, model_inferences=0, native_requests=0, original_labels_changed=0, training_admission=False,
        gold_admission=False, threshold_selection=False, calibration=False, final_test=False, production_change=False,
        safety_limit=.0025, gold_requirements=source['gold_requirements'])
    save(PLAN, plan)
    return dict(status='frozen', inputs=len(paths), code_files=len(code), rows=75000)


def inputs(commit):
    plan = json.loads(committed(PLAN, commit))
    guard = fit.TrainingReadGuard(Path.cwd(), plan['inputs'], ROOT)
    sys.addaudithook(guard)
    for path, digest in {**plan['inputs'], **plan['code']}.items(): require(sha(path) == digest, 'artifact_changed')
    for path in plan['code']: committed(path, commit)
    source = read(SOURCE_REPORT)
    require(source['verification']['status'] == 'passed'
            and source['verification']['pool_manifest_sha256'] == sha(POOL/'manifest.json'), 'source_proof')
    pool = load_prepared(POOL, sha(POOL/'manifest.json'), purpose='numeric_verification')
    require(pool['manifest'] == source['pool_manifest'], 'source_manifest')
    require(fit.TRAIN_CACHE.resolve() == CACHE.resolve(), 'numeric_reader_path')
    arrays, indices, cache = fit.load_training(read(OLD_FIT))
    proof = read(NUMERIC)
    require(proof['status'] == 'passed' and proof['cache_manifest_sha256'] == sha(CACHE/'manifest.json')
            and proof['row_chain_head'] == cache['row_chain_head'], 'numeric_proof')
    receipts = verify_chain((CACHE/'row-receipts.jsonl').read_bytes(), 75000, cache['row_chain_head'])
    cohort, decoded = [], 0
    with gzip.open(COHORT, 'rb') as stream:
        while True:
            line = stream.readline(262145)
            if not line: break
            decoded += len(line)
            require(len(cohort) < 75000 and len(line) <= 262144 and line.endswith(b'\n') and decoded <= 134217728, 'cohort_bound')
            cohort.append(json.loads(line))
    require(len(cohort) == 75000 and guard.blocked == 0, 'cohort_count_or_forbidden_read')
    return plan, guard, pool, cohort, receipts, arrays, {k: v.tolist() for k, v in indices.items()}, cache


if __name__ == '__main__':
    print(json.dumps(freeze()))
