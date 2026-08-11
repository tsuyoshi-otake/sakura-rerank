"""Reproducible exact surface-to-readings index from audited category TSVs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_pair_atomic
from .contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    canonical_json_bytes,
    canonical_jsonl_bytes,
)
from .tier_a import (
    DICTIONARY_INDEX_MANIFEST_KIND,
    DICTIONARY_INDEX_RECORD_TYPE,
    MAX_DICTIONARY_RECORDS,
    TierAError,
    ensure_distinct_tier_a_paths,
    validate_dictionary_index,
)


INDEX_MANIFEST_SCHEMA_VERSION = 2
PINNED_AUDIT_SHA256 = "da41e32e31956a67dd65d88a4e87ad233dd39039b2230ee2974f1ab2471deb85"
MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_CATEGORY_BYTES = 64 * 1024 * 1024


class DictionaryIndexError(TierAError):
    """Audited dictionary inputs cannot produce a trustworthy exact index."""


def _load_audit(path: Path, *, expected_sha256: str) -> tuple[dict[str, Any], str]:
    try:
        size = path.stat().st_size
        payload = path.read_bytes()
    except OSError as error:
        raise DictionaryIndexError(
            f"audit report: cannot read ({type(error).__name__})"
        ) from error
    if not 0 < size <= MAX_AUDIT_BYTES or len(payload) != size:
        raise DictionaryIndexError("audit report: outside bounded size or changed")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise DictionaryIndexError("audit report: does not match the pinned SHA-256")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DictionaryIndexError("audit report: invalid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise DictionaryIndexError("audit report: must be an object")
    return value, digest


def _audit_category_records(audit: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    try:
        if audit["schema_version"] != "sakura-rerank.current-state-audit.v1":
            raise DictionaryIndexError("audit report: unsupported schema")
        if audit["sakura_input"]["head"] != PINNED_SAKURA_INPUT_HEAD:
            raise DictionaryIndexError("audit report: wrong pinned Sakura Input HEAD")
        if audit["dictionary"]["compiled"]["sha256"] != PINNED_DICTIONARY_SHA256:
            raise DictionaryIndexError("audit report: wrong pinned compiled dictionary")
        checks = audit["checks"]
        if not audit["all_artifact_checks_passed"] or not all(
            checks[name]
            for name in (
                "category_entry_count_matches_compiled_header",
                "category_files_match_checked_report",
                "dictionary_matches_checked_report",
            )
        ):
            raise DictionaryIndexError("audit report: dictionary checks did not pass")
        category = audit["dictionary"]["categories"]
        files = category["files"]
        expected_total = category["entry_count"]
    except (KeyError, TypeError) as error:
        raise DictionaryIndexError("audit report: missing dictionary evidence") from error
    if not isinstance(files, list) or not files or len(files) > 128:
        raise DictionaryIndexError("audit report: category files must be bounded")
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(files):
        if not isinstance(record, Mapping) or set(record) != {
            "path",
            "bytes",
            "sha256",
            "entry_count",
        }:
            raise DictionaryIndexError(
                f"audit report category {index}: fields do not match schema"
            )
        name = record["path"]
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or not name.endswith(".tsv")
        ):
            raise DictionaryIndexError(f"audit report category {index}: unsafe path")
        byte_size = record["bytes"]
        entry_count = record["entry_count"]
        sha256 = record["sha256"]
        if (
            isinstance(byte_size, bool)
            or not isinstance(byte_size, int)
            or not 0 < byte_size <= MAX_CATEGORY_BYTES
            or isinstance(entry_count, bool)
            or not isinstance(entry_count, int)
            or not 0 <= entry_count <= MAX_DICTIONARY_RECORDS
            or not isinstance(sha256, str)
            or len(sha256) != 64
        ):
            raise DictionaryIndexError(f"audit report category {index}: invalid metadata")
        normalized.append(
            {
                "path": name,
                "bytes": byte_size,
                "sha256": sha256,
                "entry_count": entry_count,
            }
        )
    if normalized != sorted(normalized, key=lambda record: record["path"]):
        raise DictionaryIndexError("audit report: category paths must be sorted")
    if len({record["path"] for record in normalized}) != len(normalized):
        raise DictionaryIndexError("audit report: duplicate category path")
    if isinstance(expected_total, bool) or expected_total != sum(
        record["entry_count"] for record in normalized
    ):
        raise DictionaryIndexError("audit report: category entry total mismatch")
    return normalized, expected_total


def _read_category(
    path: Path, expected: Mapping[str, Any], readings_by_surface: dict[str, set[str]]
) -> int:
    try:
        stat = path.stat()
        payload = path.read_bytes()
    except OSError as error:
        raise DictionaryIndexError(
            f"category {expected['path']}: cannot stat ({type(error).__name__})"
        ) from error
    if (
        not path.is_file()
        or stat.st_size != expected["bytes"]
        or len(payload) != stat.st_size
    ):
        raise DictionaryIndexError(f"category {expected['path']}: byte size mismatch")
    if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise DictionaryIndexError(f"category {expected['path']}: SHA-256 mismatch")
    count = 0
    try:
        text = payload.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(text, newline=""), delimiter="\t")
        header = next(rows, None)
        if header is None or header[:2] != ["reading", "surface"]:
            raise DictionaryIndexError(
                f"category {expected['path']}: invalid header"
            )
        for line_number, row in enumerate(rows, start=2):
            if not row:
                continue
            if len(row) < 2 or not row[0] or not row[1]:
                raise DictionaryIndexError(
                    f"category {expected['path']} line {line_number}: invalid row"
                )
            if any(character in row[0] + row[1] for character in "\x00\r\n"):
                raise DictionaryIndexError(
                    f"category {expected['path']} line {line_number}: control character"
                )
            readings_by_surface[row[1]].add(row[0])
            count += 1
    except (UnicodeDecodeError, csv.Error) as error:
        raise DictionaryIndexError(
            f"category {expected['path']}: cannot parse ({type(error).__name__})"
        ) from error
    if count != expected["entry_count"]:
        raise DictionaryIndexError(f"category {expected['path']}: entry count mismatch")
    return count


def build_dictionary_index(
    category_directory: str | Path,
    audit_report: str | Path,
    *,
    indexer_git_sha: str,
    expected_audit_sha256: str = PINNED_AUDIT_SHA256,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(indexer_git_sha) != 40 or any(
        character not in "0123456789abcdef" for character in indexer_git_sha
    ):
        raise DictionaryIndexError("indexer_git_sha: must be lowercase Git SHA-1")
    audit, audit_sha256 = _load_audit(
        Path(audit_report), expected_sha256=expected_audit_sha256
    )
    category_records, expected_total = _audit_category_records(audit)
    directory = Path(category_directory)
    readings_by_surface: dict[str, set[str]] = defaultdict(set)
    actual_total = sum(
        _read_category(directory / record["path"], record, readings_by_surface)
        for record in category_records
    )
    if actual_total != expected_total:
        raise DictionaryIndexError("category sources: total entry count mismatch")
    records = validate_dictionary_index(
        [
            {
                "schema_version": 1,
                "record_type": DICTIONARY_INDEX_RECORD_TYPE,
                "surface": surface,
                "readings": sorted(readings),
            }
            for surface, readings in sorted(readings_by_surface.items())
        ]
    )
    output_payload = canonical_jsonl_bytes(records)
    source_payload = canonical_json_bytes(category_records)
    manifest = {
        "schema_version": INDEX_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": DICTIONARY_INDEX_MANIFEST_KIND,
        "verification_status": "measured",
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "indexer_git_sha": indexer_git_sha,
        "normalization": "exact_unicode_v1",
        "user_dictionary_enabled": False,
        "source_audit_sha256": audit_sha256,
        "category_sources_sha256": hashlib.sha256(source_payload).hexdigest(),
        "category_file_count": len(category_records),
        "source_entry_count": actual_total,
        "record_count": len(records),
        "content_sha256": hashlib.sha256(output_payload).hexdigest(),
    }
    canonical_json_bytes(manifest)
    return records, manifest


def publish_dictionary_index(
    output_path: str | Path,
    manifest_path: str | Path,
    records: list[dict[str, Any]],
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    ensure_distinct_tier_a_paths(
        {"output": output_path, "manifest": manifest_path}
    )
    output_payload = canonical_jsonl_bytes(validate_dictionary_index(records))
    if manifest.get("content_sha256") != hashlib.sha256(output_payload).hexdigest():
        raise DictionaryIndexError("manifest.content_sha256: does not match output")
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    write_bytes_pair_atomic(
        output_path, output_payload, manifest_path, manifest_payload
    )
    return (
        hashlib.sha256(output_payload).hexdigest(),
        hashlib.sha256(manifest_payload).hexdigest(),
    )
