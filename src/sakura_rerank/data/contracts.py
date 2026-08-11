"""Versioned, deterministic JSONL contracts for converter-labelled examples."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_atomic


CONTRACT_SCHEMA_VERSION = 3
CONVERTER_FEATURE_CONTRACT_VERSION = 1
TIER_A_VERIFICATION_CONTRACT_VERSION = 2
RESEARCH_EXPORTER_CONTRACT_VERSION = 1
RECORD_TYPE = "training_example"
MAX_LEFT_CONTEXT_CHARS = 64
MAX_READING_CHARS = 128
MAX_SURFACE_CHARS = 256
MAX_CONVERTER_SEGMENTS = 18
TRAINING_TOP_K = 32
PRODUCTION_TOP_K = 6
PINNED_SAKURA_INPUT_HEAD = "8e966dff456e4e7165e025f97c1f73327ff3f550"
PINNED_DICTIONARY_SHA256 = (
    "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad"
)
PINNED_JAWIKI_SNAPSHOT_DATE = "2026-08-01"
REAL_RECORD_PROVENANCE = "sakura_input_converter_export"
FIXTURE_RECORD_PROVENANCE = "contract_fixture"
REAL_CANDIDATE_SOURCE = "sakura_converter_full_reading_nbest"
FIXTURE_CANDIDATE_SOURCE = "fixture_full_reading_nbest"
AUTOMATIC_TIER_A_SOURCE = "sakura_converter_forward_verification"
SPLITS = ("train", "dev", "final-holdout")

# Commit C intentionally leaves the verified identity allowlist empty.  Commit
# D may add exactly one measured Git-tree/binary pair together with the complete
# trusted build metadata.  The pinned Sakura Input HEAD alone is never an
# exporter identity: the production converter bound remains 18, while this
# research binary is isolated behind the Sakura Input research-top32 feature and
# patch.
VERIFIED_RESEARCH_EXPORTER_IDENTITIES: frozenset[tuple[str, str]] = frozenset()
VERIFIED_RESEARCH_EXPORTER_TRUSTED_METADATA: dict[tuple[str, str], dict[str, Any]] = {}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{16}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SEGMENT_SOURCE_CATEGORIES = frozenset(
    {
        "system_dictionary",
        "user_dictionary",
        "reading_fallback",
        "katakana_fallback",
        "generated_literal",
    }
)
_CANDIDATE_SOURCE_CATEGORIES = _SEGMENT_SOURCE_CATEGORIES | {"mixed"}
_EXACT_DICTIONARY_SEGMENT_SOURCES = frozenset(
    {"system_dictionary", "user_dictionary"}
)


class ContractError(ValueError):
    """A JSONL record violates the versioned data boundary."""


def _error(field: str, message: str) -> None:
    raise ContractError(f"{field}: {message}")


def _reject_unknown_keys(value: Mapping[str, Any], allowed: Iterable[str], field: str) -> None:
    if set(value) - set(allowed):
        _error(field, "contains unknown fields")


def _require_string(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
    max_chars: int | None = None,
) -> str:
    if not isinstance(value, str):
        _error(field, "must be a string")
    if not allow_empty and not value:
        _error(field, "must not be empty")
    if "\x00" in value or "\r" in value or "\n" in value:
        _error(field, "contains a forbidden control character")
    if max_chars is not None and len(value) > max_chars:
        _error(field, "exceeds the bounded character length")
    return value


def _require_identifier(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if _ID_RE.fullmatch(value) is None:
        _error(field, "must be a bounded stable identifier")
    return value


def _require_sha256(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if _SHA256_RE.fullmatch(value) is None:
        _error(field, "must be a lowercase SHA-256 hex digest")
    return value


def _require_git_sha(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if _GIT_SHA_RE.fullmatch(value) is None:
        _error(field, "must be a lowercase Git SHA-1")
    return value


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _error(field, "must be boolean")
    return value


def _require_integer(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _error(field, "must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        _error(field, "is outside the allowed range")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON with stable key order, separators, Unicode, and numbers."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError("canonical JSON: value is not deterministic JSON") from error


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_jsonl_bytes(records: Sequence[Mapping[str, Any]]) -> bytes:
    """Return byte-identical JSONL independent of input mapping order."""

    ordered = sorted(records, key=lambda record: str(record.get("stable_id", "")))
    if not ordered:
        return b""
    return b"\n".join(canonical_json_bytes(record) for record in ordered) + b"\n"


def write_jsonl(path: str | Path, records: Sequence[Mapping[str, Any]]) -> str:
    """Validate and write sorted canonical JSONL, returning its SHA-256."""

    validated = validate_records(records)
    payload = canonical_jsonl_bytes(validated)
    write_bytes_atomic(path, payload)
    return hashlib.sha256(payload).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sentence_shingle_hashes(text: str, *, width: int = 3) -> list[str]:
    """Create privacy-preserving character-shingle hashes for duplicate checks."""

    if width < 1:
        raise ContractError("shingle width: must be positive")
    normalized = " ".join(unicodedata.normalize("NFKC", text).split()).casefold()
    if not normalized:
        return []
    shingles = {
        text_sha256(normalized[index : index + width])
        for index in range(max(1, len(normalized) - width + 1))
    }
    return sorted(shingles)


def candidate_fingerprint(surface: str, local_cost: int) -> str:
    """Return Sakura Input HEAD's FNV-1a fingerprint over surface and i64 cost."""

    fingerprint = 0xCBF29CE484222325
    for byte in surface.encode("utf-8") + local_cost.to_bytes(8, "little", signed=True):
        fingerprint ^= byte
        fingerprint = (fingerprint * 0x00000100000001B3) & 0xFFFF_FFFF_FFFF_FFFF
    return f"{fingerprint:016x}"


