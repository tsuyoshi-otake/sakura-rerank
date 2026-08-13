"""Fail-closed contracts for the v5 symmetric blind teacher screen.

The v4 cascade asked a second teacher only about rows rejected by the first
teacher.  This module deliberately makes the two passes symmetric: every
provisional Tier A row is shown, in the same stable-ID order, to two distinct
AI-teacher identities.  Neither queue contains split information, earlier
verdicts, notes, or historical labels.

Queue and bucket artifacts contain research text and remain generated data.
Their manifests and reports contain aggregate counts and cryptographic
commitments only.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_atomic
from .contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    validate_records,
)
from .corpus_v4 import (
    GATE_A_REVIEWER_ID,
    build_gate_a_teacher_batches,
    publish_teacher_queue_directory,
    validate_gate_a_teacher_queue_binding,
)
from .human_audit import (
    VERDICTS,
    select_audit_records,
    validate_audit_queue,
    validate_queue_manifest,
)
from .splitter import SplitError, assign_splits
from .tier_a import TierAError


V5_SCHEMA_VERSION = 1
V5_QUEUE_SCHEMA_VERSION = 3
V5_QUEUE_RECORD_TYPE = "tier_a_v5_blind_queue_row"
V5_VERDICT_RECORD_TYPE = "tier_a_v5_teacher_verdict_batch"
V5_QUEUE_MANIFEST_KIND = "tier_a_v5_blind_teacher_queue"
V5_PARTITION_REPORT_KIND = "tier_a_v5_admissibility_partition"
V5_QUEUE_ALGORITHM = "full_stable_id_order_blind_batches_v1"
V5_PARTITION_ALGORITHM = "two_full_blind_passes_precedence_v1"
V5_GATE_A_PROVENANCE_KIND = "tier_a_v5_gate_a_source_provenance"
V5_GATE_A_QUEUE_MANIFEST_KIND = "tier_a_v5_gate_a_teacher_queue"

FIRST_PASS = "first_screen"
CONFIRMATION_PASS = "blind_confirmation"
PASS_NAMES = (FIRST_PASS, CONFIRMATION_PASS)
REVIEWER_KIND = "ai_teacher"

MAX_RECORDS = 1_000_000
MAX_BATCH_ITEMS = 40
MAX_BATCHES = 100_000
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_NOTE_CHARS = 200
V5_SPLIT_SEED = 20260811
V5_SPLIT_RATIOS = {"train": 0.70, "dev": 0.10, "final-holdout": 0.20}
V5_GATE_A_AUDIT_SEED = 20260812
V5_GATE_A_MINIMUM_SAMPLE_SIZE = 3_000

_DIRECTORY_PUBLISH_MAX_ATTEMPTS = 8
_DIRECTORY_PUBLISH_INITIAL_BACKOFF_SECONDS = 0.05
_DIRECTORY_PUBLISH_MAX_BACKOFF_SECONDS = 1.0
_WINDOWS_TRANSIENT_REPLACE_ERRORS = frozenset({5, 32})

ELIGIBLE_BUCKET = "eligible_unanimous_valid"
AMBIGUOUS_BUCKET = "intrinsic_surface_ambiguity"
REPAIRABLE_BUCKET = "repairable_label_error"
NOISE_BUCKET = "extraction_noise"
UNRESOLVED_BUCKET = "unresolved_disagreement"
BUCKETS = (
    ELIGIBLE_BUCKET,
    AMBIGUOUS_BUCKET,
    REPAIRABLE_BUCKET,
    NOISE_BUCKET,
    UNRESOLVED_BUCKET,
)

_WRONG_LABEL_VERDICTS = frozenset(
    {"wrong_reading", "wrong_segmentation", "wrong_gold_surface"}
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BATCH_FILE = re.compile(r"batch-([0-9]{3,})\.json")
_VERDICT_FILE = re.compile(r"verdicts-([0-9]{3,})\.json")


def _fail(message: str) -> None:
    raise TierAError(f"corpus v5: {message}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"{field} is not a bounded identifier")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{field} is not a lowercase SHA-256")
    return value


def _canonical_payload(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _canonical_jsonl_hash(records: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(canonical_json_bytes(record))
        digest.update(b"\n")
    return digest.hexdigest()


def _rename_directory_without_overwrite(source: Path, target: Path) -> None:
    """Atomically publish on Windows only when no target directory exists."""

    # Windows ``rename`` fails if target exists, unlike ``replace``.  This
    # closes the target-existence race between the precheck and the final move.
    os.rename(source, target)


def _is_transient_windows_rename_error(error: OSError) -> bool:
    """Return whether Windows may release a locked directory shortly."""

    return getattr(error, "winerror", None) in _WINDOWS_TRANSIENT_REPLACE_ERRORS


def _directory_publish_retry_delay(attempt: int) -> float:
    """Bound exponential backoff and jitter for a transient directory lock."""

    maximum = min(
        _DIRECTORY_PUBLISH_INITIAL_BACKOFF_SECONDS * (2**attempt),
        _DIRECTORY_PUBLISH_MAX_BACKOFF_SECONDS,
    )
    return min(
        _DIRECTORY_PUBLISH_MAX_BACKOFF_SECONDS,
        maximum + random.uniform(0.0, maximum),
    )


def _publish_directory_atomically(
    temporary: Path,
    target: Path,
    *,
    immutable_message: str,
) -> None:
    """Move a complete temporary directory without replacing an existing target.

    Windows virus scanners and indexers can briefly retain a directory handle
    after its final file is closed.  Only the corresponding transient Windows
    access/sharing failures are retried; every other error remains observable
    to the caller immediately.
    """

    for attempt in range(_DIRECTORY_PUBLISH_MAX_ATTEMPTS):
        if target.exists():
            _fail(immutable_message)
        try:
            _rename_directory_without_overwrite(temporary, target)
        except OSError as error:
            if not _is_transient_windows_rename_error(error):
                raise
            if attempt + 1 == _DIRECTORY_PUBLISH_MAX_ATTEMPTS:
                raise
            time.sleep(_directory_publish_retry_delay(attempt))
        else:
            return

    raise AssertionError("bounded directory publication loop reached no terminal state")


def _strict_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
        or not records
        or len(records) > MAX_RECORDS
    ):
        _fail("records are empty or outside the bound")
    try:
        normalized = validate_records(records, require_split=False)
    except ContractError as error:
        raise TierAError(f"corpus v5: records: {error}") from error
    if any(record.get("is_fixture") for record in normalized):
        _fail("fixture records cannot enter blind teacher review")
    return sorted(normalized, key=lambda record: record["stable_id"])


def _reading_bucket(length: int) -> str:
    if length <= 9:
        return "reading-03-09"
    if length <= 30:
        return "reading-10-30"
    return "reading-31-128"


def _candidate_bucket(count: int) -> str:
    if count <= 6:
        return "candidates-02-06"
    if count <= 16:
        return "candidates-07-16"
    return "candidates-17-32"


def _stratum(record: Mapping[str, Any]) -> str:
    candidates = record["candidate_snapshots"]["training_top32"]["candidates"]
    local = "local-correct" if record["gold_index"] == 0 else "local-wrong"
    return "/".join(
        (_reading_bucket(len(record["reading"])), _candidate_bucket(len(candidates)), local)
    )


def _queue_item(record: Mapping[str, Any]) -> dict[str, Any]:
    top32 = record["candidate_snapshots"]["training_top32"]["candidates"]
    top6 = record["candidate_snapshots"]["production_top6"]["candidates"]
    gold = top32[record["gold_index"]]
    return {
        "schema_version": V5_QUEUE_SCHEMA_VERSION,
        "record_type": V5_QUEUE_RECORD_TYPE,
        "stable_id": record["stable_id"],
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


def _validate_queue_item(item: Any) -> dict[str, Any]:
    fields = {
        "schema_version",
        "record_type",
        "stable_id",
        "stratum",
        "source",
        "left_context",
        "reading",
        "gold_surface",
        "gold_index",
        "gold_segments",
        "production_candidates",
    }
    if not isinstance(item, Mapping) or set(item) != fields:
        _fail("queue item fields do not match the blind schema")
    if (
        item.get("schema_version") != V5_QUEUE_SCHEMA_VERSION
        or item.get("record_type") != V5_QUEUE_RECORD_TYPE
    ):
        _fail("queue item schema is unsupported")
    _identifier(item.get("stable_id"), "queue stable_id")
    stratum = item.get("stratum")
    if not isinstance(stratum, str) or not stratum or len(stratum) > 128:
        _fail("queue stratum is invalid")
    source = item.get("source")
    if not isinstance(source, Mapping) or set(source) != {"page_id", "revision_id"}:
        _fail("queue source is invalid")
    for name in ("page_id", "revision_id"):
        _identifier(source.get(name), f"queue source.{name}")
    for name, maximum, allow_empty in (
        ("left_context", 64, True),
        ("reading", 128, False),
        ("gold_surface", 256, False),
    ):
        value = item.get(name)
        if (
            not isinstance(value, str)
            or (not allow_empty and not value)
            or len(value) > maximum
            or any(character in value for character in "\0\r\n")
        ):
            _fail(f"queue {name} is invalid")
    if type(item.get("gold_index")) is not int or item["gold_index"] < 0:
        _fail("queue gold_index is invalid")
    segments = item.get("gold_segments")
    if not isinstance(segments, list) or not segments:
        _fail("queue gold_segments are invalid")
    candidates = item.get("production_candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 6:
        _fail("queue production candidates are invalid")
    for expected_rank, candidate in enumerate(candidates):
        if (
            not isinstance(candidate, Mapping)
            or set(candidate) != {"rank", "surface"}
            or candidate.get("rank") != expected_rank
            or not isinstance(candidate.get("surface"), str)
            or not candidate["surface"]
            or len(candidate["surface"]) > 256
            or any(character in candidate["surface"] for character in "\0\r\n")
        ):
            _fail("queue production candidate is invalid")
    try:
        canonical_json_bytes(item)
    except (TypeError, ValueError) as error:
        raise TierAError("corpus v5: queue item is not canonicalizable") from error
    return json.loads(json.dumps(item, ensure_ascii=False, sort_keys=True))


def validate_blind_teacher_batches(
    batches: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if (
        not isinstance(batches, Sequence)
        or isinstance(batches, (str, bytes))
        or not batches
        or len(batches) > MAX_BATCHES
    ):
        _fail("batches are empty or outside the bound")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for expected_index, batch in enumerate(batches):
        if (
            not isinstance(batch, Mapping)
            or set(batch) != {"batch_index", "items"}
            or batch.get("batch_index") != expected_index
        ):
            _fail("batch indexes must be contiguous and exact")
        items = batch.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
            _fail("batch item count is outside the bound")
        checked = [_validate_queue_item(item) for item in items]
        identifiers = [item["stable_id"] for item in checked]
        if (
            identifiers != sorted(identifiers)
            or len(identifiers) != len(set(identifiers))
            or seen.intersection(identifiers)
        ):
            _fail("queue stable IDs must be globally unique and ordered")
        seen.update(identifiers)
        normalized.append({"batch_index": expected_index, "items": checked})
    if len(seen) > MAX_RECORDS:
        _fail("queue record count is outside the bound")
    return normalized


def build_blind_teacher_batches(
    records: Sequence[Mapping[str, Any]], *, batch_size: int = MAX_BATCH_ITEMS
) -> list[dict[str, Any]]:
    """Build a complete pre-split queue with no prior-review information."""

    normalized = _strict_records(records)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_ITEMS:
        _fail("batch_size is outside the bound")
    items = [_queue_item(record) for record in normalized]
    return validate_blind_teacher_batches(
        [
            {"batch_index": index, "items": items[start : start + batch_size]}
            for index, start in enumerate(range(0, len(items), batch_size))
        ]
    )


def _validate_pass_identity(pass_name: Any, reviewer_id: Any) -> tuple[str, str]:
    if pass_name not in PASS_NAMES:
        _fail("pass_name is unsupported")
    return pass_name, _identifier(reviewer_id, "reviewer_id")


def build_blind_queue_manifest(
    records: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
    *,
    pass_name: str,
    reviewer_id: str,
) -> dict[str, Any]:
    normalized_records = _strict_records(records)
    normalized_batches = validate_blind_teacher_batches(batches)
    pass_name, reviewer_id = _validate_pass_identity(pass_name, reviewer_id)
    expected_items = [_queue_item(record) for record in normalized_records]
    items = [item for batch in normalized_batches for item in batch["items"]]
    if items != expected_items:
        _fail("blind queue does not bind the source dataset exactly")
    batch_files = []
    for batch in normalized_batches:
        payload = _canonical_payload(batch)
        batch_files.append(
            {
                "name": f"batch-{batch['batch_index']:03d}.json",
                "item_count": len(batch["items"]),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schema_version": V5_SCHEMA_VERSION,
        "manifest_kind": V5_QUEUE_MANIFEST_KIND,
        "algorithm": V5_QUEUE_ALGORITHM,
        "pass_name": pass_name,
        "reviewer_kind": REVIEWER_KIND,
        "reviewer_id": reviewer_id,
        "batch_size_limit": MAX_BATCH_ITEMS,
        "batch_count": len(normalized_batches),
        "source_dataset_record_count": len(normalized_records),
        "source_dataset_content_sha256": _canonical_jsonl_hash(normalized_records),
        "record_count": len(items),
        "content_sha256": _canonical_jsonl_hash(items),
        "batch_files": batch_files,
        "prior_verdicts_visible": False,
        "prior_notes_visible": False,
        "historical_labels_visible": False,
        "raw_text_in_manifest": False,
    }


def validate_blind_teacher_queue_binding(
    records: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(manifest, Mapping):
        _fail("queue manifest must be an object")
    expected = build_blind_queue_manifest(
        records,
        batches,
        pass_name=manifest.get("pass_name"),
        reviewer_id=manifest.get("reviewer_id"),
    )
    if dict(manifest) != expected:
        _fail("queue manifest does not bind the source dataset exactly")
    return validate_blind_teacher_batches(batches)


def publish_blind_teacher_queue_directory(
    directory: str | Path,
    records: Sequence[Mapping[str, Any]],
    *,
    pass_name: str,
    reviewer_id: str,
    batch_size: int = MAX_BATCH_ITEMS,
) -> dict[str, Any]:
    """Atomically publish one immutable complete blind-pass queue directory."""

    target = Path(directory)
    if target.exists():
        _fail("queue directory already exists and is immutable")
    if not target.parent.is_dir():
        _fail("queue parent directory does not exist")
    batches = build_blind_teacher_batches(records, batch_size=batch_size)
    manifest = build_blind_queue_manifest(
        records, batches, pass_name=pass_name, reviewer_id=reviewer_id
    )
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for batch in batches:
            write_bytes_atomic(
                temporary / f"batch-{batch['batch_index']:03d}.json",
                _canonical_payload(batch),
            )
        write_bytes_atomic(temporary / "manifest.json", _canonical_payload(manifest))
        _publish_directory_atomically(
            temporary,
            target,
            immutable_message="queue directory already exists and is immutable",
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def _read_canonical_json(path: Path, maximum_bytes: int) -> Any:
    try:
        payload = path.read_bytes()
    except OSError as error:
        _fail(f"cannot read {path.name} ({type(error).__name__})")
    if not payload or len(payload) > maximum_bytes:
        _fail(f"{path.name} is empty or outside the byte bound")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{path.name} is not UTF-8 JSON ({type(error).__name__})")
    if payload != _canonical_payload(value):
        _fail(f"{path.name} is not canonical JSON with LF")
    return value


def _validate_manifest_intrinsic(manifest: Any) -> dict[str, Any]:
    fields = {
        "schema_version",
        "manifest_kind",
        "algorithm",
        "pass_name",
        "reviewer_kind",
        "reviewer_id",
        "batch_size_limit",
        "batch_count",
        "source_dataset_record_count",
        "source_dataset_content_sha256",
        "record_count",
        "content_sha256",
        "batch_files",
        "prior_verdicts_visible",
        "prior_notes_visible",
        "historical_labels_visible",
        "raw_text_in_manifest",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != fields:
        _fail("queue manifest fields do not match schema")
    if (
        manifest.get("schema_version") != V5_SCHEMA_VERSION
        or manifest.get("manifest_kind") != V5_QUEUE_MANIFEST_KIND
        or manifest.get("algorithm") != V5_QUEUE_ALGORITHM
        or manifest.get("reviewer_kind") != REVIEWER_KIND
        or manifest.get("batch_size_limit") != MAX_BATCH_ITEMS
        or manifest.get("prior_verdicts_visible") is not False
        or manifest.get("prior_notes_visible") is not False
        or manifest.get("historical_labels_visible") is not False
        or manifest.get("raw_text_in_manifest") is not False
    ):
        _fail("queue manifest values are invalid")
    _validate_pass_identity(manifest.get("pass_name"), manifest.get("reviewer_id"))
    for name in ("batch_count", "source_dataset_record_count", "record_count"):
        value = manifest.get(name)
        if type(value) is not int or not 1 <= value <= MAX_RECORDS:
            _fail(f"queue manifest {name} is outside the bound")
    if manifest["batch_count"] > MAX_BATCHES:
        _fail("queue manifest batch_count is outside the bound")
    if manifest["source_dataset_record_count"] != manifest["record_count"]:
        _fail("blind queue must cover the complete source dataset")
    _sha256(manifest.get("source_dataset_content_sha256"), "source dataset hash")
    _sha256(manifest.get("content_sha256"), "queue content hash")
    files = manifest.get("batch_files")
    if not isinstance(files, list) or len(files) != manifest["batch_count"]:
        _fail("queue manifest batch files are invalid")
    for index, entry in enumerate(files):
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"name", "item_count", "content_sha256"}
            or entry.get("name") != f"batch-{index:03d}.json"
            or type(entry.get("item_count")) is not int
            or not 1 <= entry["item_count"] <= MAX_BATCH_ITEMS
        ):
            _fail("queue manifest batch entry is invalid")
        _sha256(entry.get("content_sha256"), "queue batch hash")
    return dict(manifest)


def read_blind_teacher_queue_directory(
    directory: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        _fail("queue directory is missing")
    try:
        names = {entry.name for entry in root.iterdir()}
    except OSError as error:
        _fail(f"cannot list queue directory ({type(error).__name__})")
    if "manifest.json" not in names or any(
        name != "manifest.json" and _BATCH_FILE.fullmatch(name) is None
        for name in names
    ):
        _fail("queue directory contains unexpected files")
    manifest = _validate_manifest_intrinsic(
        _read_canonical_json(root / "manifest.json", MAX_MANIFEST_BYTES)
    )
    expected_names = {"manifest.json"}
    batches: list[dict[str, Any]] = []
    for index, entry in enumerate(manifest["batch_files"]):
        name = f"batch-{index:03d}.json"
        expected_names.add(name)
        batch = _read_canonical_json(root / name, MAX_BATCH_BYTES)
        payload = _canonical_payload(batch)
        if hashlib.sha256(payload).hexdigest() != entry["content_sha256"]:
            _fail("queue batch hash mismatch")
        batches.append(batch)
    if names != expected_names:
        _fail("queue directory file set does not match manifest")
    normalized = validate_blind_teacher_batches(batches)
    items = [item for batch in normalized for item in batch["items"]]
    if (
        len(items) != manifest["record_count"]
        or sum(entry["item_count"] for entry in manifest["batch_files"])
        != manifest["record_count"]
        or _canonical_jsonl_hash(items) != manifest["content_sha256"]
    ):
        _fail("queue manifest count or content hash mismatch")
    return normalized, manifest


def validate_blind_teacher_verdict_batch(
    batch: Mapping[str, Any],
    verdict_payload: Mapping[str, Any],
    *,
    reviewer_id: str,
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "record_type",
        "batch_index",
        "reviewer_kind",
        "reviewer_id",
        "verdicts",
    }
    reviewer_id = _identifier(reviewer_id, "reviewer_id")
    if not isinstance(verdict_payload, Mapping) or set(verdict_payload) != expected:
        _fail("verdict fields do not match schema")
    if (
        verdict_payload.get("schema_version") != V5_SCHEMA_VERSION
        or verdict_payload.get("record_type") != V5_VERDICT_RECORD_TYPE
        or verdict_payload.get("batch_index") != batch.get("batch_index")
        or verdict_payload.get("reviewer_kind") != REVIEWER_KIND
        or verdict_payload.get("reviewer_id") != reviewer_id
    ):
        _fail("verdict batch provenance does not match queue")
    entries = verdict_payload.get("verdicts")
    items = batch.get("items")
    if not isinstance(entries, list) or not isinstance(items, list) or len(entries) != len(items):
        _fail("verdict coverage does not match batch")
    checked: list[dict[str, str]] = []
    for item, entry in zip(items, entries, strict=True):
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"stable_id", "verdict", "note"}
            or entry.get("stable_id") != item.get("stable_id")
        ):
            _fail("verdict stable IDs must exactly match queue order")
        if entry.get("verdict") not in VERDICTS:
            _fail("verdict enum is invalid")
        note = entry.get("note")
        if (
            not isinstance(note, str)
            or len(note) > MAX_NOTE_CHARS
            or any(character in note for character in "\0\r\n")
        ):
            _fail("verdict note is invalid")
        checked.append(dict(entry))
    return {
        "schema_version": V5_SCHEMA_VERSION,
        "record_type": V5_VERDICT_RECORD_TYPE,
        "batch_index": batch["batch_index"],
        "reviewer_kind": REVIEWER_KIND,
        "reviewer_id": reviewer_id,
        "verdicts": checked,
    }


def scan_blind_verdict_directory(
    queue_directory: str | Path, verdict_directory: str | Path
) -> tuple[dict[int, dict[str, Any]], list[int]]:
    """Validate every present verdict file; absent expected files are resumable."""

    batches, manifest = read_blind_teacher_queue_directory(queue_directory)
    root = Path(verdict_directory)
    if not root.exists():
        return {}, list(range(len(batches)))
    if not root.is_dir():
        _fail("verdict directory is not a directory")
    try:
        names = {entry.name for entry in root.iterdir()}
    except OSError as error:
        _fail(f"cannot list verdict directory ({type(error).__name__})")
    expected_names = {f"verdicts-{index:03d}.json" for index in range(len(batches))}
    if any(_VERDICT_FILE.fullmatch(name) is None for name in names) or names - expected_names:
        _fail("verdict directory contains unexpected files")
    completed: dict[int, dict[str, Any]] = {}
    pending: list[int] = []
    for batch in batches:
        index = batch["batch_index"]
        path = root / f"verdicts-{index:03d}.json"
        if not path.exists():
            pending.append(index)
            continue
        value = _read_canonical_json(path, MAX_BATCH_BYTES)
        completed[index] = validate_blind_teacher_verdict_batch(
            batch, value, reviewer_id=manifest["reviewer_id"]
        )
    return completed, pending


def _complete_verdicts(
    batches: Sequence[Mapping[str, Any]],
    verdicts: Mapping[int, Mapping[str, Any]],
    *,
    reviewer_id: str,
) -> tuple[dict[str, str], str]:
    normalized_batches = validate_blind_teacher_batches(batches)
    if not isinstance(verdicts, Mapping) or set(verdicts) != set(range(len(normalized_batches))):
        _fail("verdicts must cover every batch exactly")
    by_id: dict[str, str] = {}
    state_rows: list[dict[str, Any]] = []
    for batch in normalized_batches:
        checked = validate_blind_teacher_verdict_batch(
            batch,
            verdicts[batch["batch_index"]],
            reviewer_id=reviewer_id,
        )
        for entry in checked["verdicts"]:
            if entry["stable_id"] in by_id:
                _fail("verdict state contains duplicate stable IDs")
            by_id[entry["stable_id"]] = entry["verdict"]
            state_rows.append(
                {
                    "stable_id": entry["stable_id"],
                    "batch_index": batch["batch_index"],
                    "reviewer_kind": REVIEWER_KIND,
                    "reviewer_id": reviewer_id,
                    "verdict": entry["verdict"],
                    "note": entry["note"],
                }
            )
    return by_id, _canonical_jsonl_hash(state_rows)


def _bucket(first: str, confirmation: str) -> str:
    pair = {first, confirmation}
    if "extraction_noise" in pair:
        return NOISE_BUCKET
    if pair.intersection(_WRONG_LABEL_VERDICTS):
        return REPAIRABLE_BUCKET
    if "ambiguous" in pair:
        return AMBIGUOUS_BUCKET
    if first == confirmation == "valid":
        return ELIGIBLE_BUCKET
    _fail("validated verdict pair has no explicit terminal bucket")


def partition_blind_teacher_passes(
    records: Sequence[Mapping[str, Any]],
    first_batches: Sequence[Mapping[str, Any]],
    first_manifest: Mapping[str, Any],
    first_verdicts: Mapping[int, Mapping[str, Any]],
    confirmation_batches: Sequence[Mapping[str, Any]],
    confirmation_manifest: Mapping[str, Any],
    confirmation_verdicts: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Partition only after two distinct, complete, dataset-bound blind passes."""

    normalized_records = _strict_records(records)
    normalized_first = validate_blind_teacher_queue_binding(
        normalized_records, first_batches, first_manifest
    )
    normalized_confirmation = validate_blind_teacher_queue_binding(
        normalized_records, confirmation_batches, confirmation_manifest
    )
    if first_manifest.get("pass_name") != FIRST_PASS:
        _fail("first queue is not the first_screen pass")
    if confirmation_manifest.get("pass_name") != CONFIRMATION_PASS:
        _fail("confirmation queue is not the blind_confirmation pass")
    first_reviewer = first_manifest["reviewer_id"]
    confirmation_reviewer = confirmation_manifest["reviewer_id"]
    if first_reviewer == confirmation_reviewer:
        _fail("blind passes require distinct reviewer identities")
    if normalized_first != normalized_confirmation:
        _fail("blind passes must expose exactly the same queue rows and order")
    first_by_id, first_state_hash = _complete_verdicts(
        normalized_first, first_verdicts, reviewer_id=first_reviewer
    )
    confirmation_by_id, confirmation_state_hash = _complete_verdicts(
        normalized_confirmation,
        confirmation_verdicts,
        reviewer_id=confirmation_reviewer,
    )
    identifiers = [record["stable_id"] for record in normalized_records]
    if set(first_by_id) != set(identifiers) or set(confirmation_by_id) != set(identifiers):
        _fail("blind verdict coverage does not equal the source dataset")

    buckets = {name: [] for name in BUCKETS}
    pair_counts: Counter[str] = Counter()
    for record in normalized_records:
        identifier = record["stable_id"]
        first = first_by_id[identifier]
        confirmation = confirmation_by_id[identifier]
        terminal = _bucket(first, confirmation)
        buckets[terminal].append(record)
        pair_counts[f"{first}/{confirmation}"] += 1

    bucket_summary = {
        name: {
            "record_count": len(buckets[name]),
            "content_sha256": _canonical_jsonl_hash(buckets[name]),
        }
        for name in BUCKETS
    }
    if sum(entry["record_count"] for entry in bucket_summary.values()) != len(normalized_records):
        _fail("bucket counts do not reconcile with the source dataset")
    report = {
        "schema_version": V5_SCHEMA_VERSION,
        "report_kind": V5_PARTITION_REPORT_KIND,
        "algorithm": V5_PARTITION_ALGORITHM,
        "source_dataset_record_count": len(normalized_records),
        "source_dataset_content_sha256": _canonical_jsonl_hash(normalized_records),
        "passes": {
            FIRST_PASS: {
                "reviewer_kind": REVIEWER_KIND,
                "reviewer_id": first_reviewer,
                "queue_manifest_content_sha256": hashlib.sha256(
                    _canonical_payload(first_manifest)
                ).hexdigest(),
                "queue_content_sha256": first_manifest["content_sha256"],
                "verdict_state_content_sha256": first_state_hash,
                "record_count": len(first_by_id),
            },
            CONFIRMATION_PASS: {
                "reviewer_kind": REVIEWER_KIND,
                "reviewer_id": confirmation_reviewer,
                "queue_manifest_content_sha256": hashlib.sha256(
                    _canonical_payload(confirmation_manifest)
                ).hexdigest(),
                "queue_content_sha256": confirmation_manifest["content_sha256"],
                "verdict_state_content_sha256": confirmation_state_hash,
                "record_count": len(confirmation_by_id),
            },
        },
        "verdict_pair_counts": dict(sorted(pair_counts.items())),
        "buckets": bucket_summary,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
        "raw_notes_in_report": False,
    }
    return buckets, _validate_partition_report_intrinsic(report)


