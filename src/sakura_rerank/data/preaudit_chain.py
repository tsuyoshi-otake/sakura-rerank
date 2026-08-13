"""Aggregate-only contract for a reproducible Tier A pre-audit chain.

The contract deliberately contains hashes, counts, and run settings only.  It
binds the Stage 4 exclusion commitment through the source spans, Tier A output,
split, and final-holdout audit queue without allowing raw corpus text or raw
stable IDs into a tracked manifest.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


PRE_AUDIT_CHAIN_SCHEMA_VERSION = 1
PRE_AUDIT_CHAIN_MANIFEST_KIND = "tier_a_pre_audit_chain"
PRE_AUDIT_CHAIN_STATUS = "pre_audit_ready"
SOURCE_SPAN_CLEANER_VERSION = "conservative_wikitext_v4"
STABLE_ID_EXCLUSION_FORMAT_VERSION = 1
STABLE_ID_EXCLUSION_CANONICALIZATION = "utf8_lf_sorted_unique_stable_id_jsonl_v1"
MINIMUM_FINAL_HOLDOUT_AUDIT_RECORDS = 3_000
MAX_RECORDS = 100_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class DataValidationError(ValueError):
    """A pre-audit chain manifest fails its strict aggregate-only contract."""


def _fail(field: str, message: str) -> None:
    raise DataValidationError(f"pre-audit chain {field}: {message}")


def _object(value: Any, fields: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _fail(field, "fields do not match schema")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(field, "must be a lowercase SHA-256")
    return value


def _git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        _fail(field, "must be a lowercase Git SHA-1")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = MAX_RECORDS) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(field, f"must be an integer in [{minimum}, {maximum}]")
    return value


def _ratio(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field, "must be a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        _fail(field, "must be a finite number")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DataValidationError(f"pre-audit chain {field}: must be a finite number") from error
    if not Decimal("0") < decimal < Decimal("1"):
        _fail(field, "must be strictly between zero and one")
    return float(decimal)


def _validate_partition(value: Any) -> dict[str, Any]:
    partition = _object(value, {"report_sha256", "stage4_stable_id_exclusion"}, "partition")
    exclusion = _object(
        partition["stage4_stable_id_exclusion"],
        {
            "format_version",
            "canonicalization",
            "count",
            "content_sha256",
            "raw_stable_ids_in_report",
        },
        "partition.stage4_stable_id_exclusion",
    )
    if exclusion["format_version"] != STABLE_ID_EXCLUSION_FORMAT_VERSION:
        _fail("partition.stage4_stable_id_exclusion.format_version", "unsupported format")
    if exclusion["canonicalization"] != STABLE_ID_EXCLUSION_CANONICALIZATION:
        _fail("partition.stage4_stable_id_exclusion.canonicalization", "unsupported canonicalization")
    if exclusion["raw_stable_ids_in_report"] is not False:
        _fail("partition.stage4_stable_id_exclusion.raw_stable_ids_in_report", "must be false")
    return {
        "report_sha256": _sha256(partition["report_sha256"], "partition.report_sha256"),
        "stage4_stable_id_exclusion": {
            "format_version": STABLE_ID_EXCLUSION_FORMAT_VERSION,
            "canonicalization": STABLE_ID_EXCLUSION_CANONICALIZATION,
            "count": _integer(
                exclusion["count"], "partition.stage4_stable_id_exclusion.count"
            ),
            "content_sha256": _sha256(
                exclusion["content_sha256"],
                "partition.stage4_stable_id_exclusion.content_sha256",
            ),
            "raw_stable_ids_in_report": False,
        },
    }


def _validate_source_spans(value: Any) -> dict[str, Any]:
    source_spans = _object(
        value,
        {
            "manifest_sha256",
            "record_count",
            "content_sha256",
            "extractor_git_sha",
            "cleaner_version",
        },
        "source_spans",
    )
    if source_spans["cleaner_version"] != SOURCE_SPAN_CLEANER_VERSION:
        _fail("source_spans.cleaner_version", "must be conservative_wikitext_v4")
    return {
        "manifest_sha256": _sha256(source_spans["manifest_sha256"], "source_spans.manifest_sha256"),
        "record_count": _integer(source_spans["record_count"], "source_spans.record_count", minimum=1),
        "content_sha256": _sha256(source_spans["content_sha256"], "source_spans.content_sha256"),
        "extractor_git_sha": _git_sha(source_spans["extractor_git_sha"], "source_spans.extractor_git_sha"),
        "cleaner_version": SOURCE_SPAN_CLEANER_VERSION,
    }


def _validate_tier_a(value: Any, source_spans: Mapping[str, Any]) -> dict[str, Any]:
    tier_a = _object(
        value,
        {"report_sha256", "record_count", "content_sha256", "source_span_content_sha256"},
        "tier_a",
    )
    source_span_content_sha256 = _sha256(
        tier_a["source_span_content_sha256"], "tier_a.source_span_content_sha256"
    )
    if source_span_content_sha256 != source_spans["content_sha256"]:
        _fail("tier_a.source_span_content_sha256", "does not bind source_spans.content_sha256")
    return {
        "report_sha256": _sha256(tier_a["report_sha256"], "tier_a.report_sha256"),
        "record_count": _integer(tier_a["record_count"], "tier_a.record_count", minimum=1),
        "content_sha256": _sha256(tier_a["content_sha256"], "tier_a.content_sha256"),
        "source_span_content_sha256": source_span_content_sha256,
    }


def _validate_split(value: Any, tier_a: Mapping[str, Any]) -> dict[str, Any]:
    split = _object(
        value,
        {
            "report_sha256",
            "seed",
            "ratios",
            "record_count",
            "tier_a_content_sha256",
            "content_sha256",
            "split_counts",
            "split_content_sha256",
            "near_duplicate_threshold",
            "cross_split_leakage_count",
        },
        "split",
    )
    ratios = _object(split["ratios"], {"train", "dev", "final_holdout"}, "split.ratios")
    normalized_ratios = {
        name: _ratio(ratios[name], f"split.ratios.{name}")
        for name in ("train", "dev", "final_holdout")
    }
    if sum((Decimal(str(value)) for value in normalized_ratios.values()), Decimal("0")) != Decimal("1"):
        _fail("split.ratios", "must sum exactly to one")
    split_counts = _object(
        split["split_counts"], {"train", "dev", "final_holdout"}, "split.split_counts"
    )
    normalized_counts = {
        name: _integer(split_counts[name], f"split.split_counts.{name}", minimum=1)
        for name in ("train", "dev", "final_holdout")
    }
    record_count = _integer(split["record_count"], "split.record_count", minimum=1)
    if record_count != tier_a["record_count"]:
        _fail("split.record_count", "does not bind tier_a.record_count")
    if sum(normalized_counts.values()) != record_count:
        _fail("split.split_counts", "must sum to split.record_count")
    tier_a_content_sha256 = _sha256(
        split["tier_a_content_sha256"], "split.tier_a_content_sha256"
    )
    if tier_a_content_sha256 != tier_a["content_sha256"]:
        _fail("split.tier_a_content_sha256", "does not bind tier_a.content_sha256")
    content_sha256 = _sha256(split["content_sha256"], "split.content_sha256")
    split_hashes = _object(
        split["split_content_sha256"],
        {"train", "dev", "final_holdout"},
        "split.split_content_sha256",
    )
    threshold = _ratio(split["near_duplicate_threshold"], "split.near_duplicate_threshold")
    if not threshold <= 1.0:
        _fail("split.near_duplicate_threshold", "must not exceed one")
    if _integer(split["cross_split_leakage_count"], "split.cross_split_leakage_count") != 0:
        _fail("split.cross_split_leakage_count", "must be zero")
    return {
        "report_sha256": _sha256(split["report_sha256"], "split.report_sha256"),
        "seed": _integer(split["seed"], "split.seed", maximum=2**63 - 1),
        "ratios": normalized_ratios,
        "record_count": record_count,
        "tier_a_content_sha256": tier_a_content_sha256,
        "content_sha256": content_sha256,
        "split_counts": normalized_counts,
        "split_content_sha256": {
            name: _sha256(split_hashes[name], f"split.split_content_sha256.{name}")
            for name in ("train", "dev", "final_holdout")
        },
        "near_duplicate_threshold": threshold,
        "cross_split_leakage_count": 0,
    }


def _validate_human_audit(value: Any, split: Mapping[str, Any]) -> dict[str, Any]:
    human_audit = _object(
        value,
        {
            "queue_manifest_sha256",
            "seed",
            "minimum_sample_size",
            "dataset_record_count",
            "dataset_content_sha256",
            "queue_record_count",
            "final_holdout_count",
            "queue_content_sha256",
            "final_holdout_content_sha256",
        },
        "human_audit",
    )
    minimum_sample_size = _integer(
        human_audit["minimum_sample_size"],
        "human_audit.minimum_sample_size",
        minimum=MINIMUM_FINAL_HOLDOUT_AUDIT_RECORDS,
    )
    dataset_record_count = _integer(
        human_audit["dataset_record_count"], "human_audit.dataset_record_count", minimum=1
    )
    if dataset_record_count != split["record_count"]:
        _fail("human_audit.dataset_record_count", "does not bind split.record_count")
    dataset_content_sha256 = _sha256(
        human_audit["dataset_content_sha256"], "human_audit.dataset_content_sha256"
    )
    if dataset_content_sha256 != split["content_sha256"]:
        _fail("human_audit.dataset_content_sha256", "does not bind split.content_sha256")
    queue_record_count = _integer(
        human_audit["queue_record_count"], "human_audit.queue_record_count", minimum=MINIMUM_FINAL_HOLDOUT_AUDIT_RECORDS
    )
    final_holdout_count = _integer(
        human_audit["final_holdout_count"], "human_audit.final_holdout_count", minimum=MINIMUM_FINAL_HOLDOUT_AUDIT_RECORDS
    )
    if queue_record_count != final_holdout_count:
        _fail("human_audit.queue_record_count", "must equal human_audit.final_holdout_count")
    if minimum_sample_size > queue_record_count:
        _fail("human_audit.minimum_sample_size", "must not exceed human_audit.queue_record_count")
    if final_holdout_count != split["split_counts"]["final_holdout"]:
        _fail("human_audit.final_holdout_count", "does not bind split.split_counts.final_holdout")
    final_holdout_content_sha256 = _sha256(
        human_audit["final_holdout_content_sha256"],
        "human_audit.final_holdout_content_sha256",
    )
    if final_holdout_content_sha256 != split["split_content_sha256"]["final_holdout"]:
        _fail(
            "human_audit.final_holdout_content_sha256",
            "does not bind split.split_content_sha256.final_holdout",
        )
    return {
        "queue_manifest_sha256": _sha256(
            human_audit["queue_manifest_sha256"], "human_audit.queue_manifest_sha256"
        ),
        "seed": _integer(human_audit["seed"], "human_audit.seed", maximum=2**63 - 1),
        "minimum_sample_size": minimum_sample_size,
        "dataset_record_count": dataset_record_count,
        "dataset_content_sha256": dataset_content_sha256,
        "queue_record_count": queue_record_count,
        "final_holdout_count": final_holdout_count,
        "queue_content_sha256": _sha256(
            human_audit["queue_content_sha256"], "human_audit.queue_content_sha256"
        ),
        "final_holdout_content_sha256": final_holdout_content_sha256,
    }


def validate_pre_audit_chain_manifest(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and deep-copy one aggregate-only v4 pre-audit chain manifest."""

    manifest = _object(
        mapping,
        {
            "schema_version",
            "manifest_kind",
            "variant",
            "status",
            "raw_text_in_manifest",
            "partition",
            "source_spans",
            "tier_a",
            "split",
            "human_audit",
        },
        "manifest",
    )
    if manifest["schema_version"] != PRE_AUDIT_CHAIN_SCHEMA_VERSION:
        _fail("schema_version", "unsupported schema")
    if manifest["manifest_kind"] != PRE_AUDIT_CHAIN_MANIFEST_KIND:
        _fail("manifest_kind", "unsupported manifest kind")
    if manifest["variant"] not in {"A", "B"}:
        _fail("variant", "must be A or B")
    if manifest["status"] != PRE_AUDIT_CHAIN_STATUS:
        _fail("status", "must be pre_audit_ready")
    if manifest["raw_text_in_manifest"] is not False:
        _fail("raw_text_in_manifest", "must be false")
    partition = _validate_partition(manifest["partition"])
    source_spans = _validate_source_spans(manifest["source_spans"])
    tier_a = _validate_tier_a(manifest["tier_a"], source_spans)
    split = _validate_split(manifest["split"], tier_a)
    human_audit = _validate_human_audit(manifest["human_audit"], split)
    return copy.deepcopy(
        {
            "schema_version": PRE_AUDIT_CHAIN_SCHEMA_VERSION,
            "manifest_kind": PRE_AUDIT_CHAIN_MANIFEST_KIND,
            "variant": manifest["variant"],
            "status": PRE_AUDIT_CHAIN_STATUS,
            "raw_text_in_manifest": False,
            "partition": partition,
            "source_spans": source_spans,
            "tier_a": tier_a,
            "split": split,
            "human_audit": human_audit,
        }
    )
