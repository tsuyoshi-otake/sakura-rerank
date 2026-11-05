"""Verify the frozen preparation receipts without fitting or opening evaluation bodies."""
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys

from comparison_common import ROOT, HERE, PLAN, authenticate, read, rows, save, sha
from prepare_cohorts import SCOPE_PLAN, SCOPE_ROOT
from prepare_numeric import RUN_ROOT, OUTPUT

BASE_COMMIT = '229e960ad91c6efb1f49fd9c3f2d448b6317711c'


def require(value, code):
    if not value:
        raise ValueError(code)


def static_checks():
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', BASE_COMMIT, 'HEAD'], text=True, timeout=15
    ).splitlines()
    paths = sorted({p for p in changed if p.endswith('.py')}
                   | {Path(__file__).relative_to(Path.cwd()).as_posix()})
    trees = {p: ast.parse(Path(p).read_text(encoding='utf-8-sig')) for p in paths}
    evidence = []
    for path, tree in trees.items():
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        imported = {
            alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)
            for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names if alias.name != 'annotations'
        }
        unused = imported - used
        reexports = []
        if path.endswith('/comparison_common.py') and 'save' in unused:
            callers = [other for other, parsed in trees.items() if any(
                isinstance(node, ast.ImportFrom) and node.module == 'comparison_common'
                and any(alias.name == 'save' for alias in node.names)
                for node in ast.walk(parsed))]
            require(bool(callers), 'comparison_unused_reexport')
            unused.remove('save')
            reexports.append(dict(name='save', callers=callers))
        require(not unused, 'comparison_unreferenced_import')
        evidence.append(dict(path=path, ast_parsed=True, unreferenced_imports=[], reexports=reexports))
    return dict(status='passed', files=evidence,
                scope='AST syntax and imported-name references; static type checking not performed')