def _validate_partition_report_intrinsic(report: Any) -> dict[str, Any]:
    """Validate every aggregate commitment before an evidence report is published."""

    report_fields = {
        "schema_version",
        "report_kind",
        "algorithm",
        "source_dataset_record_count",
        "source_dataset_content_sha256",
        "passes",
        "verdict_pair_counts",
        "buckets",
        "raw_text_in_report",
        "raw_stable_ids_in_report",
        "raw_notes_in_report",
    }
    if (
        not isinstance(report, Mapping)
        or set(report) != report_fields
        or report.get("schema_version") != V5_SCHEMA_VERSION
        or report.get("report_kind") != V5_PARTITION_REPORT_KIND
        or report.get("algorithm") != V5_PARTITION_ALGORITHM
        or report.get("raw_text_in_report") is not False
        or report.get("raw_stable_ids_in_report") is not False
        or report.get("raw_notes_in_report") is not False
    ):
        _fail("partition report is invalid or unsafe")

    record_count = report.get("source_dataset_record_count")
    if type(record_count) is not int or not 1 <= record_count <= MAX_RECORDS:
        _fail("partition report source count is outside the bound")
    _sha256(report.get("source_dataset_content_sha256"), "partition source hash")

    passes = report.get("passes")
    pass_fields = {
        "reviewer_kind",
        "reviewer_id",
        "queue_manifest_content_sha256",
        "queue_content_sha256",
        "verdict_state_content_sha256",
        "record_count",
    }
    if not isinstance(passes, Mapping) or set(passes) != set(PASS_NAMES):
        _fail("partition report passes are invalid")
    reviewer_ids: list[str] = []
    queue_hashes: list[str] = []
    for pass_name in PASS_NAMES:
        entry = passes[pass_name]
        if (
            not isinstance(entry, Mapping)
            or set(entry) != pass_fields
            or entry.get("reviewer_kind") != REVIEWER_KIND
            or entry.get("record_count") != record_count
        ):
            _fail("partition report pass entry is invalid")
        reviewer_ids.append(_identifier(entry.get("reviewer_id"), "partition reviewer_id"))
        for field in (
            "queue_manifest_content_sha256",
            "queue_content_sha256",
            "verdict_state_content_sha256",
        ):
            _sha256(entry.get(field), f"partition {pass_name} {field}")
        queue_hashes.append(entry["queue_content_sha256"])
    if len(set(reviewer_ids)) != len(PASS_NAMES):
        _fail("partition report requires distinct reviewer identities")
    if len(set(queue_hashes)) != 1:
        _fail("partition report pass queues do not match")

    pair_counts = report.get("verdict_pair_counts")
    if not isinstance(pair_counts, Mapping) or not pair_counts:
        _fail("partition report verdict pairs are invalid")
    terminal_counts: Counter[str] = Counter()
    verdict_set = set(VERDICTS)
    pair_total = 0
    for key, value in pair_counts.items():
        if not isinstance(key, str) or key.count("/") != 1:
            _fail("partition report verdict pair key is invalid")
        first, confirmation = key.split("/", 1)
        if first not in verdict_set or confirmation not in verdict_set:
            _fail("partition report verdict pair key is invalid")
        if type(value) is not int or not 1 <= value <= record_count:
            _fail("partition report verdict pair count is invalid")
        terminal_counts[_bucket(first, confirmation)] += value
        pair_total += value
    if pair_total != record_count:
        _fail("partition report verdict pair counts do not reconcile")

    bucket_summary = report.get("buckets")
    if not isinstance(bucket_summary, Mapping) or set(bucket_summary) != set(BUCKETS):
        _fail("partition report buckets are invalid")
    bucket_total = 0
    for name in BUCKETS:
        entry = bucket_summary[name]
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"record_count", "content_sha256"}
            or type(entry.get("record_count")) is not int
            or not 0 <= entry["record_count"] <= record_count
        ):
            _fail("partition report bucket entry is invalid")
        _sha256(entry.get("content_sha256"), f"partition {name} hash")
        if entry["record_count"] != terminal_counts[name]:
            _fail("partition report bucket counts do not match verdict pairs")
        bucket_total += entry["record_count"]
    if bucket_total != record_count:
        _fail("partition report bucket counts do not reconcile")

    canonical_json_bytes(report)
    return json.loads(json.dumps(report, ensure_ascii=False, sort_keys=True))


