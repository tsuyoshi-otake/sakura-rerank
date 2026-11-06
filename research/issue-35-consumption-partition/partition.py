"""Prospective hash-only quarantine diagnostics; never an admission certificate."""
from bisect import bisect_right
from collections import Counter, defaultdict
import re

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.relation_witnesses import KINDS, component_labels

SOURCE_RELATIONS = tuple(kind for kind in KINDS if kind != 'input')
PARTITIONS = frozenset(('train', 'calibration', 'test', 'research_evaluation'))
CHANNELS = frozenset(('input', 'left_context', 'teacher', 'body_pretraining'))
MAX_INPUTS = 100_000
MAX_SPANS = 100_000
REASONS = ('historical_source_component', 'cross_partition_source_component',
           'historical_input', 'cross_partition_input', 'repeated_new_input')


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def audit(graph, assignments, historical_aliases, exposed_sources):
    """Keep all source relations; quarantine shared input units without union.

    The supplied graph/history and input hashes must already be authenticated.
    A hypothetical clear row is still missing consumption, numeric and Gold
    evidence. This function never modifies original records, roles or exclusions.
    """
    require(isinstance(assignments, dict) and 1 <= len(assignments) <= MAX_INPUTS,
            'partition_assignment_bound')
    require(all(isinstance(role, str) and role in PARTITIONS for role in assignments.values()), 'partition_role')
    require(isinstance(historical_aliases, (list, tuple, set, frozenset))
            and len(historical_aliases) <= 1_000_000, 'partition_alias_bound')
    require(isinstance(exposed_sources, (list, tuple, set, frozenset))
            and len(exposed_sources) <= 10_000, 'partition_exposure_bound')
    aliases, exposed = set(historical_aliases), set(exposed_sources)
    require(len(aliases) <= 1_000_000 and all(digest(v) for v in aliases), 'partition_alias_schema')
    require(len(exposed) <= 10_000, 'partition_exposure_bound')
    actual = {r['stable_id'] for r in graph.records if r['population'] in ('train', 'evaluation')}
    require(set(assignments) == actual, 'partition_assignment_extent')
    source_ids = {r['stable_id'] for r in graph.records if r['population'] == 'source_coverage'}
    require(exposed <= source_ids, 'partition_unknown_exposed_source')
    labels = component_labels(graph, SOURCE_RELATIONS)
    history = set(aliases)
    blocked_sources, group_roles = set(), defaultdict(set)
    targets, input_members, wanted = [], defaultdict(list), set()
    for i, row in enumerate(graph.records):
        role = row['population']
        if role == 'historical' or row['stable_id'] in exposed:
            blocked_sources.add(labels[i])
        if role == 'historical' and row.get('input_hash') is not None:
            history.add(row['input_hash'])
        if row['stable_id'] in assignments:
            require(digest(row.get('input_hash')), 'partition_target_input_hash')
            targets.append(i)
            wanted.add(labels[i])
            group_roles[labels[i]].add(assignments[row['stable_id']])
            input_members[row['input_hash']].append(i)
    members = {key:[] for key in wanted}
    for i, row in enumerate(graph.records):
        if labels[i] in members:
            members[labels[i]].append(row['stable_id'])
    keys = {key:canonical_json_hash(sorted(ids)) for key, ids in members.items()}
    input_roles = {value:{assignments[graph.records[i]['stable_id']] for i in indices}
                   for value, indices in input_members.items()}
    rows, exclusive, overlapping = [], Counter(), Counter()
    for i in targets:
        row, label = graph.records[i], labels[i]
        value = row['input_hash']
        reasons = [reason for reason, yes in zip(REASONS, (
            label in blocked_sources, len(group_roles[label]) > 1, value in history,
            len(input_roles[value]) > 1, len(input_members[value]) > 1)) if yes]
        status = reasons[0] if reasons else 'metadata_only_unblocked'
        rows.append(dict(stable_id=row['stable_id'], partition=assignments[row['stable_id']],
                         source_component=keys[label], reasons=reasons, status=status))
        exclusive[status] += 1
        overlapping.update(reasons)
    remaining = [r for r in rows if r['status'] == 'metadata_only_unblocked']
    clear_ids = {r['stable_id'] for r in remaining}
    clear_indices = [i for i in targets if graph.records[i]['stable_id'] in clear_ids]
    # Executable invariants on the hypothetical remainder, not provenance claims.
    require(all(labels[i] not in blocked_sources and len(group_roles[labels[i]]) == 1
                and graph.records[i]['input_hash'] not in history for i in clear_indices),
            'partition_clear_source_or_history_conflict')
    require(len({graph.records[i]['input_hash'] for i in clear_indices}) == len(clear_indices),
            'partition_clear_input_repeat')
    return dict(rows=rows, summary=dict(inputs=len(rows), source_components=len(wanted),
        exclusive_statuses=dict(exclusive), overlapping_reasons=dict(overlapping),
        metadata_only_unblocked=len(remaining),
        metadata_only_unblocked_source_components=len({r['source_component'] for r in remaining}),
        unique_supplied_historical_inputs=len(history),
        status='diagnostic_only_pending_consumption_numeric_gold',
        training_admission=False, calibration=False, gold_admission=False, final_test=False))


