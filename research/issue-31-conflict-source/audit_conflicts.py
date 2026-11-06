"""Complete input/source diagnosis and independent recount of consumed rows."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import sys
import time
import unittest

import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS, LABEL_FIELDS, validate_arrays, verify_chain, tensor_hash
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.research_tiny import character_ids
from sakura_rerank.source_model_inputs import encode_snapshot

from conflict_common import HERE, ROOT, BASE, CACHE, CPU, authenticate, freeze, read, require, rows, save, sha
from conflict_metrics import CONTEXT_LENGTHS, census, mixture, notation_class
from source_evidence import provenance, recover


def load_population():
    manifest = read(CACHE/'manifest.json')
    require(manifest['rows'] == 75000 and manifest['status'] == 'prepared_unverified'
            and manifest['training_eligible'] is False and manifest['independent_gold_eligible'] is False, 'cache_contract')
    with np.load(CACHE/'arrays.npz', allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    validate_arrays(arrays, 75000)
    ledger = verify_chain((CACHE/'row-receipts.jsonl').read_bytes(), 75000, manifest['row_chain_head'])
    source = list(rows(BASE/'scope-v1/cohorts/rows.jsonl.gz', 75000))
    by_id = {r['encoder_input']['stable_id']: r for r in source}
    require(len(by_id) == len(source) == 75000, 'cohort_uniqueness')
    cohort = [by_id[r['origin']['stable_id']] for r in ledger]
    for index, (record, row) in enumerate(zip(ledger, cohort, strict=True)):
        value, origin = row['encoder_input'], row['origin']
        require(all(record['origin'][k] == v for k, v in origin.items()), 'cohort_ledger_origin')
        require(origin['training_eligible'] is False and origin['independent_gold_eligible'] is False
                and origin['ime_quality'] == 'unresolved', 'cohort_admission')
        require(record['origin']['stable_id'] == value['stable_id'] and record['origin']['component_id'] == value['component_id'], 'row_identity')
        require(tensor_hash(arrays, index, MODEL_FIELDS) == record['input_tensor_sha256']
                and tensor_hash(arrays, index, LABEL_FIELDS) == record['label_tensor_sha256'], 'numeric_receipt')
    require(canonical_json_hash([r['encoder_input']['stable_id'] for r in cohort]) == manifest['source_order_sha256'], 'source_order')
    return arrays, ledger, cohort


def stratum(row):
    return 'common_wikipedia' if row['encoder_input']['corpus'] == 'jawiki' else row['origin']['group']+'_aozora'


def independent_hash(values):
    """Explicit byte layout, independent of consumed_numeric.tensor_hash."""
    digest = hashlib.sha256()
    for name in ('context_ids','context_lengths','reading_ids','reading_lengths',
                 'candidate_ids','candidate_lengths','features','candidate_mask'):
        value = np.asarray(values[name][0])
        header = json.dumps([name, value.dtype.str, list(value.shape)], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        digest.update(header)
        digest.update(value.tobytes(order='C'))
    return digest.hexdigest()


def raw_inputs(arrays, cohort, *, independent=False):
    requests = defaultdict(list)
    for i, row in enumerate(cohort):
        requests[row['encoder_input']['candidate_request_id']].append(i)
    expected_empty = read(CPU/'empty-metadata.json')['numeric_hashes']
    expected_source = read(CPU/'source-metadata.json')['numeric_hashes']
    raw_keys, profiles, seen = [None]*75000, Counter(), set()
    for snapshot in rows(BASE/'scope-v1/cohorts/snapshots.jsonl.gz', 21459):
        request = snapshot['stable_id']
        require(request in requests and request not in seen, 'snapshot_join')
        seen.add(request)
        encoded, profile = encode_snapshot(snapshot)
        surfaces = [c['surface'] for c in snapshot['candidate_snapshots']['production_top6']['candidates']]
        raw_key = canonical_json_hash([snapshot['reading'], surfaces, encoded['features'][0].tolist()])
        empty_key = independent_hash(encoded) if independent else tensor_hash(encoded, 0, MODEL_FIELDS)
        profiles.update({key: int(value) for key, value in profile.items() if isinstance(value, (bool, int))})
        for i in requests[request]:
            row = cohort[i]['encoder_input']
            require(row['reading'] == snapshot['reading'] and request == 'growth-reading-'+canonical_json_hash(row['reading']), 'reading_request')
            require(surfaces[int(arrays['gold'][i])] == row['target'], 'literal_source_label')
            require(empty_key == expected_empty[i], 'empty_input_hash')
            for key in MODEL_FIELDS[2:]:
                require(np.array_equal(encoded[key][0], arrays[key][i]), 'snapshot_tensor')
            ids, length = character_ids(row['left_context'], 64)
            require(length == int(arrays['context_lengths'][i]) and np.array_equal(ids, arrays['context_ids'][i]), 'context_tensor')
            encoded['context_ids'][0] = ids
            encoded['context_lengths'][0] = length
            source_key = independent_hash(encoded) if independent else tensor_hash(encoded, 0, MODEL_FIELDS)
            require(source_key == expected_source[i], 'source_input_hash')
            encoded['context_ids'][0] = 0
            encoded['context_lengths'][0] = 0
            raw_keys[i] = raw_key
    require(seen == set(requests) and len(seen) == 21459 and all(raw_keys), 'snapshot_count')
    aliases = defaultdict(set)
    for key, raw in zip(expected_empty, raw_keys, strict=True):
        aliases[key].add(raw)
    aliased = {key for key, raw in aliases.items() if len(raw) > 1}
    return expected_empty, raw_keys, dict(snapshots=len(seen), source_and_empty_rows_verified=75000,
        numeric_groups_with_distinct_literal_inputs=len(aliased), rows_in_literal_input_aliases=sum(k in aliased for k in expected_empty),
        snapshot_profile_sums=dict(profiles))


def context_keys(cohort, empty, length, numeric):
    values = []
    for row, key in zip(cohort, empty, strict=True):
        text = row['encoder_input']['left_context'][-length:] if length else ''
        if numeric:
            ids, size = character_ids(text, 64)
            values.append((key, size, tuple(ids)))
        else:
            values.append((key, text))
    return values


def scalar_census(keys, labels):
    """Independent sorted run-length count, not the audit's Counter algorithm."""
    ordered = sorted(zip(keys, labels, strict=True))
    groups = conflicting = affected = loss = 0
    cursor = 0
    while cursor < len(ordered):
        end = cursor+1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        counts = [0]*6
        for _, label in ordered[cursor:end]:
            counts[label] += 1
        groups += 1
        if sum(c > 0 for c in counts) > 1:
            conflicting += 1
            affected += end-cursor
            loss += end-cursor-max(counts)
        cursor = end
    n = len(ordered)
    return dict(rows=n, unique_inputs=groups, conflicting_groups=conflicting, conflicting_rows=affected,
                minimum_source_mismatches=loss, maximum_source_matches=n-loss, empirical_source_match_ceiling=(n-loss)/n)