def _validate_date(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        _error(field, "must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        _error(field, "is not a calendar date")
    return value


def _validate_timestamp(value: Any, field: str) -> str:
    value = _require_string(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _error(field, "must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error(field, "must include a timezone")
    return value


def _validate_hash_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _error(field, "must be a non-empty list")
    normalized = [
        _require_sha256(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    ]
    if len(normalized) > 512 or normalized != sorted(set(normalized)):
        _error(field, "must be sorted, unique, and bounded")
    return normalized


def _validate_source(source: Any, *, is_fixture: bool) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        _error("source", "must be an object")
    expected = {
        "corpus",
        "snapshot_date",
        "article_id",
        "page_id",
        "revision_id",
        "paragraph_hash",
        "sentence_hash",
        "sentence_shingle_hashes",
        "template_cluster_id",
    }
    _reject_unknown_keys(source, expected, "source")
    if set(source) != expected:
        _error("source", "page and leakage provenance fields are required")
    corpus = _require_string(source["corpus"], "source.corpus")
    if corpus not in ({"fixture"} if is_fixture else {"jawiki"}):
        _error("source.corpus", "does not match the fixture/production status")
    template_cluster_id = source["template_cluster_id"]
    if template_cluster_id is not None:
        template_cluster_id = _require_identifier(
            template_cluster_id, "source.template_cluster_id"
        )
    snapshot_date = _validate_date(
        source["snapshot_date"], "source.snapshot_date"
    )
    if not is_fixture and snapshot_date != PINNED_JAWIKI_SNAPSHOT_DATE:
        _error("source.snapshot_date", "does not match the pinned jawiki snapshot")
    return {
        "corpus": corpus,
        "snapshot_date": snapshot_date,
        "article_id": _require_identifier(source["article_id"], "source.article_id"),
        "page_id": _require_identifier(source["page_id"], "source.page_id"),
        "revision_id": _require_identifier(source["revision_id"], "source.revision_id"),
        "paragraph_hash": _require_sha256(
            source["paragraph_hash"], "source.paragraph_hash"
        ),
        "sentence_hash": _require_sha256(
            source["sentence_hash"], "source.sentence_hash"
        ),
        "sentence_shingle_hashes": _validate_hash_list(
            source["sentence_shingle_hashes"], "source.sentence_shingle_hashes"
        ),
        "template_cluster_id": template_cluster_id,
    }


def _validate_session(session: Any) -> dict[str, str]:
    if not isinstance(session, Mapping):
        _error("session", "must be an object")
    expected = {"session_id", "left_context", "left_context_policy"}
    _reject_unknown_keys(session, expected, "session")
    if set(session) != expected:
        _error("session", "same-session context provenance is required")
    policy = _require_string(session["left_context_policy"], "session.left_context_policy")
    if policy != "sakura_input_committed_same_session":
        _error("session.left_context_policy", "untrusted context source")
    return {
        "session_id": _require_identifier(session["session_id"], "session.session_id"),
        "left_context": _require_string(
            session["left_context"],
            "session.left_context",
            allow_empty=True,
            max_chars=MAX_LEFT_CONTEXT_CHARS,
        ),
        "left_context_policy": policy,
    }


def _validate_converter_provenance(value: Any, *, is_fixture: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("converter_provenance", "must be an object")
    expected = {
        "kind",
        "sakura_input_head",
        "dictionary_sha256",
        "feature_contract_version",
    }
    _reject_unknown_keys(value, expected, "converter_provenance")
    if set(value) != expected:
        _error("converter_provenance", "all converter identity fields are required")
    version = _require_integer(
        value["feature_contract_version"],
        "converter_provenance.feature_contract_version",
    )
    if version != CONVERTER_FEATURE_CONTRACT_VERSION:
        _error(
            "converter_provenance.feature_contract_version",
            "unsupported converter feature contract",
        )

    if is_fixture:
        if value["kind"] != FIXTURE_RECORD_PROVENANCE:
            _error("converter_provenance.kind", "fixture provenance is required")
        if value["sakura_input_head"] is not None or value["dictionary_sha256"] is not None:
            _error(
                "converter_provenance",
                "fixtures must not claim a Sakura Input revision or dictionary",
            )
        return {
            "kind": FIXTURE_RECORD_PROVENANCE,
            "sakura_input_head": None,
            "dictionary_sha256": None,
            "feature_contract_version": CONVERTER_FEATURE_CONTRACT_VERSION,
        }

    if value["kind"] != REAL_RECORD_PROVENANCE:
        _error("converter_provenance.kind", "actual converter export provenance is required")
    head = _require_string(value["sakura_input_head"], "converter_provenance.sakura_input_head")
    if _GIT_SHA_RE.fullmatch(head) is None:
        _error("converter_provenance.sakura_input_head", "must be a lowercase Git SHA-1")
    if head != PINNED_SAKURA_INPUT_HEAD:
        _error("converter_provenance.sakura_input_head", "does not match the pinned Sakura Input HEAD")
    dictionary_sha256 = _require_sha256(
        value["dictionary_sha256"], "converter_provenance.dictionary_sha256"
    )
    if dictionary_sha256 != PINNED_DICTIONARY_SHA256:
        _error("converter_provenance.dictionary_sha256", "does not match the pinned dictionary")
    return {
        "kind": REAL_RECORD_PROVENANCE,
        "sakura_input_head": head,
        "dictionary_sha256": dictionary_sha256,
        "feature_contract_version": CONVERTER_FEATURE_CONTRACT_VERSION,
    }


def _utf8_boundaries(value: str) -> set[int]:
    boundaries = {0}
    offset = 0
    for character in value:
        offset += len(character.encode("utf-8"))
        boundaries.add(offset)
    return boundaries


def _validate_segment(
    segment: Any,
    field: str,
    *,
    is_fixture: bool,
    expected_reading_start: int,
    expected_text_start: int,
    reading_boundaries: set[int],
    text_boundaries: set[int],
) -> dict[str, Any]:
    if not isinstance(segment, Mapping):
        _error(field, "must be an object")
    expected = {
        "reading_start",
        "reading_end",
        "text_start",
        "text_end",
        "left_id",
        "right_id",
        "flags",
        "source_category",
    }
    _reject_unknown_keys(segment, expected, field)
    if set(segment) != expected:
        _error(field, "all converter-derived segment fields are required")
    reading_start = _require_integer(
        segment["reading_start"], f"{field}.reading_start", maximum=0xFFFF
    )
    reading_end = _require_integer(
        segment["reading_end"], f"{field}.reading_end", maximum=0xFFFF
    )
    text_start = _require_integer(
        segment["text_start"], f"{field}.text_start", maximum=0xFFFF
    )
    text_end = _require_integer(
        segment["text_end"], f"{field}.text_end", maximum=0xFFFF
    )
    if reading_start != expected_reading_start or text_start != expected_text_start:
        _error(field, "segment ranges must be contiguous and start at zero")
    if reading_end <= reading_start or text_end <= text_start:
        _error(field, "segment ranges must be non-empty")
    if reading_start not in reading_boundaries or reading_end not in reading_boundaries:
        _error(field, "reading range must use UTF-8 byte boundaries")
    if text_start not in text_boundaries or text_end not in text_boundaries:
        _error(field, "text range must use UTF-8 byte boundaries")
    category = _require_string(segment["source_category"], f"{field}.source_category")
    allowed_categories = {"fixture"} if is_fixture else _SEGMENT_SOURCE_CATEGORIES
    if category not in allowed_categories:
        _error(f"{field}.source_category", "unsupported or fixture segment provenance")
    return {
        "reading_start": reading_start,
        "reading_end": reading_end,
        "text_start": text_start,
        "text_end": text_end,
        "left_id": _require_integer(segment["left_id"], f"{field}.left_id", maximum=0xFFFF),
        "right_id": _require_integer(
            segment["right_id"], f"{field}.right_id", maximum=0xFFFF
        ),
        "flags": _require_integer(segment["flags"], f"{field}.flags", maximum=0xFFFF),
        "source_category": category,
    }


def _validate_candidate(
    candidate: Any,
    field: str,
    *,
    rank: int,
    reading: str,
    is_fixture: bool,
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        _error(field, "must be an object")
    expected = {
        "rank",
        "surface",
        "local_cost",
        "source_category",
        "fingerprint",
        "system_entry_index",
        "segments",
    }
    _reject_unknown_keys(candidate, expected, field)
    if set(candidate) != expected:
        _error(field, "all versioned converter candidate features are required")
    if _require_integer(candidate["rank"], f"{field}.rank") != rank:
        _error(f"{field}.rank", "must equal the immutable converter order")
    surface = _require_string(
        candidate["surface"], f"{field}.surface", max_chars=MAX_SURFACE_CHARS
    )
    local_cost = _require_integer(
        candidate["local_cost"],
        f"{field}.local_cost",
        minimum=-(2**63),
        maximum=2**63 - 1,
    )
    fingerprint = _require_string(candidate["fingerprint"], f"{field}.fingerprint")
    if _FINGERPRINT_RE.fullmatch(fingerprint) is None:
        _error(f"{field}.fingerprint", "must be lowercase 16-digit hex")
    if fingerprint != candidate_fingerprint(surface, local_cost):
        _error(f"{field}.fingerprint", "does not match the pinned converter algorithm")

    segments = candidate["segments"]
    if (
        not isinstance(segments, list)
        or not segments
        or len(segments) > MAX_CONVERTER_SEGMENTS
    ):
        _error(f"{field}.segments", "must be a non-empty bounded segment list")
    reading_boundaries = _utf8_boundaries(reading)
    text_boundaries = _utf8_boundaries(surface)
    normalized_segments: list[dict[str, Any]] = []
    reading_start = 0
    text_start = 0
    for index, segment in enumerate(segments):
        normalized = _validate_segment(
            segment,
            f"{field}.segments[{index}]",
            is_fixture=is_fixture,
            expected_reading_start=reading_start,
            expected_text_start=text_start,
            reading_boundaries=reading_boundaries,
            text_boundaries=text_boundaries,
        )
        normalized_segments.append(normalized)
        reading_start = normalized["reading_end"]
        text_start = normalized["text_end"]
    if reading_start != len(reading.encode("utf-8")):
        _error(f"{field}.segments", "must cover the complete reading")
    if text_start != len(surface.encode("utf-8")):
        _error(f"{field}.segments", "must cover the complete surface")

    category = _require_string(candidate["source_category"], f"{field}.source_category")
    if is_fixture:
        expected_category = "fixture"
    else:
        segment_categories = {segment["source_category"] for segment in normalized_segments}
        expected_category = next(iter(segment_categories)) if len(segment_categories) == 1 else "mixed"
        if category not in _CANDIDATE_SOURCE_CATEGORIES:
            _error(f"{field}.source_category", "unsupported or fixture candidate provenance")
    if category != expected_category:
        _error(f"{field}.source_category", "does not match segment provenance")

    system_entry_index = candidate["system_entry_index"]
    is_single_system_entry = (
        not is_fixture
        and len(normalized_segments) == 1
        and category == "system_dictionary"
    )
    if is_single_system_entry:
        system_entry_index = _require_integer(
            system_entry_index, f"{field}.system_entry_index", maximum=2**32 - 1
        )
    elif system_entry_index is not None:
        _error(
            f"{field}.system_entry_index",
            "must be null unless the converter reports one system-dictionary edge",
        )

    return {
        "rank": rank,
        "surface": surface,
        "local_cost": local_cost,
        "source_category": category,
        "fingerprint": fingerprint,
        "system_entry_index": system_entry_index,
        "segments": normalized_segments,
    }


def _candidate_snapshot_hash(
    snapshot: Mapping[str, Any], converter_provenance: Mapping[str, Any]
) -> str:
    payload = {
        "limit": snapshot["limit"],
        "source": snapshot["source"],
        "feature_contract_version": snapshot["feature_contract_version"],
        "converter_provenance": converter_provenance,
        "reading": snapshot["reading"],
        "candidates": snapshot["candidates"],
    }
    if "exporter_run" in snapshot:
        payload["exporter_run"] = snapshot["exporter_run"]
    return canonical_json_hash(payload)


def _validate_research_exporter_run(
    value: Any,
    *,
    is_fixture: bool,
    returned_count: int,
) -> dict[str, Any]:
    field = "candidate_snapshots.training_top32.exporter_run"
    if not isinstance(value, Mapping):
        _error(field, "must be an object")
    expected = {
        "contract_version",
        "verification_status",
        "exporter_git_sha",
        "exporter_binary_sha256",
        "requested_limit",
        "effective_converter_bound",
        "returned_count",
        "result_status",
    }
    _reject_unknown_keys(value, expected, field)
    if set(value) != expected:
        _error(field, "immutable exporter identity and complete run evidence are required")

    version = _require_integer(value["contract_version"], f"{field}.contract_version")
    if version != RESEARCH_EXPORTER_CONTRACT_VERSION:
        _error(f"{field}.contract_version", "unsupported exporter evidence contract")
    requested_limit = _require_integer(value["requested_limit"], f"{field}.requested_limit")
    if requested_limit != TRAINING_TOP_K:
        _error(f"{field}.requested_limit", "must request the top-32 contract bound")
    recorded_count = _require_integer(value["returned_count"], f"{field}.returned_count")
    if recorded_count != returned_count:
        _error(f"{field}.returned_count", "does not match the candidate snapshot")
    result_status = _require_string(value["result_status"], f"{field}.result_status")
    if result_status not in {"search_exhausted", "truncated"}:
        _error(f"{field}.result_status", "must be search_exhausted or truncated")
    if returned_count < requested_limit and result_status != "search_exhausted":
        _error(
            f"{field}.result_status",
            "a short top-32 result requires explicit search_exhausted evidence",
        )

    verification_status = _require_string(
        value["verification_status"], f"{field}.verification_status"
    )
    exporter_git_sha = value["exporter_git_sha"]
    exporter_binary_sha256 = value["exporter_binary_sha256"]
    effective_bound = value["effective_converter_bound"]
    if is_fixture:
        if verification_status != "fixture":
            _error(f"{field}.verification_status", "fixtures require fixture status")
        if exporter_git_sha is not None or exporter_binary_sha256 is not None:
            _error(field, "fixtures cannot claim an immutable research exporter identity")
        if effective_bound is not None:
            _error(field, "fixtures cannot claim a converter execution bound")
    else:
        if verification_status not in {"unverified", "verified"}:
            _error(
                f"{field}.verification_status",
                "production evidence must be unverified or verified",
            )
        if exporter_git_sha is not None:
            exporter_git_sha = _require_git_sha(
                exporter_git_sha, f"{field}.exporter_git_sha"
            )
        if exporter_binary_sha256 is not None:
            exporter_binary_sha256 = _require_sha256(
                exporter_binary_sha256, f"{field}.exporter_binary_sha256"
            )
        if verification_status == "verified" and (
            exporter_git_sha is None and exporter_binary_sha256 is None
        ):
            _error(field, "verified evidence requires an exporter Git SHA or binary SHA-256")
        effective_bound = _require_integer(
            effective_bound,
            f"{field}.effective_converter_bound",
            minimum=1,
            maximum=2**16,
        )
        if effective_bound < requested_limit:
            _error(
                f"{field}.effective_converter_bound",
                "cannot satisfy the top-32 contract bound",
            )
        if returned_count > effective_bound:
            _error(f"{field}.returned_count", "exceeds the effective converter bound")

    return {
        "contract_version": RESEARCH_EXPORTER_CONTRACT_VERSION,
        "verification_status": verification_status,
        "exporter_git_sha": exporter_git_sha,
        "exporter_binary_sha256": exporter_binary_sha256,
        "requested_limit": TRAINING_TOP_K,
        "effective_converter_bound": effective_bound,
        "returned_count": returned_count,
        "result_status": result_status,
    }


def _has_verified_research_exporter(value: Mapping[str, Any]) -> bool:
    identity = (value["exporter_git_sha"], value["exporter_binary_sha256"])
    return (
        value["verification_status"] == "verified"
        and identity in VERIFIED_RESEARCH_EXPORTER_IDENTITIES
    )


def _validate_snapshot(
    snapshot: Any,
    field: str,
    *,
    limit: int,
    reading: str,
    is_fixture: bool,
    converter_provenance: Mapping[str, Any],
    require_exporter_run: bool = False,
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        _error(field, "must be an object")
    expected = {
        "limit",
        "source",
        "feature_contract_version",
        "reading",
        "candidates",
        "content_sha256",
    }
    if require_exporter_run:
        expected.add("exporter_run")
    _reject_unknown_keys(snapshot, expected, field)
    if set(snapshot) != expected:
        _error(field, "snapshot identity, features, candidates, and hash are required")
    if _require_integer(snapshot["limit"], f"{field}.limit") != limit:
        _error(f"{field}.limit", "does not match the contract bound")
    source = _require_string(snapshot["source"], f"{field}.source")
    expected_source = FIXTURE_CANDIDATE_SOURCE if is_fixture else REAL_CANDIDATE_SOURCE
    if source != expected_source:
        _error(f"{field}.source", "does not prove the required candidate provenance")
    version = _require_integer(
        snapshot["feature_contract_version"], f"{field}.feature_contract_version"
    )
    if version != CONVERTER_FEATURE_CONTRACT_VERSION:
        _error(f"{field}.feature_contract_version", "unsupported feature contract")
    snapshot_reading = _require_string(
        snapshot["reading"], f"{field}.reading", max_chars=MAX_READING_CHARS
    )
    if snapshot_reading != reading:
        _error(f"{field}.reading", "does not match the example reading")
    candidates = snapshot["candidates"]
    if not isinstance(candidates, list) or not candidates or len(candidates) > limit:
        _error(f"{field}.candidates", "must be a non-empty list within its limit")
    normalized_candidates = [
        _validate_candidate(
            candidate,
            f"{field}.candidates[{index}]",
            rank=index,
            reading=reading,
            is_fixture=is_fixture,
        )
        for index, candidate in enumerate(candidates)
    ]
    surfaces = [candidate["surface"] for candidate in normalized_candidates]
    if len(surfaces) != len(set(surfaces)):
        _error(f"{field}.candidates", "candidate surfaces must be unique")
    content_sha256 = _require_sha256(snapshot["content_sha256"], f"{field}.content_sha256")
    normalized = {
        "limit": limit,
        "source": source,
        "feature_contract_version": CONVERTER_FEATURE_CONTRACT_VERSION,
        "reading": reading,
        "candidates": normalized_candidates,
        "content_sha256": content_sha256,
    }
    if require_exporter_run:
        normalized["exporter_run"] = _validate_research_exporter_run(
            snapshot["exporter_run"],
            is_fixture=is_fixture,
            returned_count=len(normalized_candidates),
        )
    if content_sha256 != _candidate_snapshot_hash(normalized, converter_provenance):
        _error(f"{field}.content_sha256", "does not match canonical snapshot content")
    return normalized


def _validate_tier_a_verification(value: Any, *, is_fixture: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("tier_a_verification", "must be an object")
    expected = {
        "contract_version",
        "status",
        "verification_source",
        "dictionary_unique_reading",
        "forward_conversion_matches",
        "normalized_gold_matches",
        "exact_dictionary_path_covers_reading",
    }
    _reject_unknown_keys(value, expected, "tier_a_verification")
    if set(value) != expected:
        _error("tier_a_verification", "all automatic verification fields are required")
    version = _require_integer(value["contract_version"], "tier_a_verification.contract_version")
    if version != TIER_A_VERIFICATION_CONTRACT_VERSION:
        _error("tier_a_verification.contract_version", "unsupported verification contract")
    status = _require_string(value["status"], "tier_a_verification.status")
    if status not in {"passed", "failed", "not_applicable"}:
        _error("tier_a_verification.status", "unsupported automatic verification status")
    verification_source = _require_string(
        value["verification_source"], "tier_a_verification.verification_source"
    )
    flags = {
        key: _require_bool(value[key], f"tier_a_verification.{key}")
        for key in (
            "dictionary_unique_reading",
            "forward_conversion_matches",
            "normalized_gold_matches",
            "exact_dictionary_path_covers_reading",
        )
    }
    if is_fixture:
        if status != "not_applicable" or verification_source != "not_applicable" or any(flags.values()):
            _error("tier_a_verification", "fixtures cannot claim automatic Tier A verification")
    else:
        if verification_source != AUTOMATIC_TIER_A_SOURCE:
            _error("tier_a_verification.verification_source", "must identify automatic converter verification")
        if status == "passed" and not all(flags.values()):
            _error("tier_a_verification.status", "passed requires every automatic check")
        if status == "failed" and all(flags.values()):
            _error("tier_a_verification.status", "failed requires an observed failed check")
        if status == "not_applicable" and any(flags.values()):
            _error("tier_a_verification.status", "not_applicable cannot contain positive checks")
    return {
        "contract_version": TIER_A_VERIFICATION_CONTRACT_VERSION,
        "status": status,
        "verification_source": verification_source,
        **flags,
    }


def _validate_sampled_human_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("sampled_human_audit", "must be an object")
    expected = {"selection", "status", "noise_free", "reviewer_id", "reviewed_at"}
    _reject_unknown_keys(value, expected, "sampled_human_audit")
    if set(value) != expected:
        _error("sampled_human_audit", "selection and audit outcome fields are required")
    selection = _require_string(value["selection"], "sampled_human_audit.selection")
    status = _require_string(value["status"], "sampled_human_audit.status")
    if selection == "not_sampled":
        if status != "not_reviewed" or any(
            value[key] is not None for key in ("noise_free", "reviewer_id", "reviewed_at")
        ):
            _error("sampled_human_audit", "non-sampled records cannot claim human review")
        return {
            "selection": selection,
            "status": status,
            "noise_free": None,
            "reviewer_id": None,
            "reviewed_at": None,
        }
    if selection != "selected":
        _error("sampled_human_audit.selection", "must be not_sampled or selected")
    if status == "pending":
        if any(value[key] is not None for key in ("noise_free", "reviewer_id", "reviewed_at")):
            _error("sampled_human_audit", "pending audit cannot claim an outcome")
        return {
            "selection": selection,
            "status": status,
            "noise_free": None,
            "reviewer_id": None,
            "reviewed_at": None,
        }
    if status not in {"accepted", "rejected"}:
        _error("sampled_human_audit.status", "selected audit must be pending, accepted, or rejected")
    noise_free = _require_bool(value["noise_free"], "sampled_human_audit.noise_free")
    reviewer_id = _require_identifier(value["reviewer_id"], "sampled_human_audit.reviewer_id")
    reviewed_at = _validate_timestamp(value["reviewed_at"], "sampled_human_audit.reviewed_at")
    if (status == "accepted") != noise_free:
        _error("sampled_human_audit.status", "accepted must be noise-free and rejected must not be")
    return {
        "selection": selection,
        "status": status,
        "noise_free": noise_free,
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
    }


def validate_record(record: Mapping[str, Any], *, require_split: bool = True) -> dict[str, Any]:
    """Validate one JSONL record and return a normalized copy."""

    if not isinstance(record, Mapping):
        raise ContractError("record: must be a JSON object")
    expected = {
        "schema_version",
        "record_type",
        "stable_id",
        "is_fixture",
        "source",
        "session",
        "converter_provenance",
        "reading",
        "gold_surface",
        "candidate_snapshots",
        "gold_index",
        "oracle",
        "split",
        "tier",
        "tier_a_verification",
        "sampled_human_audit",
        "training_eligible",
    }
    _reject_unknown_keys(record, expected, "record")
    if set(record) != expected:
        _error("record", "all contract fields are required")
    if (
        isinstance(record["schema_version"], bool)
        or record["schema_version"] != CONTRACT_SCHEMA_VERSION
    ):
        _error("schema_version", "unsupported contract version")
    if record["record_type"] != RECORD_TYPE:
        _error("record_type", "unsupported record type")
    stable_id = _require_identifier(record["stable_id"], "stable_id")
    is_fixture = _require_bool(record["is_fixture"], "is_fixture")
    source = _validate_source(record["source"], is_fixture=is_fixture)
    session = _validate_session(record["session"])
    converter_provenance = _validate_converter_provenance(
        record["converter_provenance"], is_fixture=is_fixture
    )
    reading = _require_string(record["reading"], "reading", max_chars=MAX_READING_CHARS)
    gold_surface = _require_string(
        record["gold_surface"], "gold_surface", max_chars=MAX_SURFACE_CHARS
    )

    snapshots = record["candidate_snapshots"]
    if not isinstance(snapshots, Mapping):
        _error("candidate_snapshots", "must be an object")
    if set(snapshots) != {"training_top32", "production_top6"}:
        _error("candidate_snapshots", "top-32 and top-6 snapshots are required")
    top32 = _validate_snapshot(
        snapshots["training_top32"],
        "candidate_snapshots.training_top32",
        limit=TRAINING_TOP_K,
        reading=reading,
        is_fixture=is_fixture,
        converter_provenance=converter_provenance,
        require_exporter_run=True,
    )
    top6 = _validate_snapshot(
        snapshots["production_top6"],
        "candidate_snapshots.production_top6",
        limit=PRODUCTION_TOP_K,
        reading=reading,
        is_fixture=is_fixture,
        converter_provenance=converter_provenance,
    )
    expected_top6 = top32["candidates"][: min(PRODUCTION_TOP_K, len(top32["candidates"]))]
    if top6["candidates"] != expected_top6:
        _error("candidate_snapshots.production_top6.candidates", "must be the top-32 prefix")

    gold_index = record["gold_index"]
    if gold_index is not None:
        gold_index = _require_integer(
            gold_index, "gold_index", maximum=len(top32["candidates"]) - 1
        )
        if top32["candidates"][gold_index]["surface"] != gold_surface:
            _error("gold_index", "does not identify gold_surface in top-32")
    elif gold_surface in {candidate["surface"] for candidate in top32["candidates"]}:
        _error("gold_index", "must be recorded when gold_surface is in top-32")

    oracle = record["oracle"]
    if not isinstance(oracle, Mapping) or set(oracle) != {"k", "hit"}:
        _error("oracle", "k and hit are required")
    if _require_integer(oracle["k"], "oracle.k") != PRODUCTION_TOP_K:
        _error("oracle.k", "must describe production top-6")
    oracle_hit = _require_bool(oracle["hit"], "oracle.hit")
    in_top6 = gold_surface in {candidate["surface"] for candidate in top6["candidates"]}
    if oracle_hit != in_top6:
        _error("oracle.hit", "does not match the production top-6 snapshot")

    split = record["split"]
    if split is not None:
        split = _require_string(split, "split")
        if split not in SPLITS:
            _error("split", "must be train, dev, or final-holdout")
    elif require_split:
        _error("split", "assignment is required")

    tier = _require_string(record["tier"], "tier")
    if tier not in {"A", "B", "C"}:
        _error("tier", "must be A, B, or C")
    automatic = _validate_tier_a_verification(
        record["tier_a_verification"], is_fixture=is_fixture
    )
    human_audit = _validate_sampled_human_audit(record["sampled_human_audit"])
    training_eligible = _require_bool(record["training_eligible"], "training_eligible")
    gold_candidate = top32["candidates"][gold_index] if gold_index is not None else None
    gold_has_exact_dictionary_path = gold_candidate is not None and all(
        segment["source_category"] in _EXACT_DICTIONARY_SEGMENT_SOURCES
        for segment in gold_candidate["segments"]
    )

    if tier == "A":
        if is_fixture or automatic["status"] != "passed":
            _error("tier_a_verification", "Tier A requires passed automatic verification")
        if gold_index is None:
            _error("gold_index", "Tier A requires a gold candidate in top-32")
        if not gold_has_exact_dictionary_path:
            _error(
                "gold_index",
                "Tier A gold path must contain only system/user dictionary segments",
            )
        if human_audit["selection"] == "selected" and human_audit["status"] == "rejected":
            _error("sampled_human_audit", "a rejected sampled audit cannot remain Tier A")
    elif training_eligible:
        _error("training_eligible", "only Tier A may be training eligible")

    if training_eligible:
        if is_fixture or converter_provenance["kind"] != REAL_RECORD_PROVENANCE:
            _error("training_eligible", "fixture provenance cannot enter training")
        if gold_index is None:
            _error("training_eligible", "training requires a gold candidate in top-32")
        if len(top32["candidates"]) < 2:
            _error("training_eligible", "training requires at least two candidates")
        if automatic["status"] != "passed":
            _error("training_eligible", "training requires passed automatic Tier A verification")
        if not gold_has_exact_dictionary_path:
            _error(
                "training_eligible",
                "training requires an exact system/user dictionary gold path",
            )
        if human_audit["selection"] == "selected" and human_audit["status"] != "accepted":
            _error("training_eligible", "a selected human audit must be accepted before training")

    if not is_fixture and not _has_verified_research_exporter(top32["exporter_run"]):
        _error(
            "candidate_snapshots.training_top32.exporter_run.verification_status",
            "top-32 remains blocked until an immutable research exporter identity is pinned",
        )

    normalized: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "stable_id": stable_id,
        "is_fixture": is_fixture,
        "source": source,
        "session": session,
        "converter_provenance": converter_provenance,
        "reading": reading,
        "gold_surface": gold_surface,
        "candidate_snapshots": {
            "training_top32": top32,
            "production_top6": top6,
        },
        "gold_index": gold_index,
        "oracle": {"k": PRODUCTION_TOP_K, "hit": oracle_hit},
        "split": split,
        "tier": tier,
        "tier_a_verification": automatic,
        "sampled_human_audit": human_audit,
        "training_eligible": training_eligible,
    }
    return json.loads(json.dumps(normalized, ensure_ascii=False, sort_keys=True))


def validate_records(
    records: Sequence[Mapping[str, Any]], *, require_split: bool = True
) -> list[dict[str, Any]]:
    if not records:
        raise ContractError("records: must not be empty")
    normalized = [
        validate_record(record, require_split=require_split) for record in records
    ]
    stable_ids = [record["stable_id"] for record in normalized]
    if len(stable_ids) != len(set(stable_ids)):
        raise ContractError("records.stable_id: values must be unique")
    return normalized


def read_jsonl(path: str | Path, *, require_split: bool = True) -> list[dict[str, Any]]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError(f"JSONL file: cannot read ({type(error).__name__})") from error
    if not lines:
        raise ContractError("JSONL file: must contain at least one record")
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ContractError(f"JSONL line {line_number}: blank lines are forbidden")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"JSONL line {line_number}: invalid JSON") from error
        if not isinstance(value, Mapping):
            raise ContractError(f"JSONL line {line_number}: record must be an object")
        records.append(value)
    return validate_records(records, require_split=require_split)
