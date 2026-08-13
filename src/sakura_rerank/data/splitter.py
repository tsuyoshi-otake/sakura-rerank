"""Deterministic, leakage-safe assignment of contract records to splits."""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_atomic, write_bytes_pair_atomic
from .contracts import (
    ContractError,
    SPLITS,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    read_jsonl,
    validate_records,
)


DEFAULT_SPLIT_RATIOS = {"train": 0.8, "dev": 0.1, "final-holdout": 0.1}
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8
MAX_COMPONENT_INPUT_RECORDS = 1_000_000


class SplitError(ValueError):
    """Input records cannot be assigned without violating leakage invariants."""


@dataclass(frozen=True)
class _LeakageComponentBuild:
    """Shared, exact relation closure used by split assignment and exclusion."""

    article_groups: dict[str, list[int]]
    paragraph_groups: dict[str, list[int]]
    template_groups: dict[str, list[int]]
    article_group_count: int
    paragraph_group_count: int
    template_group_count: int
    near_pair_count: int
    near_signature_count: int
    near_signature_comparison_count: int
    near_union: _UnionFind
    component_records: list[list[int]]


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


def _union_near_duplicates(
    records: Sequence[Mapping[str, Any]],
    union_find: _UnionFind,
    *,
    threshold: float,
) -> tuple[int, int, int, _UnionFind]:
    """Union exact Jaccard matches with length and rarity-prefix filtering.

    Identical signatures are collapsed before the join. Distinct signatures are
    processed in nondecreasing length order and indexed only by a prefix ordered
    by global shingle rarity. The filters remove only pairs that cannot meet the
    threshold; every surviving pair is still checked by exact Jaccard.
    """

    if not 0.0 < threshold <= 1.0:
        raise SplitError("near_duplicate_threshold: must be in (0, 1]")
    signature_groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        signature = tuple(record["source"]["sentence_shingle_hashes"])
        signature_groups[signature].append(index)
    signature_items = sorted(
        signature_groups.items(), key=lambda item: (len(item[0]), item[0])
    )
    signatures = [item[0] for item in signature_items]
    grouped_indexes = [item[1] for item in signature_items]
    near_union = _UnionFind(len(records))
    matching_record_pair_count = 0
    for indexes in grouped_indexes:
        first = indexes[0]
        for index in indexes[1:]:
            union_find.union(first, index)
            near_union.union(first, index)
        matching_record_pair_count += len(indexes) * (len(indexes) - 1) // 2

    global_frequency = Counter(
        shingle for signature in signatures for shingle in signature
    )
    rarity_ordered = [
        tuple(sorted(signature, key=lambda shingle: (global_frequency[shingle], shingle)))
        for signature in signatures
    ]
    prefix_lengths = []
    for signature in signatures:
        # nextafter keeps the filter conservative when a decimal threshold times
        # a length rounds infinitesimally above an integer (for example 0.07*100).
        required_overlap = max(
            1,
            math.ceil(
                math.nextafter(threshold * len(signature), -math.inf)
            ),
        )
        prefix_lengths.append(len(signature) - required_overlap + 1)

    inverted: dict[str, list[int]] = defaultdict(list)
    signature_comparison_count = 0
    signature_sets = [set(signature) for signature in signatures]
    for signature_index, shingles in enumerate(signature_sets):
        possible: set[int] = set()
        current_length = len(shingles)
        for shingle in rarity_ordered[signature_index][
            : prefix_lengths[signature_index]
        ]:
            for previous in inverted.get(shingle, ()):
                previous_length = len(signature_sets[previous])
                if previous_length / current_length >= threshold:
                    possible.add(previous)
        for previous in sorted(possible):
            signature_comparison_count += 1
            if _jaccard(shingles, signature_sets[previous]) >= threshold:
                left_indexes = grouped_indexes[previous]
                right_indexes = grouped_indexes[signature_index]
                union_find.union(left_indexes[0], right_indexes[0])
                near_union.union(left_indexes[0], right_indexes[0])
                matching_record_pair_count += len(left_indexes) * len(right_indexes)
        for shingle in rarity_ordered[signature_index][
            : prefix_lengths[signature_index]
        ]:
            inverted[shingle].append(signature_index)
    return (
        matching_record_pair_count,
        len(signatures),
        signature_comparison_count,
        near_union,
    )


