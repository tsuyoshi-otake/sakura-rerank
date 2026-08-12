"""Deterministic assembly of verified Tier A training-example records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_pair_atomic
from .contracts import (
    AUTOMATIC_TIER_A_SOURCE,
    CONTRACT_SCHEMA_VERSION,
    MAX_LEFT_CONTEXT_CHARS,
    MAX_READING_CHARS,
    MAX_SURFACE_CHARS,
    MIN_READING_CHARS,
    PINNED_DICTIONARY_SHA256,
    PINNED_JAWIKI_SNAPSHOT_DATE,
    PINNED_SAKURA_INPUT_HEAD,
    ContractError,
    _require_identifier,
    _validate_source,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    validate_records,
)
from .manifest import LOCAL_ARTIFACT_VERIFIED, PREPROCESSING_VERIFIED
from .research_exporter import MAX_EXPORT_RECORDS, validate_export_records


SOURCE_SPAN_SCHEMA_VERSION = 1
SOURCE_SPAN_RECORD_TYPE = "jawiki_tier_a_source_span"
SOURCE_SPAN_MANIFEST_SCHEMA_VERSION = 2
SUPPORTED_SOURCE_SPAN_MANIFEST_SCHEMA_VERSIONS = frozenset({1, 2})
SOURCE_SPAN_MANIFEST_KIND = "jawiki_tier_a_source_spans"
SOURCE_SPAN_CLEANER_VERSION = "conservative_wikitext_v3"
SUPPORTED_SOURCE_SPAN_CLEANER_VERSIONS = frozenset(
    {
        "conservative_wikitext_v1",
        "conservative_wikitext_v2",
        SOURCE_SPAN_CLEANER_VERSION,
    }
)
DICTIONARY_INDEX_SCHEMA_VERSION = 1
DICTIONARY_INDEX_MANIFEST_SCHEMA_VERSION = 2
DICTIONARY_INDEX_RECORD_TYPE = "system_dictionary_surface_index"
DICTIONARY_INDEX_MANIFEST_KIND = "system_dictionary_surface_index"
VERIFIED_DICTIONARY_INDEX_IDENTITIES = frozenset(
    {
        (
            "227ffe8a6b0b515c7f3cdf504b3d98b313360e53",
            "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072",
        )
    }
)
VERIFIED_DICTIONARY_INDEX_METADATA = {
    (
        "227ffe8a6b0b515c7f3cdf504b3d98b313360e53",
        "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072",
    ): {
        "source_audit_sha256": "da41e32e31956a67dd65d88a4e87ad233dd39039b2230ee2974f1ab2471deb85",
        "category_sources_sha256": "c6b84bf7cc83252966d9c2e71c82aa880f8f0a5b95b4ca7445cf68cfe5c064b5",
        "category_file_count": 14,
        "source_entry_count": 472_825,
        "record_count": 368_341,
    }
}
VERIFIED_SOURCE_SPAN_IDENTITIES = frozenset(
    {
        (
            "7cdb51f77875caab8be25683fc3bf174c0e91325",
            "f06b747dfa4ec1b650696cd04f156071acde8bf543b5ba9fe94f6146123275c9",
        ),
        (
            "7cdb51f77875caab8be25683fc3bf174c0e91325",
            "8b3067836e894b93142f502157d1a65bcb34da277b81111388d8b18220fad727",
        ),
        (
            "776e9f108bf891c6b44f0391a65370c279f95f64",
            "9338d38c0a8589b8ec78d7c14fc4d3cdd4598b8fc1f5641549f932599903fa66",
        ),
    }
)
VERIFIED_SOURCE_SPAN_METADATA: dict[tuple[str, str], Mapping[str, Any]] = {
    (
        "7cdb51f77875caab8be25683fc3bf174c0e91325",
        "f06b747dfa4ec1b650696cd04f156071acde8bf543b5ba9fe94f6146123275c9",
    ): {
        "schema_version": 1,
        "manifest_kind": "jawiki_tier_a_source_spans",
        "snapshot_date": "2026-08-01",
        "jawiki_local_sha256": "4822a58b180fc0057ce6f64325f11c34fe6396fb5ed2e4a04eaf7a9658acc12d",
        "dictionary_index_sha256": "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072",
        "cleaner_version": "conservative_wikitext_v1",
        "config": {
            "sample_modulus": 1_000_000,
            "sample_slots": 3,
            "max_records": 100_000,
            "max_records_per_page": 8,
            "max_output_bytes": 251_658_240,
            "min_sentence_chars": 4,
            "max_sentence_chars": 512,
            "min_surface_chars": 1,
            "max_surface_chars": 64,
        },
        "eligible_dictionary_surface_count": 335_218,
        "record_count": 1_969,
        "counts": {
            "dictionary_matches": 673_706_344,
            "matches_not_sampled": 673_704_375,
            "pages_non_main": 636_071,
            "pages_processed": 1_512_214,
            "pages_redirect": 952_212,
            "pages_total": 3_100_497,
            "paragraph_too_long": 290,
            "paragraphs_accepted": 14_737_408,
            "residual_markup": 103_086,
            "sentences_accepted": 32_981_912,
            "sentences_outside_bounds": 1_768_505,
            "unbalanced_link": 94_862,
            "unbalanced_template": 86_558,
        },
        "raw_text_in_report": False,
    },
    (
        "7cdb51f77875caab8be25683fc3bf174c0e91325",
        "8b3067836e894b93142f502157d1a65bcb34da277b81111388d8b18220fad727",
    ): {
        "schema_version": 1,
        "manifest_kind": "jawiki_tier_a_source_spans",
        "snapshot_date": "2026-08-01",
        "jawiki_local_sha256": "4822a58b180fc0057ce6f64325f11c34fe6396fb5ed2e4a04eaf7a9658acc12d",
        "dictionary_index_sha256": "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072",
        "cleaner_version": "conservative_wikitext_v1",
        "config": {
            "sample_modulus": 1_000_000,
            "sample_slots": 60,
            "max_records": 100_000,
            "max_records_per_page": 8,
            "max_output_bytes": 268_435_456,
            "min_sentence_chars": 4,
            "max_sentence_chars": 512,
            "min_surface_chars": 1,
            "max_surface_chars": 64,
        },
        "eligible_dictionary_surface_count": 335_218,
        "record_count": 40_703,
        "counts": {
            "dictionary_matches": 673_677_189,
            "matches_not_sampled": 673_636_486,
            "pages_hit_record_bound": 3,
            "pages_non_main": 636_071,
            "pages_processed": 1_512_214,
            "pages_redirect": 952_212,
            "pages_total": 3_100_497,
            "paragraph_too_long": 290,
            "paragraphs_accepted": 14_737_307,
            "residual_markup": 103_086,
            "sentences_accepted": 32_980_716,
            "sentences_outside_bounds": 1_768_487,
            "unbalanced_link": 94_862,
            "unbalanced_template": 86_558,
        },
        "raw_text_in_report": False,
    },
    (
        "776e9f108bf891c6b44f0391a65370c279f95f64",
        "9338d38c0a8589b8ec78d7c14fc4d3cdd4598b8fc1f5641549f932599903fa66",
    ): {
        "schema_version": 1,
        "manifest_kind": "jawiki_tier_a_source_spans",
        "snapshot_date": "2026-08-01",
        "jawiki_local_sha256": "4822a58b180fc0057ce6f64325f11c34fe6396fb5ed2e4a04eaf7a9658acc12d",
        "dictionary_index_sha256": "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072",
        "cleaner_version": "conservative_wikitext_v2",
        "config": {
            "sample_modulus": 1_000_000,
            "sample_slots": 60,
            "max_records": 100_000,
            "max_records_per_page": 8,
            "max_output_bytes": 268_435_456,
            "min_sentence_chars": 4,
            "max_sentence_chars": 512,
            "min_surface_chars": 1,
            "max_surface_chars": 64,
        },
        "eligible_dictionary_surface_count": 335_218,
        "record_count": 30_003,
        "counts": {
            "dictionary_matches": 500_010_510,
            "matches_not_sampled": 499_980_507,
            "matches_unsafe_boundary": 398_742_386,
            "pages_hit_record_bound": 1,
            "pages_non_main": 636_071,
            "pages_processed": 1_512_214,
            "pages_redirect": 952_212,
            "pages_total": 3_100_497,
            "paragraphs_accepted": 48_097_996,
            "residual_markup": 143_031,
            "sentences_accepted": 57_242_129,
            "sentences_outside_bounds": 5_856_114,
            "unbalanced_link": 94_862,
            "unbalanced_template": 86_558,
        },
        "raw_text_in_report": False,
    },
}
MAX_SOURCE_RECORDS = 1_000_000
MAX_DICTIONARY_RECORDS = 2_000_000
MAX_INPUT_FILE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_FILE_BYTES = 1024 * 1024
MAX_COMMITTED_PREFIX_CHARS = 4_096
MAX_READINGS_PER_SURFACE = 64

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class TierAError(ValueError):
    """A Tier A input or publication violates the deterministic boundary."""


class TierABlockedError(TierAError):
    """Required immutable evidence is not yet available."""

    def __init__(
        self, blocker: str, reason: str, *, details: Mapping[str, Any] | None = None
    ):
        self.report = {
            "schema_version": 1,
            "report_kind": "tier_a_generation_blocker",
            "status": "blocked",
            "blockers": [{"blocker": blocker, "reason": reason}],
        }
        if details is not None:
            self.report["details"] = dict(details)
        super().__init__(f"{blocker}: {reason}")


def _strict_object(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise TierAError(f"{name}: fields do not match schema")
    return value


def _string(value: Any, field: str, *, allow_empty: bool = False, maximum: int = 4096) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TierAError(f"{field}: must be a string")
    if len(value) > maximum or any(character in value for character in "\x00\r\n"):
        raise TierAError(f"{field}: is outside the bounded string contract")
    return value


def _sha256(value: Any, field: str) -> str:
    value = _string(value, field, maximum=64)
    if _SHA256_RE.fullmatch(value) is None:
        raise TierAError(f"{field}: must be lowercase SHA-256")
    return value


def _git_sha(value: Any, field: str) -> str:
    value = _string(value, field, maximum=40)
    if _GIT_SHA_RE.fullmatch(value) is None:
        raise TierAError(f"{field}: must be lowercase Git SHA-1")
    return value


def _integer(value: Any, field: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise TierAError(f"{field}: is outside the bounded integer contract")
    return value


def _read_jsonl(path: str | Path, *, label: str, maximum_records: int) -> list[Mapping[str, Any]]:
    source = Path(path)
    try:
        size = source.stat().st_size
        payload = source.read_bytes()
    except OSError as error:
        raise TierAError(f"{label}: cannot read ({type(error).__name__})") from error
    if size > MAX_INPUT_FILE_BYTES or len(payload) != size:
        raise TierAError(f"{label}: exceeds or changed during the bounded read")
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise TierAError(f"{label}: must be UTF-8") from error
    if not lines or len(lines) > maximum_records:
        raise TierAError(f"{label}: record count is outside the bound")
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise TierAError(f"{label} line {line_number}: blank lines are forbidden")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TierAError(f"{label} line {line_number}: invalid JSON") from error
        if not isinstance(value, Mapping):
            raise TierAError(f"{label} line {line_number}: must be an object")
        records.append(value)
    return records


def validate_source_spans(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate preprocessing output without accepting a supplied reading."""

    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        field = f"source_spans[{index}]"
        record = _strict_object(
            record,
            {
                "schema_version",
                "record_type",
                "stable_id",
                "source",
                "committed_prefix",
                "gold_surface",
            },
            field,
        )
        if record["schema_version"] != SOURCE_SPAN_SCHEMA_VERSION:
            raise TierAError(f"{field}.schema_version: unsupported schema")
        if record["record_type"] != SOURCE_SPAN_RECORD_TYPE:
            raise TierAError(f"{field}.record_type: unsupported record type")
        try:
            stable_id = _require_identifier(record["stable_id"], f"{field}.stable_id")
            source = _validate_source(record["source"], is_fixture=False)
        except ContractError as error:
            raise TierAError(str(error)) from error
        committed_prefix = _string(
            record["committed_prefix"],
            f"{field}.committed_prefix",
            maximum=MAX_COMMITTED_PREFIX_CHARS,
        )
        gold_surface = _string(
            record["gold_surface"], f"{field}.gold_surface", maximum=MAX_SURFACE_CHARS
        )
        if not committed_prefix.endswith(gold_surface):
            raise TierAError(f"{field}.committed_prefix: must end with gold_surface")
        preceding = committed_prefix[: -len(gold_surface)]
        normalized.append(
            {
                "schema_version": SOURCE_SPAN_SCHEMA_VERSION,
                "record_type": SOURCE_SPAN_RECORD_TYPE,
                "stable_id": stable_id,
                "source": source,
                "left_context": preceding[-MAX_LEFT_CONTEXT_CHARS:],
                "gold_surface": gold_surface,
            }
        )
    stable_ids = [record["stable_id"] for record in normalized]
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise TierAError("source_spans.stable_id: must be sorted and unique")
    return normalized


