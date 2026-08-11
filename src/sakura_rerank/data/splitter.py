"""Deterministic, leakage-safe assignment of contract records to splits."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    SPLITS,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    read_jsonl,
    validate_records,
    write_jsonl,
)


DEFAULT_SPLIT_RATIOS = {"train": 0.8, "dev": 0.1, "final-holdout": 0.1}
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8


class SplitError(ValueError):
    """Input records cannot be assigned without violating leakage invariants."""


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1

    def groups(self) -> dict[int, list[int]]:
        result: dict[int, list[int]] = defaultdict(list)
        for index in range(len(self.parent)):
            result[self.find(index)].append(index)
        return dict(result)


def _group_by_value(
    records: Sequence[Mapping[str, Any]], field: str, *, skip_none: bool = False
) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        value = record["source"][field]
        if value is None and skip_none:
            continue
        groups[str(value)].append(index)
    return dict(groups)


def _union_groups(union_find: _UnionFind, groups: Mapping[str, Sequence[int]]) -> int:
    duplicate_group_count = 0
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        duplicate_group_count += 1
        first = indexes[0]
        for index in indexes[1:]:
            union_find.union(first, index)
    return duplicate_group_count


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _near_duplicate_edges(
    records: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
) -> tuple[list[tuple[int, int]], _UnionFind]:
    """Find near duplicates using a shingle inverted index, not all-pairs scans."""

    if not 0.0 < threshold <= 1.0:
        raise SplitError("near_duplicate_threshold: must be in (0, 1]")
    shingle_sets = [
        set(record["source"]["sentence_shingle_hashes"]) for record in records
    ]
    inverted: dict[str, list[int]] = defaultdict(list)
    edges: list[tuple[int, int]] = []
    near_union = _UnionFind(len(records))
    for index, shingles in enumerate(shingle_sets):
        possible: set[int] = set()
        for shingle in sorted(shingles):
            possible.update(inverted.get(shingle, ()))
        for previous in sorted(possible):
            if _jaccard(shingles, shingle_sets[previous]) >= threshold:
                edges.append((previous, index))
                near_union.union(previous, index)
        for shingle in sorted(shingles):
            inverted[shingle].append(index)
    return edges, near_union


def _cross_split_group_count(
    groups: Mapping[str, Sequence[int]], assignments: Sequence[str]
) -> int:
    return sum(
        1
        for indexes in groups.values()
        if len(indexes) > 1 and len({assignments[index] for index in indexes}) > 1
    )


def _component_hash(stable_ids: Sequence[str]) -> str:
    payload = "\n".join(sorted(stable_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_ratios(ratios: Mapping[str, float]) -> dict[str, float]:
    if set(ratios) != set(SPLITS):
        raise SplitError("split_ratios: train, dev, and final-holdout are required")
    normalized = {}
    for split in SPLITS:
        value = ratios[split]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise SplitError("split_ratios: values must be positive numbers")
        normalized[split] = float(value)
    total = sum(normalized.values())
    if abs(total - 1.0) > 1e-9:
        raise SplitError("split_ratios: values must sum to one")
    return normalized


def assign_splits(
    records: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    split_ratios: Mapping[str, float] | None = None,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assign records while keeping every leakage component in one split.

    Existing non-null assignments are treated as immutable. If two records in
    one leakage component already carry different assignments, the operation
    fails instead of silently rewriting a prior train/dev/holdout decision.
    """

    normalized = validate_records(records, require_split=False)
    ratios = _validate_ratios(split_ratios or DEFAULT_SPLIT_RATIOS)
    union_find = _UnionFind(len(normalized))

    article_groups = _group_by_value(normalized, "article_id")
    paragraph_groups = _group_by_value(normalized, "paragraph_hash")
    template_groups = _group_by_value(normalized, "template_cluster_id", skip_none=True)
    article_group_count = _union_groups(union_find, article_groups)
    paragraph_group_count = _union_groups(union_find, paragraph_groups)
    template_group_count = _union_groups(union_find, template_groups)
    near_edges, near_union = _near_duplicate_edges(
        normalized, threshold=near_duplicate_threshold
    )
    for left, right in near_edges:
        union_find.union(left, right)

    components = union_find.groups()
    component_records = [
        sorted(indexes, key=lambda index: normalized[index]["stable_id"])
        for indexes in components.values()
    ]
    component_records.sort(
        key=lambda indexes: min(normalized[index]["stable_id"] for index in indexes)
    )

    assignments: dict[tuple[int, ...], str] = {}
    assigned_counts = {split: 0 for split in SPLITS}
    seed_text = str(seed)
    for indexes in component_records:
        existing = {
            normalized[index]["split"]
            for index in indexes
            if normalized[index]["split"] is not None
        }
        if len(existing) > 1:
            raise SplitError("immutable split assignment conflicts inside one leakage component")
        if existing:
            split = next(iter(existing))
            assignments[tuple(indexes)] = split
            assigned_counts[split] += len(indexes)

    unassigned = [
        indexes for indexes in component_records if tuple(indexes) not in assignments
    ]
    unassigned.sort(
        key=lambda indexes: hashlib.sha256(
            f"{seed_text}\0{min(normalized[index]['stable_id'] for index in indexes)}".encode(
                "utf-8"
            )
        ).hexdigest()
    )
    total_records = len(normalized)
    for indexes in unassigned:
        size = len(indexes)
        split = min(
            SPLITS,
            key=lambda candidate: (
                (assigned_counts[candidate] + size)
                / (total_records * ratios[candidate]),
                assigned_counts[candidate],
                SPLITS.index(candidate),
            ),
        )
        assignments[tuple(indexes)] = split
        assigned_counts[split] += size

    output: list[dict[str, Any]] = []
    assignment_by_index: list[str] = ["" for _ in normalized]
    for indexes in component_records:
        split = assignments[tuple(indexes)]
        for index in indexes:
            assignment_by_index[index] = split
            record = dict(normalized[index])
            record["split"] = split
            output.append(record)
    output.sort(key=lambda record: record["stable_id"])

    near_groups = {
        str(min(normalized[index]["stable_id"] for index in indexes)): indexes
        for indexes in near_union.groups().values()
        if len(indexes) > 1
    }
    component_hashes = sorted(
        _component_hash([normalized[index]["stable_id"] for index in indexes])
        for indexes in component_records
    )
    output_bytes = canonical_jsonl_bytes(output)
    report: dict[str, Any] = {
        "schema_version": 1,
        "seed": seed,
        "split_ratios": ratios,
        "record_count": len(output),
        "split_counts": {
            split: assignment_by_index.count(split) for split in SPLITS
        },
        "article_group_count": article_group_count,
        "paragraph_exact_group_count": paragraph_group_count,
        "sentence_near_duplicate_edge_count": len(near_edges),
        "sentence_near_duplicate_cluster_count": len(near_groups),
        "template_cluster_count": template_group_count,
        "leakage_component_count": len(component_records),
        "leakage_component_hashes": component_hashes,
        "near_duplicate_threshold": near_duplicate_threshold,
        "cross_split_leakage": {
            "article": _cross_split_group_count(article_groups, assignment_by_index),
            "paragraph_exact": _cross_split_group_count(
                paragraph_groups, assignment_by_index
            ),
            "sentence_near_duplicate": _cross_split_group_count(
                near_groups, assignment_by_index
            ),
            "template_cluster": _cross_split_group_count(
                template_groups, assignment_by_index
            ),
        },
        "content_sha256": hashlib.sha256(output_bytes).hexdigest(),
    }
    if any(value != 0 for value in report["cross_split_leakage"].values()):
        raise SplitError("splitter produced cross-split leakage")
    # Exercise the same canonical serializer used for persisted reports. This
    # also rejects accidental non-deterministic values before the caller writes.
    canonical_json_bytes(report)
    return output, report


def split_jsonl(
    input_path: str,
    output_path: str,
    report_path: str,
    *,
    seed: int,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> tuple[str, str]:
    """CLI helper: split an unassigned JSONL file and write both artifacts."""

    records = read_jsonl(input_path, require_split=False)
    output, report = assign_splits(
        records, seed=seed, near_duplicate_threshold=near_duplicate_threshold
    )
    output_hash = write_jsonl(output_path, output)
    report_payload = canonical_json_bytes(report) + b"\n"
    from pathlib import Path

    Path(report_path).write_bytes(report_payload)
    return output_hash, hashlib.sha256(report_payload).hexdigest()