def span_fields(row, used):
    expected = {'source_sha256', 'preprocessing_sha256', 'start', 'end'}
    if used:
        expected |= {'channel', 'partition'}
    require(isinstance(row, dict) and set(row) == expected, 'partition_span_schema')
    require(digest(row['source_sha256']) and digest(row['preprocessing_sha256']), 'partition_span_identity')
    require(type(row['start']) is int and type(row['end']) is int
            and 0 <= row['start'] < row['end'] <= 16_777_216, 'partition_span_extent')
    if used:
        require(isinstance(row['channel'], str) and row['channel'] in CHANNELS
                and isinstance(row['partition'], str) and row['partition'] in PARTITIONS, 'partition_span_role')


def check_spans(quarantined, used):
    """Half-open annotation-scalar intervals; completeness is never self-certified.

    O((Q+U) log Q), with merged interval lookup. A different preprocessing
    projection of the same raw source is incomparable rather than disjoint.
    Caller must separately authenticate and prove channel/offset coverage.
    """
    require(isinstance(quarantined, list) and isinstance(used, list)
            and len(quarantined) <= MAX_SPANS and len(used) <= MAX_SPANS, 'partition_span_bound')
    groups, projections = defaultdict(list), defaultdict(set)
    for row in quarantined:
        span_fields(row, False)
        key = (row['source_sha256'], row['preprocessing_sha256'])
        groups[key].append((row['start'], row['end']))
        projections[key[0]].add(key[1])
    merged = {}
    for key, intervals in groups.items():
        result = []
        for start, end in sorted(intervals):
            if result and start <= result[-1][1]:
                result[-1] = (result[-1][0], max(result[-1][1], end))
            else:
                result.append((start, end))
        merged[key] = ([v[0] for v in result], [v[1] for v in result])
    terminal, channels = Counter(), Counter()
    for row in used:
        span_fields(row, True)
        key = (row['source_sha256'], row['preprocessing_sha256'])
        if key[0] in projections and projections[key[0]] != {key[1]}:
            status = 'incomparable_preprocessing_projection'
        elif key in merged:
            starts, ends = merged[key]
            position = bisect_right(ends, row['start'])
            status = ('quarantined_span_reentry' if position < len(starts)
                      and starts[position] < row['end'] else 'no_overlap_in_supplied_spans')
        else:
            status = 'no_overlap_in_supplied_spans'
        terminal[status] += 1
        if status != 'no_overlap_in_supplied_spans':
            channels[row['channel']] += 1
    return dict(used_spans=len(used), quarantined_spans=len(quarantined),
                statuses=dict(terminal), affected_channels=dict(channels),
                coverage_certified=False, admission=False)
