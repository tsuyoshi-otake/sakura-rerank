"""Read and cross-check bounded research-exporter shard results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import ContractError, canonical_jsonl_bytes
from .exporter_requests import (
    MAX_REQUEST_SHARDS,
    validate_exporter_request_shards,
    validate_exporter_requests,
)
from .research_exporter import read_export_jsonl, read_exporter_manifest
from .tier_a import TierAError


_EXPORT_REPORT_FIELDS = {
    "status",
    "verification_status",
    "exporter_git_sha",
    "exporter_binary_sha256",
    "dictionary_sha256",
    "requested_limit",
    "effective_converter_bound",
    "record_count",
    "total_candidate_count",
    "search_exhausted_record_count",
    "truncated_record_count",
    "input_sha256",
    "output_sha256",
}


def _load_json_object(path: Path, *, label: str, maximum_bytes: int = 1024 * 1024) -> Mapping[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise TierAError(f"{label}: cannot read ({type(error).__name__})") from error
    if not payload or len(payload) > maximum_bytes:
        raise TierAError(f"{label}: empty or outside byte bound")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TierAError(f"{label}: invalid JSON") from error
    if not isinstance(value, Mapping):
        raise TierAError(f"{label}: must be an object")
    return value


def _load_request_jsonl(path: Path) -> list[dict[str, str]]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise TierAError(f"request shard: cannot read ({type(error).__name__})") from error
    if not payload or len(payload) > 4 * 1024 * 1024:
        raise TierAError("request shard: empty or outside byte bound")
    try:
        values = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TierAError("request shard: invalid UTF-8 JSONL") from error
    if any(not isinstance(value, Mapping) for value in values):
        raise TierAError("request shard: every line must be an object")
    return validate_exporter_requests(values)


def read_request_shard_directory(
    directory: str | Path,
) -> tuple[list[list[dict[str, str]]], dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        raise TierAError("request shard directory: must be a directory")
    manifest = _load_json_object(root / "manifest.json", label="request shard manifest")
    shard_count = manifest.get("shard_count")
    if type(shard_count) is not int or not 1 <= shard_count <= MAX_REQUEST_SHARDS:
        raise TierAError("request shard manifest: invalid shard count")
    expected_names = {"manifest.json"}
    shards: list[list[dict[str, str]]] = []
    for index in range(shard_count):
        name = f"requests-{index:05d}.jsonl"
        expected_names.add(name)
        shards.append(_load_request_jsonl(root / name))
    try:
        actual_names = {entry.name for entry in root.iterdir()}
    except OSError as error:
        raise TierAError("request shard directory: cannot enumerate") from error
    if actual_names != expected_names:
        raise TierAError("request shard directory: unexpected or missing entries")
    return validate_exporter_request_shards(shards, manifest)


def _validate_export_report(
    report: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    *,
    exporter_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if set(report) != _EXPORT_REPORT_FIELDS:
        raise TierAError("export shard report: fields do not match schema")
    expected_statuses = [
        record["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"]
        for record in records
    ]
    expected = {
        "status": "exported",
        "verification_status": "verified",
        "exporter_git_sha": exporter_manifest["exporter_git_sha"],
        "exporter_binary_sha256": exporter_manifest["exporter_binary_sha256"],
        "dictionary_sha256": exporter_manifest["dictionary_sha256"],
        "requested_limit": exporter_manifest["requested_limit"],
        "effective_converter_bound": exporter_manifest["effective_converter_bound"],
        "record_count": len(records),
        "total_candidate_count": sum(
            len(record["candidate_snapshots"]["training_top32"]["candidates"])
            for record in records
        ),
        "search_exhausted_record_count": expected_statuses.count("search_exhausted"),
        "truncated_record_count": expected_statuses.count("truncated"),
        "input_sha256": hashlib.sha256(canonical_jsonl_bytes(requests)).hexdigest(),
        "output_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
    }
    if dict(report) != expected:
        raise TierAError("export shard report: aggregate evidence mismatch")
    return expected


def read_exporter_output_shards(
    directory: str | Path,
    request_shards: Sequence[Sequence[Mapping[str, Any]]],
    *,
    exporter_manifest_path: str | Path,
) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        raise TierAError("export shard directory: must be a directory")
    exporter_manifest = read_exporter_manifest(exporter_manifest_path, require_verified=True)
    if not request_shards or len(request_shards) > MAX_REQUEST_SHARDS:
        raise TierAError("export shards: shard count outside bound")
    expected_names: set[str] = set()
    output_shards: list[list[dict[str, Any]]] = []
    shard_evidence: list[dict[str, Any]] = []
    for index, requests in enumerate(request_shards):
        output_name = f"output-{index:05d}.jsonl"
        report_name = f"report-{index:05d}.json"
        expected_names.update((output_name, report_name))
        try:
            records = read_export_jsonl(
                root / output_name,
                require_verified=True,
                manifest=exporter_manifest,
            )
        except ContractError as error:
            raise TierAError(f"export shard {index}: {error}") from error
        if [record["stable_id"] for record in records] != [request["stable_id"] for request in requests]:
            raise TierAError(f"export shard {index}: stable IDs do not match requests")
        report = _load_json_object(root / report_name, label=f"export shard {index} report")
        normalized_report = _validate_export_report(
            report, requests, records, exporter_manifest=exporter_manifest
        )
        output_shards.append(records)
        shard_evidence.append(
            {
                "index": index,
                "record_count": len(records),
                "input_sha256": normalized_report["input_sha256"],
                "output_sha256": normalized_report["output_sha256"],
            }
        )
    try:
        actual_names = {entry.name for entry in root.iterdir()}
    except OSError as error:
        raise TierAError("export shard directory: cannot enumerate") from error
    if actual_names != expected_names:
        raise TierAError("export shard directory: unexpected or missing entries")
    all_records = [record for shard in output_shards for record in shard]
    stable_ids = [record["stable_id"] for record in all_records]
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise TierAError("export shards: global stable IDs must be sorted and unique")
    aggregate = {
        "record_count": len(all_records),
        "content_sha256": hashlib.sha256(canonical_jsonl_bytes(all_records)).hexdigest(),
        "shard_count": len(output_shards),
        "shards": shard_evidence,
    }
    return output_shards, aggregate
