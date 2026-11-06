"""Bind the complete existing source graph and later consumed input aliases."""
from collections import Counter
import gzip
import importlib.util
import json
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.knbc_research import classify_frame, project_member, source_metadata
from prepare import ARCHIVE, REPO, ROOT, authenticate, archive, member_bytes, pilot_history, read, require, save, sha

CONSUMPTION = REPO/'data/generated/issue-35-source-consumption-v1'
TRAIN = REPO/'data/generated/issue-33-annotation-comparison-v1/attempt-02/scope-v1/cohorts/rows.jsonl.gz'
REBUILDS = REPO/'data/generated/issue-31-reading-rebuild-v1/attempt-01/requests.json'
EXTENTS = REPO/'data/generated/issue-31-source-extents-v1/attempt-01/requests.json'
NATIVE = REPO/'.codex/goal-loop/issue-35-native-paths/native-a/capture.jsonl'


def binding_inputs():
    paths = [TRAIN, REBUILDS, EXTENTS, NATIVE,
        CONSUMPTION/'consumed-slots.json', CONSUMPTION/'source-exposure-report.json',
        REPO/'data/generated/issue-35-source-pilot-v1/decoded-pilot.json',
        REPO/'data/generated/issue-35-source-units-v1/source-units.json',
        REPO/'data/generated/issue-35-source-units-v1/requests.json',
        REPO/'research/issue-35-source-pilot/history-binding-v1.json',
        REPO/'research/issue-35-source-consumption/history-binding-v1.json',
        REPO/'research/issue-35-source-consumption/source-exposure-binding-v1.json',
        REPO/'research/issue-34-cpu-proposals/plan-v1.json',
        REPO/'research/issue-31-source-extents/native-binding-v1.json',
        REPO/'research/issue-31-reading-rebuild/native-binding-v1.json',
        REPO/'reports/issue-35-native-paths-v1.json']
    history = read(REPO/'research/issue-35-source-pilot/history-binding-v1.json')
    paths.extend(REPO/p for p in history['history_artifacts'])
    return sorted(set(paths))


def binding_code():
    paths = ['research/issue-35-source-consumption/isolate_consumption.py',
        'research/issue-35-source-consumption/consume35_common.py',
        'research/issue-35-source-pilot/isolate_pilot.py', 'research/issue-35-source-pilot/pilot35_common.py',
        'research/issue-33-annotation-experiment/cohort.py', 'research/issue-33-annotation-experiment/experiment_common.py',
        'src/sakura_rerank/data/reconstruction_graph.py', 'src/sakura_rerank/data/relation_witnesses.py',
        'src/sakura_rerank/data/splitter.py', 'src/sakura_rerank/data/growth_isolation.py']
    return [REPO/p for p in paths]


