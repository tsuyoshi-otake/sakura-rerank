"""Build provenance-bound input batches for the verified research exporter."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_pair_atomic
from .contracts import canonical_json_bytes, canonical_jsonl_bytes
from .tier_a import (
    TierAError,
    validate_dictionary_index,
    validate_dictionary_index_manifest,
    validate_source_span_manifest,
    validate_source_spans,
)


REQUEST_REPORT_SCHEMA_VERSION = 1
REQUEST_REPORT_KIND = "research_top32_request_batch"
MAX_EXPORTER_REQUESTS = 4_096
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_STABLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_REPORT_FIELDS = {
    "schema_version",
    "report_kind",
    "verification_status",
    "builder_git_sha",
    "record_count",
    "content_sha256",
    "source_span_content_sha256",
    "source_span_extractor_git_sha",
    "dictionary_index_content_sha256",
    "dictionary_indexer_git_sha",
    "dictionary_sha256",
    "sakura_input_head",
    "jawiki_local_sha256",
    "raw_text_in_report",
}


def _git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise TierAError(f"{field}: must be a full lowercase Git SHA")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise TierAError(f"{field}: must be a lowercase SHA-256")
    return value


def validate_exporter_requests(
    requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    if not requests or len(requests) > MAX_EXPORTER_REQUESTS:
        raise TierAError("exporter_requests: record count is outside the exporter bound")
    normalized: list[dict[str, str]] = []
    for index, request in enumerate(requests):
        if set(request) != {"stable_id", "reading"}:
            raise TierAError(f"exporter_requests[{index}]: fields do not match the schema")
        stable_id = request["stable_id"]
        reading = request["reading"]
        if not isinstance(stable_id, str) or _STABLE_ID_PATTERN.fullmatch(stable_id) is None:
            raise TierAError(f"exporter_requests[{index}].stable_id: outside bounded alphabet")
        if (
            not isinstance(reading, str)
            or not reading
            or len(reading) > 128
            or any(character in reading for character in ("\0", "\r", "\n"))
        ):
            raise TierAError(f"exporter_requests[{index}].reading: outside bounded contract")
        normalized.append({"stable_id": stable_id, "reading": reading})
    stable_ids = [request["stable_id"] for request in normalized]
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise TierAError("exporter_requests.stable_id: must be sorted and unique")
    return normalized


def validate_request_report(
    report: Mapping[str, Any], requests: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if set(report) != _REPORT_FIELDS:
        raise TierAError("report: fields do not match the aggregate-only schema")
    if report["schema_version"] != REQUEST_REPORT_SCHEMA_VERSION:
        raise TierAError("report.schema_version: unsupported schema")
    if report["report_kind"] != REQUEST_REPORT_KIND:
        raise TierAError("report.report_kind: unsupported kind")
    if report["verification_status"] != "verified_inputs":
        raise TierAError("report.verification_status: verified_inputs is required")
    if report["raw_text_in_report"] is not False:
        raise TierAError("report.raw_text_in_report: must be false")
    if type(report["record_count"]) is not int or report["record_count"] != len(requests):
        raise TierAError("report.record_count: does not match exporter requests")
    normalized = dict(report)
    for field in (
        "builder_git_sha",
        "source_span_extractor_git_sha",
        "dictionary_indexer_git_sha",
        "sakura_input_head",
    ):
        normalized[field] = _git_sha(report[field], f"report.{field}")
    for field in (
        "content_sha256",
        "source_span_content_sha256",
        "dictionary_index_content_sha256",
        "dictionary_sha256",
        "jawiki_local_sha256",
    ):
        normalized[field] = _sha256(report[field], f"report.{field}")
    expected_sha = hashlib.sha256(canonical_jsonl_bytes(requests)).hexdigest()
    if normalized["content_sha256"] != expected_sha:
        raise TierAError("report.content_sha256: does not match exporter requests")
    return normalized


def ensure_paths_under_root(
    paths: Mapping[str, str | Path], allowed_root: str | Path
) -> None:
    """Reject paths outside the caller-owned artifact boundary."""

    try:
        root = Path(allowed_root).resolve(strict=True)
        if not root.is_dir():
            raise TierAError("allowed_root: must be a directory")
        for name, value in paths.items():
            resolved = Path(value).resolve(strict=False)
            if not resolved.is_relative_to(root):
                raise TierAError(f"paths: {name} must remain below allowed_root")
    except OSError as error:
        raise TierAError(f"paths: cannot resolve ({type(error).__name__})") from error


def generate_exporter_requests(
    source_records: Sequence[Mapping[str, Any]],
    dictionary_records: Sequence[Mapping[str, Any]],
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_manifest: Mapping[str, Any],
    source_span_manifest: Mapping[str, Any],
    builder_git_sha: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Join every verified source span to one exact system-dictionary reading."""

    builder_git_sha = _git_sha(builder_git_sha, "builder_git_sha")
    spans = validate_source_spans(source_records)
    dictionary = validate_dictionary_index(dictionary_records)
    normalized_dictionary_manifest = validate_dictionary_index_manifest(
        dictionary_manifest, dictionary, require_verified=True
    )
    normalized_source_manifest = validate_source_span_manifest(
        source_span_manifest,
        source_records,
        jawiki_manifest=jawiki_manifest,
        dictionary_manifest=normalized_dictionary_manifest,
        require_verified=True,
    )
    if not spans or len(spans) > MAX_EXPORTER_REQUESTS:
        raise TierAError("exporter_requests: record count is outside the exporter bound")

    readings_by_surface = {
        record["surface"]: record["readings"] for record in dictionary
    }
    requests: list[dict[str, str]] = []
    for span in spans:
        readings = readings_by_surface.get(span["gold_surface"])
        if readings is None:
            raise TierAError("exporter_requests: source surface is absent from dictionary index")
        if len(readings) != 1:
            raise TierAError("exporter_requests: source surface does not have exactly one reading")
        requests.append({"stable_id": span["stable_id"], "reading": readings[0]})

    requests = validate_exporter_requests(requests)
    request_payload = canonical_jsonl_bytes(requests)
    report = {
        "schema_version": REQUEST_REPORT_SCHEMA_VERSION,
        "report_kind": REQUEST_REPORT_KIND,
        "verification_status": "verified_inputs",
        "builder_git_sha": builder_git_sha,
        "record_count": len(requests),
        "content_sha256": hashlib.sha256(request_payload).hexdigest(),
        "source_span_content_sha256": normalized_source_manifest["content_sha256"],
        "source_span_extractor_git_sha": normalized_source_manifest["extractor_git_sha"],
        "dictionary_index_content_sha256": normalized_dictionary_manifest["content_sha256"],
        "dictionary_indexer_git_sha": normalized_dictionary_manifest["indexer_git_sha"],
        "dictionary_sha256": normalized_dictionary_manifest["dictionary_sha256"],
        "sakura_input_head": normalized_dictionary_manifest["sakura_input_head"],
        "jawiki_local_sha256": normalized_source_manifest["jawiki_local_sha256"],
        "raw_text_in_report": False,
    }
    return requests, report


def publish_exporter_requests(
    output_path: str | Path,
    report_path: str | Path,
    requests: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> tuple[str, str]:
    """Publish the canonical request/report pair transactionally."""

    normalized_requests = validate_exporter_requests(requests)
    normalized_report = validate_request_report(report, normalized_requests)
    output_payload = canonical_jsonl_bytes(normalized_requests)
    output_sha = hashlib.sha256(output_payload).hexdigest()
    report_payload = canonical_json_bytes(normalized_report) + b"\n"
    write_bytes_pair_atomic(output_path, output_payload, report_path, report_payload)
    return output_sha, hashlib.sha256(report_payload).hexdigest()
