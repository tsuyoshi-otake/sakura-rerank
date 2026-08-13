"""Fail-closed contracts for the v4 two-teacher corpus review cascade.

This module deliberately contains no CLI.  Its public functions operate on
already validated Tier A records and publish only immutable queue directories
or aggregate-only reports.  Queue items contain review text; manifests and
reports never do.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_atomic, write_bytes_pair_atomic
from .contracts import canonical_json_bytes, canonical_jsonl_bytes, read_jsonl, validate_records
from .human_audit import (
    QUEUE_RECORD_TYPE,
    QUEUE_SCHEMA_VERSION,
    RESPONSE_RECORD_TYPE,
    RESPONSE_SCHEMA_VERSION,
    VERDICTS,
    build_calibration_queue_manifest,
    build_quality_report,
    publish_audit_queue,
    read_audit_queue,
    read_audit_responses,
    read_queue_manifest,
    validate_audit_queue,
    validate_audit_responses,
    validate_queue_manifest,
)
from .jawiki_preprocess import (
    contains_v4_bare_pipe,
    contains_v4_decorative_corruption,
    contains_v4_residual_corruption,
)
from .manifest import load_manifest_document, validate_manifest_document
from .research_exporter import read_exporter_manifest
from .tier_a import (
    PINNED_SAKURA_INPUT_HEAD,
    TierAError,
    ensure_distinct_tier_a_paths,
    read_dictionary_index,
    read_dictionary_index_manifest,
    read_source_span_manifest,
    read_source_spans,
    validate_dictionary_index_manifest,
    validate_source_span_manifest,
)


V4_SCHEMA_VERSION = 1
V4_QUEUE_RECORD_TYPE = "tier_a_audit_queue_row"
V4_QUEUE_SCHEMA_VERSION = 2
V4_BATCH_RECORD_TYPE = "tier_a_v4_teacher_batch"
V4_VERDICT_RECORD_TYPE = "tier_a_v4_teacher_verdict_batch"
V4_QUEUE_MANIFEST_KIND = "tier_a_v4_teacher_queue"
V4_REPORT_KIND = "tier_a_v4_partition"
SCREEN_REVIEWER_ID = "gpt-5.6-sol-screen-20260812"
ADJUDICATION_REVIEWER_ID = "gpt-5.6-sol-adjudicate-20260812"
GATE_A_REVIEWER_ID = "gpt-5.6-sol-gate-a-20260813"
CALIBRATION_SEED = 20260812
V3_TIER_A_RECORD_COUNT = 24_068
V3_TIER_A_SPLIT_CONTENT_SHA256 = "82aa1622fee1571c6c80fae8668ed9e8397a1ae239d66bc4f11387c66d63b975"
V3_FINAL_HOLDOUT_COUNT = 3_610
V3_FINAL_HOLDOUT_REJECTED_COUNT = 177
HANDOFF_DEV_RECORD_COUNT = 800
MAX_BATCH_ITEMS = 40
MAX_BATCHES = 100_000
MAX_QUEUE_ITEMS = MAX_BATCH_ITEMS * MAX_BATCHES
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_NOTE_CHARS = 200
REVIEWER_KINDS = ("ai_teacher",)
STAGES = ("stage1", "stage2", "gate_a")
MAX_REVIEWED_AT_CHARS = 64
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BATCH_NAME = re.compile(r"batch-([0-9]{3,})\.json")
_VERDICT_NAME = re.compile(r"verdicts-([0-9]{3,})\.json")

_STABLE_ID_BUCKET_FILES = {
    "retained": "retained-stable-ids.jsonl",
    "excluded": "excluded-stable-ids.jsonl",
    "ambiguous_quarantine": "ambiguous-quarantine-stable-ids.jsonl",
}


def _fail(message: str) -> None:
    raise TierAError(f"corpus v4: {message}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(f"{field} is not a bounded identifier")
    return value


def _reviewer(reviewer_kind: Any, reviewer_id: Any) -> tuple[str, str]:
    if reviewer_kind not in REVIEWER_KINDS:
        _fail("reviewer_kind is unsupported")
    return reviewer_kind, _identifier(reviewer_id, "reviewer_id")


def _canonical_payload(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _canonical_jsonl_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash canonical JSONL incrementally to bound peak memory on 500 MiB inputs."""

    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item.get("stable_id", ""))):
        digest.update(canonical_json_bytes(record))
        digest.update(b"\n")
    return digest.hexdigest()


def _queue_item(record: Mapping[str, Any]) -> dict[str, Any]:
    """Render the established handoff queue shape from one Tier A record."""

    top32 = record["candidate_snapshots"]["training_top32"]["candidates"]
    top6 = record["candidate_snapshots"]["production_top6"]["candidates"]
    gold = top32[record["gold_index"]]
    return {
        "schema_version": 2,
        "record_type": V4_QUEUE_RECORD_TYPE,
        "stable_id": record["stable_id"],
        "split": record["split"],
        "stratum": _stratum(record),
        "source": {
            "page_id": record["source"]["page_id"],
            "revision_id": record["source"]["revision_id"],
        },
        "left_context": record["session"]["left_context"],
        "reading": record["reading"],
        "gold_surface": record["gold_surface"],
        "gold_index": record["gold_index"],
        "gold_segments": gold["segments"],
        "production_candidates": [
            {"rank": candidate["rank"], "surface": candidate["surface"]}
            for candidate in top6
        ],
    }


def _human_audit_item(record: Mapping[str, Any]) -> dict[str, Any]:
    """Render the public, existing human-audit item contract (not v4 batch)."""

    item = _queue_item(record)
    item["schema_version"] = QUEUE_SCHEMA_VERSION
    item["record_type"] = QUEUE_RECORD_TYPE
    return item


def _reading_bucket(length: int) -> str:
    return "reading-03-09" if length <= 9 else "reading-10-30" if length <= 30 else "reading-31-128"


def _candidate_bucket(count: int) -> str:
    return "candidates-02-06" if count <= 6 else "candidates-07-16" if count <= 16 else "candidates-17-32"


def _stratum(record: Mapping[str, Any]) -> str:
    count = len(record["candidate_snapshots"]["training_top32"]["candidates"])
    local = "local-correct" if record["gold_index"] == 0 else "local-wrong"
    return "/".join((_reading_bucket(len(record["reading"])), _candidate_bucket(count), local))


