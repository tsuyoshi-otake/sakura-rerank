"""Own one bounded retrospective metadata study or its regression test process."""
import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.relation_witnesses import WitnessGraph, component_labels
from partition import audit, require

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FRAME = REPO/'data/generated/issue-33-knbc-screening-v1/attempt-02'
PLAN = HERE/'plan-v1.json'
PREPARATION_COMMIT = 'a0d740e3dd6d7f2091bd496d06d49826e31d46e3'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def load_history():
    directory = REPO/'research/issue-33-knbc-screening'
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location('partition_knbc_history', directory/'history.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.authenticate(PREPARATION_COMMIT)
    return module.historical_records(), module.historical_aliases()


def old_replay(graph, aliases, exposed, target_ids):
    labels = component_labels(graph)
    wanted = {labels[i] for i,r in enumerate(graph.records) if r['stable_id'] in target_ids}
    members = defaultdict(list)
    for i, row in enumerate(graph.records):
        if labels[i] in wanted:
            members[labels[i]].append(row['stable_id'])
    keys = {key:canonical_json_hash(sorted(ids)) for key,ids in members.items()}
    blocked = {labels[i] for i,r in enumerate(graph.records)
               if r['population'] == 'historical' or r['stable_id'] in exposed}
    alias_groups = {labels[i] for i,r in enumerate(graph.records)
                    if r['stable_id'] in target_ids and r['input_hash'] in aliases}
    excluded, components = {}, {}
    for i, row in enumerate(graph.records):
        if row['stable_id'] not in target_ids:
            continue
        components[row['stable_id']] = keys[labels[i]]
        if labels[i] in blocked:
            excluded[row['stable_id']] = 'historical_or_consumed_source_relation'
        elif labels[i] in alias_groups:
            excluded[row['stable_id']] = 'historical_input_alias_relation'
    require(read(FRAME/'relations.private.json') == dict(excluded=excluded, components=components),
            'partition_original_decision_changed')
    return dict(component_identities=len(components), unchanged_exclusions=len(excluded))


def study(output):
    started = time.monotonic()
    plan = read(PLAN)
    for path, expected in {**plan['inputs'], **plan['code'], **plan['specification']}.items():
        require(sha(REPO/path) == expected, 'partition_frozen_bytes_changed')
    previous, aliases = load_history()
    slots = read(FRAME/'source-slots.private.json')['rows']
    exposed = {r['stable_id'] for r in previous if r['population'] == 'source_coverage'
               and r['source']['article_id'].startswith(('kwdlc:', 'tatoeba:', 'knbc:'))}
    new = []
    for slot in slots:
        if slot['source_coverage'] is not None:
            new.append(slot['source_coverage'])
        if slot['input'] is not None:
            new.append({k:slot['input'][k] for k in ('stable_id', 'population', 'source', 'input_hash')})
    print(json.dumps(dict(stage='bound_graph', nodes=len(previous)+len(new))), flush=True)
    graph = build_source_graph(previous+new)
    del previous, new
    require(graph.audit == read(REPO/'reports/issue-32-knbc-trace-v1.json')['trace']['graph'],
            'partition_graph_reference_changed')
    assignments = {r['stable_id']:'research_evaluation' for r in graph.records if r['population'] == 'evaluation'}
    reference = old_replay(graph, aliases, exposed, set(assignments))
    proposed = audit(graph, assignments, aliases, exposed)
    print(json.dumps(dict(stage='proposal_complete', **proposed['summary'])), flush=True)
    size = len(graph.records)
    reverse = WitnessGraph(list(reversed(graph.records)),
        array('I', (size-1-i for i in reversed(graph.right))),
        array('I', (size-1-i for i in reversed(graph.left))), array('B', reversed(graph.kinds)))
    replay = audit(reverse, dict(reversed(list(assignments.items()))), aliases, exposed)
    require(proposed['summary'] == replay['summary'] and sorted(proposed['rows'], key=lambda r:r['stable_id'])
            == sorted(replay['rows'], key=lambda r:r['stable_id']), 'partition_reverse_replay_changed')
    by_id = {r['stable_id']:r for r in proposed['rows']}
    census = []
    for slot in slots:
        identity = slot['input']['stable_id'] if slot['input'] is not None else None
        census.append(dict(index=slot['index'], input_id=identity,
            proposal=by_id.get(identity), original_pending_status=slot['status'],
            actual_terminal='already_consumed_reference_not_independent_test'))
    require(len(census) == plan['slots'] and len(by_id) == plan['input_hypotheses'], 'partition_acquisition_extent')
    save(output/'counterfactual-slots.private.json', dict(rows=census))
    minimum = read(REPO/'research/issue-33-knbc-screening/plan-v1.json')['readiness']
    summary = proposed['summary']
    feasible = (summary['metadata_only_unblocked'] >= minimum['minimum_retained_slots']
                and summary['metadata_only_unblocked_source_components'] >= minimum['minimum_recorded_components'])
    for path, expected in plan['inputs'].items():
        require(sha(REPO/path) == expected, 'partition_existing_input_mutated')
    result = dict(status='retrospective_metadata_complete_no_admission', plan_sha256=sha(PLAN),
        graph=graph.audit, old_reference=reference, proposed=summary,
        acquisition=dict(slots=len(slots), inputs=len(assignments),
            pending_without_input=dict(Counter(s['status'] for s in slots if s['input'] is None))),
        metadata_readiness=dict(sufficient=feasible, rule=minimum),
        missing_evidence=dict(consumption_footprint_rows=summary['metadata_only_unblocked'],
            complete_numeric_candidate_rows=summary['metadata_only_unblocked'],
            certified_ime_gold_rows=summary['metadata_only_unblocked']),
        verification=dict(full_old_replay=True, reverse_records_edges_assignments=True,
            retained_unique_inputs=True, retained_source_history_and_role_disjoint=True),
        private_slots_sha256=sha(output/'counterfactual-slots.private.json'),
        current_history=dict(all_reference_slots_consumed=True, actual_independent_test_rows=0,
                             existing_exclusions_restored=0),
        elapsed_seconds=round(time.monotonic()-started, 3),
        model_calls=0, fits=0, new_source_slots=0, training_admission=False,
        calibration=False, gold_admission=False, final_test=False, adopted_accuracy_percent=90.72)
    save(output/'report.json', result)
    return dict(status=result['status'], report_sha256=sha(output/'report.json'))


def tests(output):
    suite = unittest.defaultTestLoader.discover(str(REPO/'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    value = dict(status='passed' if result.wasSuccessful() else 'failed', tests=result.testsRun,
                 failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    save(output/'report.json', value)
    require(result.wasSuccessful() and not result.skipped, 'partition_regression_failed')
    return value


def own(stage, output):
    output.mkdir(parents=True, exist_ok=False)
    save(output/'owner.json', dict(owner_pid=os.getpid(), stage=stage, seconds_limit=900, plan_sha256=sha(PLAN)))
    child, result, started = None, dict(status='failed', stage=stage), time.monotonic()
    try:
        with (output/'run.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, '-B', '-u', str(Path(__file__).resolve()), stage,
                '--worker', '--output', str(output)], cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONPATH':os.pathsep.join((str(REPO/'src'),str(REPO))),
                     'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONIOENCODING':'utf-8'},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            result['child_pid'] = child.pid
            print(json.dumps(dict(status='running', stage=stage, child_pid=child.pid)), flush=True)
            try:
                code = child.wait(timeout=900)
                result.update(status='complete' if code == 0 else 'failed', exit_code=code)
            except subprocess.TimeoutExpired:
                result['status'] = 'timed_out'
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'], capture_output=True, timeout=30)
            child.wait(timeout=30)
            result['exit_code'] = child.returncode
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(output/'terminal.json', result)
        print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('study', 'tests'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        try:
            print(json.dumps(globals()[args.stage](args.output)), flush=True)
        except Exception as error:
            print(json.dumps(dict(status='failed', error_type=type(error).__name__,
                error_code=str(error) if isinstance(error, ValueError) and str(error).isidentifier() else None)), flush=True)
            raise SystemExit(1)
    else:
        raise SystemExit(0 if own(args.stage, args.output) else 1)
