"""Immutable scope and process/data boundaries for the training-only diagnosis."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes

HERE = Path('research/issue-31-conflict-source')
_attempt = os.environ.get('SAKURA_CONFLICT_ATTEMPT', 'attempt-01')
if not re.fullmatch('attempt-0[1-8]', _attempt):
    raise ValueError('conflict_attempt_bound')
ROOT = Path('data/generated/issue-31-conflict-source-v1')/_attempt
BASE = Path('data/generated/issue-33-annotation-comparison-v1/attempt-02')
CACHE = BASE/'numeric-r2/cache'
CPU = Path('data/generated/issue-34-cpu-proposals-v1')
ANNOTATION = Path('data/generated/issue-49-annotation-first-v1/prepared/targets.jsonl.gz')
CONSUMPTION = Path('data/generated/issue-32-consumed-source-v1/consumption-evidence.jsonl.gz')
REGISTRY = Path('data/generated/issue-48-contrast-data-v1/ruby-v1/source-receipts.json')
GROWTH = Path('data/generated/issue-33-data-growth-v1')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n')


def require(condition, code):
    if not condition:
        raise ValueError('conflict_'+code)


def rows(path, maximum):
    with gzip.open(path, 'rb') as stream:
        count = 0
        for line in stream:
            count += 1
            require(count <= maximum and len(line) <= 262144, 'source_row_bound')
            yield json.loads(line)


def committed(path, commit):
    require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit), 'commit_required')
    data = subprocess.check_output(['git', 'show', commit+':'+Path(path).as_posix()], timeout=30)
    require(data == Path(path).read_bytes(), 'committed_bytes_changed')
    return data


def authenticate(commit):
    plan = json.loads(committed(HERE/'plan-v1.json', commit))
    for path, digest in {**plan['inputs'], **plan['code']}.items():
        require(sha(path) == digest, 'bound_file_changed')
    for path in plan['code']:
        committed(path, commit)
    registry = read(REGISTRY)
    selection = {r['work_id']: r for r in read(GROWTH/'aozora-selection.json')}
    require(len(registry) == len({r['work_id'] for r in registry}) == 546, 'source_registry_count')
    require(all(selection[r['work_id']]['partition'] == 'train' for r in registry), 'source_partition')
    allowed = list(plan['inputs'])
    for record in registry:
        require(re.fullmatch('[0-9]+', record['work_id']), 'work_path')
        allowed.extend(GROWTH/'aozora-download'/(record['work_id']+suffix) for suffix in ('.json', '.zip'))
    sys.path.insert(0, 'research/issue-33-annotation-experiment')
    try:
        from experiment_fit_contract import TrainingReadGuard
    finally:
        sys.path.pop(0)
    guard = TrainingReadGuard(Path.cwd(), allowed, ROOT)
    sys.addaudithook(guard)
    return plan, registry, selection, guard


def freeze():
    from conflict_metrics import CONTEXT_LENGTHS, TRANSFORMS
    inputs = [BASE/'scope-v1/cohorts/rows.jsonl.gz', BASE/'scope-v1/cohorts/snapshots.jsonl.gz',
              BASE/'source/row-origins.jsonl.gz', BASE/'source/wikipedia-paragraphs.jsonl.gz',
              BASE/'source-report.json', ANNOTATION, CONSUMPTION, REGISTRY, GROWTH/'aozora-selection.json',
              CACHE/'manifest.json', CACHE/'arrays.npz', CACHE/'row-receipts.jsonl', CACHE/'cohort-indices.json',
              CPU/'empty-metadata.json', CPU/'source-metadata.json', CPU/'analysis.json', CPU/'verification.json',
              Path('reports/issue-34-cpu-proposals-v1.json')]
    code = list(HERE.glob('*.py')) + [Path('tests/test_conflict_source.py')]
    code.extend(Path(p) for p in (
        'src/sakura_rerank/data/contracts.py', 'src/sakura_rerank/data/consumed_numeric.py',
        'src/sakura_rerank/data/aozora_ruby_evidence.py', 'src/sakura_rerank/data/growth_corpus.py',
        'src/sakura_rerank/data/jawiki_preprocess.py', 'src/sakura_rerank/data/annotation_contrast.py',
        'src/sakura_rerank/source_model_inputs.py', 'src/sakura_rerank/research_tiny.py',
        'src/sakura_rerank/research_tiny_r2.py', 'research/issue-33-annotation-experiment/experiment_fit_contract.py'))
    plan = dict(kind='consumed_training_conflict_source_diagnosis', version=1, issues=[31, 32, 33, 34, 35], parent_issue=1,
        previous_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=15).strip(),
        inputs={p.as_posix(): sha(p) for p in inputs}, code={p.as_posix(): sha(p) for p in sorted(code)},
        rows=75000, expected_empty_inputs=21459, expected_conflicting_groups=2114, expected_conflicting_rows=22080,
        expected_unavoidable_source_mismatches=5658, context_suffix_lengths=list(CONTEXT_LENGTHS),
        notation_precedence=list(TRANSFORMS)+['distinct_after_all_mechanical_folds'],
        context_policy='Synthetic source suffixes diagnose information loss only; no claim of observed IME session text or generalization.',
        source_policy='Authenticate every raw/cache join; recover exact source spans of every conflict row. Original ruby agreement is source evidence, not Japanese/IME correctness.',
        notation_policy='Mechanical transformations only describe collisions. No accepted sets, label edits or semantic equivalence judgments.',
        boundary_policy='Adjacent source character classes are audit-only metadata, never model features or automatic rejection.',
        source_comparison='Keep all three 25000-row strata and all75000 union rows. Additional mixture loss is union loss minus the sum of per-stratum losses; source identity is not a proposed production feature.',
        bounds=dict(concurrency=1, retries=0, stage_seconds=1800, source_line_bytes=262144, archive_decoded_bytes=33554432),
        estimated_cost='Two bounded passes over already consumed metadata and original source archives; zero downloads/fits/inferences.',
        expected_effect='Separate correctable representation/source defects from unobserved distinctions before choosing another learning experiment.',
        new_fits=0, model_inferences=0, threshold_selection=False, calibration=False, final_test=False,
        human_reviews=0, ai_linguistic_reviews=0, gold_admission=False, labels_changed=0, safety_limit=0.0025,
        gold_requirements=dict(point_estimate=0.995, wilson95_lower=0.990, final_valid_minimum=3000))
    save(HERE/'plan-v1.json', plan)
    return dict(status='plan_frozen', input_files=len(inputs), implementation_files=len(code))
