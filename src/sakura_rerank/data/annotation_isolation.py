"""Larger retained-source audit using the frozen relation core and thresholds.

The 500k-node adapter stays byte-identical for historical experiment bindings.
This research boundary accepts at most the core's existing one-million limit.
"""
from collections import Counter, defaultdict

from .contracts import canonical_json_hash
from .growth_isolation import validate_metadata
from .splitter import MAX_COMPONENT_INPUT_RECORDS, _build_leakage_components, _UnionFind, _union_groups


def isolate_annotations(records):
    if not 1 <= len(records) <= MAX_COMPONENT_INPUT_RECORDS:
        raise ValueError("annotation_isolation_record_bound")
    identifiers = set()
    for row in records:
        if row["stable_id"] in identifiers:
            raise ValueError("annotation_isolation_duplicate_id")
        identifiers.add(row["stable_id"])
        if row.get("population") == "source_coverage":
            if set(row) != {"stable_id", "population", "source"}:
                raise ValueError("annotation_source_only_has_input_or_extra_state")
            validate_metadata(dict(row, population="historical"))
        else:
            validate_metadata(row)
    leakage = _build_leakage_components(records, near_duplicate_threshold=0.8)
    union = _UnionFind(len(records))
    _union_groups(union, {str(i): members for i, members in enumerate(leakage.component_records)})
    inputs = defaultdict(list)
    for i, row in enumerate(records):
        if "input_hash" in row:
            inputs[row["input_hash"]].append(i)
    duplicate_groups = _union_groups(union, inputs)
    excluded, components, counts, sizes = {}, {}, Counter(), []
    population_components = Counter()
    for members in union.groups().values():
        populations = {records[i]["population"] for i in members} - {"source_coverage"}
        reason = "historical_relation" if "historical" in populations else (
            "cross_partition_relation" if {"train", "evaluation"} <= populations else None)
        key = canonical_json_hash(sorted(records[i]["stable_id"] for i in members))
        sizes.append(len(members))
        population_components["+".join(sorted(populations)) or "source_only"] += 1
        for i in members:
            row = records[i]
            if row["population"] in ("historical", "source_coverage"):
                continue
            components[row["stable_id"]] = key
            if reason:
                excluded[row["stable_id"]] = reason
            counts[row["population"] + "/" + (reason or "retained")] += 1
    shared_paragraphs = sum({"historical", "source_coverage"} <= {records[i]["population"] for i in group}
                            for group in leakage.paragraph_groups.values())
    return excluded, components, dict(counts=dict(counts), components=len(sizes), largest_component=max(sizes),
        source_only_nodes=sum(r["population"] == "source_coverage" for r in records), source_only_input_edges=0,
        exact_input_duplicate_groups=duplicate_groups, near_pairs=leakage.near_pair_count,
        near_signature_comparisons=leakage.near_signature_comparison_count,
        records=len(records), population_component_counts=dict(population_components),
        historical_coverage_shared_paragraph_groups=shared_paragraphs)
