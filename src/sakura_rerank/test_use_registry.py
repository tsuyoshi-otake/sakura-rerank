"""Local, append-only Test consumption ledger; not a Gold admission authority.

Reserve before opening Test inputs or starting any model. A reservation consumes
its population even if execution fails. The evaluator must separately establish
Gold quality, complete historical coverage, frozen artifacts and Gate admission.
Keep the registry and an externally pinned head together across all experiments.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .data.contracts import canonical_json_bytes

EMPTY_HEAD = "0" * 64
FORMAT = b"sakura-rerank.test-use-registry.v1\n"
MAX_LEDGER_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 1000
MAX_TOKENS = 100_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class TestUseError(ValueError):
    """The evidence cannot safely advance to another consumption state."""


def _digest(value: Any) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise TestUseError("invalid SHA-256 commitment")
    return value


def _tokens(values: Any) -> list[str]:
    if not isinstance(values, list) or not 0 < len(values) <= MAX_TOKENS:
        raise TestUseError("Test token count outside bound")
    for value in values:
        _digest(value)
    if values != sorted(set(values)):
        raise TestUseError("Test tokens must be unique and sorted")
    return list(values)


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def initialize_registry(root: Path) -> None:
    """Create a new registry explicitly; never silently reset an existing one."""
    root.mkdir(parents=False, exist_ok=False)
    for name, payload in (("format", FORMAT), ("events.jsonl", b"")):
        with (root / name).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    if not root.is_dir():
        raise TestUseError("registry is not initialized")
    with (root / "format").open("rb") as stream:
        if stream.read(len(FORMAT) + 1) != FORMAT:
            raise TestUseError("registry format differs")
    lock = root / "writer.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise TestUseError("registry writer active or interrupted; do not auto-unlock") from error
    try:
        yield
    finally:
        lock.rmdir()


def _read(root: Path, expected_head: str) -> tuple[list[dict[str, Any]], str]:
    _digest(expected_head)
    with (root / "events.jsonl").open("rb") as stream:
        raw = stream.read(MAX_LEDGER_BYTES + 1)
    if len(raw) > MAX_LEDGER_BYTES or (raw and not raw.endswith(b"\n")):
        raise TestUseError("ledger exceeds bound or has an incomplete write")
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_EVENTS:
        raise TestUseError("ledger event bound exceeded")
    head = EMPTY_HEAD
    events = []
    claims: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    terminal: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError) as error:
            raise TestUseError("malformed ledger event") from error
        if not isinstance(event, dict) or canonical_json_bytes(event) + b"\n" != line:
            raise TestUseError("ledger event is not canonical")
        common = {"kind", "previous_sha256", "recorded_at"}
        if event.get("previous_sha256") != head:
            raise TestUseError("ledger chain mismatch")
        try:
            timestamp = datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00"))
            if timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
                raise ValueError("UTC required")
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise TestUseError("invalid UTC event time") from error
        if event.get("kind") == "reserved":
            if set(event) != common | {"plan_sha256", "partition_audit_sha256", "test_tokens"}:
                raise TestUseError("unexpected reservation fields")
            _digest(event["plan_sha256"])
            _digest(event["partition_audit_sha256"])
            tokens = _tokens(event["test_tokens"])
            if used.intersection(tokens) or set(claims) - terminal:
                raise TestUseError("ledger has overlapping or concurrently active reservations")
            used.update(tokens)
        elif event.get("kind") in {"completed", "failed"}:
            if set(event) != common | {"reservation_sha256", "result_sha256"}:
                raise TestUseError("unexpected terminal fields")
            claim = _digest(event["reservation_sha256"])
            if claim not in claims or claim in terminal:
                raise TestUseError("terminal event has no active reservation")
            if event["kind"] == "completed":
                _digest(event["result_sha256"])
            elif event["result_sha256"] is not None:
                raise TestUseError("failed execution must not claim a result artifact")
            terminal.add(claim)
        else:
            raise TestUseError("unknown ledger event kind")
        head = hashlib.sha256(line).hexdigest()
        if event["kind"] == "reserved":
            claims[head] = event
        events.append(event)
    if head != expected_head:
        raise TestUseError("ledger head differs from the external commitment")
    return events, head


def _append(root: Path, head: str, event: dict[str, Any]) -> str:
    event = {
        **event, "previous_sha256": head,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload = canonical_json_bytes(event) + b"\n"
    path = root / "events.jsonl"
    terminal_reserve = 4096 if event["kind"] == "reserved" else 0
    if path.stat().st_size + len(payload) + terminal_reserve > MAX_LEDGER_BYTES:
        raise TestUseError("ledger byte bound exceeded")
    # No rollback on write/fsync failure: partial evidence fails closed on read.
    with path.open("ab") as stream:
        if stream.write(payload) != len(payload):
            raise OSError("incomplete ledger write")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def inspect_registry(root: Path, *, expected_head: str) -> dict[str, Any]:
    """Verify the complete chain against a separately retained commitment."""
    with _locked(root):
        events, head = _read(root, expected_head)
    counts = {kind: sum(e["kind"] == kind for e in events)
              for kind in ("reserved", "completed", "failed")}
    return {
        "head_sha256": head, "events": len(events), **counts,
        "active": counts["reserved"] - counts["completed"] - counts["failed"],
        "gold_quality_certified": False,
    }


def reserve_test(
    root: Path, *, expected_head: str, plan_sha256: str,
    partition_report: Mapping[str, Any], test_tokens: list[str],
) -> str:
    """Consume a supplied population before Test access, regardless of outcome.

    This validates the partition receipt, not the underlying corpus or Gold.
    A changed plan, relabel, subset or article revision cannot reuse claimed
    tokens. The evaluator must pin the returned head outside this directory.
    """
    _digest(plan_sha256)
    tokens = _tokens(test_tokens)
    if not isinstance(partition_report, Mapping):
        raise TestUseError("partition receipt must be an object")
    cross = partition_report.get("cross_population_groups")
    affected = partition_report.get("affected_new_records")
    if (
        not isinstance(cross, dict)
        or set(cross) != {"article", "paragraph_exact", "template_cluster",
                          "sentence_near_duplicate", "bounded_input_exact"}
        or any(type(value) is not int or value != 0 for value in cross.values())
        or not isinstance(affected, dict)
        or set(affected) != {"train", "calibration", "test"}
        or any(type(value) is not int or value != 0 for value in affected.values())
    ):
        raise TestUseError("partition receipt contains cross-population leakage")
    if (
        partition_report.get("kind") != "evaluation_partition_audit"
        or type(partition_report.get("schema_version")) is not int
        or partition_report.get("schema_version") != 1
        or partition_report.get("algorithm") != "source_components_and_exact_bounded_input_v1"
        or partition_report.get("near_duplicate_threshold") != 0.8
        or partition_report.get("leakage_free_for_supplied_records") is not True
        or type(partition_report.get("cross_population_components")) is not int
        or partition_report.get("cross_population_components") != 0
        or partition_report.get("test_reuse_tokens_sha256") != _hash(tokens)
        or partition_report.get("test_reuse_token_count") != len(tokens)
    ):
        raise TestUseError("partition receipt is blocked or does not bind the Test tokens")
    with _locked(root):
        events, head = _read(root, expected_head)
        if len(events) >= MAX_EVENTS - 1:
            raise TestUseError("reserve capacity for the terminal event")
        consumed = {token for event in events if event["kind"] == "reserved"
                    for token in event["test_tokens"]}
        if consumed.intersection(tokens):
            raise TestUseError("Test population overlaps an already consumed population")
        if sum(e["kind"] == "reserved" for e in events) * 2 != len(events):
            raise TestUseError("a prior reservation needs an explicit terminal outcome")
        return _append(root, head, {
            "kind": "reserved", "plan_sha256": plan_sha256,
            "partition_audit_sha256": _hash(partition_report), "test_tokens": tokens,
        })


def finish_test(
    root: Path, *, expected_head: str, reservation_sha256: str,
    outcome: str, result_sha256: str | None = None,
) -> str:
    """Record one terminal result; failure never releases consumed tokens."""
    _digest(reservation_sha256)
    if outcome not in {"completed", "failed"}:
        raise TestUseError("terminal outcome must be completed or failed")
    if outcome == "completed":
        _digest(result_sha256)
    elif result_sha256 is not None:
        raise TestUseError("failed execution must not claim a result artifact")
    with _locked(root):
        events, head = _read(root, expected_head)
        if not events or events[-1]["kind"] != "reserved" or head != reservation_sha256:
            raise TestUseError("reservation is not the active last event")
        if len(events) >= MAX_EVENTS:
            raise TestUseError("ledger event bound exceeded")
        return _append(root, head, {
            "kind": outcome, "reservation_sha256": reservation_sha256,
            "result_sha256": result_sha256,
        })
