"""Independent edge legality, reverse connectivity and all-parent-path checks."""
from array import array
from collections import Counter, defaultdict
import json

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.relation_witnesses import KINDS
from sakura_rerank.data.splitter import _UnionFind
from relation_common import (ROOT, PRIOR, EVALUATION_ROLES, load_population, order_digest,
    read_array, read_json, save, sha)


def normalized(labels):
    minima = {}
    for index, label in enumerate(labels):
        minima.setdefault(label, index)
    return [minima[label] for label in labels]


def verify():
    records, roles, cohorts, newly, plan = load_population()
    records.sort(key=lambda row: row["stable_id"])
    report, execution = read_json(ROOT / "report.json"), read_json(ROOT / "execution.json")
    if (execution["status"] != "complete" or execution["report_sha256"] != sha(ROOT / "report.json")
            or order_digest(records) != report["node_order_sha256"]):
        raise ValueError("relation_verifier_execution_or_order_differs")
    for path, expected in report["implementation"].items():
        if sha(path) != expected:
            raise ValueError("relation_frozen_implementation_changed")
    artifacts = report["artifacts"]
    left, right, kinds, omitted = (read_array(artifacts[name], maximum=4_000_000)
                                   for name in ("left", "right", "kinds", "fixed_omitted_edges"))
    if len({len(left), len(right), len(kinds), len(omitted), report["graph"]["representative_edges"]}) != 1:
        raise ValueError("relation_edge_array_lengths_differ")
    signatures, signature_members = [], defaultdict(list)
    for index, row in enumerate(records):
        signature = tuple(row["source"]["sentence_shingle_hashes"])
        signatures.append(signature)
        signature_members[signature].append(index)
    prior_groups = read_json(PRIOR / "relation-witnesses.json")["groups"]
    paragraph_omissions = {g["key"] for g in prior_groups if g["kind"] == "paragraph"}
    signature_omission_hashes = {g["key"] for g in prior_groups if g["kind"] == "sentence_signature"}
    signature_omissions = {signature for signature in signature_members if canonical_json_hash(list(signature)) in signature_omission_hashes}
    if len(paragraph_omissions) != 7 or len(signature_omissions) != 31:
        raise ValueError("relation_omission_reference_differs")
    expected_near_pairs = sum(len(v) * (len(v) - 1) // 2 for v in signature_members.values())
    near_pairs, edge_counts = defaultdict(list), Counter()
    for edge, (a, b, kind) in enumerate(zip(left, right, kinds)):
        if not 0 <= a < b < len(records) or not 0 <= kind < len(KINDS):
            raise ValueError("relation_edge_endpoint_invalid")
        x, y = records[a], records[b]
        sx, sy = x["source"], y["source"]
        if kind == 0:
            legal = sx["article_id"] == sy["article_id"]
        elif kind == 1:
            legal = sx["template_cluster_id"] is not None and sx["template_cluster_id"] == sy["template_cluster_id"]
        elif kind == 2:
            legal = "input_hash" in x and "input_hash" in y and x["input_hash"] == y["input_hash"]
        elif kind == 3:
            legal = sx["paragraph_hash"] == sy["paragraph_hash"]
        elif kind == 4:
            legal = signatures[a] == signatures[b]
        else:
            first, second = set(signatures[a]), set(signatures[b])
            legal = first != second and 5 * len(first & second) >= 4 * len(first | second)
            pair = tuple(sorted((signatures[a], signatures[b])))
            if pair not in near_pairs:
                expected_near_pairs += len(signature_members[signatures[a]]) * len(signature_members[signatures[b]])
            near_pairs[pair].append((a, b))
        if not legal:
            raise ValueError("relation_edge_has_no_source_evidence")
        expected_omission = ((kind == 3 and sx["paragraph_hash"] in paragraph_omissions)
                             or (kind == 4 and signatures[a] in signature_omissions))
        if bool(omitted[edge]) != expected_omission:
            raise ValueError("relation_fixed_omission_mask_differs")
        edge_counts[KINDS[kind]] += 1
    for pair, edges in near_pairs.items():
        members = signature_members[pair[0]] + signature_members[pair[1]]
        if len(edges) != len(members) - 1 or len(set(edges)) != len(edges):
            raise ValueError("relation_near_pair_spanning_count_differs")
        local = {index: position for position, index in enumerate(members)}
        union = _UnionFind(len(members))
        for a, b in edges:
            union.union(local[a], local[b])
        if len(union.groups()) != 1:
            raise ValueError("relation_near_pair_incomplete_connectivity")
    old_audit = read_json(PRIOR / "isolation.json")["audit"]
    if (dict(edge_counts) != report["graph"]["edge_kinds"] or expected_near_pairs != old_audit["near_pairs"]
            or sum(omitted) != report["omitted_representative_edges"]):
        raise ValueError("relation_all_near_pair_mass_or_edge_counts_differ")

    def scope_names(identifier):
        value = cohorts.get(identifier)
        if value is None:
            return []
        names = [value]
        if value != "new_annotation":
            names.append("old_train")
            if identifier in newly:
                names.append("old_train/newly_connected_in_49")
        return names

    def summary(labels):
        masks, sizes = defaultdict(int), Counter(labels)
        for row, label in zip(records, labels):
            role = roles.get(row["stable_id"])
            if role is not None:
                masks[label] |= 1 if role in EVALUATION_ROLES else 2 if role == "frozen_train" else 4
        counts = defaultdict(Counter)
        for row, label in zip(records, labels):
            flags = masks[label]
            for scope in scope_names(row["stable_id"]):
                target = counts[scope]
                for key, yes in (("rows", True), ("all_history_connected", flags != 0),
                    ("explicit_evaluation_connected", bool(flags & 1)), ("known_training_connected", bool(flags & 2)),
                    ("unknown_history_connected", bool(flags & 4)), ("not_connected_to_any_history", flags == 0)):
                    target[key] += yes
        return dict(components=len(sizes), largest_component_nodes=max(sizes.values()), cohorts=dict(counts)), masks

    full_labels, identity = None, None
    masks = None
    for view, allowed in plan["views"].items():
        cut = isinstance(allowed, str)
        allowed = set(KINDS if cut else allowed)
        union = _UnionFind(len(records))
        # Independent reverse group construction, not the published star edges.
        for kind in ("article", "author", "input", "paragraph", "sentence_exact"):
            if kind not in allowed:
                continue
            leaders = {}
            for index in range(len(records) - 1, -1, -1):
                row, source = records[index], records[index]["source"]
                value = (source["article_id"] if kind == "article" else source["template_cluster_id"] if kind == "author"
                    else row.get("input_hash") if kind == "input" else source["paragraph_hash"] if kind == "paragraph" else signatures[index])
                if value is None or (cut and ((kind == "paragraph" and value in paragraph_omissions)
                                             or (kind == "sentence_exact" and value in signature_omissions))):
                    continue
                if value in leaders:
                    union.union(index, leaders[value])
                else:
                    leaders[value] = index
        if "sentence_near" in allowed:
            for edge in range(len(left) - 1, -1, -1):
                if kinds[edge] == 5:
                    union.union(left[edge], right[edge])
        labels = array("I", (union.find(i) for i in range(len(records))))
        observed, observed_masks = summary(labels)
        if observed != report["views"][view]:
            raise ValueError("relation_reverse_view_recount_differs")
        if view in ("full", "identity_only"):
            saved = read_array(artifacts["full" if view == "full" else "identity"], maximum=1_000_000)
            if normalized(saved) != normalized(labels):
                raise ValueError("relation_saved_component_memberships_differ")
            if view == "full":
                full_labels, masks = labels, observed_masks
            else:
                identity = saved
    if full_labels is None or identity is None or masks is None:
        raise ValueError("relation_required_view_verification_missing")
    groups = defaultdict(list)
    for row, label in zip(records, full_labels):
        groups[label].append(row["stable_id"])
    hashes = {label: canonical_json_hash(ids) for label, ids in groups.items()}
    original = read_json(PRIOR / "isolated/relations.json")
    for row, label in zip(records, full_labels):
        key = row["stable_id"]
        if row["population"] == "train" and (original["components"][key] != hashes[label]
                or (key in original["excluded"]) != bool(masks[label])):
            raise ValueError("relation_original_component_hash_differs")

    roots = set(identity)
    verified_parents = {}
    for name, allowed_roles in (("all_history", set(roles.values())), ("explicit_evaluation", EVALUATION_ROLES)):
        forest = {key: read_array(value, maximum=1_000_000) for key, value in artifacts[name].items()}
        if any(len(value) != len(records) for value in forest.values()):
            raise ValueError("relation_forest_size_differs")
        parent, edges, seeds, distances, path_masks = (forest[k] for k in ("parent", "edge", "seed", "distance", "content_mask"))
        for root in roots:
            should_reach = bool(masks[full_labels[root]] & (7 if name == "all_history" else 1))
            depth = distances[root]
            if (depth >= 0) != should_reach:
                raise ValueError("relation_path_reachability_differs")
            if depth == -1:
                if parent[root] != -1 or edges[root] != -1 or seeds[root] != -1 or path_masks[root]:
                    raise ValueError("relation_unreachable_state_not_terminal")
                continue
            seed = seeds[root]
            if not 0 <= seed < len(records) or roles.get(records[seed]["stable_id"]) not in allowed_roles:
                raise ValueError("relation_path_root_role_invalid")
            if depth == 0:
                if parent[root] != root or edges[root] != -1 or identity[seed] != root or path_masks[root]:
                    raise ValueError("relation_path_root_state_invalid")
            else:
                previous, edge = parent[root], edges[root]
                if (previous not in roots or not 0 <= edge < len(left) or kinds[edge] < 3
                        or {identity[left[edge]], identity[right[edge]]} != {root, previous}
                        or distances[previous] != depth - 1 or seeds[previous] != seed
                        or path_masks[root] != path_masks[previous] | (1 << kinds[edge])):
                    raise ValueError("relation_path_parent_evidence_invalid")
        for a, b, kind in zip(left, right, kinds):
            x, y = identity[a], identity[b]
            if kind >= 3 and distances[x] >= 0 and abs(distances[x] - distances[y]) > 1:
                raise ValueError("relation_bfs_distance_not_minimal")
        depths, relations, root_roles = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        for index, row in enumerate(records):
            root = identity[index]
            for scope in scope_names(row["stable_id"]):
                depths[scope][str(distances[root])] += 1
                if distances[root] >= 0:
                    kind_names = [name for k, name in enumerate(KINDS) if path_masks[root] & (1 << k)]
                    relations[scope]["+".join(kind_names) or "source_input_only"] += 1
                    root_roles[scope][roles[records[seeds[root]]["stable_id"]]] += 1
        expected = report["path_certificates"][name]
        if (depths != expected["content_edge_distance"] or relations != expected["path_relation_sets"]
                or root_roles != expected["selected_root_roles"]):
            raise ValueError("relation_path_count_recount_differs")
        verified_parents[name] = dict(identity_components=len(roots), reachable_components=sum(distances[r] >= 0 for r in roots),
            parent_edges=sum(distances[r] > 0 for r in roots), all_paths_acyclic=True, all_parent_relations_verified=True)
    result = dict(kind="source_relation_path_verification", status="passed", nodes=len(records),
        legal_representative_edges=len(left), distinct_near_signature_pairs=len(near_pairs),
        conceptual_near_pairs_recounted=expected_near_pairs, fixed_views_recounted=len(plan["views"]),
        train_component_hashes_verified=len(original["components"]), forests=verified_parents,
        report_sha256=sha(ROOT / "report.json"), script_sha256=sha(__file__),
        model_fits=0, model_inferences=0, final_test_used=False, exclusions_restored=0, gold_certified=False)
    save(ROOT / "verification.json", result)
    save("reports/issue-32-source-relations-verification-v2.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(verify()))
