"""Versioned, deterministic JSONL contracts for converter-labelled examples."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any


CONTRACT_SCHEMA_VERSION = 1
RECORD_TYPE = "training_example"
MAX_LEFT_CONTEXT_CHARS = 64
MAX_READING_CHARS = 128
MAX_SURFACE_CHARS = 256
TRAINING_TOP_K = 32
PRODUCTION_TOP_K = 6
REAL_CANDIDATE_SOURCE = "sakura_converter_full_reading_nbest"
FIXTURE_CANDIDATE_SOURCE = "fixture_full_reading_nbest"
SPLITS = ("train", "dev", "final-holdout")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_FORBIDDEN_CATEGORY_NAMES = frozenset({"synthetic", "guessed", "unknown"})


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


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _error(field, "must be boolean")
    return value


def _require_integer(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
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
    Path(path).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sentence_shingle_hashes(text: str, *, width: int = 3) -> list[str]:
    """Create privacy-preserving character-shingle hashes for near-duplicate checks.

    The splitter consumes only the hashes. The raw sentence is an input to this
    helper and is not written into leakage reports or generated artifacts.
    """

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


def _validate_date(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        _error(field, "must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        _error(field, "is not a calendar date")
    return value


def _validate_hash_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _error(field, "must be a non-empty list")
    normalized = [_require_sha256(item, f"{field}[{index}]") for index, item in enumerate(value)]
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
    snapshot_date = _validate_date(source["snapshot_date"], "source.snapshot_date")
    article_id = _require_identifier(source["article_id"], "source.article_id")
    page_id = _require_identifier(source["page_id"], "source.page_id")
    revision_id = _require_identifier(source["revision_id"], "source.revision_id")
    paragraph_hash = _require_sha256(source["paragraph_hash"], "source.paragraph_hash")
    sentence_hash = _require_sha256(source["sentence_hash"], "source.sentence_hash")
    sentence_hashes = _validate_hash_list(
        source["sentence_shingle_hashes"], "source.sentence_shingle_hashes"
    )
    template_cluster_id = source["template_cluster_id"]
    if template_cluster_id is not None:
        template_cluster_id = _require_identifier(
            template_cluster_id, "source.template_cluster_id"
        )
    return {
        "corpus": corpus,
        "snapshot_date": snapshot_date,
        "article_id": article_id,
        "page_id": page_id,
        "revision_id": revision_id,
        "paragraph_hash": paragraph_hash,
        "sentence_hash": sentence_hash,
        "sentence_shingle_hashes": sentence_hashes,
        "template_cluster_id": template_cluster_id,
    }


def _validate_session(session: Any) -> dict[str, str]:
    if not isinstance(session, Mapping):
        _error("session", "must be an object")
    expected = {"session_id", "left_context", "left_context_policy"}
    _reject_unknown_keys(session, expected, "session")
    if set(session) != expected:
        _error("session", "same-session context provenance is required")
    session_id = _require_identifier(session["session_id"], "session.session_id")
    left_context = _require_string(
        session["left_context"],
        "session.left_context",
        allow_empty=True,
        max_chars=MAX_LEFT_CONTEXT_CHARS,
    )
    policy = _require_string(session["left_context_policy"], "session.left_context_policy")
    if policy != "sakura_input_committed_same_session":
        _error("session.left_context_policy", "untrusted context source")
    return {
        "session_id": session_id,
        "left_context": left_context,
        "left_context_policy": policy,
    }


def _validate_candidate(candidate: Any, field: str, *, is_fixture: bool) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        _error(field, "must be an object")
    allowed = {"surface", "cost", "source_category", "fingerprint"}
    _reject_unknown_keys(candidate, allowed, field)
    required = {"surface", "cost", "source_category"}
    if not required.issubset(candidate):
        _error(field, "surface, cost, and source_category are required")
    surface = _require_string(
        candidate["surface"], f"{field}.surface", max_chars=MAX_SURFACE_CHARS
    )
    cost = _require_integer(candidate["cost"], f"{field}.cost", maximum=2**32 - 1)
    category = _require_string(candidate["source_category"], f"{field}.source_category").lower()
    if _CATEGORY_RE.fullmatch(category) is None:
        _error(f"{field}.source_category", "must be a bounded source category")
    if is_fixture:
        if category != "fixture":
            _error(f"{field}.source_category", "fixture records must say fixture")
    elif category in _FORBIDDEN_CATEGORY_NAMES:
        _error(f"{field}.source_category", "guessed or synthetic provenance is forbidden")
    result: dict[str, Any] = {
        "surface": surface,
        "cost": cost,
        "source_category": category,
    }
    if "fingerprint" in candidate:
        fingerprint = candidate["fingerprint"]
        if isinstance(fingerprint, bool):
            _error(f"{field}.fingerprint", "must be a u64 integer or 16-digit hex")
        if isinstance(fingerprint, int):
            _require_integer(fingerprint, f"{field}.fingerprint", maximum=2**64 - 1)
        elif isinstance(fingerprint, str):
            if re.fullmatch(r"[0-9a-f]{16}", fingerprint) is None:
                _error(f"{field}.fingerprint", "must be lowercase 16-digit hex")
        else:
            _error(f"{field}.fingerprint", "must be a u64 integer or 16-digit hex")
        result["fingerprint"] = fingerprint
    return result


def _candidate_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    payload = {
        "limit": snapshot["limit"],
        "source": snapshot["source"],
        "sakura_input_head": snapshot["sakura_input_head"],
        "dictionary_sha256": snapshot["dictionary_sha256"],
        "reading": snapshot["reading"],
        "candidates": snapshot["candidates"],
    }
    return canonical_json_hash(payload)


def _validate_snapshot(
    snapshot: Any,
    field: str,
    *,
    limit: int,
    reading: str,
    is_fixture: bool,
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        _error(field, "must be an object")
    expected = {
        "limit",
        "source",
        "sakura_input_head",
        "dictionary_sha256",
        "reading",
        "candidates",
        "content_sha256",
    }
    _reject_unknown_keys(snapshot, expected, field)
    if set(snapshot) != expected:
        _error(field, "snapshot identity, candidates, and content hash are required")
    if _require_integer(snapshot["limit"], f"{field}.limit") != limit:
        _error(f"{field}.limit", "does not match the contract bound")
    source = _require_string(snapshot["source"], f"{field}.source")
    expected_source = FIXTURE_CANDIDATE_SOURCE if is_fixture else REAL_CANDIDATE_SOURCE
    if source != expected_source:
        _error(f"{field}.source", "does not prove actual converter N-best provenance")
    head = _require_string(snapshot["sakura_input_head"], f"{field}.sakura_input_head")
    if _GIT_SHA_RE.fullmatch(head) is None:
        _error(f"{field}.sakura_input_head", "must be a lowercase Git SHA-1")
    dictionary_sha256 = _require_sha256(
        snapshot["dictionary_sha256"], f"{field}.dictionary_sha256"
    )
    snapshot_reading = _require_string(
        snapshot["reading"], f"{field}.reading", max_chars=MAX_READING_CHARS
    )
    if snapshot_reading != reading:
        _error(f"{field}.reading", "does not match the example reading")
    candidates = snapshot["candidates"]
    if not isinstance(candidates, list) or not candidates or len(candidates) > limit:
        _error(f"{field}.candidates", "must be a non-empty list within its limit")
    normalized_candidates = [
        _validate_candidate(candidate, f"{field}.candidates[{index}]", is_fixture=is_fixture)
        for index, candidate in enumerate(candidates)
    ]
    surfaces = [candidate["surface"] for candidate in normalized_candidates]
    if len(surfaces) != len(set(surfaces)):
        _error(f"{field}.candidates", "candidate surfaces must be unique")
    content_sha256 = _require_sha256(snapshot["content_sha256"], f"{field}.content_sha256")
    normalized = {
        "limit": limit,
        "source": source,
        "sakura_input_head": head,
        "dictionary_sha256": dictionary_sha256,
        "reading": reading,
        "candidates": normalized_candidates,
        "content_sha256": content_sha256,
    }
    if content_sha256 != _candidate_snapshot_hash(normalized):
        _error(f"{field}.content_sha256", "does not match canonical snapshot content")
    return normalized


def _validate_human_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("human_audit", "must be an object")
    allowed = {
        "status",
        "dictionary_unique_reading",
        "forward_conversion_matches",
        "noise_free",
        "reviewer_id",
        "reviewed_at",
    }
    _reject_unknown_keys(value, allowed, "human_audit")
    required = {
        "status",
        "dictionary_unique_reading",
        "forward_conversion_matches",
        "noise_free",
    }
    if not required.issubset(value):
        _error("human_audit", "annotation flags are required")
    status = _require_string(value["status"], "human_audit.status")
    if status not in {"accepted", "needs_review", "rejected", "not_applicable"}:
        _error("human_audit.status", "unsupported annotation status")
    result: dict[str, Any] = {
        "status": status,
        "dictionary_unique_reading": _require_bool(
            value["dictionary_unique_reading"], "human_audit.dictionary_unique_reading"
        ),
        "forward_conversion_matches": _require_bool(
            value["forward_conversion_matches"], "human_audit.forward_conversion_matches"
        ),
        "noise_free": _require_bool(value["noise_free"], "human_audit.noise_free"),
    }
    if "reviewer_id" in value:
        result["reviewer_id"] = _require_identifier(value["reviewer_id"], "human_audit.reviewer_id")
    if "reviewed_at" in value:
        result["reviewed_at"] = _require_string(value["reviewed_at"], "human_audit.reviewed_at")
    return result


def validate_record(record: Mapping[str, Any], *, require_split: bool = True) -> dict[str, Any]:
    """Validate one JSONL training-example record and return a normalized copy."""

    if not isinstance(record, Mapping):
        raise ContractError("record: must be a JSON object")
    expected = {
        "schema_version",
        "record_type",
        "stable_id",
        "is_fixture",
        "source",
        "session",
        "reading",
        "gold_surface",
        "candidate_snapshots",
        "gold_index",
        "oracle",
        "split",
        "tier",
        "human_audit",
        "training_eligible",
    }
    _reject_unknown_keys(record, expected, "record")
    if set(record) != expected:
        _error("record", "all contract fields are required")
    if isinstance(record["schema_version"], bool) or record["schema_version"] != CONTRACT_SCHEMA_VERSION:
        _error("schema_version", "unsupported contract version")
    if record["record_type"] != RECORD_TYPE:
        _error("record_type", "unsupported record type")
    stable_id = _require_identifier(record["stable_id"], "stable_id")
    is_fixture = _require_bool(record["is_fixture"], "is_fixture")
    source = _validate_source(record["source"], is_fixture=is_fixture)
    session = _validate_session(record["session"])
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
    )
    top6 = _validate_snapshot(
        snapshots["production_top6"],
        "candidate_snapshots.production_top6",
        limit=PRODUCTION_TOP_K,
        reading=reading,
        is_fixture=is_fixture,
    )
    for key in ("source", "sakura_input_head", "dictionary_sha256", "reading"):
        if top32[key] != top6[key]:
            _error(f"candidate_snapshots.production_top6.{key}", "does not match top-32 identity")
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
    if not isinstance(oracle, Mapping):
        _error("oracle", "must be an object")
    if set(oracle) != {"k", "hit"}:
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
    human_audit = _validate_human_audit(record["human_audit"])
    training_eligible = _require_bool(record["training_eligible"], "training_eligible")
    if is_fixture and training_eligible:
        _error("training_eligible", "fixture records cannot be training data")
    if tier == "A":
        for key in (
            "dictionary_unique_reading",
            "forward_conversion_matches",
            "noise_free",
        ):
            if human_audit[key] is not True:
                _error(f"human_audit.{key}", "Tier A requires a positive verified flag")
        if human_audit["status"] != "accepted":
            _error("human_audit.status", "Tier A requires accepted human audit")
        if not is_fixture and not training_eligible:
            _error("training_eligible", "verified Tier A must be trainable")
    elif training_eligible:
        _error("training_eligible", "only Tier A may be training eligible")

    normalized: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "stable_id": stable_id,
        "is_fixture": is_fixture,
        "source": source,
        "session": session,
        "reading": reading,
        "gold_surface": gold_surface,
        "candidate_snapshots": {"training_top32": top32, "production_top6": top6},
        "gold_index": gold_index,
        "oracle": {"k": PRODUCTION_TOP_K, "hit": oracle_hit},
        "split": split,
        "tier": tier,
        "human_audit": human_audit,
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
