"""Explain a consumed frame's relations; diagnostic views never admit rows."""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.relation_witnesses import KINDS, component_labels, trace_paths
from prepare import HERE, REPO, ROOT, authenticate, read, require, save, sha

PLAN = HERE/'trace-plan-v2.json'
PREPARATION_COMMIT = 'a0d740e3dd6d7f2091bd496d06d49826e31d46e3'
VIEWS = {
    'input_only': ['input'],
    'article_input': ['article', 'input'],
    'template_input': ['author', 'input'],
    'identity_only': list(KINDS[:3]),
    'content_only': list(KINDS[3:]),
    'identity_and_exact': list(KINDS[:5]),
    'without_template': [kind for kind in KINDS if kind != 'author'],
    'full': list(KINDS),
}


def source_kind(row):
    article = row['source']['article_id']
    return next((prefix for prefix in ('knbc', 'kwdlc', 'tatoeba')
                 if article.startswith(prefix+':')), 'other_history')


def census(labels, targets, seeds):
    touched = {name: {labels[i] for i in indices} for name, indices in seeds.items()}
    union = set().union(*touched.values())
    return dict(input_components=len({labels[i] for i in targets}),
        connected_inputs={name: sum(labels[i] in values for i in targets)
                          for name, values in touched.items()},
        any_seed_connected=sum(labels[i] in union for i in targets),
        unconnected_inputs=sum(labels[i] not in union for i in targets))


def verify_edges(graph):
    for a, b, kind in zip(graph.left, graph.right, graph.kinds):
        require(0 <= a < b < len(graph.records) and kind < len(KINDS), 'trace_edge_bounds')
        x, y = graph.records[a], graph.records[b]
        first, second = x['source'], y['source']
        if kind in (0, 1, 3):
            field = {0:'article_id', 1:'template_cluster_id', 3:'paragraph_hash'}[kind]
            legal = first[field] is not None and first[field] == second[field]
        elif kind == 2:
            legal = x.get('input_hash') is not None and x['input_hash'] == y.get('input_hash')
        elif kind == 4:
            legal = first['sentence_shingle_hashes'] == second['sentence_shingle_hashes']
        else:
            left, right = set(first['sentence_shingle_hashes']), set(second['sentence_shingle_hashes'])
            legal = left != right and 5*len(left & right) >= 4*len(left | right)
        require(legal, 'trace_edge_without_metadata_evidence')
    return len(graph.left)


def verify_forest(graph, identity, full, seeds, forest):
    roots, seeds = set(identity), set(seeds)
    reachable = {full[i] for i in seeds}
    parent, edge, seed, distance, mask = (forest[k] for k in
        ('parent', 'edge', 'seed', 'distance', 'content_mask'))
    for root in roots:
        depth = distance[root]
        require((depth >= 0) == (full[root] in reachable), 'trace_forest_reachability')
        if depth < 0:
            require(parent[root] == edge[root] == seed[root] == -1 and mask[root] == 0,
                    'trace_unreachable_terminal')
            continue
        require(seed[root] in seeds, 'trace_seed_not_authorized')
        if depth == 0:
            require(parent[root] == root and identity[seed[root]] == root
                    and edge[root] == -1 and mask[root] == 0, 'trace_root_certificate')
            continue
        previous, via = parent[root], edge[root]
        require(previous in roots and 0 <= via < len(graph.left), 'trace_parent_bounds')
        require({identity[graph.left[via]], identity[graph.right[via]]} == {root, previous}
                and graph.kinds[via] >= 3, 'trace_parent_edge')
        require(distance[previous] == depth-1 and seed[previous] == seed[root]
                and mask[root] == mask[previous] | (1 << graph.kinds[via]),
                'trace_parent_monotonicity')
    for a, b, kind in zip(graph.left, graph.right, graph.kinds):
        if kind < 3:
            require(identity[a] == identity[b], 'trace_identity_missing_edge')
        else:
            x, y = distance[identity[a]], distance[identity[b]]
            require((x < 0 and y < 0) or (x >= 0 and y >= 0 and abs(x-y) <= 1),
                    'trace_distance_not_minimal')
    return len(roots)