def historical_records():
    path = REPO/'research/issue-35-source-consumption'
    sys.path.insert(0, str(path))
    try:
        spec = importlib.util.spec_from_file_location('knbc_previous_consumption', path/'isolate_consumption.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous, _ = module.history_records()
    finally:
        sys.path.pop(0)
    require(len(previous) == 989018, 'knbc_screening_history_base_count')
    for row in read(CONSUMPTION/'consumed-slots.json')['rows']:
        if row['source_coverage'] is not None:
            previous.append(row['source_coverage'])
        previous.extend(dict(stable_id=r['stable_id'], population='historical', source=r['source'],
                             input_hash=r['input_hash']) for r in row['inputs'])
    require(len(previous) == 991255, 'knbc_screening_history_extended_count')
    _, pilot = pilot_history()
    for row in pilot:
        if row['annotation'] is not None:
            source = source_metadata(row, row['annotation']['annotation_surface'])
            previous.append(dict(stable_id='knbc-format-source-'+canonical_json_hash(row['path']),
                                 population='source_coverage', source=source))
    require(len(previous) == 991354, 'knbc_screening_history_pilot_count')
    return previous


def historical_aliases():
    aliases, count = set(), 0
    with gzip.open(TRAIN, 'rb') as stream:
        for line in stream:
            require(len(line) <= 256*1024, 'knbc_screening_train_metadata_line')
            value = json.loads(line)['encoder_input']
            aliases.add(canonical_json_hash([value['left_context'], value['reading']]))
            aliases.add(canonical_json_hash(['', value['reading']]))
            count += 1
    require(count == 75000, 'knbc_screening_train_input_count')
    for row in read(REBUILDS)['requests']+read(EXTENTS)['all_requests']:
        aliases.add(canonical_json_hash(['', row['reading']]))
    native_events = [json.loads(line) for line in NATIVE.read_bytes().splitlines()]
    require(len(native_events) == 62, 'knbc_screening_native_history_extent')
    for event in native_events:
        for capture in event['captures']:
            reading = bytes.fromhex(capture['reading_hex']).decode('utf-8')
            aliases.add(canonical_json_hash(['', reading]))
    return aliases


def history(commit):
    start = time.monotonic()
    plan = authenticate(commit)
    prep = read(ROOT/'preparation.json')
    require(sha(ROOT/'source-slots.private.json') == prep['slots_sha256'], 'knbc_screening_preparation_identity')
    save(ROOT/'history-reservation.json', dict(commit=commit, slots_sha256=prep['slots_sha256'], fits=0))
    previous = historical_records()
    rows = read(ROOT/'source-slots.private.json')['rows']
    exposed = {r['stable_id'] for r in previous if r['population'] == 'source_coverage'
               and r['source']['article_id'].startswith(('kwdlc:', 'tatoeba:', 'knbc:'))}
    new = []
    for row in rows:
        if row['source_coverage'] is not None:
            new.append(row['source_coverage'])
        if row['input'] is not None:
            new.append({k:row['input'][k] for k in ('stable_id', 'population', 'source', 'input_hash')})
    records = previous+new
    require(len(records) <= plan['limits']['graph_nodes'], 'knbc_screening_complete_graph_bound')
    aliases = historical_aliases()
    print(json.dumps(dict(stage='complete_history_forward', previous_nodes=len(previous), new_nodes=len(new),
                         aliases=len(aliases), exposed_sources=len(exposed))), flush=True)
    excluded, components, audit = classify_frame(records, aliases, exposed)
    print(json.dumps(dict(stage='complete_history_reverse', nodes=len(records))), flush=True)
    require((excluded, components, audit) == classify_frame(list(reversed(records)), aliases, exposed),
            'knbc_screening_history_reverse_mismatch')
    slots = []
    for row in rows:
        status = row['status']
        identity = row['input']['stable_id'] if row['input'] is not None else None
        if identity is not None:
            status = excluded.get(identity, 'retained_for_candidate_binding')
        slots.append(dict(index=row['index'], status=status, input_id=identity,
                          component=components.get(identity)))
    retained = [r for r in slots if r['status'] == 'retained_for_candidate_binding']
    component_count = len({r['component'] for r in retained})
    ready = (len(retained) >= plan['readiness']['minimum_retained_slots']
             and component_count >= plan['readiness']['minimum_recorded_components'])
    save(ROOT/'history-slots.private.json', dict(rows=slots))
    save(ROOT/'relations.private.json', dict(excluded=excluded, components=components))
    report = dict(status='candidate_binding_ready_not_fit_authorized' if ready else 'insufficient_do_not_fit',
        previous_nodes=len(previous), new_nodes=len(new), all_nodes=len(records),
        slot_count=len(slots), statuses=dict(Counter(r['status'] for r in slots)),
        retained_slots=len(retained), retained_recorded_components=component_count, audit=audit,
        full_reverse_parity=True, history_slots_sha256=sha(ROOT/'history-slots.private.json'),
        relations_sha256=sha(ROOT/'relations.private.json'), elapsed_seconds=round(time.monotonic()-start, 3),
        numeric_candidate_input_history_pending=True, authorship_independence_certified=False,
        statistical_independence_certified=False, original_labels_changed=0, model_calls=0, fits=0,
        training_admission=False, gold_admission=False, calibration=False, final_test=False)
    save(ROOT/'history-report.json', report)
    return report


def verify(commit):
    authenticate(commit)
    reservation = read(ROOT/'selection.private.json')
    rows = read(ROOT/'source-slots.private.json')['rows']
    prep = read(ROOT/'preparation.json')
    events = [json.loads(line) for line in (ROOT/'consumption-ledger.private.jsonl').read_bytes().splitlines()]
    previous = sha(ROOT/'consumption-reservation.json')
    with archive() as arc:
        for event, slot, row in zip(events, reservation['slots'], rows, strict=True):
            require(event['index'] == slot['index'] == row['index'], 'knbc_screening_verify_slot_order')
            value = dict(event)
            digest = value.pop('event_sha256')
            require(value['previous'] == previous and canonical_json_hash(value) == digest,
                    'knbc_screening_verify_ledger')
            previous = digest
            raw = member_bytes(arc, slot)
            try:
                derived = project_member(raw, slot)
            except (ValueError, UnicodeError) as error:
                require(row['input'] is None and row['source_coverage'] is None, 'knbc_screening_verify_failed_slot')
                code = str(error) if isinstance(error, ValueError) and str(error).isidentifier() else 'invalid_source_encoding'
                require(row['status'] == 'pending_'+code, 'knbc_screening_verify_failure_reason')
                continue
            require(derived['source_coverage'] == row['source_coverage'], 'knbc_screening_verify_source')
            if row.get('documentation_exact_hit'):
                require(row['input'] is None and row['status'] == 'pending_exposed_documentation', 'knbc_screening_verify_documentation')
            else:
                require(derived['input'] == row['input'] and derived['status'] == row['status'], 'knbc_screening_verify_input')
            if row['input'] is not None:
                # Separate raw-column grouping and scalar concatenation, not project_member output.
                groups, current = [], []
                for line in raw.decode('utf-8').splitlines():
                    if line.startswith('* '):
                        if current:
                            groups.append(current)
                        current = []
                    elif line and not line.startswith(('#', '+ ', '@ ')) and line != 'EOS':
                        current.append(line.split(maxsplit=11))
                if current:
                    groups.append(current)
                chosen = groups[row['selected_bunsetsu']]
                require(''.join(t[0] for t in chosen) == row['input']['source_surface']
                        and ''.join(t[1] for t in chosen) == row['input']['reading'], 'knbc_screening_verify_raw_fields')
    require(len(rows) == len(events) == 2786 and previous == prep['ledger_head'], 'knbc_screening_verify_extent')
    require(sha(ROOT/'source-slots.private.json') == prep['slots_sha256']
            and sha(ROOT/'consumption-ledger.private.jsonl') == prep['ledger_sha256'], 'knbc_screening_verify_hashes')
    history = read(ROOT/'history-report.json')
    terminals = read(ROOT/'history-slots.private.json')['rows']
    require(len(terminals) == len(rows) and dict(Counter(r['status'] for r in terminals)) == history['statuses'],
            'knbc_screening_verify_history_census')
    result = dict(status='passed', source_slots=len(rows), ledger_events=len(events),
                  literal_input_pairs=sum(r['input'] is not None for r in rows),
                  history_report_sha256=sha(ROOT/'history-report.json'), source_archive_sha256=sha(ARCHIVE),
                  new_source_replacements=0, fits=0, model_calls=0, final_test=False)
    save(ROOT/'verification.json', result)
    return result