def _build_leakage_components(
    records: Sequence[Mapping[str, Any]], *, near_duplicate_threshold: float
) -> _LeakageComponentBuild:
    """Return the complete closure over every split leakage relation.

    This is deliberately the sole implementation of article, paragraph,
    template, and sentence-near-duplicate component construction. Callers must
    validate records before using it so every relation is bounded by the data
    contract.
    """

    union_find = _UnionFind(len(records))
    article_groups = _group_by_value(records, "article_id")
    paragraph_groups = _group_by_value(records, "paragraph_hash")
    template_groups = _group_by_value(records, "template_cluster_id", skip_none=True)
    article_group_count = _union_groups(union_find, article_groups)
    paragraph_group_count = _union_groups(union_find, paragraph_groups)
    template_group_count = _union_groups(union_find, template_groups)
    (
        near_pair_count,
        near_signature_count,
        near_signature_comparison_count,
        near_union,
    ) = _union_near_duplicates(
        records, union_find, threshold=near_duplicate_threshold
    )
    components = union_find.groups()
    component_records = [
        sorted(indexes, key=lambda index: records[index]["stable_id"])
        for indexes in components.values()
    ]
    component_records.sort(
        key=lambda indexes: min(records[index]["stable_id"] for index in indexes)
    )
    return _LeakageComponentBuild(
        article_groups=article_groups,
        paragraph_groups=paragraph_groups,
        template_groups=template_groups,
        article_group_count=article_group_count,
        paragraph_group_count=paragraph_group_count,
        template_group_count=template_group_count,
        near_pair_count=near_pair_count,
        near_signature_count=near_signature_count,
        near_signature_comparison_count=near_signature_comparison_count,
        near_union=near_union,
        component_records=component_records,
    )


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
    leakage = _build_leakage_components(
        normalized, near_duplicate_threshold=near_duplicate_threshold
    )
    article_groups = leakage.article_groups
    paragraph_groups = leakage.paragraph_groups
    template_groups = leakage.template_groups
    component_records = leakage.component_records

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
        for indexes in leakage.near_union.groups().values()
        if len(indexes) > 1
    }
    component_hashes = sorted(
        _component_hash([normalized[index]["stable_id"] for index in indexes])
        for indexes in component_records
    )
    output_bytes = canonical_jsonl_bytes(output)
    split_content_sha256 = {
        split: hashlib.sha256(
            canonical_jsonl_bytes(
                [record for record in output if record["split"] == split]
            )
        ).hexdigest()
        for split in SPLITS
    }
    report: dict[str, Any] = {
        "schema_version": 3,
        "seed": seed,
        "split_ratios": ratios,
        "record_count": len(output),
        "split_counts": {
            split: assignment_by_index.count(split) for split in SPLITS
        },
        "article_group_count": leakage.article_group_count,
        "paragraph_exact_group_count": leakage.paragraph_group_count,
        "sentence_near_duplicate_pair_count": leakage.near_pair_count,
        "sentence_near_duplicate_cluster_count": len(near_groups),
        "sentence_signature_count": leakage.near_signature_count,
        "sentence_signature_total_pair_count": (
            leakage.near_signature_count * (leakage.near_signature_count - 1) // 2
        ),
        "sentence_signature_comparison_count": leakage.near_signature_comparison_count,
        "sentence_signature_join_algorithm": "exact_length_rarity_prefix_v1",
        "template_cluster_count": leakage.template_group_count,
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
        "split_content_sha256": split_content_sha256,
    }
    if any(value != 0 for value in report["cross_split_leakage"].values()):
        raise SplitError("splitter produced cross-split leakage")
    # Exercise the same canonical serializer used for persisted reports. This
    # also rejects accidental non-deterministic values before the caller writes.
    canonical_json_bytes(report)
    return output, report


def _validate_tier_a_component_input(
    records: Sequence[Mapping[str, Any]], *, name: str
) -> list[dict[str, Any]]:
    """Normalize one exclusion input or fail before component construction."""

    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
        or not records
        or len(records) > MAX_COMPONENT_INPUT_RECORDS
    ):
        raise SplitError(f"{name}: record count is empty or outside the bound")
    try:
        normalized = validate_records(records, require_split=False)
    except (ContractError, TypeError) as error:
        raise SplitError(f"{name}: contract validation failed") from error
    if any(record["tier"] != "A" for record in normalized):
        raise SplitError(f"{name}: every record must be Tier A")
    return normalized