def trace(commit, output):
    started = time.monotonic()
    plan = read(PLAN)
    require(plan['views'] == VIEWS and plan['preparation_commit'] == commit,
            'trace_plan_contract')
    authenticate(commit)
    for path, digest in {**plan['inputs'], **plan['code']}.items():
        require(sha(REPO/path) == digest, 'trace_bound_bytes_changed')
    # Prior research also imports a module named history. Do not occupy that
    # global import name with this frame's adapter.
    spec = importlib.util.spec_from_file_location('knbc_trace_history', HERE/'history.py')
    history = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(history)
    previous = history.historical_records()
    exposed = {r['stable_id'] for r in previous if r['population'] == 'source_coverage'
               and source_kind(r) != 'other_history'}
    rows = read(ROOT/'source-slots.private.json')['rows']
    new = []
    for row in rows:
        if row['source_coverage'] is not None:
            new.append(row['source_coverage'])
        if row['input'] is not None:
            new.append({k:row['input'][k] for k in ('stable_id', 'population', 'source', 'input_hash')})
    aliases = history.historical_aliases()
    print(json.dumps(dict(stage='building_bound_graph', nodes=len(previous)+len(new))), flush=True)
    graph = build_source_graph(previous+new)
    del previous, new, rows
    targets = [i for i, row in enumerate(graph.records) if row['population'] == 'evaluation']
    seeds = {
        'historical_input': [i for i, row in enumerate(graph.records) if row['population'] == 'historical'],
        'consumed_source': [i for i, row in enumerate(graph.records) if row['stable_id'] in exposed],
        'known_input_alias': [i for i in targets if graph.records[i]['input_hash'] in aliases],
    }
    require(len(targets) == 1158 and len(seeds['known_input_alias']) == 167
            and len(exposed) == 6260 and len(aliases) == 96748, 'trace_history_extent')
    verification = dict(legal_edges=verify_edges(graph))
    full = component_labels(graph)
    original = read(ROOT/'relations.private.json')
    wanted = {full[i] for i in targets}
    members = defaultdict(list)
    for i, row in enumerate(graph.records):
        if full[i] in wanted:
            members[full[i]].append(row['stable_id'])
    keys = {label: canonical_json_hash(ids) for label, ids in members.items()}
    del members
    components = {graph.records[i]['stable_id']: keys[full[i]] for i in targets}
    blocked = {full[i] for i in seeds['historical_input']+seeds['consumed_source']}
    alias_blocked = {full[i] for i in seeds['known_input_alias']}
    excluded = {}
    for i in targets:
        if full[i] in blocked:
            excluded[graph.records[i]['stable_id']] = 'historical_or_consumed_source_relation'
        elif full[i] in alias_blocked:
            excluded[graph.records[i]['stable_id']] = 'historical_input_alias_relation'
    require(original == dict(excluded=excluded, components=components), 'trace_old_decision_differs')
    for key, value in graph.audit.items():
        require(value == read(ROOT/'history-report.json')['audit'][key], 'trace_graph_replay')
    verification.update(component_identities=len(components), preserved_exclusions=len(excluded))
    views, identity = {}, None
    for name, allowed in VIEWS.items():
        labels = full if name == 'full' else component_labels(graph, allowed)
        views[name] = census(labels, targets, seeds)
        if name == 'identity_only':
            identity = labels
        print(json.dumps(dict(stage='view_complete', view=name, **views[name])), flush=True)
    require(identity is not None, 'trace_identity_view_absent')
    paths, certificates = {}, {}
    for name, indices in seeds.items():
        forest = trace_paths(graph, identity, indices)
        checked = verify_forest(graph, identity, full, indices, forest)
        depths, masks, origins = Counter(), Counter(), Counter()
        witnesses = []
        for i in targets:
            root = identity[i]
            depth, seed = forest['distance'][root], forest['seed'][root]
            depths[str(depth)] += 1
            if depth >= 0:
                origins[source_kind(graph.records[seed])] += 1
                names = '+'.join(kind for k, kind in enumerate(KINDS) if forest['content_mask'][root] & (1 << k))
                masks[names or 'identity_only'] += 1
            chain, cursor = [], root
            while forest['distance'][cursor] > 0:
                via = forest['edge'][cursor]
                chain.append([graph.left[via], graph.right[via], KINDS[graph.kinds[via]]])
                cursor = forest['parent'][cursor]
            witnesses.append(dict(target_index=i, seed_index=seed, content_edges=chain))
        paths[name] = dict(verified_identity_roots=checked, content_edge_distance=dict(depths),
                          selected_path_content_kinds=dict(masks), selected_seed_source=dict(origins))
        certificates[name] = witnesses
    groups = []
    for label in sorted(wanted, key=lambda v: (-sum(full[i] == v for i in targets), keys[v])):
        indices = [i for i in targets if full[i] == label]
        groups.append(dict(inputs=len(indices), direct_known_inputs=sum(i in seeds['known_input_alias'] for i in indices),
            new_articles=len({graph.records[i]['source']['article_id'] for i in indices}),
            new_prefix_families=len({graph.records[i]['source']['template_cluster_id'] for i in indices}),
            seeds={name: sum(full[i] == label for i in values) for name, values in seeds.items()}))
    save(output/'path-witnesses.private.json', dict(node_order_sha256=canonical_json_hash(
        [r['stable_id'] for r in graph.records]), paths=certificates))
    # Recheck exact bytes after analysis: no diagnostic may mutate the old decision.
    for path, digest in plan['inputs'].items():
        require(sha(REPO/path) == digest, 'trace_old_input_mutated')
    result = dict(kind='consumed_knbc_relation_trace_v1', status='complete_diagnostic_only',
        plan_sha256=sha(PLAN), graph=graph.audit, seed_counts={k:len(v) for k,v in seeds.items()},
        views=views, paths=paths, new_input_components=groups, verification=verification,
        witnesses_sha256=sha(output/'path-witnesses.private.json'),
        elapsed_seconds=round(time.monotonic()-started, 3),
        interpretation='author edges use template_cluster_id; KNBC prefixes are not certified authors. Distances count content edges on the representative graph after identity contraction. Diagnostic omission is not admission or a new independent evaluation.',
        model_calls=0, fits=0, changed_exclusions=0, training_admission=False,
        gold_admission=False, calibration=False, final_test=False)
    save(output/'report.json', result)
    return dict(status=result['status'], report_sha256=sha(output/'report.json'))


