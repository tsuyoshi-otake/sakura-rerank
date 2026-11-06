"""Identity-bound source screening for a separately authorized research fit.

The caller authenticates source-pool and numeric-cache bytes and verifies their
numeric tensors. This module joins their complete populations, retains lineage,
and exposes indices for fit-binding preparation. It never authorizes a fit or
certifies original-source reconstruction as intended Japanese conversion.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .contracts import canonical_json_hash

MAX_ROWS = 100000
MAX_BYTES = 128 * 1024 * 1024
ARMS = ('dictionary', 'annotation')
TIERS = {'ready_original_annotation': 'original_annotation',
         'ready_dictionary_only_weak': 'dictionary_only_weak',
         'pending_annotation_missing': 'pending', 'pending_reading_conflict': 'pending',
         'pending_annotation_scope': 'pending', 'pending_annotation_parse': 'pending',
         'pending_annotation_reading': 'pending'}
GROUPS = {'jawiki_dictionary': ['dictionary', 'annotation'],
          'aozora_dictionary': ['dictionary'], 'aozora_annotation': ['annotation']}
READING_ORIGINS = {'frozen_unique_dictionary': 'frozen_unique_dictionary',
                   'original_ruby_annotation': 'original_ruby'}
ROW_FIELDS = {'index', 'source_input_sha256', 'component_id', 'group', 'source_terminal',
              'tier', 'status', 'source_decision_sha256', 'numeric_receipt_sha256',
              'input_tensor_sha256', 'label_tensor_sha256'}


def require(value, code):
    if not value:
        raise ValueError('source_recipe_' + code)


def digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def policy(allow_dictionary_only=False):
    require(type(allow_dictionary_only) is bool, 'weak_policy_boolean')
    return dict(version=1, allow_dictionary_only=allow_dictionary_only,
                task='original_source_reconstruction', candidate_scope='previously_verified_top6_training_cache',
                context='unchanged_synthetic_source_prefix_not_observed_session')


def terminal(source_terminal, allow_weak):
    require(source_terminal in TIERS, 'source_terminal')
    tier = TIERS[source_terminal]
    status = ('pending_source' if tier == 'pending' else
              'weak_source_disabled' if tier == 'dictionary_only_weak' and not allow_weak else
              'eligible_for_fit_binding')
    return tier, status


def summarize(rows, allow_weak):
    require(isinstance(rows, list) and 1 <= len(rows) <= MAX_ROWS, 'row_bound')
    original = {arm: [] for arm in ARMS}
    selected = {arm: [] for arm in ARMS}
    seen = set()
    counts, tiers = Counter(), Counter()
    for i, row in enumerate(rows):
        require(isinstance(row, dict) and set(row) == ROW_FIELDS and type(row['index']) is int
                and row['index'] == i, 'row_schema_or_order')
        require(all(digest(row[k]) for k in ROW_FIELDS if k.endswith('_sha256'))
                and row['source_input_sha256'] not in seen, 'row_identity')
        require(isinstance(row['component_id'], str) and 1 <= len(row['component_id']) <= 256
                and row['group'] in GROUPS, 'lineage_or_group')
        tier, status = terminal(row['source_terminal'], allow_weak)
        require((row['tier'], row['status']) == (tier, status), 'row_selection')
        seen.add(row['source_input_sha256'])
        counts[status] += 1
        tiers[tier] += 1
        for arm in GROUPS[row['group']]:
            original[arm].append(i)
            if status == 'eligible_for_fit_binding':
                selected[arm].append(i)
    arms = {}
    for arm in ARMS:
        arms[arm] = dict(original_rows=len(original[arm]), selected_rows=len(selected[arm]),
                         excluded_rows=len(original[arm])-len(selected[arm]),
                         selected_tiers=dict(Counter(rows[i]['tier'] for i in selected[arm])))
    summary = dict(population_rows=len(rows), source_tiers=dict(tiers), terminal_counts=dict(counts),
                   selected_union=counts['eligible_for_fit_binding'], arms=arms)
    return original, selected, summary


def build_recipe(cohort, source_pool, receipts, *, source_manifest_sha256,
                 numeric_manifest_sha256, numeric_manifest, allow_dictionary_only=False):
    """Bind all original cache positions to source decisions, never source order.

    `source_pool` comes from load_prepared; receipts and numeric_manifest come
    from authenticated, tensor-verified cache bytes. Eligibility here only means
    eligible for a later, separately committed research fit binding.
    """
    current_policy = policy(allow_dictionary_only)
    require(digest(source_manifest_sha256) and digest(numeric_manifest_sha256), 'artifact_binding')
    require(isinstance(cohort, list) and isinstance(receipts, list)
            and 1 <= len(cohort) == len(receipts) <= MAX_ROWS, 'population')
    require(numeric_manifest['rows'] == len(cohort) and numeric_manifest['training_eligible'] is False
            and numeric_manifest['independent_gold_eligible'] is False, 'numeric_admission')
    manifest = source_pool['manifest']
    require(manifest['input_rows'] == len(cohort) and manifest['training_eligible'] is False
            and manifest['independent_gold_eligible'] is False, 'source_population')
    decisions = source_pool['decisions']
    by_hash = {d['input_sha256']: d for d in decisions}
    require(len(decisions) == len(by_hash) == len(cohort), 'source_population_identity')
    ready = {k: d for k, d in by_hash.items() if terminal(d['terminal'], allow_dictionary_only)[0] != 'pending'}
    prepared = source_pool['rows']
    require(len(prepared) == len(ready) == manifest['preparable_rows'], 'prepared_population')
    prepared_hashes = set()
    for entry in prepared:
        key = canonical_json_hash(entry['input'])
        require(key in ready and key not in prepared_hashes
                and entry['decision_sha256'] == canonical_json_hash(ready[key]), 'prepared_identity')
        prepared_hashes.add(key)
    rows, identities = [], []
    previous = '0' * 64
    for i, (row, receipt) in enumerate(zip(cohort, receipts, strict=True)):
        require(set(row) == {'encoder_input', 'origin', 'membership'}, 'cohort_schema')
        item, origin = row['encoder_input'], row['origin']
        key = canonical_json_hash(item)
        require(key in by_hash, 'cohort_source_join')
        decision = by_hash[key]
        require(origin['training_eligible'] is False and origin['independent_gold_eligible'] is False
                and origin['ime_quality'] == 'unresolved', 'cohort_admission')
        require(decision['training_eligible'] is False and decision['independent_gold_eligible'] is False
                and decision['source']['original_row_sha256'] == origin['original_row_sha256']
                and decision['source']['origin_kind'] == READING_ORIGINS.get(origin['reading_provenance']), 'source_origin')
        group = item['corpus'] + '_' + origin['group']
        require(group in GROUPS and row['membership'] == GROUPS[group], 'cohort_membership')
        require(type(receipt['index']) is int and receipt['index'] == i
                and receipt['previous_sha256'] == previous
                and canonical_json_hash({k: v for k, v in receipt.items() if k != 'record_sha256'}) == receipt['record_sha256'], 'numeric_chain')
        sealed = receipt['origin']
        require(all(sealed.get(k) == v for k, v in origin.items())
                and sealed['cohort_record_sha256'] == canonical_json_hash(row)
                and sealed['stable_id'] == item['stable_id'] and sealed['component_id'] == item['component_id'], 'numeric_cohort_join')
        tier, status = terminal(decision['terminal'], allow_dictionary_only)
        require(type(decision['candidate_preparation_allowed']) is bool
                and decision['candidate_preparation_allowed'] == (tier != 'pending'), 'source_preparation')
        rows.append(dict(index=i, source_input_sha256=key, component_id=item['component_id'], group=group,
                         source_terminal=decision['terminal'], tier=tier, status=status,
                         source_decision_sha256=canonical_json_hash(decision), numeric_receipt_sha256=receipt['record_sha256'],
                         input_tensor_sha256=receipt['input_tensor_sha256'], label_tensor_sha256=receipt['label_tensor_sha256']))
        identities.append(item['stable_id'])
        previous = receipt['record_sha256']
    require(previous == numeric_manifest['row_chain_head']
            and canonical_json_hash(identities) == numeric_manifest['source_order_sha256'], 'numeric_population')
    original, selected, summary = summarize(rows, allow_dictionary_only)
    return dict(kind='source_screened_research_recipe', version=1, status='ready_for_separate_fit_binding',
                policy=current_policy, bindings=dict(source_manifest_sha256=source_manifest_sha256,
                numeric_manifest_sha256=numeric_manifest_sha256, numeric_chain_head=previous,
                source_order_sha256=numeric_manifest['source_order_sha256']), rows=rows,
                original_indices=original, selected_indices=selected, summary=summary,
                consumer_purposes=['fit_binding_preparation'], training_eligible=False,
                independent_gold_eligible=False, independent_evaluation_eligible=False)


def load_recipe(path, expected_sha256, *, expected_bindings, purpose):
    """Return complete authenticated recipe; no training/Gold/Test purpose."""
    require(purpose == 'fit_binding_preparation' and digest(expected_sha256), 'consumer_purpose')
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES, 'recipe_file_bound')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256, 'recipe_hash')
    value = json.loads(raw)
    require(set(value) == {'kind', 'version', 'status', 'policy', 'bindings', 'rows', 'original_indices',
            'selected_indices', 'summary', 'consumer_purposes', 'training_eligible',
            'independent_gold_eligible', 'independent_evaluation_eligible'}, 'recipe_schema')
    require(value['kind'] == 'source_screened_research_recipe' and type(value['version']) is int and value['version'] == 1
            and value['status'] == 'ready_for_separate_fit_binding'
            and value['consumer_purposes'] == ['fit_binding_preparation']
            and all(value[k] is False for k in ('training_eligible', 'independent_gold_eligible', 'independent_evaluation_eligible')), 'recipe_admission')
    require(set(expected_bindings) == {'source_manifest_sha256', 'numeric_manifest_sha256', 'numeric_chain_head', 'source_order_sha256'}
            and all(digest(v) for v in expected_bindings.values()) and value['bindings'] == expected_bindings, 'consumer_bindings')
    allow_weak = value['policy']['allow_dictionary_only']
    require(value['policy'] == policy(allow_weak), 'recipe_policy')
    original, selected, summary = summarize(value['rows'], allow_weak)
    require((value['original_indices'], value['selected_indices'], value['summary']) == (original, selected, summary), 'recipe_selection')
    return value
