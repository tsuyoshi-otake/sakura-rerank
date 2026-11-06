"""Prepare a frozen source-screened recipe and replay it independently."""
import argparse
from collections import Counter
import json
import sys
import time
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.source_research_recipe import build_recipe, load_recipe
from recipe_common import CACHE, PLAN, POOL, ROOT, inputs, read, require, save, sha


def bindings(cache, indices):
    return dict(source_manifest_sha256=sha(POOL/'manifest.json'), numeric_manifest_sha256=sha(CACHE/'manifest.json'),
                numeric_chain_head=cache['row_chain_head'], source_order_sha256=cache['source_order_sha256'],
                original_arm_order_sha256=canonical_json_hash(indices))


def prepare(commit):
    started = time.monotonic()
    plan, guard, pool, cohort, receipts, arrays, indices, cache = inputs(commit)
    bound = bindings(cache, indices)
    recipe = build_recipe(cohort, pool, receipts, source_manifest_sha256=bound['source_manifest_sha256'],
        numeric_manifest_sha256=bound['numeric_manifest_sha256'], numeric_manifest=cache, original_indices=indices,
        allow_dictionary_only=plan['allow_dictionary_only'])
    require(recipe['original_indices'] == indices, 'original_membership_changed')
    baseline = {}
    for arm, old in indices.items():
        selected = recipe['selected_indices'][arm]
        before = sum(int(arrays['gold'][i] == 0) for i in old)
        after = sum(int(arrays['gold'][i] == 0) for i in selected)
        baseline[arm] = dict(original_rows=len(old), selected_rows=len(selected), excluded_rows=len(old)-len(selected),
                             original_source_top1=before, selected_source_top1=after, excluded_source_top1=before-after)
    excluded = Counter(row['source_terminal'] for row in recipe['rows'] if row['status'] != 'eligible_for_fit_binding')
    require(guard.blocked == 0, 'forbidden_read')
    save(ROOT/'recipe.json', recipe)
    load_recipe(ROOT/'recipe.json', sha(ROOT/'recipe.json'), expected_bindings=bound, purpose='fit_binding_preparation')
    result = dict(status='prepared_for_separate_fit_binding', plan_commit=commit, plan_sha256=sha(PLAN),
        recipe_sha256=sha(ROOT/'recipe.json'), bindings=bound, summary=recipe['summary'], excluded_source_reasons=dict(excluded),
        baseline_source_counts=baseline, numeric_rows_verified=len(receipts), source_rows_verified=len(cohort),
        candidate_scope=plan['candidate_scope'], elapsed_seconds=round(time.monotonic()-started, 3), forbidden_data_reads=guard.blocked,
        new_fits=0, model_inferences=0, native_requests=0, original_labels_changed=0, training_admission=False, gold_admission=False, final_test=False)
    save(ROOT/'preparation.json', result)
    return result


