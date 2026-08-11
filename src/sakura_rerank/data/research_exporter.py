"""Validation boundary for research-only Sakura converter exports.

This module deliberately validates exporter snapshots separately from the
training-example contract.  A converter snapshot contains no corpus, gold
label, session context, split, or training eligibility claim; it is an
immutable upstream artifact that a later dataset stage may consume.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import (
    CONTRACT_SCHEMA_VERSION,
    CONVERTER_FEATURE_CONTRACT_VERSION,
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    PRODUCTION_TOP_K,
    RESEARCH_EXPORTER_CONTRACT_VERSION,
    TRAINING_TOP_K,
    VERIFIED_RESEARCH_EXPORTER_IDENTITIES,
    ContractError,
    _has_verified_research_exporter,
    _require_bool,
    _require_identifier,
    _require_git_sha,
    _require_integer,
    _require_sha256,
    _require_string,
    _validate_converter_provenance,
    _validate_snapshot,
    canonical_jsonl_bytes,
)


EXPORTER_MANIFEST_SCHEMA_VERSION = 1
EXPORTER_MANIFEST_KIND = "research_top32_exporter"
EXPORT_RECORD_TYPE = "research_converter_snapshot"
MAX_EXPORT_RECORDS = 4_096
MAX_EXPORT_FILE_BYTES = 256 * 1024 * 1024

_MANIFEST_FIELDS = {
    "schema_version",
    "manifest_kind",
    "verification_status",
    "exporter_git_sha",
    "exporter_binary_sha256",
    "sakura_input_head",
    "dictionary_sha256",
    "instrumentation_patch_sha256",
    "cargo_lock_sha256",
    "rustc_version",
    "cargo_version",
    "target_triple",
    "profile",
    "requested_limit",
    "effective_converter_bound",
    "user_dictionary_enabled",
}


def _reject_unknown_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ContractError(f"{field}: fields do not match the exporter schema")


def _load_object(path: str | Path, field: str) -> Mapping[str, Any]:
    try:
        payload = Path(path).read_bytes()
    except OSError as error:
        raise ContractError(f"{field}: cannot read ({type(error).__name__})") from error
    if len(payload) > MAX_EXPORT_FILE_BYTES:
        raise ContractError(f"{field}: exceeds the bounded artifact size")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"{field}: invalid JSON") from error
    if not isinstance(value, Mapping):
        raise ContractError(f"{field}: must be a JSON object")
    return value


def validate_exporter_manifest(
    manifest: Mapping[str, Any], *, require_verified: bool = True
) -> dict[str, Any]:
    """Validate the measured exporter identity manifest.

    The manifest itself is small and may be committed.  It never contains a
    binary or generated JSONL payload; those are checked by their hashes and
    remain outside the repository.
    """

    if not isinstance(manifest, Mapping):
        raise ContractError("exporter_manifest: must be a JSON object")
    _reject_unknown_keys(manifest, _MANIFEST_FIELDS, "exporter_manifest")
    if (
        _require_integer(manifest["schema_version"], "exporter_manifest.schema_version")
        != EXPORTER_MANIFEST_SCHEMA_VERSION
    ):
        raise ContractError("exporter_manifest.schema_version: unsupported schema")
    if manifest["manifest_kind"] != EXPORTER_MANIFEST_KIND:
        raise ContractError("exporter_manifest.manifest_kind: unsupported manifest kind")

    status = _require_string(
        manifest["verification_status"], "exporter_manifest.verification_status"
    )
    if status not in {"unverified", "verified"}:
        raise ContractError("exporter_manifest.verification_status: unsupported status")
    exporter_git_sha = _require_git_sha(
        manifest["exporter_git_sha"], "exporter_manifest.exporter_git_sha"
    )
    exporter_binary_sha256 = _require_sha256(
        manifest["exporter_binary_sha256"], "exporter_manifest.exporter_binary_sha256"
    )
    sakura_input_head = _require_git_sha(
        manifest["sakura_input_head"], "exporter_manifest.sakura_input_head"
    )
    if sakura_input_head != PINNED_SAKURA_INPUT_HEAD:
        raise ContractError("exporter_manifest.sakura_input_head: wrong pinned HEAD")
    dictionary_sha256 = _require_sha256(
        manifest["dictionary_sha256"], "exporter_manifest.dictionary_sha256"
    )
    if dictionary_sha256 != PINNED_DICTIONARY_SHA256:
        raise ContractError("exporter_manifest.dictionary_sha256: wrong pinned dictionary")
    instrumentation_patch_sha256 = _require_sha256(
        manifest["instrumentation_patch_sha256"],
        "exporter_manifest.instrumentation_patch_sha256",
    )
    cargo_lock_sha256 = _require_sha256(
        manifest["cargo_lock_sha256"], "exporter_manifest.cargo_lock_sha256"
    )
    rustc_version = _require_string(
        manifest["rustc_version"], "exporter_manifest.rustc_version", max_chars=256
    )
    cargo_version = _require_string(
        manifest["cargo_version"], "exporter_manifest.cargo_version", max_chars=256
    )
    target_triple = _require_string(
        manifest["target_triple"], "exporter_manifest.target_triple", max_chars=128
    )
    profile = _require_string(manifest["profile"], "exporter_manifest.profile")
    if profile != "release":
        raise ContractError("exporter_manifest.profile: release is required")
    requested_limit = _require_integer(
        manifest["requested_limit"], "exporter_manifest.requested_limit"
    )
    effective_bound = _require_integer(
        manifest["effective_converter_bound"],
        "exporter_manifest.effective_converter_bound",
    )
    if requested_limit != TRAINING_TOP_K or effective_bound != TRAINING_TOP_K:
        raise ContractError("exporter_manifest: requested and effective bounds must be 32")
    if _require_bool(
        manifest["user_dictionary_enabled"], "exporter_manifest.user_dictionary_enabled"
    ):
        raise ContractError("exporter_manifest.user_dictionary_enabled: must be false")

    identity = (exporter_git_sha, exporter_binary_sha256)
    if status == "verified" and identity not in VERIFIED_RESEARCH_EXPORTER_IDENTITIES:
        raise ContractError("exporter_manifest: verified identity is outside the allowlist")
    if require_verified and (status != "verified" or identity not in VERIFIED_RESEARCH_EXPORTER_IDENTITIES):
        raise ContractError("exporter_manifest: an allowlisted verified identity is required")

    return {
        "schema_version": EXPORTER_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": EXPORTER_MANIFEST_KIND,
        "verification_status": status,
        "exporter_git_sha": exporter_git_sha,
        "exporter_binary_sha256": exporter_binary_sha256,
        "sakura_input_head": sakura_input_head,
        "dictionary_sha256": dictionary_sha256,
        "instrumentation_patch_sha256": instrumentation_patch_sha256,
        "cargo_lock_sha256": cargo_lock_sha256,
        "rustc_version": rustc_version,
        "cargo_version": cargo_version,
        "target_triple": target_triple,
        "profile": profile,
        "requested_limit": TRAINING_TOP_K,
        "effective_converter_bound": TRAINING_TOP_K,
        "user_dictionary_enabled": False,
    }


def read_exporter_manifest(path: str | Path, *, require_verified: bool = True) -> dict[str, Any]:
    return validate_exporter_manifest(
        _load_object(path, "exporter_manifest"), require_verified=require_verified
    )


def _validate_export_record(
    record: Mapping[str, Any],
    *,
    require_verified: bool,
    manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ContractError("export record: must be a JSON object")
    expected = {
        "schema_version",
        "record_type",
        "stable_id",
        "reading",
        "converter_provenance",
        "candidate_snapshots",
    }
    _reject_unknown_keys(record, expected, "export record")
    if _require_integer(record["schema_version"], "export record.schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ContractError("export record.schema_version: unsupported schema")
    if record["record_type"] != EXPORT_RECORD_TYPE:
        raise ContractError("export record.record_type: unsupported record type")

    stable_id = _require_identifier(record["stable_id"], "export record.stable_id")
    reading = _require_string(
        record["reading"], "export record.reading", max_chars=128
    )
    converter_provenance = _validate_converter_provenance(
        record["converter_provenance"], is_fixture=False
    )
    snapshots = record["candidate_snapshots"]
    if not isinstance(snapshots, Mapping) or set(snapshots) != {
        "training_top32",
        "production_top6",
    }:
        raise ContractError(
            "export record.candidate_snapshots: top-32 and top-6 are required"
        )

    top32 = _validate_snapshot(
        snapshots["training_top32"],
        "export record.candidate_snapshots.training_top32",
        limit=TRAINING_TOP_K,
        reading=reading,
        is_fixture=False,
        converter_provenance=converter_provenance,
        require_exporter_run=True,
    )
    exporter_run = top32["exporter_run"]
    if exporter_run["effective_converter_bound"] != TRAINING_TOP_K:
        raise ContractError("export record.exporter_run: effective bound must be 32")
    if exporter_run["verification_status"] == "verified" and not _has_verified_research_exporter(
        exporter_run
    ):
        raise ContractError("export record.exporter_run: identity is outside the allowlist")
    if require_verified and not _has_verified_research_exporter(exporter_run):
        raise ContractError("export record.exporter_run: an allowlisted identity is required")
    if manifest is not None:
        if (
            exporter_run["exporter_git_sha"],
            exporter_run["exporter_binary_sha256"],
        ) != (manifest["exporter_git_sha"], manifest["exporter_binary_sha256"]):
            raise ContractError("export record.exporter_run: identity differs from the manifest")

    top6 = _validate_snapshot(
        snapshots["production_top6"],
        "export record.candidate_snapshots.production_top6",
        limit=PRODUCTION_TOP_K,
        reading=reading,
        is_fixture=False,
        converter_provenance=converter_provenance,
    )
    expected_top6 = top32["candidates"][:PRODUCTION_TOP_K]
    if top6["candidates"] != expected_top6:
        raise ContractError("export record.candidate_snapshots.production_top6: not a top-32 prefix")

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "record_type": EXPORT_RECORD_TYPE,
        "stable_id": stable_id,
        "reading": reading,
        "converter_provenance": converter_provenance,
        "candidate_snapshots": {
            "training_top32": top32,
            "production_top6": top6,
        },
    }


def validate_export_records(
    records: Sequence[Mapping[str, Any]],
    *,
    require_verified: bool = True,
    manifest: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate exporter records and return normalized copies."""

    if not records:
        raise ContractError("export records: must not be empty")
    if len(records) > MAX_EXPORT_RECORDS:
        raise ContractError("export records: exceeds the bounded record count")
    normalized_manifest = None
    if manifest is not None:
        normalized_manifest = validate_exporter_manifest(
            manifest, require_verified=require_verified
        )
    normalized = [
        _validate_export_record(
            record,
            require_verified=require_verified,
            manifest=normalized_manifest,
        )
        for record in records
    ]
    stable_ids = [record["stable_id"] for record in normalized]
    if len(stable_ids) != len(set(stable_ids)):
        raise ContractError("export records.stable_id: values must be unique")
    if stable_ids != sorted(stable_ids):
        raise ContractError("export records.stable_id: output must be sorted")
    return normalized


def read_export_jsonl(
    path: str | Path,
    *,
    require_verified: bool = True,
    manifest: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        payload = Path(path).read_bytes()
    except OSError as error:
        raise ContractError(f"export JSONL: cannot read ({type(error).__name__})") from error
    if len(payload) > MAX_EXPORT_FILE_BYTES:
        raise ContractError("export JSONL: exceeds the bounded artifact size")
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ContractError("export JSONL: must be UTF-8") from error
    if not lines:
        raise ContractError("export JSONL: must contain at least one record")
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ContractError(f"export JSONL line {line_number}: blank lines are forbidden")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"export JSONL line {line_number}: invalid JSON") from error
        if not isinstance(value, Mapping):
            raise ContractError(f"export JSONL line {line_number}: record must be an object")
        records.append(value)
    return validate_export_records(
        records,
        require_verified=require_verified,
        manifest=manifest,
    )


def validate_export_file(
    path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    require_verified: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    manifest = (
        read_exporter_manifest(manifest_path, require_verified=require_verified)
        if manifest_path is not None
        else None
    )
    records = read_export_jsonl(
        path,
        require_verified=require_verified,
        manifest=manifest,
    )
    return records, hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest()
