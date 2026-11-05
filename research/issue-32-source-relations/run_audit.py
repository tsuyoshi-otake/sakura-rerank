"""Reconstruct exact typed relations, fixed views and historical path certificates."""
from collections import Counter, defaultdict
import json
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.relation_witnesses import (
    KINDS, build_witness_graph, component_labels, exact_group_omissions, trace_paths)
from relation_common import (ROOT, PRIOR, PLAN, PLAN_COMMIT, EVALUATION_ROLES, boundary, load_population,
    component_summary, order_digest, read_json, save, scopes, sha, write_array)

CODE = ("src/sakura_rerank/data/relation_witnesses.py", "research/issue-32-source-relations/relation_common.py",
        "research/issue-32-source-relations/run_audit.py")


def compare_original(records, labels, roles):
    previous = read_json(PRIOR / "isolated/relations.json")
    members, historical = defaultdict(list), set()
    for row, label in zip(records, labels):
        members[label].append(row["stable_id"])
        if row["stable_id"] in roles:
            historical.add(label)
    hashes = {key: canonical_json_hash(sorted(ids)) for key, ids in members.items()}
    actual, excluded = {}, {}
    for row, label in zip(records, labels):
        if row["population"] == "train":
            actual[row["stable_id"]] = hashes[label]
            if label in historical:
                excluded[row["stable_id"]] = "historical_relation"
    if actual != previous["components"] or excluded != previous["excluded"]:
        raise ValueError("relation_full_closure_parity_failed")
    return dict(train_memberships=len(actual), excluded_rows=len(excluded), all_component_hashes_and_exclusions_equal=True)


def omission_contract(graph):
    groups = read_json(PRIOR / "relation-witnesses.json")["groups"]
    representatives = {g["coverage_ids"][0]: g["key"] for g in groups if g["kind"] == "sentence_signature"}
    signatures = set()
    for row in graph.records:
        if row["stable_id"] in representatives:
            signature = tuple(row["source"]["sentence_shingle_hashes"])
            if canonical_json_hash(list(signature)) != representatives[row["stable_id"]]:
                raise ValueError("relation_fixed_omission_signature_changed")
            signatures.add(signature)
    paragraphs = {g["key"] for g in groups if g["kind"] == "paragraph"}
    if len(signatures) != 31 or len(paragraphs) != 7:
        raise ValueError("relation_fixed_omission_population_changed")
    return exact_group_omissions(graph, paragraphs, signatures)


def path_summary(graph, identity, forest, roles, cohorts, newly):
    depths, masks, seed_roles = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for index, row in enumerate(graph.records):
        root = identity[index]
        distance = forest["distance"][root]
        for scope in scopes(row["stable_id"], cohorts, newly):
            depths[scope][str(distance)] += 1
            if distance >= 0:
                masks[scope]["+".join(name for k, name in enumerate(KINDS) if forest["content_mask"][root] & (1 << k)) or "source_input_only"] += 1
                seed_roles[scope][roles[graph.records[forest["seed"][root]]["stable_id"]]] += 1
    return dict(content_edge_distance=dict(depths), path_relation_sets=dict(masks), selected_root_roles=dict(seed_roles),
        distance_unit="Edges in the graph of source/input components; not raw-record shortest distance or a unique causal explanation.")


def run():
    records, roles, cohorts, newly, plan = load_population()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    print(json.dumps(dict(stage="recording_relation_witnesses", nodes=len(records))), flush=True)
    graph = build_witness_graph(records)
    print(json.dumps(dict(stage="witnesses_recorded", **graph.audit)), flush=True)
    artifacts = {name: write_array(name, getattr(graph, name)) for name in ("left", "right", "kinds")}
    omitted = omission_contract(graph)
    artifacts["fixed_omitted_edges"] = write_array("fixed-omitted-edges", omitted)
    views = {}
    full, identity = None, None
    for name, allowed in plan["views"].items():
        labels = component_labels(graph, allowed if isinstance(allowed, list) else KINDS,
                                  omitted=omitted if isinstance(allowed, str) else None)
        views[name] = component_summary(graph.records, labels, roles, cohorts, newly)
        if name == "full":
            full = labels
        if name == "identity_only":
            identity = labels
        print(json.dumps(dict(stage="diagnostic_view", view=name, cohorts=views[name]["cohorts"])), flush=True)
    if full is None or identity is None:
        raise ValueError("relation_required_views_missing")
    parity = compare_original(graph.records, full, roles)
    previous = read_json(PRIOR / "isolation.json")["audit"]
    if (graph.audit["conceptual_near_record_pairs"] != previous["near_pairs"]
            or graph.audit["actual_signature_comparisons"] != previous["near_signature_comparisons"]
            or views["full"]["components"] != previous["components"]):
        raise ValueError("relation_core_metrics_differ")
    artifacts["identity"] = write_array("identity", identity)
    artifacts["full"] = write_array("full", full)
    paths = {}
    for name, selected_roles in (("all_history", set(roles.values())), ("explicit_evaluation", EVALUATION_ROLES)):
        seeds = [i for i, row in enumerate(graph.records) if roles.get(row["stable_id"]) in selected_roles]
        forest = trace_paths(graph, identity, seeds)
        artifacts[name] = {key: write_array(name + "-" + key, values) for key, values in forest.items()}
        paths[name] = path_summary(graph, identity, forest, roles, cohorts, newly)
    result = dict(kind="source_relation_path_diagnostics", status="complete", plan_commit=PLAN_COMMIT,
        plan_sha256=sha(PLAN), execution_commit=head, implementation={p: sha(p) for p in CODE},
        graph=graph.audit, node_order_sha256=order_digest(graph.records), historical_roles=dict(Counter(roles.values())),
        views=views, path_certificates=paths, baseline_parity=parity,
        omitted_representative_edges=sum(omitted), artifacts=artifacts,
        interpretation="Diagnostic disconnection is not data admission. All nodes, including historical training and unknown roles, remain in every graph. No character-length threshold was selected or applied; exact stars and per-near-pair bipartite spanning trees preserve each view's connectivity, not all raw pair/path multiplicities.",
        rules_unchanged=True, exclusions_restored=0, training_labels_admitted=0, model_fits=0,
        model_inferences=0, final_test_used=False, gold_certified=False, safety_threshold=.0025)
    save(ROOT / "report.json", result)
    save("reports/issue-32-source-relations-v2.json", result)
    return dict(status=result["status"], graph=graph.audit, parity=parity)


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    execution = ROOT / "execution.json"
    if execution.exists() or (ROOT / "report.json").exists():
        raise ValueError("relation_attempt_already_terminal")
    started = time.monotonic()
    try:
        output = run()
    except Exception as error:
        save(execution, dict(status="failed", error_type=type(error).__name__, elapsed_seconds=round(time.monotonic() - started, 3)))
        print(json.dumps(dict(status="failed", error_type=type(error).__name__)), flush=True)
        raise SystemExit(1) from None
    save(execution, dict(status="complete", elapsed_seconds=round(time.monotonic() - started, 3), report_sha256=sha(ROOT / "report.json")))
    print(json.dumps(output), flush=True)