def verify(commit):
    started = time.monotonic()
    plan, guard, pool, cohort, receipts, arrays, indices, cache = inputs(commit)
    report = read(ROOT/'preparation.json')
    require(report['plan_commit'] == commit and report['plan_sha256'] == sha(PLAN), 'preparation_binding')
    recipe = load_recipe(ROOT/'recipe.json', report['recipe_sha256'], expected_bindings=bindings(cache, indices), purpose='fit_binding_preparation')
    decision_by_input = {d['input_sha256']: d for d in pool['decisions']}
    allowed = set()
    status_counts, tier_counts, exclusions = Counter(), Counter(), Counter()
    for i, (row, receipt, actual) in enumerate(zip(cohort, receipts, recipe['rows'], strict=True)):
        item = row['encoder_input']; d = decision_by_input[canonical_json_hash(item)]
        state = d['reading_evidence']
        if state == 'exact_ruby_reading_match': tier = 'original_annotation'
        elif state in ('no_ruby_overlap', 'wikipedia_no_original_reading_annotation') and d['source']['origin_kind'] == 'frozen_unique_dictionary': tier = 'dictionary_only_weak'
        else: tier = 'pending'
        status = 'pending_source' if tier == 'pending' else 'weak_source_disabled' if tier == 'dictionary_only_weak' and not plan['allow_dictionary_only'] else 'eligible_for_fit_binding'
        expected = dict(index=i, source_input_sha256=canonical_json_hash(item), component_id=item['component_id'],
            group=item['corpus']+'_'+row['origin']['group'], source_terminal=d['terminal'], tier=tier, status=status,
            source_decision_sha256=canonical_json_hash(d), numeric_receipt_sha256=receipt['record_sha256'],
            input_tensor_sha256=receipt['input_tensor_sha256'], label_tensor_sha256=receipt['label_tensor_sha256'])
        require(actual == expected, 'independent_row_replay')
        status_counts[status] += 1; tier_counts[tier] += 1
        if status != 'eligible_for_fit_binding': exclusions[d['terminal']] += 1
        else: allowed.add(i)
    selected = {arm: [i for i in old if i in allowed] for arm, old in indices.items()}
    require(selected == recipe['selected_indices'] and indices == recipe['original_indices'], 'independent_selection')
    arms, baseline = {}, {}
    for arm, old in indices.items():
        keep = set(selected[arm]); excluded = set(old)-keep
        arms[arm] = dict(original_rows=len(old), selected_rows=len(keep), excluded_rows=len(excluded),
                         selected_tiers=dict(Counter(recipe['rows'][i]['tier'] for i in sorted(keep))))
        baseline[arm] = dict(original_rows=len(old), selected_rows=len(keep), excluded_rows=len(excluded),
            original_source_top1=sum(bool(arrays['correct_mask'][i, 0]) for i in old),
            selected_source_top1=sum(bool(arrays['correct_mask'][i, 0]) for i in keep),
            excluded_source_top1=sum(bool(arrays['correct_mask'][i, 0]) for i in excluded))
    summary = dict(population_rows=75000, source_tiers=dict(tier_counts), terminal_counts=dict(status_counts),
                   selected_union=status_counts['eligible_for_fit_binding'], arms=arms)
    require(summary == report['summary'] == recipe['summary'] and baseline == report['baseline_source_counts']
            and dict(exclusions) == report['excluded_source_reasons'] and guard.blocked == 0, 'independent_census')
    proof = dict(status='passed', plan_commit=commit, preparation_sha256=sha(ROOT/'preparation.json'), recipe_sha256=sha(ROOT/'recipe.json'),
        rows_verified=75000, numeric_tensor_rows_reverified=75000, original_arm_indices_verified=100000,
        selected_arm_indices_verified=sum(map(len, selected.values())), independent_source_state_classification=True,
        original_components_preserved=True, excluded_history_preserved=True, original_arm_presentation_order_preserved=True,
        source_tier_census=summary,
        forbidden_data_reads=guard.blocked, elapsed_seconds=round(time.monotonic()-started, 3),
        training_admission=False, gold_admission=False, final_test=False)
    save(ROOT/'verification.json', proof)
    return proof


def tests(targeted=False):
    suite = unittest.defaultTestLoader.discover('tests', pattern='test_source_research_recipe.py' if targeted else 'test*.py')
    expected = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    value = dict(tests=result.testsRun, expected=expected, successful=result.wasSuccessful(), failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    save(ROOT/('targeted-tests.json' if targeted else 'full-tests.json'), value)
    require(result.wasSuccessful() and result.testsRun == expected and not result.skipped, 'tests_failed')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=('prepare', 'verify', 'tests', 'targeted')); parser.add_argument('--commit')
    args = parser.parse_args()
    try:
        value = prepare(args.commit) if args.stage == 'prepare' else verify(args.commit) if args.stage == 'verify' else tests(args.stage == 'targeted')
    except Exception as error:
        failure = dict(status='failed', error_type=type(error).__name__)
        if isinstance(error, ValueError) and str(error).startswith(('recipe_run_', 'source_recipe_')): failure['error_code'] = str(error)
        print(json.dumps(failure), flush=True); sys.exit(1)
    print(json.dumps(value), flush=True)