def validate_dictionary_index(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        field = f"dictionary_index[{index}]"
        record = _strict_object(
            record, {"schema_version", "record_type", "surface", "readings"}, field
        )
        if record["schema_version"] != DICTIONARY_INDEX_SCHEMA_VERSION:
            raise TierAError(f"{field}.schema_version: unsupported schema")
        if record["record_type"] != DICTIONARY_INDEX_RECORD_TYPE:
            raise TierAError(f"{field}.record_type: unsupported record type")
        surface = _string(record["surface"], f"{field}.surface", maximum=MAX_SURFACE_CHARS)
        readings = record["readings"]
        if not isinstance(readings, list) or not readings or len(readings) > MAX_READINGS_PER_SURFACE:
            raise TierAError(f"{field}.readings: must be a bounded non-empty list")
        normalized_readings = [
            _string(
                reading,
                f"{field}.readings[{reading_index}]",
                maximum=MAX_READING_CHARS,
            )
            for reading_index, reading in enumerate(readings)
        ]
        if normalized_readings != sorted(set(normalized_readings)):
            raise TierAError(f"{field}.readings: must be sorted and unique")
        normalized.append(
            {
                "schema_version": DICTIONARY_INDEX_SCHEMA_VERSION,
                "record_type": DICTIONARY_INDEX_RECORD_TYPE,
                "surface": surface,
                "readings": normalized_readings,
            }
        )
    surfaces = [record["surface"] for record in normalized]
    if surfaces != sorted(surfaces) or len(surfaces) != len(set(surfaces)):
        raise TierAError("dictionary_index.surface: must be sorted and unique")
    return normalized


def validate_dictionary_index_manifest(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    require_verified: bool = True,
) -> dict[str, Any]:
    fields = {
        "schema_version",
        "manifest_kind",
        "verification_status",
        "dictionary_sha256",
        "sakura_input_head",
        "indexer_git_sha",
        "normalization",
        "user_dictionary_enabled",
        "record_count",
        "content_sha256",
        "source_audit_sha256",
        "category_sources_sha256",
        "category_file_count",
        "source_entry_count",
    }
    manifest = _strict_object(manifest, fields, "dictionary_index_manifest")
    if manifest["schema_version"] != DICTIONARY_INDEX_MANIFEST_SCHEMA_VERSION:
        raise TierAError("dictionary_index_manifest.schema_version: unsupported schema")
    if manifest["manifest_kind"] != DICTIONARY_INDEX_MANIFEST_KIND:
        raise TierAError("dictionary_index_manifest.manifest_kind: unsupported kind")
    verification_status = manifest["verification_status"]
    if verification_status not in {"measured", "verified"}:
        raise TierAError("dictionary_index_manifest.verification_status: unsupported status")
    dictionary_sha = _sha256(
        manifest["dictionary_sha256"],
        "dictionary_index_manifest.dictionary_sha256",
    )
    if dictionary_sha != PINNED_DICTIONARY_SHA256:
        raise TierAError("dictionary_index_manifest.dictionary_sha256: wrong pinned dictionary")
    if manifest["sakura_input_head"] != PINNED_SAKURA_INPUT_HEAD:
        raise TierAError("dictionary_index_manifest.sakura_input_head: wrong pinned HEAD")
    indexer_git_sha = _git_sha(
        manifest["indexer_git_sha"], "dictionary_index_manifest.indexer_git_sha"
    )
    if manifest["normalization"] != "exact_unicode_v1":
        raise TierAError("dictionary_index_manifest.normalization: exact_unicode_v1 is required")
    if manifest["user_dictionary_enabled"] is not False:
        raise TierAError("dictionary_index_manifest.user_dictionary_enabled: must be false")
    count = _integer(
        manifest["record_count"],
        "dictionary_index_manifest.record_count",
        maximum=MAX_DICTIONARY_RECORDS,
    )
    if count < 1:
        raise TierAError("dictionary_index_manifest.record_count: must be positive")
    if count != len(records):
        raise TierAError("dictionary_index_manifest.record_count: does not match index")
    content_sha = _sha256(manifest["content_sha256"], "dictionary_index_manifest.content_sha256")
    expected_sha = hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest()
    if content_sha != expected_sha:
        raise TierAError("dictionary_index_manifest.content_sha256: does not match index")
    source_audit_sha256 = _sha256(
        manifest["source_audit_sha256"],
        "dictionary_index_manifest.source_audit_sha256",
    )
    category_sources_sha256 = _sha256(
        manifest["category_sources_sha256"],
        "dictionary_index_manifest.category_sources_sha256",
    )
    category_file_count = _integer(
        manifest["category_file_count"],
        "dictionary_index_manifest.category_file_count",
        maximum=128,
    )
    source_entry_count = _integer(
        manifest["source_entry_count"],
        "dictionary_index_manifest.source_entry_count",
        maximum=MAX_DICTIONARY_RECORDS,
    )
    if category_file_count < 1 or source_entry_count < count:
        raise TierAError("dictionary_index_manifest: invalid source coverage counts")
    normalized = {
        "schema_version": DICTIONARY_INDEX_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": DICTIONARY_INDEX_MANIFEST_KIND,
        "verification_status": verification_status,
        "dictionary_sha256": dictionary_sha,
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "indexer_git_sha": indexer_git_sha,
        "normalization": "exact_unicode_v1",
        "user_dictionary_enabled": False,
        "record_count": count,
        "content_sha256": content_sha,
        "source_audit_sha256": source_audit_sha256,
        "category_sources_sha256": category_sources_sha256,
        "category_file_count": category_file_count,
        "source_entry_count": source_entry_count,
    }
    identity = (indexer_git_sha, content_sha)
    if verification_status == "verified":
        if identity not in VERIFIED_DICTIONARY_INDEX_IDENTITIES:
            raise TierAError("dictionary_index_manifest: verified identity is outside the allowlist")
        trusted_metadata = VERIFIED_DICTIONARY_INDEX_METADATA[identity]
        if any(normalized[field] != value for field, value in trusted_metadata.items()):
            raise TierAError("dictionary_index_manifest: verified metadata does not match identity")
    if require_verified and verification_status != "verified":
        raise TierABlockedError(
            "dictionary_index", "an allowlisted verified dictionary index is required"
        )
    return normalized


def require_preprocessing_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != PREPROCESSING_VERIFIED:
        raise TierABlockedError(
            "jawiki_preprocessing",
            "jawiki manifest must be preprocessing_verified before Tier A generation",
        )
    if manifest.get("snapshot_date") != PINNED_JAWIKI_SNAPSHOT_DATE:
        raise TierAError("jawiki_manifest.snapshot_date: wrong pinned snapshot")
    _git_sha(manifest.get("preprocessing_git_sha"), "jawiki_manifest.preprocessing_git_sha")
    _sha256(manifest.get("local_sha256"), "jawiki_manifest.local_sha256")


def validate_source_span_manifest(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_manifest: Mapping[str, Any],
    require_verified: bool = True,
) -> dict[str, Any]:
    """Bind source spans to the exact dump, dictionary index, code and config."""

    fields = {
        "schema_version",
        "manifest_kind",
        "verification_status",
        "snapshot_date",
        "jawiki_local_sha256",
        "dictionary_index_sha256",
        "extractor_git_sha",
        "cleaner_version",
        "config",
        "eligible_dictionary_surface_count",
        "record_count",
        "content_sha256",
        "counts",
        "raw_text_in_report",
    }
    manifest = _strict_object(manifest, fields, "source_span_manifest")
    manifest_schema_version = manifest["schema_version"]
    if (
        type(manifest_schema_version) is not int
        or manifest_schema_version not in SUPPORTED_SOURCE_SPAN_MANIFEST_SCHEMA_VERSIONS
    ):
        raise TierAError("source_span_manifest.schema_version: unsupported schema")
    if manifest["manifest_kind"] != SOURCE_SPAN_MANIFEST_KIND:
        raise TierAError("source_span_manifest.manifest_kind: unsupported kind")
    status = manifest["verification_status"]
    if status not in {"measured", "verified"}:
        raise TierAError("source_span_manifest.verification_status: unsupported status")
    if manifest["snapshot_date"] != PINNED_JAWIKI_SNAPSHOT_DATE:
        raise TierAError("source_span_manifest.snapshot_date: wrong pinned snapshot")
    if jawiki_manifest.get("status") not in {
        LOCAL_ARTIFACT_VERIFIED,
        PREPROCESSING_VERIFIED,
    }:
        raise TierABlockedError(
            "jawiki_artifact", "a verified local jawiki artifact is required"
        )
    if jawiki_manifest.get("snapshot_date") != PINNED_JAWIKI_SNAPSHOT_DATE:
        raise TierAError("jawiki_manifest.snapshot_date: wrong pinned snapshot")
    jawiki_sha = _sha256(
        manifest["jawiki_local_sha256"], "source_span_manifest.jawiki_local_sha256"
    )
    if jawiki_sha != jawiki_manifest.get("local_sha256"):
        raise TierAError("source_span_manifest.jawiki_local_sha256: does not match dump")
    dictionary_sha = _sha256(
        manifest["dictionary_index_sha256"],
        "source_span_manifest.dictionary_index_sha256",
    )
    if dictionary_sha != dictionary_manifest.get("content_sha256"):
        raise TierAError(
            "source_span_manifest.dictionary_index_sha256: does not match dictionary index"
        )
    extractor_git_sha = _git_sha(
        manifest["extractor_git_sha"], "source_span_manifest.extractor_git_sha"
    )
    cleaner_version = manifest["cleaner_version"]
    if cleaner_version not in SUPPORTED_SOURCE_SPAN_CLEANER_VERSIONS:
        raise TierAError("source_span_manifest.cleaner_version: unsupported cleaner")
    if manifest_schema_version == 1 and cleaner_version not in {
        "conservative_wikitext_v1",
        "conservative_wikitext_v2",
    }:
        raise TierAError("source_span_manifest: legacy schema requires a legacy cleaner")
    if manifest_schema_version == 2 and cleaner_version != SOURCE_SPAN_CLEANER_VERSION:
        raise TierAError("source_span_manifest: current schema requires the current cleaner")
    config_fields = {
        "sample_modulus",
        "sample_slots",
        "max_records",
        "max_records_per_page",
        "max_output_bytes",
        "min_sentence_chars",
        "max_sentence_chars",
        "min_surface_chars",
        "max_surface_chars",
    }
    if manifest_schema_version == 2:
        config_fields.update({"min_reading_chars", "max_reading_chars"})
    config = _strict_object(
        manifest["config"],
        config_fields,
        "source_span_manifest.config",
    )
    integer_bounds = {
        "sample_modulus": 1_000_000,
        "sample_slots": 1_000_000,
        "max_records": MAX_SOURCE_RECORDS,
        "max_records_per_page": 1_000,
        "max_output_bytes": MAX_INPUT_FILE_BYTES,
        "min_sentence_chars": 4_096,
        "max_sentence_chars": 4_096,
        "min_surface_chars": 256,
        "max_surface_chars": 256,
    }
    if manifest_schema_version == 2:
        integer_bounds.update(
            {
                "min_reading_chars": MAX_READING_CHARS,
                "max_reading_chars": MAX_READING_CHARS,
            }
        )
    normalized_config = {
        field: _integer(config[field], f"source_span_manifest.config.{field}", maximum=bound)
        for field, bound in integer_bounds.items()
    }
    if not (
        1 <= normalized_config["sample_slots"] <= normalized_config["sample_modulus"]
        and 1 <= normalized_config["max_records"]
        and 1 <= normalized_config["max_records_per_page"]
        and 1 <= normalized_config["max_output_bytes"]
        and 1
        <= normalized_config["min_sentence_chars"]
        <= normalized_config["max_sentence_chars"]
        and 1
        <= normalized_config["min_surface_chars"]
        <= normalized_config["max_surface_chars"]
    ):
        raise TierAError("source_span_manifest.config: invalid bounds")
    if manifest_schema_version == 2 and not (
        MIN_READING_CHARS
        <= normalized_config["min_reading_chars"]
        <= normalized_config["max_reading_chars"]
        <= MAX_READING_CHARS
    ):
        raise TierAError("source_span_manifest.config: invalid reading bounds")
    surface_count = _integer(
        manifest["eligible_dictionary_surface_count"],
        "source_span_manifest.eligible_dictionary_surface_count",
        maximum=MAX_DICTIONARY_RECORDS,
    )
    if surface_count < 1:
        raise TierAError(
            "source_span_manifest.eligible_dictionary_surface_count: must be positive"
        )
    record_count = _integer(
        manifest["record_count"],
        "source_span_manifest.record_count",
        maximum=MAX_SOURCE_RECORDS,
    )
    if record_count < 1 or record_count != len(records):
        raise TierAError("source_span_manifest.record_count: does not match source spans")
    content_sha = _sha256(
        manifest["content_sha256"], "source_span_manifest.content_sha256"
    )
    if content_sha != hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest():
        raise TierAError("source_span_manifest.content_sha256: does not match source spans")
    counts = manifest["counts"]
    if not isinstance(counts, Mapping) or not counts:
        raise TierAError("source_span_manifest.counts: must be a non-empty object")
    normalized_counts: dict[str, int] = {}
    for key, value in counts.items():
        key = _string(key, "source_span_manifest.counts key", maximum=64)
        if re.fullmatch(r"[a-z][a-z0-9_]*", key) is None:
            raise TierAError("source_span_manifest.counts: invalid key")
        normalized_counts[key] = _integer(
            value, f"source_span_manifest.counts.{key}", maximum=10_000_000_000
        )
    if manifest["raw_text_in_report"] is not False:
        raise TierAError("source_span_manifest.raw_text_in_report: must be false")
    normalized = {
        "schema_version": manifest_schema_version,
        "manifest_kind": SOURCE_SPAN_MANIFEST_KIND,
        "verification_status": status,
        "snapshot_date": PINNED_JAWIKI_SNAPSHOT_DATE,
        "jawiki_local_sha256": jawiki_sha,
        "dictionary_index_sha256": dictionary_sha,
        "extractor_git_sha": extractor_git_sha,
        "cleaner_version": cleaner_version,
        "config": normalized_config,
        "eligible_dictionary_surface_count": surface_count,
        "record_count": record_count,
        "content_sha256": content_sha,
        "counts": dict(sorted(normalized_counts.items())),
        "raw_text_in_report": False,
    }
    identity = (extractor_git_sha, content_sha)
    if status == "verified":
        if identity not in VERIFIED_SOURCE_SPAN_IDENTITIES:
            raise TierAError("source_span_manifest: verified identity is outside the allowlist")
        if VERIFIED_SOURCE_SPAN_METADATA.get(identity) != {
            field: value
            for field, value in normalized.items()
            if field not in {"verification_status", "extractor_git_sha", "content_sha256"}
        }:
            raise TierAError("source_span_manifest: verified metadata does not match identity")
    if require_verified and status != "verified":
        raise TierABlockedError(
            "jawiki_source_spans", "an allowlisted verified source-span manifest is required"
        )
    return normalized


def generate_tier_a_records(
    source_spans: Sequence[Mapping[str, Any]],
    dictionary_index: Sequence[Mapping[str, Any]],
    exporter_records: Sequence[Mapping[str, Any]],
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_manifest: Mapping[str, Any],
    source_span_manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join validated immutable inputs and retain only automatic Tier A passes."""

    source_content_sha256 = hashlib.sha256(
        canonical_jsonl_bytes(source_spans)
    ).hexdigest()
    spans = validate_source_spans(source_spans)
    dictionary = validate_dictionary_index(dictionary_index)
    normalized_dictionary_manifest = validate_dictionary_index_manifest(
        dictionary_manifest, dictionary
    )
    normalized_source_manifest = validate_source_span_manifest(
        source_span_manifest,
        source_spans,
        jawiki_manifest=jawiki_manifest,
        dictionary_manifest=normalized_dictionary_manifest,
    )
    dictionary_by_surface = {record["surface"]: record["readings"] for record in dictionary}
    if not exporter_records or len(exporter_records) > MAX_SOURCE_RECORDS:
        raise TierAError("exporter_records: record count is outside the dataset bound")
    try:
        verified_exporter_records = []
        for start in range(0, len(exporter_records), MAX_EXPORT_RECORDS):
            verified_exporter_records.extend(
                validate_export_records(
                    exporter_records[start : start + MAX_EXPORT_RECORDS],
                    require_verified=True,
                )
            )
    except ContractError as error:
        raise TierAError(f"exporter_records: {error}") from error
    exporter_ids = [record["stable_id"] for record in verified_exporter_records]
    if exporter_ids != sorted(exporter_ids):
        raise TierAError("exporter_records.stable_id: must be globally sorted")
    exporter_by_id = {
        record["stable_id"]: record for record in verified_exporter_records
    }
    if len(exporter_by_id) != len(exporter_records):
        raise TierAError("exporter_records.stable_id: must be unique")

    rejected: Counter[str] = Counter()
    output: list[dict[str, Any]] = []
    source_ids = {span["stable_id"] for span in spans}
    for span in spans:
        readings = dictionary_by_surface.get(span["gold_surface"])
        if readings is None:
            rejected["dictionary_surface_missing"] += 1
            continue
        if len(readings) != 1:
            rejected["dictionary_reading_ambiguous"] += 1
            continue
        exporter = exporter_by_id.get(span["stable_id"])
        if exporter is None:
            rejected["exporter_snapshot_missing"] += 1
            continue
        reading = readings[0]
        if not MIN_READING_CHARS <= len(reading) <= MAX_READING_CHARS:
            rejected["reading_outside_target_bounds"] += 1
            continue
        if exporter["reading"] != reading:
            rejected["exporter_reading_mismatch"] += 1
            continue
        top32 = exporter["candidate_snapshots"]["training_top32"]
        if len(top32["candidates"]) < 2:
            rejected["insufficient_candidates"] += 1
            continue
        normalized_gold = unicodedata.normalize("NFKC", span["gold_surface"])
        matches = [
            index
            for index, candidate in enumerate(top32["candidates"])
            if unicodedata.normalize("NFKC", candidate["surface"]) == normalized_gold
        ]
        if len(matches) != 1:
            rejected["normalized_gold_not_unique"] += 1
            continue
        gold_index = matches[0]
        gold_candidate = top32["candidates"][gold_index]
        if not all(
            segment["source_category"] == "system_dictionary"
            for segment in gold_candidate["segments"]
        ):
            rejected["gold_path_not_exact_system_dictionary"] += 1
            continue

        record = {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "record_type": "training_example",
            "stable_id": span["stable_id"],
            "is_fixture": False,
            "source": span["source"],
            "session": {
                "session_id": span["stable_id"],
                "left_context": span["left_context"],
                "left_context_policy": "sakura_input_committed_same_session",
            },
            "converter_provenance": exporter["converter_provenance"],
            "reading": reading,
            "gold_surface": gold_candidate["surface"],
            "candidate_snapshots": exporter["candidate_snapshots"],
            "gold_index": gold_index,
            "oracle": {
                "k": 6,
                "hit": gold_index
                < len(
                    exporter["candidate_snapshots"]["production_top6"][
                        "candidates"
                    ]
                ),
            },
            "split": None,
            "tier": "A",
            "tier_a_verification": {
                "contract_version": 2,
                "status": "passed",
                "verification_source": AUTOMATIC_TIER_A_SOURCE,
                "dictionary_unique_reading": True,
                "forward_conversion_matches": True,
                "normalized_gold_matches": True,
                "exact_dictionary_path_covers_reading": True,
            },
            "sampled_human_audit": {
                "selection": "not_sampled",
                "status": "not_reviewed",
                "noise_free": None,
                "reviewer_id": None,
                "reviewed_at": None,
            },
            "training_eligible": True,
        }
        try:
            output.append(validate_records([record], require_split=False)[0])
        except ContractError as error:
            raise TierAError(f"generated record {span['stable_id']}: {error}") from error

    if not output:
        raise TierABlockedError(
            "tier_a_output",
            "no source span passed every automatic Tier A check",
            details={
                "input_record_count": len(spans),
                "rejection_counts": dict(sorted(rejected.items())),
            },
        )
    output = validate_records(output, require_split=False)
    output_payload = canonical_jsonl_bytes(output)
    report = {
        "schema_version": 1,
        "report_kind": "tier_a_generation",
        "status": "generated",
        "input_record_count": len(spans),
        "accepted_record_count": len(output),
        "rejected_record_count": sum(rejected.values()),
        "rejection_counts": dict(sorted(rejected.items())),
        "unused_exporter_snapshot_count": len(set(exporter_by_id) - source_ids),
        "jawiki_local_sha256": jawiki_manifest["local_sha256"],
        "jawiki_preprocessing_git_sha": normalized_source_manifest["extractor_git_sha"],
        "dictionary_indexer_git_sha": normalized_dictionary_manifest["indexer_git_sha"],
        "source_content_sha256": source_content_sha256,
        "source_span_manifest_kind": normalized_source_manifest["manifest_kind"],
        "dictionary_index_content_sha256": hashlib.sha256(
            canonical_jsonl_bytes(dictionary)
        ).hexdigest(),
        "exporter_content_sha256": hashlib.sha256(
            canonical_jsonl_bytes(verified_exporter_records)
        ).hexdigest(),
        "content_sha256": hashlib.sha256(output_payload).hexdigest(),
    }
    canonical_json_bytes(report)
    return output, report


def ensure_distinct_tier_a_paths(paths: Mapping[str, str | Path]) -> None:
    named = {name: Path(path) for name, path in paths.items()}
    try:
        resolved = {
            name: os.path.normcase(os.fspath(path.resolve(strict=False)))
            for name, path in named.items()
        }
    except OSError as error:
        raise TierAError(f"paths: cannot resolve ({type(error).__name__})") from error
    names = tuple(named)
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1 :]:
            same = resolved[left_name] == resolved[right_name]
            if named[left_name].exists() and named[right_name].exists():
                try:
                    same = same or named[left_name].samefile(named[right_name])
                except OSError as error:
                    raise TierAError("paths: cannot establish file identity") from error
            if same:
                raise TierAError(f"paths: {left_name} and {right_name} must be distinct")


def publish_tier_a_artifacts(
    output_path: str | Path,
    report_path: str | Path,
    records: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> tuple[str, str]:
    output_payload = canonical_jsonl_bytes(validate_records(records, require_split=False))
    if report.get("content_sha256") != hashlib.sha256(output_payload).hexdigest():
        raise TierAError("report.content_sha256: does not match output")
    report_payload = canonical_json_bytes(report) + b"\n"
    write_bytes_pair_atomic(output_path, output_payload, report_path, report_payload)
    return hashlib.sha256(output_payload).hexdigest(), hashlib.sha256(report_payload).hexdigest()


def read_source_spans(path: str | Path) -> list[Mapping[str, Any]]:
    return _read_jsonl(path, label="source spans", maximum_records=MAX_SOURCE_RECORDS)


def read_dictionary_index(path: str | Path) -> list[dict[str, Any]]:
    return validate_dictionary_index(
        _read_jsonl(
            path, label="dictionary index", maximum_records=MAX_DICTIONARY_RECORDS
        )
    )


def read_dictionary_index_manifest(path: str | Path) -> Mapping[str, Any]:
    try:
        manifest_path = Path(path)
        if manifest_path.stat().st_size > MAX_MANIFEST_FILE_BYTES:
            raise TierAError("dictionary index manifest: exceeds bounded size")
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TierAError(f"dictionary index manifest: cannot read ({type(error).__name__})") from error
    if not isinstance(value, Mapping):
        raise TierAError("dictionary index manifest: must be an object")
    return value


def read_source_span_manifest(path: str | Path) -> Mapping[str, Any]:
    try:
        manifest_path = Path(path)
        if manifest_path.stat().st_size > MAX_MANIFEST_FILE_BYTES:
            raise TierAError("source span manifest: exceeds bounded size")
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TierAError(f"source span manifest: cannot read ({type(error).__name__})") from error
    if not isinstance(value, Mapping):
        raise TierAError("source span manifest: must be an object")
    return value