def run():
    plan = authenticate()
    for path, digest in read(SCOPE_PLAN)['inputs'].items():
        require(sha(path) == digest, 'comparison_scope_input_changed')
    source = read(ROOT/'source-report.json')
    source_verification = read(ROOT/'source-verification.json')
    cohort = read(SCOPE_ROOT/'report.json')
    numeric = read(RUN_ROOT/'report.json')
    cache = read(OUTPUT/'manifest.json')
    for report_path, execution_path in (
        (ROOT/'source-report.json', ROOT/'source-execution.json'),
        (SCOPE_ROOT/'report.json', SCOPE_ROOT/'execution.json'),
        (RUN_ROOT/'report.json', RUN_ROOT/'execution.json'),
    ):
        execution = read(execution_path)
        require(execution['status'] == 'complete' and execution['report_sha256'] == sha(report_path),
                'comparison_incomplete_stage')
    for report, base in ((source, ROOT/'source'), (cohort, SCOPE_ROOT/'cohorts')):
        for artifact in report['artifacts'].values():
            require(sha(base/artifact['path']) == artifact['sha256'], 'comparison_artifact_changed')
    for report in (source, cohort, cache):
        for path, digest in report['implementation'].items():
            require(sha(path) == digest, 'comparison_implementation_changed')
    require(source_verification['report_sha256'] == sha(ROOT/'source-report.json')
            and source_verification['status'] == 'passed'
            and source_verification['script_sha256'] == sha(HERE/'verify_sources.py'),
            'comparison_source_verification_changed')
    reservation = read(ROOT/'reservation-verification.json')
    require(reservation['status'] == 'passed' and reservation['overlap'] == 0
            and reservation['reserved_documents'] == 1000
            and reservation['selection_sha256'] == sha(plan['evaluation']['selection_path'])
            and reservation['script_sha256'] == sha(HERE/'verify_reservation.py'),
            'comparison_reservation_verification_changed')
    require(cohort['legacy_graph_byte_parity'] and cohort['reverse_replay_passed']
            and cohort['rows_per_arm'] == {'dictionary': 50000, 'annotation': 50000},
            'comparison_cohort_contract')
    require(numeric['status'] == 'passed' and numeric['bitwise_equal']
            and numeric['rows'] == 75000 and numeric['tensor_elements_verified'] == 26775000
            and numeric['cache_manifest_sha256'] == sha(OUTPUT/'manifest.json')
            and numeric['source_and_cohort_report_sha256'] == sha(SCOPE_ROOT/'report.json')
            and numeric['script_sha256'] == sha(HERE/'prepare_numeric.py')
            and sha(OUTPUT/'verification.json') == sha(RUN_ROOT/'report.json'),
            'comparison_numeric_verification_changed')
    for filename, digest in cache['artifacts'].items():
        require(sha(OUTPUT/filename) == digest, 'comparison_numeric_artifact_changed')
    require(not (RUN_ROOT/'cache.partial').exists(), 'comparison_successful_partial_remains')
    diagnosis = read(ROOT/'numeric-diagnosis.json')
    for filename, digest in diagnosis['preserved_partial'].items():
        require(sha(ROOT/'numeric-v1.partial'/filename) == digest, 'comparison_failed_attempt_changed')
    require(read(ROOT/'numeric-execution.json')['status'] == 'failed', 'comparison_failure_overwritten')

    ledger = list(rows(OUTPUT/'row-receipts.jsonl'))
    records = list(rows(SCOPE_ROOT/'cohorts/rows.jsonl.gz'))
    indices = read(OUTPUT/'cohort-indices.json')
    duplicate_sources = {}
    for name, positions in indices.items():
        grouped = defaultdict(list)
        for i in positions:
            grouped[ledger[i]['input_tensor_sha256']].append(i)
        counts = Counter()
        for positions in grouped.values():
            if len(positions) > 1:
                corpora = {records[i]['encoder_input']['corpus'] for i in positions}
                counts['+'.join(sorted(corpora))] += 1
        duplicate_sources[name] = dict(counts)
        require(sum(counts.values()) == numeric['input_duplicates_per_arm'][name]['duplicate_groups'],
                'comparison_duplicate_count')
    old_cache = read(ROOT/'numeric-v1.partial/manifest.json')
    require(cache['artifacts'] == old_cache['artifacts']
            and cache['row_chain_head'] == old_cache['row_chain_head'], 'comparison_retry_numeric_changed')
    suite = read(ROOT/'unit-tests-r3.json')
    require(suite == dict(tests=644, successful=True, errors=0, failures=0, skipped=0),
            'comparison_unit_suite')
    integrity = json.loads(subprocess.check_output(
        [sys.executable, 'research/issue-33-data-growth/verify_integrity.py'],
        text=True, timeout=120))
    require(integrity['status'] == 'passed' and integrity['original_artifacts'] == 16
            and integrity['bound_fit_artifacts'] == 25, 'comparison_original_integrity')
    subprocess.run(['git', 'diff', '--check'], check=True, timeout=15, capture_output=True)
    require(not subprocess.check_output(['git', 'ls-files', 'data'], text=True, timeout=15).strip(),
            'comparison_raw_data_tracked')
    ignored = subprocess.check_output(['git', 'check-ignore', str(ROOT),
        '.codex/goal-loop/issue-33-annotation-comparison/'], text=True, timeout=15).splitlines()
    require(len(ignored) == 2, 'comparison_private_paths_not_ignored')
    result = dict(kind='annotation_comparison_preparation_checks', status='passed',
        plan_sha256=sha(PLAN), plan_inputs_verified=len(plan['inputs']),
        source_verification_sha256=sha(ROOT/'source-verification.json'),
        scope_report_sha256=sha(SCOPE_ROOT/'report.json'), numeric_report_sha256=sha(RUN_ROOT/'report.json'),
        reservation_verification_sha256=sha(ROOT/'reservation-verification.json'),
        cache_manifest_sha256=sha(OUTPUT/'manifest.json'), duplicate_groups_by_source=duplicate_sources,
        retry_numeric_artifacts_byte_identical=True, original_failures_preserved=True,
        static_analysis=static_checks(), full_suite=suite, original_integrity=integrity,
        git_diff_check='passed', tracked_data_files=0, raw_artifacts_git_ignored=True,
        model_fits=0, model_inferences=0, new_native_requests=0, fresh_evaluation_bodies_fetched=0,
        final_test_used=False, gold_certified=False, safety_threshold=.0025,
        original_labels_and_models_changed=False, full_release_goal='active_not_achieved',
        verification_method='Direct Codex verification; no external agent or human review',
        script_sha256=sha(__file__),
        scope='Preparation binding verification; all-tensor recomputation in numeric report; cleanup and remote publication recorded separately')
    save(ROOT/'preparation-checks.json', result)
    print(json.dumps({key: result[key] for key in ('status', 'full_suite', 'duplicate_groups_by_source',
                                                  'retry_numeric_artifacts_byte_identical', 'original_integrity')}))


if __name__ == '__main__':
    run()