def _content_aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the only record-content representation permitted in an audit report."""

    payload = canonical_jsonl_bytes(records)
    return {
        "count": len(records),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _validate_exclusion_threshold(value: float) -> float:
    """Reject non-finite and boolean thresholds at the public boundary."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 < value <= 1.0
    ):
        raise SplitError("near_duplicate_threshold: must be a finite number in (0, 1]")
    return float(value)


def exclude_historical_components(
    historical_records: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    *,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Fail closed by excluding candidates linked to historical Tier-A records.

    The relation closure is exactly the same one used by :func:`assign_splits`:
    shared article ID, paragraph hash, non-null template cluster, or sentence
    shingle Jaccard at ``near_duplicate_threshold``. Inputs are validated as
    bounded Tier-A contract records and must have disjoint stable IDs. Returned
    candidate records are stable-ID sorted; the report contains aggregates and
    hashes only, never raw text or stable IDs.
    """

    historical = _validate_tier_a_component_input(
        historical_records, name="historical_records"
    )
    candidates = _validate_tier_a_component_input(
        candidate_records, name="candidate_records"
    )
    if len(historical) + len(candidates) > MAX_COMPONENT_INPUT_RECORDS:
        raise SplitError("historical and candidate union is outside the record bound")
    threshold = _validate_exclusion_threshold(near_duplicate_threshold)
    historical_ids = {record["stable_id"] for record in historical}
    if historical_ids.intersection(record["stable_id"] for record in candidates):
        raise SplitError("stable_id: historical and candidate inputs must be disjoint")

    # Sorting the union makes both component indexing and all aggregate results
    # independent of the order in which the two immutable inputs were supplied.
    combined = sorted([*historical, *candidates], key=lambda record: record["stable_id"])
    leakage = _build_leakage_components(
        combined, near_duplicate_threshold=threshold
    )

    excluded_indexes: set[int] = set()
    historical_component_count = 0
    excluded_component_count = 0
    eligible_component_count = 0
    for indexes in leakage.component_records:
        touches_historical = any(
            combined[index]["stable_id"] in historical_ids for index in indexes
        )
        candidate_indexes = [
            index
            for index in indexes
            if combined[index]["stable_id"] not in historical_ids
        ]
        if touches_historical:
            historical_component_count += 1
            if candidate_indexes:
                excluded_component_count += 1
                excluded_indexes.update(candidate_indexes)
        elif candidate_indexes:
            eligible_component_count += 1

    eligible = [
        dict(record)
        for index, record in enumerate(combined)
        if record["stable_id"] not in historical_ids and index not in excluded_indexes
    ]
    excluded = [
        dict(record)
        for index, record in enumerate(combined)
        if record["stable_id"] not in historical_ids and index in excluded_indexes
    ]
    # ``combined`` is stable-ID sorted, but keep this terminal invariant local
    # to the public result even if its construction changes in the future.
    eligible.sort(key=lambda record: record["stable_id"])
    excluded.sort(key=lambda record: record["stable_id"])
    report: dict[str, Any] = {
        "schema_version": 1,
        "algorithm": "historical_component_exclusion_v1",
        "leakage_component_algorithm": (
            "union_article_paragraph_template_sentence_jaccard_v1"
        ),
        "sentence_signature_join_algorithm": "exact_length_rarity_prefix_v1",
        "near_duplicate_threshold": threshold,
        "historical_input": _content_aggregate(historical),
        "candidate_input": _content_aggregate(candidates),
        "eligible": _content_aggregate(eligible),
        "excluded": _content_aggregate(excluded),
        "union_record_count": len(combined),
        "leakage_component_count": len(leakage.component_records),
        "historical_component_count": historical_component_count,
        "historical_touching_component_count": historical_component_count,
        "excluded_component_count": excluded_component_count,
        "eligible_component_count": eligible_component_count,
        "raw_text": False,
        "raw_ids": False,
    }
    canonical_json_bytes(report)
    return eligible, excluded, report


def _validate_expected_content_commitment(
    *, name: str, record_count: int, content_sha256: str
) -> dict[str, Any]:
    if type(record_count) is not int or not 1 <= record_count <= MAX_COMPONENT_INPUT_RECORDS:
        raise SplitError(f"{name}: expected record count is outside the bound")
    if not isinstance(content_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
        raise SplitError(f"{name}: expected content hash is not a lowercase SHA-256")
    return {"count": record_count, "content_sha256": content_sha256}


def publish_historical_exclusion_directory(
    directory: str | Path,
    historical_records: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    *,
    expected_historical_record_count: int,
    expected_historical_content_sha256: str,
    expected_candidate_record_count: int,
    expected_candidate_content_sha256: str,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> dict[str, Any]:
    """Publish one immutable, input-bound historical-exclusion evidence directory."""

    expected_historical = _validate_expected_content_commitment(
        name="historical_records",
        record_count=expected_historical_record_count,
        content_sha256=expected_historical_content_sha256,
    )
    expected_candidate = _validate_expected_content_commitment(
        name="candidate_records",
        record_count=expected_candidate_record_count,
        content_sha256=expected_candidate_content_sha256,
    )
    eligible, excluded, report = exclude_historical_components(
        historical_records,
        candidate_records,
        near_duplicate_threshold=near_duplicate_threshold,
    )
    if report["historical_input"] != expected_historical:
        raise SplitError("historical_records: input does not match the expected commitment")
    if report["candidate_input"] != expected_candidate:
        raise SplitError("candidate_records: input does not match the expected commitment")

    target = Path(directory)
    if target.exists():
        raise SplitError("historical exclusion directory already exists and is immutable")
    if not target.parent.is_dir():
        raise SplitError("historical exclusion parent directory does not exist")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        write_bytes_atomic(temporary / "eligible.jsonl", canonical_jsonl_bytes(eligible))
        write_bytes_atomic(temporary / "excluded.jsonl", canonical_jsonl_bytes(excluded))
        write_bytes_atomic(
            temporary / "report.json", canonical_json_bytes(report) + b"\n"
        )
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def ensure_distinct_paths(
    input_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
) -> None:
    """Reject aliases/hardlinks before a split command reads or writes data."""

    named_paths = {
        "input": Path(input_path),
        "output": Path(output_path),
        "report": Path(report_path),
    }
    resolved: dict[str, str] = {}
    try:
        for name, path in named_paths.items():
            resolved[name] = os.path.normcase(os.fspath(path.resolve(strict=False)))
    except OSError as error:
        raise SplitError(f"paths: cannot resolve ({type(error).__name__})") from error

    names = tuple(named_paths)
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1 :]:
            same_resolved_path = resolved[left_name] == resolved[right_name]
            same_existing_file = False
            left_path = named_paths[left_name]
            right_path = named_paths[right_name]
            if left_path.exists() and right_path.exists():
                try:
                    same_existing_file = left_path.samefile(right_path)
                except OSError as error:
                    raise SplitError(
                        f"paths: cannot compare {left_name} and {right_name} "
                        f"({type(error).__name__})"
                    ) from error
            if same_resolved_path or same_existing_file:
                raise SplitError(
                    f"paths: {left_name} and {right_name} must be distinct"
                )


def publish_split_artifacts(
    output_path: str | Path,
    report_path: str | Path,
    output: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> tuple[str, str]:
    """Build and transactionally publish the canonical output/report pair."""

    normalized_output = validate_records(output)
    output_payload = canonical_jsonl_bytes(normalized_output)
    report_payload = canonical_json_bytes(report) + b"\n"
    write_bytes_pair_atomic(
        output_path,
        output_payload,
        report_path,
        report_payload,
    )
    return (
        hashlib.sha256(output_payload).hexdigest(),
        hashlib.sha256(report_payload).hexdigest(),
    )


def split_jsonl(
    input_path: str,
    output_path: str,
    report_path: str,
    *,
    seed: int,
    split_ratios: Mapping[str, float] | None = None,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> tuple[str, str]:
    """CLI helper: split an unassigned JSONL file and write both artifacts."""

    ensure_distinct_paths(input_path, output_path, report_path)
    records = read_jsonl(input_path, require_split=False)
    output, report = assign_splits(
        records,
        seed=seed,
        split_ratios=split_ratios,
        near_duplicate_threshold=near_duplicate_threshold,
    )
    return publish_split_artifacts(output_path, report_path, output, report)