def strict_preflight(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate a complete immutable non-fixture Tier A input in stable-ID order."""

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        _fail("records must be a bounded sequence")
    if not records or len(records) > MAX_QUEUE_ITEMS:
        _fail("record count is empty or outside the bound")
    normalized = validate_records(records, require_split=True)
    if any(record.get("is_fixture") for record in normalized):
        _fail("fixture records cannot enter v4 teacher review")
    ids = [record["stable_id"] for record in normalized]
    if len(ids) != len(set(ids)):
        _fail("stable IDs must be unique")
    return sorted(normalized, key=lambda record: record["stable_id"])


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        _fail(f"cannot hash input file ({type(error).__name__})")
    return digest.hexdigest()


def preflight_v4_inputs(
    *,
    dataset_path: str | Path,
    source_spans_path: str | Path,
    source_span_manifest_path: str | Path,
    jawiki_manifest_path: str | Path,
    dictionary_index_path: str | Path,
    dictionary_manifest_path: str | Path,
    exporter_manifest_path: str | Path,
    v3_audit_queue_path: str | Path,
    v3_audit_manifest_path: str | Path,
    v3_audit_responses_path: str | Path,
    handoff_directory: str | Path,
    allowed_root: str | Path,
) -> dict[str, Any]:
    """Validate every immutable input and pinned identity before Stage 1.

    The returned object is intentionally aggregate-only.  It is safe to print
    or attach to the tracking issue and never contains review notes or corpus
    text.
    """

    dataset_file_sha = _file_sha256(dataset_path)
    if dataset_file_sha != V3_TIER_A_SPLIT_CONTENT_SHA256:
        _fail("Tier A v3 split dataset hash does not match the pinned input")
    records = strict_preflight(read_jsonl(dataset_path))
    if len(records) != V3_TIER_A_RECORD_COUNT:
        _fail("Tier A v3 split dataset count does not match the pinned input")
    record_ids = {record["stable_id"] for record in records}

    root = Path(allowed_root).resolve(strict=True)
    jawiki_manifest = validate_manifest_document(
        load_manifest_document(jawiki_manifest_path), root
    )
    dictionary_records = read_dictionary_index(dictionary_index_path)
    dictionary_manifest = validate_dictionary_index_manifest(
        read_dictionary_index_manifest(dictionary_manifest_path),
        dictionary_records,
        require_verified=True,
    )
    source_spans = read_source_spans(source_spans_path)
    source_span_manifest = validate_source_span_manifest(
        read_source_span_manifest(source_span_manifest_path),
        source_spans,
        jawiki_manifest=jawiki_manifest,
        dictionary_manifest=dictionary_manifest,
        require_verified=True,
    )
    exporter_manifest = read_exporter_manifest(
        exporter_manifest_path, require_verified=True
    )
    if (
        dictionary_manifest["sakura_input_head"] != PINNED_SAKURA_INPUT_HEAD
        or exporter_manifest["sakura_input_head"] != PINNED_SAKURA_INPUT_HEAD
    ):
        _fail("verified inputs do not share the pinned Sakura Input HEAD")

    audit_queue = read_audit_queue(v3_audit_queue_path)
    validate_queue_manifest(read_queue_manifest(v3_audit_manifest_path), audit_queue)
    audit_responses = read_audit_responses(v3_audit_responses_path)
    audit_ids = [item["stable_id"] for item in audit_queue]
    response_ids = [item["stable_id"] for item in audit_responses]
    if (
        len(audit_queue) != V3_FINAL_HOLDOUT_COUNT
        or len(audit_responses) != V3_FINAL_HOLDOUT_COUNT
        or set(audit_ids) != set(response_ids)
        or len(response_ids) != len(set(response_ids))
        or set(audit_ids) - record_ids
    ):
        _fail("v3 final-holdout audit coverage is inconsistent")
    if any(response.get("reviewer_kind") != "ai_teacher" for response in audit_responses):
        _fail("v3 final-holdout responses are not bound to ai_teacher")
    audit_rejected = sum(
        response["verdict"] != "valid" for response in audit_responses
    )
    if audit_rejected != V3_FINAL_HOLDOUT_REJECTED_COUNT:
        _fail("v3 final-holdout rejection count does not match the pinned evidence")

    handoff = Path(handoff_directory)
    dev_batches = read_handoff_batches(handoff / "dev-batches")
    if sum(len(batch["items"]) for batch in dev_batches) != HANDOFF_DEV_RECORD_COUNT:
        _fail("handoff dev batch count does not match the pinned evidence")
    sol_payloads, sol_pending = read_handoff_verdict_directory(
        dev_batches, handoff / "dev-verdicts-sol"
    )
    if sol_pending:
        _fail("Sol dev verdicts must be complete")
    opus_directory = handoff / "dev-verdicts-opus"
    opus_missing = (
        (15,)
        if not (opus_directory / "verdicts-015.json").exists()
        else ()
    )
    opus_payloads, opus_pending = read_handoff_verdict_directory(
        dev_batches,
        opus_directory,
        allowed_missing_indexes=opus_missing,
    )
    sol_by_id = flatten_handoff_verdicts(dev_batches, sol_payloads)
    opus_by_id: dict[str, str] = {}
    for index, payload in opus_payloads.items():
        batch = dev_batches[index]
        opus_by_id.update(
            {
                item["stable_id"]: entry["verdict"]
                for item, entry in zip(batch["items"], payload["verdicts"], strict=True)
            }
        )
    disagreements = discover_teacher_disagreements(handoff)
    for row in disagreements:
        identifier = row["stable_id"]
        if (
            identifier not in opus_by_id
            or identifier not in sol_by_id
            or row["verdict_a"] != opus_by_id[identifier]
            or row["verdict_b"] != sol_by_id[identifier]
        ):
            _fail("handoff disagreement rows do not match teacher verdicts")
    computed_disagreements = {
        identifier
        for identifier in opus_by_id
        if opus_by_id[identifier] != sol_by_id[identifier]
    }
    if computed_disagreements != {row["stable_id"] for row in disagreements}:
        _fail("handoff disagreement list is incomplete or has extra IDs")

    return {
        "schema_version": V4_SCHEMA_VERSION,
        "report_kind": "tier_a_v4_preflight",
        "status": "validated",
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "dataset_record_count": len(records),
        "dataset_content_sha256": dataset_file_sha,
        "source_span_record_count": source_span_manifest["record_count"],
        "source_span_content_sha256": source_span_manifest["content_sha256"],
        "dictionary_record_count": dictionary_manifest["record_count"],
        "dictionary_content_sha256": dictionary_manifest["content_sha256"],
        "exporter_binary_sha256": exporter_manifest["exporter_binary_sha256"],
        "v3_audit_record_count": len(audit_responses),
        "v3_audit_rejected_count": audit_rejected,
        "handoff_dev_record_count": len(sol_by_id),
        "handoff_opus_record_count": len(opus_by_id),
        "handoff_opus_missing_batch_count": len(opus_pending),
        "handoff_disagreement_record_count": len(disagreements),
        "raw_text_in_report": False,
    }


def _review_text(item: Mapping[str, Any]) -> str:
    if "session" in item:
        session = item.get("session")
        if not isinstance(session, Mapping) or not isinstance(session.get("left_context"), str):
            _fail("record session is invalid")
        left_context = session["left_context"]
    else:
        left_context = item.get("left_context")
        if not isinstance(left_context, str):
            _fail("queue left_context is invalid")
    gold_surface = item.get("gold_surface")
    if not isinstance(gold_surface, str):
        _fail("gold_surface is invalid")
    return left_context + gold_surface


def stage0_deterministic_hit_ids(
    records: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return the Tier A IDs hit by the exact adopted v4 cleaner predicate."""

    normalized = strict_preflight(records)
    return [
        record["stable_id"]
        for record in normalized
        if contains_v4_residual_corruption(_review_text(record))
    ]


def _stage0_candidate_probes() -> dict[str, Any]:
    residual_markup = ("{{", "}}", "[[", "]]", "{|", "|}", "http://", "https://", "''")
    namespace = re.compile(
        r"(?<![A-Za-z0-9_])(?:file|image|category|template|help|portal|wikipedia|media):",
        re.IGNORECASE,
    )
    opening = {"(": ")", "[": "]", "{": "}", "（": "）", "「": "」", "『": "』"}

    def unbalanced_bracket(text: str) -> bool:
        return any(text.count(left) != text.count(right) for left, right in opening.items())

    return {
        "adopted_bare_pipe": contains_v4_bare_pipe,
        "adopted_decorative_corruption": contains_v4_decorative_corruption,
        "brace_or_bracket_fragment": lambda text: any(token in text for token in ("{", "}", "[", "]")),
        "heading_equals": lambda text: "==" in text,
        "namespace": lambda text: namespace.search(text) is not None,
        "residual_markup": lambda text: any(token in text for token in residual_markup),
        "unbalanced_bracket": unbalanced_bracket,
    }


def analyze_stage0_dev_rules(
    items: Sequence[Mapping[str, Any]], verdict_by_id: Mapping[str, str]
) -> dict[str, Any]:
    """Measure candidate cleaner rules on Sol-valid and extraction-noise dev rows.

    Only aggregate numerators and denominators leave this function.  The adopted
    rule is fixed independently in ``contains_v4_residual_corruption``; this
    report proves its dev behavior and records why broader probes were rejected.
    """

    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
        _fail("stage0 dev items are empty or invalid")
    normalized = [_validate_queue_item(item) for item in items]
    identifiers = [item["stable_id"] for item in normalized]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(verdict_by_id):
        _fail("stage0 dev verdict coverage does not match items")
    for identifier, verdict in verdict_by_id.items():
        _identifier(identifier, "stage0 stable_id")
        if verdict not in VERDICTS:
            _fail("stage0 verdict enum is invalid")
    verdict_counts = Counter(verdict_by_id.values())
    valid_denominator = verdict_counts.get("valid", 0)
    noise_denominator = verdict_counts.get("extraction_noise", 0)
    if not valid_denominator or not noise_denominator:
        _fail("stage0 analysis needs both valid and extraction-noise rows")
    probes = _stage0_candidate_probes()
    evidence: dict[str, dict[str, Any]] = {}
    for name, probe in sorted(probes.items()):
        hits = Counter()
        for item in normalized:
            if probe(_review_text(item)):
                hits[verdict_by_id[item["stable_id"]]] += 1
        evidence[name] = {
            "adopted": name
            in {"adopted_bare_pipe", "adopted_decorative_corruption"},
            "extraction_noise_hits": hits.get("extraction_noise", 0),
            "extraction_noise_denominator": noise_denominator,
            "valid_false_fires": hits.get("valid", 0),
            "valid_denominator": valid_denominator,
        }
    return {
        "schema_version": V4_SCHEMA_VERSION,
        "report_kind": "tier_a_v4_stage0_dev_rule_analysis",
        "input_record_count": len(normalized),
        "verdict_counts": {name: verdict_counts.get(name, 0) for name in sorted(VERDICTS)},
        "candidate_rule_evidence": evidence,
        "raw_text_in_report": False,
    }


def stage0_probe_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return aggregate-only deterministic markup-probe evidence for Stage 0.

    This is intentionally analysis, not a silent record mutator.  Any later
    cleaner adoption must cite this report and regenerate the source chain.
    """

    normalized = strict_preflight(records)
    probes = _stage0_candidate_probes()
    counts = Counter()
    marked = 0
    for record in normalized:
        hit = False
        text = _review_text(record)
        for name, probe in probes.items():
            if probe(text):
                counts[name] += 1
                hit = True
        marked += hit
    return {
        "schema_version": V4_SCHEMA_VERSION,
        "report_kind": "tier_a_v4_stage0_probe",
        "input_record_count": len(normalized),
        "input_content_sha256": _canonical_jsonl_sha256(normalized),
        "marked_record_count": marked,
        "probe_counts": {name: counts.get(name, 0) for name in sorted(probes)},
        "raw_text_in_report": False,
    }


def build_teacher_batches(records: Sequence[Mapping[str, Any]], *, batch_size: int = MAX_BATCH_ITEMS) -> list[dict[str, Any]]:
    """Build every Tier A row into deterministic handoff-compatible batches."""

    normalized = strict_preflight(records)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_ITEMS:
        _fail("batch_size is outside the bound")
    items = [_queue_item(record) for record in normalized]
    return [
        {"batch_index": index, "items": items[start : start + batch_size]}
        for index, start in enumerate(range(0, len(items), batch_size))
    ]


def build_gate_a_teacher_batches(
    queue: Sequence[Mapping[str, Any]], *, batch_size: int = MAX_BATCH_ITEMS
) -> list[dict[str, Any]]:
    """Adapt a validated standard audit queue into strict in-memory v4 batches."""

    normalized = validate_audit_queue(queue)
    if not normalized:
        _fail("gate_a audit queue is empty")
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_ITEMS:
        _fail("batch_size is outside the bound")
    items = [
        {
            **item,
            "schema_version": V4_QUEUE_SCHEMA_VERSION,
            "record_type": V4_QUEUE_RECORD_TYPE,
        }
        for item in normalized
    ]
    return validate_teacher_batches(
        [
            {"batch_index": index, "items": items[start : start + batch_size]}
            for index, start in enumerate(range(0, len(items), batch_size))
        ]
    )


def validate_gate_a_teacher_queue_binding(
    queue: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Bind a strict Gate-A teacher queue to one standard audit queue exactly."""

    normalized_queue = validate_audit_queue(queue)
    normalized_batches = validate_teacher_batches(batches)
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("stage") != "gate_a"
        or manifest.get("reviewer_kind") != "ai_teacher"
        or manifest.get("reviewer_id") != GATE_A_REVIEWER_ID
        or manifest.get("record_count") != len(normalized_queue)
    ):
        _fail("Gate-A teacher queue provenance is invalid")
    adapted = [item for batch in normalized_batches for item in batch["items"]]
    expected = [
        {
            **item,
            "schema_version": V4_QUEUE_SCHEMA_VERSION,
            "record_type": V4_QUEUE_RECORD_TYPE,
        }
        for item in normalized_queue
    ]
    if adapted != expected:
        _fail("Gate-A teacher queue does not bind the audit queue exactly")
    return normalized_batches