def validate_partition_report_intrinsic(report: Any) -> dict[str, Any]:
    """Public aggregate-only validator for a completed v5 partition report."""

    return _validate_partition_report_intrinsic(report)


def read_admissibility_partition_report(path: str | Path) -> dict[str, Any]:
    """Read one canonical bounded v5 partition report and validate it intrinsically."""

    value = _read_canonical_json(Path(path), MAX_MANIFEST_BYTES)
    return validate_partition_report_intrinsic(value)


def read_v5_split_report(path: str | Path) -> dict[str, Any]:
    """Read canonical split metadata; full semantic checks occur against its inputs."""

    value = _read_canonical_json(Path(path), MAX_MANIFEST_BYTES)
    if not isinstance(value, Mapping):
        _fail("split report must be an object")
    return dict(value)


def _validate_v5_split_and_audit_chain(
    partition_eligible_records: Sequence[Mapping[str, Any]],
    split_dataset: Sequence[Mapping[str, Any]],
    split_report: Mapping[str, Any],
    queue: Sequence[Mapping[str, Any]],
    queue_manifest: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    """Reproduce the frozen v5 split and its complete final-holdout queue."""

    eligible = _strict_records(partition_eligible_records)
    normalized_split = validate_records(split_dataset, require_split=True)
    unsplit = []
    for record in eligible:
        value = dict(record)
        value["split"] = None
        unsplit.append(value)
    try:
        expected_split, expected_report = assign_splits(
            unsplit,
            seed=V5_SPLIT_SEED,
            split_ratios=V5_SPLIT_RATIOS,
        )
    except SplitError as error:
        raise TierAError(f"corpus v5: frozen split reproduction failed: {error}") from error
    if normalized_split != expected_split or dict(split_report) != expected_report:
        _fail("split dataset/report do not reproduce the partition eligible bucket")

    normalized_queue = validate_audit_queue(queue)
    validate_queue_manifest(queue_manifest, normalized_queue)
    final_holdout_count = expected_report["split_counts"]["final-holdout"]
    if final_holdout_count < V5_GATE_A_MINIMUM_SAMPLE_SIZE:
        _fail(
            f"frozen split has fewer than {V5_GATE_A_MINIMUM_SAMPLE_SIZE} "
            "final-holdout records"
        )
    expected_queue = select_audit_records(
        normalized_split,
        seed=V5_GATE_A_AUDIT_SEED,
        minimum_sample_size=V5_GATE_A_MINIMUM_SAMPLE_SIZE,
    )
    if normalized_queue != expected_queue:
        _fail("Gate-A audit queue is not the frozen complete final holdout")
    if (
        queue_manifest.get("seed") != V5_GATE_A_AUDIT_SEED
        or queue_manifest.get("minimum_sample_size") != V5_GATE_A_MINIMUM_SAMPLE_SIZE
        or queue_manifest.get("dataset_record_count") != len(normalized_split)
        or queue_manifest.get("dataset_content_sha256")
        != hashlib.sha256(canonical_jsonl_bytes(normalized_split)).hexdigest()
        or queue_manifest.get("record_count") != final_holdout_count
        or queue_manifest.get("final_holdout_count") != final_holdout_count
        or queue_manifest.get("split_counts")
        != {"final-holdout": final_holdout_count}
    ):
        _fail("Gate-A audit manifest does not bind the frozen complete final holdout")
    return eligible, normalized_split, expected_report, normalized_queue


def _validate_gate_a_reviewer_id(
    partition_report: Mapping[str, Any], reviewer_id: Any
) -> tuple[dict[str, Any], str]:
    checked_report = validate_partition_report_intrinsic(partition_report)
    checked_reviewer_id = _identifier(reviewer_id, "Gate-A reviewer_id")
    forbidden = {
        GATE_A_REVIEWER_ID,
        checked_report["passes"][FIRST_PASS]["reviewer_id"],
        checked_report["passes"][CONFIRMATION_PASS]["reviewer_id"],
    }
    if checked_reviewer_id in forbidden:
        _fail("Gate-A reviewer_id must be fresh and distinct from both blind passes")
    return checked_report, checked_reviewer_id


def _gate_a_source_provenance(
    partition_report: Mapping[str, Any],
    partition_eligible_records: Sequence[Mapping[str, Any]],
    split_dataset: Sequence[Mapping[str, Any]],
    split_report: Mapping[str, Any],
    queue: Sequence[Mapping[str, Any]],
    queue_manifest: Mapping[str, Any],
    *,
    reviewer_id: Any,
) -> tuple[dict[str, Any], str]:
    checked_report, checked_reviewer_id = _validate_gate_a_reviewer_id(
        partition_report, reviewer_id
    )
    eligible = checked_report["buckets"][ELIGIBLE_BUCKET]
    (
        normalized_eligible,
        normalized_split,
        checked_split_report,
        normalized_queue,
    ) = _validate_v5_split_and_audit_chain(
        partition_eligible_records,
        split_dataset,
        split_report,
        queue,
        queue_manifest,
    )
    if (
        eligible["record_count"] != len(normalized_eligible)
        or eligible["content_sha256"] != _canonical_jsonl_hash(normalized_eligible)
    ):
        _fail("partition eligible artifact does not match the partition report")
    split_dataset_sha = hashlib.sha256(
        canonical_jsonl_bytes(normalized_split)
    ).hexdigest()
    provenance = {
        "schema_version": V5_SCHEMA_VERSION,
        "provenance_kind": V5_GATE_A_PROVENANCE_KIND,
        "partition_report_content_sha256": hashlib.sha256(
            _canonical_payload(checked_report)
        ).hexdigest(),
        "partition_source_dataset_content_sha256": checked_report[
            "source_dataset_content_sha256"
        ],
        "eligible_record_count": eligible["record_count"],
        "eligible_content_sha256": eligible["content_sha256"],
        "split_seed": checked_split_report["seed"],
        "split_ratios": checked_split_report["split_ratios"],
        "split_dataset_record_count": len(normalized_split),
        "split_dataset_content_sha256": split_dataset_sha,
        "split_report_content_sha256": hashlib.sha256(
            _canonical_payload(checked_split_report)
        ).hexdigest(),
        "split_counts": checked_split_report["split_counts"],
        "split_content_sha256": checked_split_report["split_content_sha256"],
        "near_duplicate_threshold": checked_split_report[
            "near_duplicate_threshold"
        ],
        "cross_split_leakage": checked_split_report["cross_split_leakage"],
        "audit_queue_manifest_content_sha256": hashlib.sha256(
            _canonical_payload(queue_manifest)
        ).hexdigest(),
        "audit_queue_record_count": len(normalized_queue),
        "audit_queue_content_sha256": queue_manifest["content_sha256"],
        "raw_text_in_provenance": False,
        "raw_stable_ids_in_provenance": False,
        "raw_notes_in_provenance": False,
    }
    canonical_json_bytes(provenance)
    return provenance, checked_reviewer_id


def publish_v5_gate_a_teacher_queue_directory(
    directory: str | Path,
    partition_eligible_records: Sequence[Mapping[str, Any]],
    split_dataset: Sequence[Mapping[str, Any]],
    split_report: Mapping[str, Any],
    queue: Sequence[Mapping[str, Any]],
    queue_manifest: Mapping[str, Any],
    partition_report: Mapping[str, Any],
    *,
    reviewer_id: str,
    batch_size: int = MAX_BATCH_ITEMS,
) -> dict[str, Any]:
    """Publish one fresh, partition-bound v5 Gate-A queue immutably."""

    normalized_queue = validate_audit_queue(queue)
    provenance, checked_reviewer_id = _gate_a_source_provenance(
        partition_report,
        partition_eligible_records,
        split_dataset,
        split_report,
        normalized_queue,
        queue_manifest,
        reviewer_id=reviewer_id,
    )
    batches = build_gate_a_teacher_batches(normalized_queue, batch_size=batch_size)

    def publish_directory(temporary: Path, target: Path) -> None:
        _publish_directory_atomically(
            temporary,
            target,
            immutable_message="queue directory already exists and is immutable",
        )

    return publish_teacher_queue_directory(
        directory,
        batches,
        stage="gate_a",
        reviewer_kind=REVIEWER_KIND,
        reviewer_id=checked_reviewer_id,
        manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
        source_provenance=provenance,
        directory_publisher=publish_directory,
    )


def validate_v5_gate_a_teacher_queue_binding(
    partition_eligible_records: Sequence[Mapping[str, Any]],
    split_dataset: Sequence[Mapping[str, Any]],
    split_report: Mapping[str, Any],
    queue: Sequence[Mapping[str, Any]],
    queue_manifest: Mapping[str, Any],
    batches: Sequence[Mapping[str, Any]],
    teacher_manifest: Mapping[str, Any],
    partition_report: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Rebind a v5 Gate-A queue to its partition, audit queue, and manifest ID."""

    normalized_queue = validate_audit_queue(queue)
    if not isinstance(teacher_manifest, Mapping):
        _fail("Gate-A teacher manifest must be an object")
    reviewer_id = teacher_manifest.get("reviewer_id")
    expected_provenance, checked_reviewer_id = _gate_a_source_provenance(
        partition_report,
        partition_eligible_records,
        split_dataset,
        split_report,
        normalized_queue,
        queue_manifest,
        reviewer_id=reviewer_id,
    )
    if teacher_manifest.get("source_provenance") != expected_provenance:
        _fail("Gate-A teacher queue source provenance does not match")
    normalized_batches = validate_gate_a_teacher_queue_binding(
        normalized_queue,
        batches,
        teacher_manifest,
        reviewer_id=checked_reviewer_id,
        manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
    )
    return normalized_batches, checked_reviewer_id


def publish_admissibility_partition_directory(
    directory: str | Path,
    buckets: Mapping[str, Sequence[Mapping[str, Any]]],
    report: Mapping[str, Any],
) -> None:
    """Publish the already validated bucket sidecars and aggregate report atomically."""

    if not isinstance(buckets, Mapping) or set(buckets) != set(BUCKETS):
        _fail("partition buckets do not match the terminal-state contract")
    checked_report = _validate_partition_report_intrinsic(report)
    normalized: dict[str, list[dict[str, Any]]] = {}
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in BUCKETS:
        rows = list(buckets[name])
        if rows:
            checked = _strict_records(rows)
        else:
            checked = []
        identifiers = [record["stable_id"] for record in checked]
        if seen.intersection(identifiers):
            _fail("partition buckets overlap")
        seen.update(identifiers)
        summary = checked_report["buckets"].get(name)
        if (
            not isinstance(summary, Mapping)
            or set(summary) != {"record_count", "content_sha256"}
            or summary.get("record_count") != len(checked)
            or summary.get("content_sha256") != _canonical_jsonl_hash(checked)
        ):
            _fail("partition bucket does not match its aggregate commitment")
        normalized[name] = checked
        all_records.extend(checked)
    if len(seen) != checked_report["source_dataset_record_count"]:
        _fail("partition bucket coverage does not reconcile")
    all_records.sort(key=lambda record: record["stable_id"])
    if checked_report["source_dataset_content_sha256"] != _canonical_jsonl_hash(all_records):
        _fail("partition source dataset commitment does not reconcile")

    target = Path(directory)
    if target.exists():
        _fail("partition directory already exists and is immutable")
    if not target.parent.is_dir():
        _fail("partition parent directory does not exist")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for name in BUCKETS:
            payload = b"".join(
                canonical_json_bytes(record) + b"\n" for record in normalized[name]
            )
            write_bytes_atomic(temporary / f"{name.replace('_', '-')}.jsonl", payload)
        write_bytes_atomic(temporary / "report.json", _canonical_payload(checked_report))
        _publish_directory_atomically(
            temporary,
            target,
            immutable_message="partition directory already exists and is immutable",
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
