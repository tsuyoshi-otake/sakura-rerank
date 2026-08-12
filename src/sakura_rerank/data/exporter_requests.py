"""Build provenance-bound input batches for the verified research exporter."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_pair_atomic
from .contracts import (
    MAX_READING_CHARS,
    MIN_READING_CHARS,
    canonical_json_bytes,
    canonical_jsonl_bytes,
)
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
MAX_REQUEST_SHARDS = 256
REQUEST_SHARD_MANIFEST_SCHEMA_VERSION = 1
REQUEST_SHARD_MANIFEST_KIND = "research_top32_request_shards"
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
_SHARD_MANIFEST_FIELDS = {
    "schema_version",
    "manifest_kind",
    "verification_status",
    "builder_git_sha",
    "record_count",
    "shard_size",
    "shard_count",
    "content_sha256",
    "source_span_content_sha256",
    "source_span_extractor_git_sha",
    "dictionary_index_content_sha256",
    "dictionary_indexer_git_sha",
    "dictionary_sha256",
    "sakura_input_head",
    "jawiki_local_sha256",
    "shards",
    "raw_text_in_manifest",
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
            or not MIN_READING_CHARS <= len(reading) <= MAX_READING_CHARS
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


def verify_builder_checkout(builder_git_sha: str, repository_root: str | Path) -> None:
    """Require the builder identity to be the exact clean checkout HEAD."""

    expected = _git_sha(builder_git_sha, "builder_git_sha")
    root = Path(repository_root).resolve(strict=True)
    try:
        head = subprocess.run(
            ["git", "-C", os.fspath(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", os.fspath(root), "status", "--porcelain=v1", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise TierAError("builder checkout: Git identity cannot be established") from error
    if head != expected:
        raise TierAError("builder_git_sha: does not match the checkout HEAD")
    if status:
        raise TierAError("builder checkout: tracked worktree must be clean")


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

    requests, provenance = _join_verified_requests(
        source_records,
        dictionary_records,
        jawiki_manifest=jawiki_manifest,
        dictionary_manifest=dictionary_manifest,
        source_span_manifest=source_span_manifest,
        builder_git_sha=builder_git_sha,
    )
    if len(requests) > MAX_EXPORTER_REQUESTS:
        raise TierAError("exporter_requests: record count is outside the exporter bound")
    requests = validate_exporter_requests(requests)
    request_payload = canonical_jsonl_bytes(requests)
    report = {
        "schema_version": REQUEST_REPORT_SCHEMA_VERSION,
        "report_kind": REQUEST_REPORT_KIND,
        "verification_status": "verified_inputs",
        **provenance,
        "record_count": len(requests),
        "content_sha256": hashlib.sha256(request_payload).hexdigest(),
        "raw_text_in_report": False,
    }
    return requests, report


def _join_verified_requests(
    source_records: Sequence[Mapping[str, Any]],
    dictionary_records: Sequence[Mapping[str, Any]],
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_manifest: Mapping[str, Any],
    source_span_manifest: Mapping[str, Any],
    builder_git_sha: str,
) -> tuple[list[dict[str, str]], dict[str, str]]:
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
    if not spans:
        raise TierAError("exporter_requests: no source records")

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
        if not MIN_READING_CHARS <= len(readings[0]) <= MAX_READING_CHARS:
            raise TierAError("exporter_requests: source reading is outside target bounds")
        requests.append({"stable_id": span["stable_id"], "reading": readings[0]})

    provenance = {
        "builder_git_sha": builder_git_sha,
        "source_span_content_sha256": normalized_source_manifest["content_sha256"],
        "source_span_extractor_git_sha": normalized_source_manifest["extractor_git_sha"],
        "dictionary_index_content_sha256": normalized_dictionary_manifest["content_sha256"],
        "dictionary_indexer_git_sha": normalized_dictionary_manifest["indexer_git_sha"],
        "dictionary_sha256": normalized_dictionary_manifest["dictionary_sha256"],
        "sakura_input_head": normalized_dictionary_manifest["sakura_input_head"],
        "jawiki_local_sha256": normalized_source_manifest["jawiki_local_sha256"],
    }
    return requests, provenance


def generate_exporter_request_shards(
    source_records: Sequence[Mapping[str, Any]],
    dictionary_records: Sequence[Mapping[str, Any]],
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_manifest: Mapping[str, Any],
    source_span_manifest: Mapping[str, Any],
    builder_git_sha: str,
    shard_size: int = MAX_EXPORTER_REQUESTS,
) -> tuple[list[list[dict[str, str]]], dict[str, Any]]:
    """Create globally ordered exporter-sized shards and an aggregate manifest."""

    if type(shard_size) is not int or not 1 <= shard_size <= MAX_EXPORTER_REQUESTS:
        raise TierAError("shard_size: must be within the exporter record bound")
    requests, provenance = _join_verified_requests(
        source_records,
        dictionary_records,
        jawiki_manifest=jawiki_manifest,
        dictionary_manifest=dictionary_manifest,
        source_span_manifest=source_span_manifest,
        builder_git_sha=builder_git_sha,
    )
    shard_count = (len(requests) + shard_size - 1) // shard_size
    if shard_count > MAX_REQUEST_SHARDS:
        raise TierAError("exporter_request_shards: shard count exceeds the bound")
    shards = [
        validate_exporter_requests(requests[start : start + shard_size])
        for start in range(0, len(requests), shard_size)
    ]
    shard_records = []
    for index, shard in enumerate(shards):
        payload = canonical_jsonl_bytes(shard)
        shard_records.append(
            {
                "file_name": f"requests-{index:05d}.jsonl",
                "record_count": len(shard),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    full_payload = canonical_jsonl_bytes(requests)
    manifest = {
        "schema_version": REQUEST_SHARD_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": REQUEST_SHARD_MANIFEST_KIND,
        "verification_status": "verified_inputs",
        **provenance,
        "record_count": len(requests),
        "shard_size": shard_size,
        "shard_count": len(shards),
        "content_sha256": hashlib.sha256(full_payload).hexdigest(),
        "shards": shard_records,
        "raw_text_in_manifest": False,
    }
    return shards, manifest


def validate_exporter_request_shards(
    shards: Sequence[Sequence[Mapping[str, Any]]],
    manifest: Mapping[str, Any],
) -> tuple[list[list[dict[str, str]]], dict[str, Any]]:
    """Validate a complete globally ordered request-shard bundle."""

    if not shards or len(shards) > MAX_REQUEST_SHARDS:
        raise TierAError("exporter_request_shards: shard count is outside the bound")
    if set(manifest) != _SHARD_MANIFEST_FIELDS:
        raise TierAError("manifest: fields do not match the aggregate-only schema")
    if manifest["schema_version"] != REQUEST_SHARD_MANIFEST_SCHEMA_VERSION:
        raise TierAError("manifest.schema_version: unsupported schema")
    if manifest["manifest_kind"] != REQUEST_SHARD_MANIFEST_KIND:
        raise TierAError("manifest.manifest_kind: unsupported kind")
    if manifest["verification_status"] != "verified_inputs":
        raise TierAError("manifest.verification_status: verified_inputs is required")
    for field in (
        "builder_git_sha",
        "source_span_extractor_git_sha",
        "dictionary_indexer_git_sha",
        "sakura_input_head",
    ):
        _git_sha(manifest[field], f"manifest.{field}")
    for field in (
        "content_sha256",
        "source_span_content_sha256",
        "dictionary_index_content_sha256",
        "dictionary_sha256",
        "jawiki_local_sha256",
    ):
        _sha256(manifest[field], f"manifest.{field}")
    if type(manifest["shard_size"]) is not int or not 1 <= manifest["shard_size"] <= MAX_EXPORTER_REQUESTS:
        raise TierAError("manifest.shard_size: outside the exporter bound")
    if type(manifest["shard_count"]) is not int or manifest["shard_count"] != len(shards):
        raise TierAError("manifest.shard_count: does not match request shards")
    expected_shards = manifest["shards"]
    if not isinstance(expected_shards, list) or len(expected_shards) != len(shards):
        raise TierAError("manifest.shards: does not match request shards")

    normalized_shards: list[list[dict[str, str]]] = []
    all_requests: list[dict[str, str]] = []
    for index, (shard, expected) in enumerate(zip(shards, expected_shards, strict=True)):
        normalized = validate_exporter_requests(shard)
        payload = canonical_jsonl_bytes(normalized)
        expected_record = {
            "file_name": f"requests-{index:05d}.jsonl",
            "record_count": len(normalized),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
        }
        if expected != expected_record:
            raise TierAError("manifest.shards: content identity mismatch")
        normalized_shards.append(normalized)
        all_requests.extend(normalized)
    stable_ids = [record["stable_id"] for record in all_requests]
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise TierAError("exporter_request_shards: global stable IDs must be sorted and unique")
    if manifest.get("record_count") != len(all_requests):
        raise TierAError("manifest.record_count: does not match request shards")
    combined_sha = hashlib.sha256(canonical_jsonl_bytes(all_requests)).hexdigest()
    if manifest.get("content_sha256") != combined_sha:
        raise TierAError("manifest.content_sha256: does not match request shards")
    if manifest.get("raw_text_in_manifest") is not False:
        raise TierAError("manifest.raw_text_in_manifest: must be false")
    return normalized_shards, dict(manifest)


def publish_exporter_request_shards(
    output_directory: str | Path,
    shards: Sequence[Sequence[Mapping[str, Any]]],
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    """Atomically publish a new immutable directory of request shards."""

    destination = Path(output_directory)
    if destination.exists():
        raise TierAError("output_directory: already exists")
    if not destination.parent.is_dir():
        raise TierAError("output_directory: parent directory does not exist")
    normalized_shards, normalized_manifest = validate_exporter_request_shards(
        shards, manifest
    )
    combined_sha = normalized_manifest["content_sha256"]

    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        for index, shard in enumerate(normalized_shards):
            path = staged / f"requests-{index:05d}.jsonl"
            with path.open("wb") as output:
                output.write(canonical_jsonl_bytes(shard))
                output.flush()
                os.fsync(output.fileno())
        manifest_payload = canonical_json_bytes(normalized_manifest) + b"\n"
        with (staged / "manifest.json").open("wb") as output:
            output.write(manifest_payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
    return combined_sha, manifest_sha


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