def own(output):
    output.mkdir(parents=True, exist_ok=False)
    save(output/'owner.json', dict(owner_pid=os.getpid(), seconds_limit=900, plan_sha256=sha(PLAN)))
    child, result, started = None, dict(status='failed'), time.monotonic()
    try:
        with (output/'run.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, '-B', '-u', str(Path(__file__).resolve()), '--worker',
                '--output', str(output)], cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONPATH':os.pathsep.join((str(REPO/'src'), str(REPO))),
                     'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONIOENCODING':'utf-8'},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            result['child_pid'] = child.pid
            print(json.dumps(dict(status='running', child_pid=child.pid)), flush=True)
            try:
                code = child.wait(timeout=900)
                result.update(status='complete' if code == 0 else 'failed', exit_code=code)
            except subprocess.TimeoutExpired:
                result['status'] = 'timed_out'
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=30)
            child.wait(timeout=30)
            result['exit_code'] = child.returncode
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(output/'terminal.json', result)
        print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        try:
            print(json.dumps(trace(PREPARATION_COMMIT, args.output)), flush=True)
        except Exception as error:
            print(json.dumps(dict(status='failed', error_type=type(error).__name__,
                error_code=str(error) if isinstance(error, ValueError) and str(error).isidentifier() else None)), flush=True)
            raise SystemExit(1)
    else:
        raise SystemExit(0 if own(args.output) else 1)
