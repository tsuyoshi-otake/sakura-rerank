"""Typed connectivity certificates for research source isolation, never admission.

Equal-key groups use spanning stars; the frozen signature join emits one edge
per matching signature pair. Connectivity is exact, but these are not all raw
record pairs and compressed path lengths are not raw-graph shortest distances.
"""
from array import array
from collections import Counter, deque
from dataclasses import dataclass, field

from .growth_isolation import validate_metadata
from .splitter import (MAX_COMPONENT_INPUT_RECORDS, _UnionFind, _group_by_value,
                       _union_groups, _union_near_duplicates)

KINDS = ("article", "author", "input", "paragraph", "sentence_exact", "sentence_near")
IDENTITY_KINDS = frozenset(KINDS[:3])
MAX_EDGES = 4_000_000


@dataclass
class WitnessGraph:
    records: list
    left: array = field(default_factory=lambda: array("I"))
    right: array = field(default_factory=lambda: array("I"))
    kinds: array = field(default_factory=lambda: array("B"))
    audit: dict = field(default_factory=dict)


class _Recorder:
    def __init__(self, graph, maximum):
        self.graph, self.maximum, self.kind = graph, maximum, 0

    def union(self, left, right):
        if len(self.graph.left) >= self.maximum:
            raise ValueError("relation_witness_edge_bound")
        kind = self.kind
        if kind == 4:
            records = self.graph.records
            if records[left]["source"]["sentence_shingle_hashes"] != records[right]["source"]["sentence_shingle_hashes"]:
                kind = 5
        self.graph.left.append(min(left, right))
        self.graph.right.append(max(left, right))
        self.graph.kinds.append(kind)


def build_witness_graph(records, *, max_edges=MAX_EDGES):
    """Validate and sort hash-only nodes; record exact existing relation edges."""
    if (not 1 <= len(records) <= MAX_COMPONENT_INPUT_RECORDS
            or type(max_edges) is not int or not 1 <= max_edges <= MAX_EDGES):
        raise ValueError("relation_witness_population_bound")
    ordered = sorted(records, key=lambda row: row["stable_id"])
    previous = None
    for row in ordered:
        if row["stable_id"] == previous:
            raise ValueError("relation_witness_duplicate_id")
        previous = row["stable_id"]
        if row["population"] == "source_coverage":
            if set(row) != {"stable_id", "population", "source"}:
                raise ValueError("relation_source_only_has_input_or_extra_state")
            validate_metadata(dict(row, population="historical"))
        else:
            validate_metadata(row)
    graph = WitnessGraph(ordered)
    recorder = _Recorder(graph, max_edges)
    groups = {}
    for kind, source_field in ((0, "article_id"), (1, "template_cluster_id"), (3, "paragraph_hash")):
        recorder.kind = kind
        groups[KINDS[kind]] = _union_groups(recorder, _group_by_value(ordered, source_field, skip_none=kind == 1))
    inputs = {}
    for index, row in enumerate(ordered):
        if "input_hash" in row:
            inputs.setdefault(row["input_hash"], []).append(index)
    recorder.kind = 2
    groups["input"] = _union_groups(recorder, inputs)
    recorder.kind = 4
    pairs, signatures, comparisons, _ = _union_near_duplicates(ordered, recorder, threshold=0.8)
    graph.audit = dict(nodes=len(ordered), representative_edges=len(graph.left),
        edge_kinds={KINDS[k]: count for k, count in sorted(Counter(graph.kinds).items())},
        duplicate_key_groups=groups, conceptual_near_record_pairs=pairs,
        distinct_signatures=signatures, actual_signature_comparisons=comparisons)
    return graph


def component_labels(graph, allowed=KINDS, *, omitted=None):
    """Diagnostic connectivity labels. No split, exclusion or admission is written."""
    if not set(allowed) <= set(KINDS) or (omitted is not None and len(omitted) != len(graph.left)):
        raise ValueError("relation_view_contract")
    active = {KINDS.index(name) for name in allowed}
    union = _UnionFind(len(graph.records))
    for edge, (left, right, kind) in enumerate(zip(graph.left, graph.right, graph.kinds)):
        if kind in active and (omitted is None or not omitted[edge]):
            union.union(left, right)
    return array("I", (union.find(i) for i in range(len(graph.records))))


def exact_group_omissions(graph, paragraph_hashes, signatures):
    """A fixed sensitivity view, not permission to ignore repeated source text."""
    omitted = array("B", [0]) * len(graph.left)
    for edge, (left, kind) in enumerate(zip(graph.left, graph.kinds)):
        source = graph.records[left]["source"]
        if kind == 3:
            omitted[edge] = source["paragraph_hash"] in paragraph_hashes
        elif kind == 4:
            omitted[edge] = tuple(source["sentence_shingle_hashes"]) in signatures
    return omitted


def trace_paths(graph, identity, seed_indices):
    """BFS on source/input components; each parent names an original content edge.

    Every unreachable component stays explicit (-1). Source-only nodes do not
    become roots unless their actual component contains a supplied historical seed.
    """
    size = len(graph.records)
    if (len(identity) != size or any(not 0 <= root < size for root in identity)
            or any(identity[root] != root for root in identity)):
        raise ValueError("relation_identity_labels_invalid")
    seeds = sorted(set(seed_indices))
    if any(type(i) is not int or not 0 <= i < size for i in seeds):
        raise ValueError("relation_seed_invalid")
    offsets = array("I", [0]) * (size + 1)
    for left, right, kind in zip(graph.left, graph.right, graph.kinds):
        a, b = identity[left], identity[right]
        if kind >= 3 and a != b:
            offsets[a + 1] += 1
            offsets[b + 1] += 1
    for i in range(size):
        offsets[i + 1] += offsets[i]
    adjacency = array("I", [0]) * offsets[-1]
    cursor = array("I", offsets)
    for edge, (left, right, kind) in enumerate(zip(graph.left, graph.right, graph.kinds)):
        a, b = identity[left], identity[right]
        if kind >= 3 and a != b:
            adjacency[cursor[a]], adjacency[cursor[b]] = edge, edge
            cursor[a] += 1
            cursor[b] += 1
    parent, via, seed, distance = (array("i", [-1]) * size for _ in range(4))
    masks = array("B", [0]) * size
    queue = deque()
    for index in seeds:
        root = identity[index]
        if distance[root] == -1:
            parent[root] = root
            seed[root] = index
            distance[root] = 0
            queue.append(root)
    while queue:
        current = queue.popleft()
        for position in range(offsets[current], offsets[current + 1]):
            edge = adjacency[position]
            a, b = identity[graph.left[edge]], identity[graph.right[edge]]
            other = b if a == current else a
            if distance[other] != -1:
                continue
            parent[other], via[other], seed[other] = current, edge, seed[current]
            distance[other] = distance[current] + 1
            masks[other] = masks[current] | (1 << graph.kinds[edge])
            queue.append(other)
    return dict(parent=parent, edge=via, seed=seed, distance=distance, content_mask=masks)