def run(commit, *, verify=False):
    started = time.monotonic()
    plan, registry, selection, guard = authenticate(commit)
    arrays, ledger, cohort = load_population()
    empty, raw_keys, encoding = raw_inputs(arrays, cohort, independent=verify)
    labels = list(map(int, arrays['gold']))
    strata = [stratum(row) for row in cohort]
    require(Counter(strata) == dict(common_wikipedia=25000, dictionary_aozora=25000, annotation_aozora=25000), 'stratum_sizes')
    origins = provenance(cohort)
    buckets = defaultdict(list)
    for i, key in enumerate(empty): buckets[key].append(i)
    conflicts = {key: indices for key, indices in buckets.items() if len({labels[i] for i in indices}) > 1}
    positions = sorted(i for indices in conflicts.values() for i in indices)
    require(len(conflicts) == plan['expected_conflicting_groups'] and len(positions) == plan['expected_conflicting_rows'], 'conflict_population')
    observations, opened, source_summary = recover(cohort, origins, positions, registry, selection)
    categories = defaultdict(lambda: dict(groups=0, rows=0, minimum_source_mismatches=0))
    group_records, row_records = [], []
    reading_by_stratum = defaultdict(Counter)
    for key, indices in sorted(conflicts.items()):
        category = notation_class(cohort[i]['encoder_input']['target'] for i in indices)
        counts = Counter(labels[i] for i in indices)
        loss = len(indices)-max(counts.values())
        categories[category]['groups'] += 1
        categories[category]['rows'] += len(indices)
        categories[category]['minimum_source_mismatches'] += loss
        group_records.append(dict(input_key=key, indices=indices, source_rows=len(indices),
            raw_input_variants=len({raw_keys[i] for i in indices}), literal_target_variants=len({cohort[i]['encoder_input']['target'] for i in indices}),
            notation_class=category, minimum_source_mismatches=loss,
            source_strata=dict(Counter(strata[i] for i in indices)),
            reading_evidence=dict(Counter(observations[i]['reading_evidence'] for i in indices))))
    for i in positions:
        reading_by_stratum[strata[i]][observations[i]['reading_evidence']] += 1
        row_records.append(dict(observations[i], input_key=empty[i], raw_input_key=raw_keys[i], stratum=strata[i],
            source_label_slot=labels[i], original_row_sha256=ledger[i]['origin']['original_row_sha256'],
            consumption_sha256=ledger[i]['origin']['consumption_sha256']))
    context = []
    counter = scalar_census if verify else census
    for length in CONTEXT_LENGTHS:
        raw = counter(context_keys(cohort, empty, length, False), labels)
        numeric = counter(context_keys(cohort, empty, length, True), labels)
        context.append(dict(source_suffix_characters=length, literal_context=raw, hashed_context=numeric))
    mixing = mixture(empty, labels, strata)
    if verify:
        require(scalar_census(empty, labels) == mixing['union'], 'independent_union_census')
        for name, value in mixing['strata'].items():
            indices = [i for i, s in enumerate(strata) if s == name]
            require(scalar_census([empty[i] for i in indices], [labels[i] for i in indices]) == value, 'independent_stratum_census')
    require(mixing['union']['minimum_source_mismatches'] == 5658, 'previous_census_loss')
    require(sum(v['groups'] for v in categories.values()) == 2114 and sum(v['rows'] for v in categories.values()) == 22080
            and sum(v['minimum_source_mismatches'] for v in categories.values()) == 5658, 'category_totals')
    summary = dict(kind='consumed_training_conflict_source_diagnosis', status='complete', rows=75000,
        conflicting_groups=2114, conflicting_rows=22080, encoding=encoding, notation_categories=dict(categories),
        source_evidence=source_summary, reading_by_stratum={k: dict(v) for k, v in reading_by_stratum.items()},
        context_information_bounds=context, source_mixture=mixing, source_metadata_joins=75000,
        classification_kind='deterministic_source_evidence_not_semantic_review',
        new_fits=0, model_inferences=0, labels_changed=0, accepted_sets_created=0, human_reviews=0, ai_linguistic_reviews=0,
        independent_accuracy_estimated=False, gold_admission=False, calibration=False, threshold_selection=False, final_test=False,
        safety_limit=0.0025, forbidden_data_reads=guard.blocked)
    require(guard.blocked == 0, 'data_read_guard')
    if verify:
        audit = read(ROOT/'audit.json')
        require(summary == audit['summary'], 'independent_aggregate_recount')
        require(group_records == read(ROOT/'groups.json') and row_records == read(ROOT/'rows.json')
                and opened == read(ROOT/'opened-sources.json'), 'evidence_replay')
        for path, digest in audit['artifacts'].items(): require(sha(path) == digest, 'audit_artifact_hash')
        result = dict(status='passed', code_commit=commit, audit_sha256=sha(ROOT/'audit.json'),
            verified_rows=75000, source_spans=22080, groups=2114, independent_context_censuses=16,
            independent_mixture_censuses=4, source_joins_replayed=True, numeric_hash_algorithm='separate_explicit_bytes',
            limitation='Source parser and literal projection are reused; exact spans, hashes and source outputs replay. No independent linguistic review.',
            elapsed_seconds=round(time.monotonic()-started, 3), forbidden_data_reads=guard.blocked)
        save(ROOT/'verification.json', result)
        return result
    save(ROOT/'groups.json', group_records)
    save(ROOT/'rows.json', row_records)
    save(ROOT/'opened-sources.json', opened)
    result = dict(summary=summary, code_commit=commit, plan_sha256=sha(HERE/'plan-v1.json'),
        artifacts={str(ROOT/name).replace('\\','/'): sha(ROOT/name) for name in ('groups.json','rows.json','opened-sources.json')},
        elapsed_seconds=round(time.monotonic()-started, 3))
    save(ROOT/'audit.json', result)
    return dict(status='complete', rows=75000, groups=2114, source_spans=22080, elapsed_seconds=result['elapsed_seconds'])


def tests():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    value = dict(tests=result.testsRun, successful=result.wasSuccessful(), failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    save(ROOT/'full-tests.json', value)
    require(result.wasSuccessful() and not result.skipped, 'full_test_suite')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('plan', 'audit', 'verify', 'tests'))
    parser.add_argument('--commit')
    args = parser.parse_args()
    try:
        if args.stage == 'plan': result = freeze()
        elif args.stage == 'tests': result = tests()
        else: result = run(args.commit, verify=args.stage == 'verify')
    except Exception as error:
        # Only fixed error type/code: never dump source strings or native payloads.
        value = dict(status='failed', error_type=type(error).__name__)
        if isinstance(error, ValueError) and str(error).startswith('conflict_'): value['error_code'] = str(error)
        print(json.dumps(value), flush=True)
        sys.exit(1)
    print(json.dumps(result), flush=True)