def _gate_a_reviewed_at(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_REVIEWED_AT_CHARS
        or "\0" in value
        or "\n" in value
        or "\r" in value
    ):
        _fail("gate_a reviewed_at is invalid or outside the bound")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TierAError("corpus v4: gate_a reviewed_at is not ISO 8601") from error
    if timestamp.tzinfo is None:
        _fail("gate_a reviewed_at needs timezone")
    return value


def finalize_gate_a_teacher_responses(
    batches: Sequence[Mapping[str, Any]],
    verdicts: Mapping[int, Mapping[str, Any]],
    *,
    reviewed_at: str,
) -> list[dict[str, Any]]:
    """Finalize one complete Gate-A teacher pass as standard audit responses."""

    normalized = validate_teacher_batches(batches)
    if not isinstance(verdicts, Mapping) or set(verdicts) != set(range(len(normalized))):
        _fail("gate_a verdicts must cover every batch exactly")
    timestamp = _gate_a_reviewed_at(reviewed_at)
    responses: list[dict[str, Any]] = []
    for batch in normalized:
        verdict_batch = validate_teacher_verdict_batch(
            batch,
            verdicts[batch["batch_index"]],
            reviewer_kind="ai_teacher",
            reviewer_id=GATE_A_REVIEWER_ID,
        )
        responses.extend(
            {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "record_type": RESPONSE_RECORD_TYPE,
                "stable_id": outcome["stable_id"],
                "verdict": outcome["verdict"],
                "reviewer_id": GATE_A_REVIEWER_ID,
                "reviewer_kind": "ai_teacher",
                "reviewed_at": timestamp,
                "note": outcome["note"],
            }
            for outcome in verdict_batch["verdicts"]
        )
    return validate_audit_responses(responses)


def publish_gate_a_teacher_evidence(
    response_path: str | Path,
    report_path: str | Path,
    queue: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    """Publish canonical AI responses and their aggregate Gate-A report as one pair."""

    normalized_queue = validate_audit_queue(queue)
    normalized_responses = validate_audit_responses(responses)
    if (
        not normalized_responses
        or len(normalized_responses) != len(normalized_queue)
        or any(
            response["reviewer_kind"] != "ai_teacher"
            or response["reviewer_id"] != GATE_A_REVIEWER_ID
            for response in normalized_responses
        )
    ):
        _fail("Gate-A responses use invalid reviewer provenance")
    report = build_quality_report(
        normalized_queue,
        normalized_responses,
        allow_ai_teacher=True,
    )
    if (
        report.get("raw_text_in_report") is not False
        or report.get("completed_record_count") != len(normalized_queue)
        or report.get("pending_record_count") != 0
        or report.get("gate_a_human_audit_pass") is not False
    ):
        _fail("Gate-A quality report is incomplete or unsafe")
    response_payload = canonical_jsonl_bytes(normalized_responses)
    report_payload = canonical_json_bytes(report) + b"\n"
    write_bytes_pair_atomic(
        response_path,
        response_payload,
        report_path,
        report_payload,
    )
    return (
        hashlib.sha256(response_payload).hexdigest(),
        hashlib.sha256(report_payload).hexdigest(),
        report,
    )


def _validate_queue_item(item: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"schema_version", "record_type", "stable_id", "split", "stratum", "source", "left_context", "reading", "gold_surface", "gold_index", "gold_segments", "production_candidates"}
    if not isinstance(item, Mapping) or set(item) != expected:
        _fail("queue item fields do not match the handoff schema")
    if (
        item["schema_version"] != V4_QUEUE_SCHEMA_VERSION
        or item["record_type"] != V4_QUEUE_RECORD_TYPE
    ):
        _fail("queue item uses an unsupported schema")
    _identifier(item["stable_id"], "queue stable_id")
    if item["split"] not in {"train", "dev", "final-holdout"}:
        _fail("queue split is invalid")
    if not isinstance(item["stratum"], str) or not item["stratum"] or len(item["stratum"]) > 128:
        _fail("queue stratum is invalid")
    if not isinstance(item["source"], Mapping) or set(item["source"]) != {"page_id", "revision_id"}:
        _fail("queue source is invalid")
    for field in ("left_context", "reading", "gold_surface"):
        if not isinstance(item[field], str) or "\0" in item[field] or "\n" in item[field] or "\r" in item[field]:
            _fail(f"queue {field} is invalid")
    if type(item["gold_index"]) is not int or item["gold_index"] < 0:
        _fail("queue gold_index is invalid")
    if not isinstance(item["gold_segments"], list) or not item["gold_segments"]:
        _fail("queue gold_segments is invalid")
    candidates = item["production_candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 6:
        _fail("queue candidates are invalid")
    for rank, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping) or set(candidate) != {"rank", "surface"} or candidate["rank"] != rank or not isinstance(candidate["surface"], str):
            _fail("queue candidate is invalid")
    return dict(item)


def validate_teacher_batches(batches: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(batches, Sequence) or not batches or len(batches) > MAX_BATCHES:
        _fail("batches are empty or outside the bound")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for expected_index, batch in enumerate(batches):
        if not isinstance(batch, Mapping) or set(batch) != {"batch_index", "items"} or batch.get("batch_index") != expected_index:
            _fail("batch indexes must be contiguous and exact")
        items = batch.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
            _fail("batch item count is outside the bound")
        normalized = [_validate_queue_item(item) for item in items]
        ids = [item["stable_id"] for item in normalized]
        if ids != sorted(ids) or len(ids) != len(set(ids)) or seen.intersection(ids):
            _fail("queue stable IDs must be globally unique and ordered")
        seen.update(ids)
        result.append({"batch_index": expected_index, "items": normalized})
    if len(seen) > MAX_QUEUE_ITEMS:
        _fail("queue item count is outside the bound")
    return result


def _manifest(batches: Sequence[Mapping[str, Any]], *, stage: str, reviewer_kind: str, reviewer_id: str) -> dict[str, Any]:
    normalized = validate_teacher_batches(batches)
    kind, identifier = _reviewer(reviewer_kind, reviewer_id)
    if stage not in STAGES:
        _fail("stage is unsupported")
    files = []
    for batch in normalized:
        name = f"batch-{batch['batch_index']:03d}.json"
        payload = _canonical_payload(batch)
        files.append({"name": name, "item_count": len(batch["items"]), "content_sha256": hashlib.sha256(payload).hexdigest()})
    return {
        "schema_version": V4_SCHEMA_VERSION,
        "manifest_kind": V4_QUEUE_MANIFEST_KIND,
        "stage": stage,
        "reviewer_kind": kind,
        "reviewer_id": identifier,
        "batch_size_limit": MAX_BATCH_ITEMS,
        "batch_count": len(normalized),
        "record_count": sum(len(batch["items"]) for batch in normalized),
        "batch_files": files,
        "content_sha256": _canonical_jsonl_sha256(
            [item for batch in normalized for item in batch["items"]]
        ),
        "raw_text_in_manifest": False,
    }


def publish_teacher_queue_directory(directory: str | Path, batches: Sequence[Mapping[str, Any]], *, stage: str, reviewer_kind: str, reviewer_id: str) -> dict[str, Any]:
    """Publish an immutable queue directory by one final same-parent rename."""

    target = Path(directory)
    if target.exists():
        _fail("queue directory already exists and is immutable")
    if not target.parent.is_dir():
        _fail("queue parent directory does not exist")
    normalized = validate_teacher_batches(batches)
    manifest = _manifest(normalized, stage=stage, reviewer_kind=reviewer_kind, reviewer_id=reviewer_id)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for batch in normalized:
            write_bytes_atomic(temporary / f"batch-{batch['batch_index']:03d}.json", _canonical_payload(batch))
        write_bytes_atomic(temporary / "manifest.json", _canonical_payload(manifest))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def _read_json(path: Path, maximum: int) -> Any:
    try:
        payload = path.read_bytes()
    except OSError as error:
        _fail(f"cannot read {path.name} ({type(error).__name__})")
    if not payload or len(payload) > maximum:
        _fail(f"{path.name} is empty or outside the byte bound")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{path.name} is not valid UTF-8 JSON ({type(error).__name__})")


def read_teacher_queue_directory(directory: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        _fail("queue directory is missing")
    names = {entry.name for entry in root.iterdir()}
    if "manifest.json" not in names or any(name != "manifest.json" and _BATCH_NAME.fullmatch(name) is None for name in names):
        _fail("queue directory contains unexpected files")
    manifest = _read_json(root / "manifest.json", MAX_MANIFEST_BYTES)
    expected = {"schema_version", "manifest_kind", "stage", "reviewer_kind", "reviewer_id", "batch_size_limit", "batch_count", "record_count", "batch_files", "content_sha256", "raw_text_in_manifest"}
    if not isinstance(manifest, Mapping) or set(manifest) != expected or manifest.get("schema_version") != V4_SCHEMA_VERSION or manifest.get("manifest_kind") != V4_QUEUE_MANIFEST_KIND:
        _fail("queue manifest fields do not match schema")
    if manifest.get("stage") not in STAGES or manifest.get("batch_size_limit") != MAX_BATCH_ITEMS or manifest.get("raw_text_in_manifest") is not False:
        _fail("queue manifest values are invalid")
    _reviewer(manifest.get("reviewer_kind"), manifest.get("reviewer_id"))
    files = manifest.get("batch_files")
    if not isinstance(files, list) or manifest.get("batch_count") != len(files) or not files:
        _fail("queue manifest batch files are invalid")
    expected_names = {"manifest.json"}
    batches: list[dict[str, Any]] = []
    for index, entry in enumerate(files):
        name = f"batch-{index:03d}.json"
        if not isinstance(entry, Mapping) or set(entry) != {"name", "item_count", "content_sha256"} or entry.get("name") != name or type(entry.get("item_count")) is not int or not 1 <= entry["item_count"] <= MAX_BATCH_ITEMS or not isinstance(entry.get("content_sha256"), str) or _SHA256.fullmatch(entry["content_sha256"]) is None:
            _fail("queue manifest batch entry is invalid")
        expected_names.add(name)
        batch_path = root / name
        batch = _read_json(batch_path, MAX_BATCH_BYTES)
        if hashlib.sha256(_canonical_payload(batch)).hexdigest() != entry["content_sha256"]:
            _fail("queue batch hash mismatch")
        batches.append(batch)
    if names != expected_names:
        _fail("queue directory file set does not match manifest")
    normalized = validate_teacher_batches(batches)
    if manifest.get("record_count") != sum(len(batch["items"]) for batch in normalized):
        _fail("queue manifest record count mismatch")
    content = _canonical_jsonl_sha256(
        [item for batch in normalized for item in batch["items"]]
    )
    if manifest.get("content_sha256") != content:
        _fail("queue manifest content hash mismatch")
    return normalized, dict(manifest)


def validate_teacher_verdict_batch(batch: Mapping[str, Any], verdict_payload: Mapping[str, Any], *, reviewer_kind: str, reviewer_id: str) -> dict[str, Any]:
    """Require exact in-order coverage and reviewer-bound, versioned verdicts."""

    expected = {"schema_version", "record_type", "batch_index", "reviewer_kind", "reviewer_id", "verdicts"}
    if not isinstance(verdict_payload, Mapping) or set(verdict_payload) != expected:
        _fail("verdict fields do not match schema")
    kind, identifier = _reviewer(reviewer_kind, reviewer_id)
    if verdict_payload.get("schema_version") != V4_SCHEMA_VERSION or verdict_payload.get("record_type") != V4_VERDICT_RECORD_TYPE or verdict_payload.get("batch_index") != batch.get("batch_index") or verdict_payload.get("reviewer_kind") != kind or verdict_payload.get("reviewer_id") != identifier:
        _fail("verdict batch provenance does not match queue")
    verdicts = verdict_payload.get("verdicts")
    items = batch.get("items")
    if not isinstance(verdicts, list) or not isinstance(items, list) or len(verdicts) != len(items):
        _fail("verdict coverage does not match batch")
    output: list[dict[str, str]] = []
    for item, verdict in zip(items, verdicts, strict=True):
        if not isinstance(verdict, Mapping) or set(verdict) != {"stable_id", "verdict", "note"} or verdict.get("stable_id") != item.get("stable_id"):
            _fail("verdict stable IDs must exactly match queue order")
        if verdict.get("verdict") not in VERDICTS:
            _fail("verdict enum is invalid")
        note = verdict.get("note")
        if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS or "\0" in note or "\n" in note or "\r" in note:
            _fail("verdict note is invalid")
        output.append(dict(verdict))
    return {"schema_version": V4_SCHEMA_VERSION, "record_type": V4_VERDICT_RECORD_TYPE, "batch_index": batch["batch_index"], "reviewer_kind": kind, "reviewer_id": identifier, "verdicts": output}


def scan_verdict_directory(queue_directory: str | Path, verdict_directory: str | Path) -> tuple[dict[int, dict[str, Any]], list[int]]:
    """Return mechanically valid completed batches and pending indexes.

    Missing expected files are resumable.  Every present file is validated;
    malformed, foreign, or extra output is an error rather than a skip.
    """

    batches, manifest = read_teacher_queue_directory(queue_directory)
    root = Path(verdict_directory)
    if not root.exists():
        return {}, list(range(len(batches)))
    if not root.is_dir():
        _fail("verdict directory is not a directory")
    names = {entry.name for entry in root.iterdir()}
    expected_names = {f"verdicts-{batch['batch_index']:03d}.json" for batch in batches}
    if any(_VERDICT_NAME.fullmatch(name) is None for name in names) or names - expected_names:
        _fail("verdict directory contains unexpected files")
    completed: dict[int, dict[str, Any]] = {}
    pending: list[int] = []
    for batch in batches:
        index = batch["batch_index"]
        path = root / f"verdicts-{index:03d}.json"
        if not path.exists():
            pending.append(index)
            continue
        value = _read_json(path, MAX_BATCH_BYTES)
        try:
            completed[index] = validate_teacher_verdict_batch(
                batch,
                value,
                reviewer_kind=manifest["reviewer_kind"],
                reviewer_id=manifest["reviewer_id"],
            )
        except TierAError as exc:
            _fail(f"verdict batch {index:03d}: {exc}")
    return completed, pending


def teacher_verdict_state_sha256(
    verdicts: Mapping[int, Mapping[str, Any]],
) -> str:
    """Hash the exact reviewer-bound verdict state without emitting its notes."""

    rows: list[dict[str, Any]] = []
    for index in sorted(verdicts):
        payload = verdicts[index]
        if (
            type(index) is not int
            or not isinstance(payload, Mapping)
            or payload.get("batch_index") != index
            or not isinstance(payload.get("verdicts"), list)
        ):
            _fail("teacher verdict state is invalid")
        for entry in payload["verdicts"]:
            if not isinstance(entry, Mapping) or set(entry) != {
                "stable_id",
                "verdict",
                "note",
            }:
                _fail("teacher verdict state entry is invalid")
            rows.append(
                {
                    "stable_id": entry["stable_id"],
                    "batch_index": index,
                    "reviewer_kind": payload.get("reviewer_kind"),
                    "reviewer_id": payload.get("reviewer_id"),
                    "verdict": entry["verdict"],
                    "note": entry["note"],
                }
            )
    return _canonical_jsonl_sha256(rows)


def read_handoff_batches(directory: str | Path) -> list[dict[str, Any]]:
    """Read the legacy v4 handoff batches with stricter production validation."""

    root = Path(directory)
    if not root.is_dir():
        _fail("handoff batch directory is missing")
    paths = sorted(root.glob("batch-*.json"))
    if not paths or len(paths) > MAX_BATCHES:
        _fail("handoff batch files are empty or outside the bound")
    names = {entry.name for entry in root.iterdir()}
    expected_names = {f"batch-{index:03d}.json" for index in range(len(paths))}
    if names != expected_names:
        _fail("handoff batch directory file set is not contiguous and exact")
    return validate_teacher_batches(
        [_read_json(root / name, MAX_BATCH_BYTES) for name in sorted(expected_names)]
    )


def read_handoff_verdict_directory(
    batches: Sequence[Mapping[str, Any]],
    verdict_directory: str | Path,
    *,
    allowed_missing_indexes: Sequence[int] = (),
) -> tuple[dict[int, dict[str, Any]], list[int]]:
    """Read legacy handoff verdicts with exact order, enum, and note<=200.

    The dev handoff predates reviewer-bound v4 production verdicts, so it is
    accepted only by this isolated adapter.  Missing files must be explicitly
    allowlisted; every present file and the complete directory file set remain
    fail-closed.
    """

    normalized = validate_teacher_batches(batches)
    allowed_missing = set(allowed_missing_indexes)
    if (
        len(allowed_missing) != len(allowed_missing_indexes)
        or any(type(index) is not int or not 0 <= index < len(normalized) for index in allowed_missing)
    ):
        _fail("handoff allowed-missing indexes are invalid")
    root = Path(verdict_directory)
    if not root.is_dir():
        _fail("handoff verdict directory is missing")
    names = {entry.name for entry in root.iterdir()}
    expected_names = {
        f"verdicts-{batch['batch_index']:03d}.json" for batch in normalized
    }
    if any(_VERDICT_NAME.fullmatch(name) is None for name in names) or names - expected_names:
        _fail("handoff verdict directory contains unexpected files")
    completed: dict[int, dict[str, Any]] = {}
    pending: list[int] = []
    for batch in normalized:
        index = batch["batch_index"]
        name = f"verdicts-{index:03d}.json"
        if name not in names:
            pending.append(index)
            continue
        value = _read_json(root / name, MAX_BATCH_BYTES)
        if not isinstance(value, Mapping) or set(value) != {"batch_index", "verdicts"} or value.get("batch_index") != index:
            _fail("handoff verdict fields do not match schema")
        entries = value.get("verdicts")
        if not isinstance(entries, list) or len(entries) != len(batch["items"]):
            _fail("handoff verdict coverage does not match batch")
        checked: list[dict[str, str]] = []
        for item, entry in zip(batch["items"], entries, strict=True):
            if (
                not isinstance(entry, Mapping)
                or set(entry) != {"stable_id", "verdict", "note"}
                or entry.get("stable_id") != item["stable_id"]
            ):
                _fail("handoff verdict stable IDs must exactly match queue order")
            if entry.get("verdict") not in VERDICTS:
                _fail("handoff verdict enum is invalid")
            note = entry.get("note")
            if (
                not isinstance(note, str)
                or len(note) > MAX_NOTE_CHARS
                or "\0" in note
                or "\n" in note
                or "\r" in note
            ):
                _fail("handoff verdict note is invalid")
            checked.append(dict(entry))
        completed[index] = {"batch_index": index, "verdicts": checked}
    if set(pending) - allowed_missing or allowed_missing - set(pending):
        _fail("handoff verdict missing files do not match the explicit allowance")
    return completed, pending


def flatten_handoff_verdicts(
    batches: Sequence[Mapping[str, Any]], verdicts: Mapping[int, Mapping[str, Any]]
) -> dict[str, str]:
    normalized = validate_teacher_batches(batches)
    if set(verdicts) != set(range(len(normalized))):
        _fail("handoff verdicts must cover every batch")
    result: dict[str, str] = {}
    for batch in normalized:
        payload = verdicts[batch["batch_index"]]
        if (
            not isinstance(payload, Mapping)
            or payload.get("batch_index") != batch["batch_index"]
            or not isinstance(payload.get("verdicts"), list)
        ):
            _fail("handoff verdict payload is invalid")
        for item, entry in zip(batch["items"], payload["verdicts"], strict=True):
            if entry.get("stable_id") != item["stable_id"] or entry.get("verdict") not in VERDICTS:
                _fail("handoff verdict payload no longer matches its batch")
            result[item["stable_id"]] = entry["verdict"]
    return result


def flatten_teacher_verdicts(
    batches: Sequence[Mapping[str, Any]],
    verdicts: Mapping[int, Mapping[str, Any]],
    *,
    reviewer_id: str,
) -> dict[str, str]:
    normalized = validate_teacher_batches(batches)
    if set(verdicts) != set(range(len(normalized))):
        _fail("teacher verdicts must cover every batch")
    result: dict[str, str] = {}
    for batch in normalized:
        checked = validate_teacher_verdict_batch(
            batch,
            verdicts[batch["batch_index"]],
            reviewer_kind="ai_teacher",
            reviewer_id=reviewer_id,
        )
        result.update(
            {entry["stable_id"]: entry["verdict"] for entry in checked["verdicts"]}
        )
    return result


def build_stage2_batches(stage1_batches: Sequence[Mapping[str, Any]], stage1_verdicts: Mapping[int, Mapping[str, Any]], *, batch_size: int = MAX_BATCH_ITEMS) -> list[dict[str, Any]]:
    """Build a fresh note-free Stage 2 queue from every Stage 1 non-valid row."""

    batches = validate_teacher_batches(stage1_batches)
    if set(stage1_verdicts) != set(range(len(batches))):
        _fail("stage1 verdicts must cover every batch before stage2")
    selected: list[dict[str, Any]] = []
    for batch in batches:
        verdict = validate_teacher_verdict_batch(
            batch,
            stage1_verdicts[batch["batch_index"]],
            reviewer_kind="ai_teacher",
            reviewer_id=SCREEN_REVIEWER_ID,
        )
        selected.extend(item for item, outcome in zip(batch["items"], verdict["verdicts"], strict=True) if outcome["verdict"] != "valid")
    if not selected:
        _fail("stage1 has no non-valid rows for stage2")
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_ITEMS:
        _fail("batch_size is outside the bound")
    selected.sort(key=lambda item: item["stable_id"])
    return [{"batch_index": index, "items": selected[start : start + batch_size]} for index, start in enumerate(range(0, len(selected), batch_size))]


def merge_external_verdict_maps(
    *verdict_maps: Mapping[str, str],
) -> dict[str, str]:
    """Merge trusted prior-review outcomes, rejecting conflicting evidence."""

    merged: dict[str, str] = {}
    for values in verdict_maps:
        if not isinstance(values, Mapping):
            _fail("external verdict input is invalid")
        for identifier, verdict in values.items():
            _identifier(identifier, "external verdict stable_id")
            if verdict not in VERDICTS:
                _fail("external verdict enum is invalid")
            prior = merged.get(identifier)
            if prior is not None and prior != verdict:
                _fail("external verdict sources conflict for one stable ID")
            merged[identifier] = verdict
    return dict(sorted(merged.items()))


def audit_response_verdict_map(
    responses: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Extract only stable-ID/verdict state from already validated responses."""

    result: dict[str, str] = {}
    for response in responses:
        if not isinstance(response, Mapping):
            _fail("audit response is invalid")
        identifier = _identifier(response.get("stable_id"), "audit response stable_id")
        verdict = response.get("verdict")
        if verdict not in VERDICTS:
            _fail("audit response verdict enum is invalid")
        if identifier in result:
            _fail("audit responses contain duplicate stable IDs")
        result[identifier] = verdict
    return dict(sorted(result.items()))


def partition_stage2(
    records: Sequence[Mapping[str, Any]],
    stage1_batches: Sequence[Mapping[str, Any]],
    stage1_verdicts: Mapping[int, Mapping[str, Any]],
    stage2_batches: Sequence[Mapping[str, Any]],
    stage2_verdicts: Mapping[int, Mapping[str, Any]],
    *,
    external_verdicts: Mapping[str, str],
    stage0_hit_ids: Sequence[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build the exact v4 retained/excluded/quarantine partition.

    Exclusion is the union of (a) rows rejected by both fresh passes, excluding
    ambiguous outcomes, (b) trusted prior Opus/dev and v3-holdout rejections,
    and (c) the adopted deterministic cleaner hits.  The owner-approved
    precision-first policy quarantines both any ambiguous outcome and every row
    flagged by Stage 1 but returned to valid by Stage 2.  Quarantine wins over
    independent exclusion evidence so the disputed row is never declared a
    confirmed rejection.
    """

    normalized = strict_preflight(records)
    first = validate_teacher_batches(stage1_batches)
    second = validate_teacher_batches(stage2_batches)
    first_by_id = flatten_teacher_verdicts(
        first, stage1_verdicts, reviewer_id=SCREEN_REVIEWER_ID
    )
    second_by_id = flatten_teacher_verdicts(
        second, stage2_verdicts, reviewer_id=ADJUDICATION_REVIEWER_ID
    )
    record_ids = {record["stable_id"] for record in normalized}
    expected_second = {
        identifier for identifier, verdict in first_by_id.items() if verdict != "valid"
    }
    if set(first_by_id) != record_ids or set(second_by_id) != expected_second:
        _fail("teacher queue coverage does not match the immutable input")
    external = merge_external_verdict_maps(external_verdicts)
    if set(external) - record_ids:
        _fail("external verdicts contain IDs outside the immutable input")
    stage0_ids = set(stage0_hit_ids)
    if len(stage0_ids) != len(stage0_hit_ids) or stage0_ids - record_ids:
        _fail("Stage 0 hit IDs are duplicate or outside the immutable input")

    ambiguous_ids = {
        identifier
        for identifier in record_ids
        if "ambiguous"
        in (
            first_by_id[identifier],
            second_by_id.get(identifier),
            external.get(identifier),
        )
    }
    both_nonvalid_ids = {
        identifier
        for identifier, first_verdict in first_by_id.items()
        if first_verdict != "valid"
        and second_by_id[identifier] != "valid"
        and "ambiguous" not in (first_verdict, second_by_id[identifier])
    }
    external_nonvalid_ids = {
        identifier
        for identifier, verdict in external.items()
        if verdict not in {"valid", "ambiguous"}
    }
    stage1_nonvalid_stage2_valid_ids = {
        identifier
        for identifier, first_verdict in first_by_id.items()
        if first_verdict != "valid" and second_by_id[identifier] == "valid"
    }
    quarantine_ids = ambiguous_ids | stage1_nonvalid_stage2_valid_ids
    rejected_ids = (
        both_nonvalid_ids | external_nonvalid_ids | stage0_ids
    ) - quarantine_ids
    retained_ids = record_ids - rejected_ids - quarantine_ids

    result = {"retained": [], "excluded": [], "ambiguous_quarantine": []}
    for record in normalized:
        identifier = record["stable_id"]
        if identifier in quarantine_ids:
            result["ambiguous_quarantine"].append(record)
        elif identifier in rejected_ids:
            result["excluded"].append(record)
        else:
            result["retained"].append(record)

    def stratum_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        counts = Counter(_stratum(record) for record in rows)
        return dict(sorted(counts.items()))

    report = {
        "schema_version": V4_SCHEMA_VERSION,
        "report_kind": V4_REPORT_KIND,
        "input_record_count": len(normalized),
        "retained_record_count": len(result["retained"]),
        "excluded_record_count": len(result["excluded"]),
        "ambiguous_quarantine_record_count": len(result["ambiguous_quarantine"]),
        "partition_policy": "precision_first_quarantine_one_pass_recovery_v1",
        "exclusion_reason_counts": {
            "both_new_passes_nonvalid": len(both_nonvalid_ids - quarantine_ids),
            "prior_opus_or_v3_nonvalid": len(external_nonvalid_ids - quarantine_ids),
            "stage0_deterministic_hit": len(stage0_ids - quarantine_ids),
            "union": len(rejected_ids),
        },
        "quarantine_reason_counts": {
            "ambiguous_outcome": len(ambiguous_ids),
            "stage1_nonvalid_stage2_valid": len(
                stage1_nonvalid_stage2_valid_ids
            ),
            "union": len(quarantine_ids),
        },
        "bucket_stratum_counts": {
            name: stratum_counts(rows) for name, rows in sorted(result.items())
        },
        "stage1_verdict_counts": {
            name: Counter(first_by_id.values()).get(name, 0) for name in sorted(VERDICTS)
        },
        "stage2_verdict_counts": {
            name: Counter(second_by_id.values()).get(name, 0) for name in sorted(VERDICTS)
        },
        "external_verdict_counts": {
            name: Counter(external.values()).get(name, 0) for name in sorted(VERDICTS)
        },
        "input_content_sha256": _canonical_jsonl_sha256(normalized),
        "raw_text_in_report": False,
    }
    bucket_ids = {
        name: {record["stable_id"] for record in rows}
        for name, rows in result.items()
    }
    if (
        sum(len(rows) for rows in result.values()) != len(normalized)
        or set().union(*bucket_ids.values()) != record_ids
        or any(
            bucket_ids[left] & bucket_ids[right]
            for left, right in (
                ("retained", "excluded"),
                ("retained", "ambiguous_quarantine"),
                ("excluded", "ambiguous_quarantine"),
            )
        )
    ):
        _fail("partition does not exhaust the immutable input")
    return result, report


def stage3_one_pass_only_ids(
    first_verdicts: Mapping[str, str], second_verdicts: Mapping[str, str]
) -> list[str]:
    """Return rows where exactly one of the two new passes is non-valid."""

    for identifier, verdict in [*first_verdicts.items(), *second_verdicts.items()]:
        _identifier(identifier, "stage3 stable_id")
        if verdict not in VERDICTS:
            _fail("stage3 verdict enum is invalid")
    expected_second = {
        identifier for identifier, verdict in first_verdicts.items() if verdict != "valid"
    }
    if set(second_verdicts) != expected_second:
        _fail("stage3 Stage 2 coverage does not match Stage 1 non-valid rows")
    return sorted(
        identifier
        for identifier in expected_second
        if second_verdicts[identifier] == "valid"
    )


def select_stage3_ids(
    disagreement_ids: Sequence[str], one_pass_only_ids: Sequence[str], *, seed: int
) -> tuple[list[str], list[str]]:
    """Select all handoff disagreements plus exactly 100 independent one-pass IDs."""

    if type(seed) is not int:
        _fail("stage3 seed must be an integer")
    disagreements = set(disagreement_ids)
    if len(disagreements) != len(disagreement_ids):
        _fail("stage3 disagreement IDs are duplicate")
    for identifier in disagreements:
        _identifier(identifier, "stage3 disagreement stable_id")
    candidates = set(one_pass_only_ids)
    if len(candidates) != len(one_pass_only_ids):
        _fail("one-pass-only IDs are duplicate")
    for identifier in candidates:
        _identifier(identifier, "stage3 one-pass stable_id")
    candidates -= disagreements
    if len(candidates) < 100:
        _fail("stage3 needs at least 100 one-pass-only candidates outside disagreements")
    chosen = sorted(
        candidates,
        key=lambda identifier: (
            hashlib.sha256(f"{seed}\0{identifier}".encode("utf-8")).digest(),
            identifier,
        ),
    )[:100]
    return sorted(disagreements | set(chosen)), sorted(chosen)


def discover_teacher_disagreements(directory: str | Path) -> list[dict[str, str]]:
    """Load every aggregate-only disagreement JSONL without double-counting IDs.

    The handoff may contain the final consolidated file and/or per-run files.
    Repeated identical rows are harmless provenance duplication; conflicting
    rows for one stable ID are evidence corruption and fail closed.
    """

    root = Path(directory)
    if not root.is_dir():
        _fail("teacher disagreement directory is missing")
    paths = sorted(root.glob("teacher-disagreements-*.jsonl"))
    if not paths:
        _fail("teacher disagreement files are missing")
    by_id: dict[str, dict[str, str]] = {}
    expected = {"stable_id", "stratum", "verdict_a", "verdict_b"}
    for path in paths:
        try:
            payload = path.read_bytes()
        except OSError as error:
            _fail(f"cannot read disagreement file ({type(error).__name__})")
        if not payload or len(payload) > MAX_BATCH_BYTES:
            _fail("teacher disagreement file is empty or outside the byte bound")
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            _fail(f"teacher disagreement file is not UTF-8 ({type(error).__name__})")
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                _fail("teacher disagreement file has invalid JSON")
            if not isinstance(value, Mapping) or set(value) != expected:
                _fail("teacher disagreement fields do not match schema")
            identifier = _identifier(value.get("stable_id"), "teacher disagreement stable_id")
            if not isinstance(value.get("stratum"), str) or not value["stratum"] or len(value["stratum"]) > 128:
                _fail("teacher disagreement stratum is invalid")
            if value.get("verdict_a") not in VERDICTS or value.get("verdict_b") not in VERDICTS or value["verdict_a"] == value["verdict_b"]:
                _fail("teacher disagreement verdicts are invalid")
            normalized = {"stable_id": identifier, "stratum": value["stratum"], "verdict_a": value["verdict_a"], "verdict_b": value["verdict_b"]}
            prior = by_id.get(identifier)
            if prior is not None and prior != normalized:
                _fail("teacher disagreement stable ID has conflicting rows")
            by_id[identifier] = normalized
    return [by_id[identifier] for identifier in sorted(by_id)]


def stage3_human_audit_items(records: Sequence[Mapping[str, Any]], stable_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Convert selected v4 records to the established standard human-audit items."""

    normalized = strict_preflight(records)
    if not stable_ids or len(stable_ids) != len(set(stable_ids)):
        _fail("stage3 stable IDs are empty or duplicate")
    by_id = {record["stable_id"]: record for record in normalized}
    if set(stable_ids) - set(by_id):
        _fail("stage3 stable IDs are outside input")
    return [_human_audit_item(by_id[identifier]) for identifier in sorted(stable_ids)]


def _partition_ids(
    partition: Mapping[str, Sequence[Mapping[str, Any] | str]],
) -> dict[str, list[str]]:
    if not isinstance(partition, Mapping) or set(partition) != set(_STABLE_ID_BUCKET_FILES):
        _fail("partition buckets do not match schema")
    output: dict[str, list[str]] = {}
    seen: set[str] = set()
    for name in sorted(_STABLE_ID_BUCKET_FILES):
        rows = partition[name]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            _fail("partition bucket is invalid")
        identifiers: list[str] = []
        for row in rows:
            identifier = row if isinstance(row, str) else row.get("stable_id")
            identifiers.append(_identifier(identifier, "partition stable_id"))
        if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
            _fail("partition bucket stable IDs must be sorted and unique")
        if seen.intersection(identifiers):
            _fail("partition buckets overlap")
        seen.update(identifiers)
        output[name] = identifiers
    return output


def _stable_id_jsonl(ids: Sequence[str]) -> bytes:
    return canonical_jsonl_bytes([{"stable_id": identifier} for identifier in ids])


def publish_partition_directory(
    directory: str | Path,
    partition: Mapping[str, Sequence[Mapping[str, Any] | str]],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish canonical stable-ID buckets and their aggregate report immutably."""

    target = Path(directory)
    if target.exists():
        _fail("partition directory already exists and is immutable")
    if not target.parent.is_dir():
        _fail("partition parent directory does not exist")
    identifiers = _partition_ids(partition)
    input_count = sum(len(values) for values in identifiers.values())
    expected_counts = {
        "retained_record_count": len(identifiers["retained"]),
        "excluded_record_count": len(identifiers["excluded"]),
        "ambiguous_quarantine_record_count": len(identifiers["ambiguous_quarantine"]),
    }
    if (
        not isinstance(report, Mapping)
        or report.get("report_kind") != V4_REPORT_KIND
        or report.get("input_record_count") != input_count
        or any(report.get(field) != count for field, count in expected_counts.items())
        or report.get("raw_text_in_report") is not False
    ):
        _fail("partition report does not reconcile with buckets")
    payloads = {
        name: _stable_id_jsonl(identifiers[name]) for name in sorted(identifiers)
    }
    stage4_ids = sorted(
        identifiers["excluded"] + identifiers["ambiguous_quarantine"]
    )
    stage4_payload = _stable_id_jsonl(stage4_ids)
    published_report = dict(report)
    published_report["bucket_content_sha256"] = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in sorted(payloads.items())
    }
    published_report["stage4_stable_id_exclusion"] = {
        "format_version": 1,
        "canonicalization": "utf8_lf_sorted_unique_stable_id_jsonl_v1",
        "count": len(stage4_ids),
        "content_sha256": hashlib.sha256(stage4_payload).hexdigest(),
        "raw_stable_ids_in_report": False,
    }
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for name, payload in payloads.items():
            write_bytes_atomic(temporary / _STABLE_ID_BUCKET_FILES[name], payload)
        write_bytes_atomic(temporary / "stage4-stable-id-exclusion.jsonl", stage4_payload)
        write_bytes_atomic(temporary / "report.json", _canonical_payload(published_report))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return published_report


def build_stage3_calibration_queue(
    records: Sequence[Mapping[str, Any]],
    disagreement_rows: Sequence[Mapping[str, str]],
    stage1_verdicts: Mapping[str, str],
    stage2_verdicts: Mapping[str, str],
    *,
    seed: int = CALIBRATION_SEED,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Prepare, but never answer, the owner calibration queue."""

    normalized = strict_preflight(records)
    by_id = {record["stable_id"]: record for record in normalized}
    record_ids = set(by_id)
    disagreement_ids: list[str] = []
    normalized_disagreements: list[dict[str, str]] = []
    for row in disagreement_rows:
        if not isinstance(row, Mapping) or set(row) != {
            "stable_id",
            "stratum",
            "verdict_a",
            "verdict_b",
        }:
            _fail("Stage 3 disagreement row fields do not match schema")
        identifier = _identifier(row["stable_id"], "Stage 3 disagreement stable_id")
        if identifier not in record_ids:
            _fail("Stage 3 disagreement ID is outside the source dataset")
        if row["stratum"] != _stratum(by_id[identifier]):
            _fail("Stage 3 disagreement stratum does not match the source dataset")
        if (
            row["verdict_a"] not in VERDICTS
            or row["verdict_b"] not in VERDICTS
            or row["verdict_a"] == row["verdict_b"]
        ):
            _fail("Stage 3 disagreement verdicts are invalid")
        disagreement_ids.append(identifier)
        normalized_disagreements.append(dict(row))
    if (
        not normalized_disagreements
        or disagreement_ids != sorted(disagreement_ids)
        or len(disagreement_ids) != len(set(disagreement_ids))
    ):
        _fail("Stage 3 disagreement rows must be non-empty, sorted, and unique")
    if set(stage1_verdicts) != record_ids:
        _fail("Stage 3 Stage 1 state does not cover the source dataset")
    one_pass_only = stage3_one_pass_only_ids(stage1_verdicts, stage2_verdicts)
    selected_ids, selected_one_pass = select_stage3_ids(
        disagreement_ids, one_pass_only, seed=seed
    )
    queue = stage3_human_audit_items(normalized, selected_ids)
    teacher_state_rows = [
        {
            "stable_id": identifier,
            "stage1_verdict": stage1_verdicts[identifier],
            "stage2_verdict": stage2_verdicts.get(identifier),
        }
        for identifier in sorted(stage1_verdicts)
    ]
    manifest = build_calibration_queue_manifest(
        queue,
        seed=seed,
        source_dataset_record_count=len(normalized),
        source_dataset_content_sha256=_canonical_jsonl_sha256(normalized),
        teacher_state_content_sha256=_canonical_jsonl_sha256(teacher_state_rows),
        disagreement_list_content_sha256=_canonical_jsonl_sha256(
            normalized_disagreements
        ),
        disagreement_record_count=len(disagreement_ids),
        one_pass_eligible_record_count=len(set(one_pass_only) - set(disagreement_ids)),
        one_pass_selected_record_count=len(selected_one_pass),
    )
    return queue, manifest, selected_one_pass


def publish_stage3_calibration_queue(
    queue_path: str | Path,
    manifest_path: str | Path,
    records: Sequence[Mapping[str, Any]],
    disagreement_rows: Sequence[Mapping[str, str]],
    stage1_verdicts: Mapping[str, str],
    stage2_verdicts: Mapping[str, str],
    *,
    seed: int = CALIBRATION_SEED,
) -> tuple[dict[str, Any], str, str]:
    queue_target = Path(queue_path)
    manifest_target = Path(manifest_path)
    try:
        ensure_distinct_tier_a_paths(
            {"calibration_queue": queue_target, "calibration_manifest": manifest_target}
        )
    except TierAError as error:
        _fail(str(error))
    if queue_target.exists() or manifest_target.exists():
        _fail("calibration queue artifacts already exist and are immutable")
    if not queue_target.parent.is_dir() or not manifest_target.parent.is_dir():
        _fail("calibration queue parent directory is missing")
    queue, manifest, _ = build_stage3_calibration_queue(
        records,
        disagreement_rows,
        stage1_verdicts,
        stage2_verdicts,
        seed=seed,
    )
    queue_sha, manifest_sha = publish_audit_queue(
        queue_path, manifest_path, queue, manifest
    )
    return manifest, queue_sha, manifest_sha
