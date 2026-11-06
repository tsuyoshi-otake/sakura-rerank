"""Authenticate offline evaluation artifacts before consuming a one-use Test.

This is an access boundary, not a Gold certifier, model runner or release gate.
No independent Gold evidence has been verified for this repository yet.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Iterator, Mapping

from .atomic_io import write_bytes_atomic
from .data.contracts import canonical_json_bytes
from .evaluation_statistics import wilson95
from .test_use_registry import EMPTY_HEAD, finish_test, inspect_registry, reserve_test

# Adding an identity requires independently verified evidence, not an AI vote,
# a self-reported pass flag, or an owner permission to waive the quality criteria.
VERIFIED_GOLD_CERTIFICATES: frozenset[str] = frozenset()
MAX_PLAN_BYTES = 512 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 768 * 1024 * 1024
DATA_ROLES = frozenset({
    "historical", "train", "calibration", "test", "policy", "partition",
    "tokens", "sampling", "provenance", "experiment",
})
MODEL_ROLES = frozenset({"weights", "tokenizer", "features", "gate"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


class AdmissionError(ValueError):
    """Access was refused or its durable terminal state needs reconciliation."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise AdmissionError("invalid SHA-256 identity")
    return value


def _object(value: object, keys: set | frozenset) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        raise AdmissionError("unexpected object fields")
    return value


def _json(raw: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AdmissionError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_):
        raise AdmissionError("non-finite JSON value")

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            invalid_constant(text)
        return value

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise AdmissionError("invalid bounded JSON metadata") from error


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AdmissionError("artifact is not a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise AdmissionError("artifact byte bound exceeded")
    return raw


@dataclass(frozen=True)
class _Artifact:
    path: Path
    role: str
    sha256: str
    size: int
    identity: tuple[int, int]

    def authenticate(self, *, retain: bool) -> bytes | None:
        digest = hashlib.sha256()
        blocks = []
        count = 0
        with self.path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self.identity:
                raise AdmissionError("artifact identity changed before authentication")
            while block := stream.read(min(1024 * 1024, self.size - count + 1)):
                count += len(block)
                if count > self.size:
                    raise AdmissionError("artifact size differs")
                digest.update(block)
                if retain:
                    blocks.append(block)
        if count != self.size or digest.hexdigest() != self.sha256:
            raise AdmissionError("artifact bytes differ from the frozen plan")
        return b"".join(blocks) if retain else None


def _catalog(root: Path, value: object) -> dict[str, _Artifact]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 64:
        raise AdmissionError("artifact count outside bound")
    catalog = {}
    identities = set()
    for key, spec in value.items():
        if not _ID.fullmatch(key):
            raise AdmissionError("invalid artifact ID")
        _object(spec, {"path", "role", "sha256", "bytes"})
        relative = spec["path"]
        if (not isinstance(relative, str) or not 1 <= len(relative) <= 240
                or "\\" in relative or ":" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or PurePosixPath(relative).is_absolute()):
            raise AdmissionError("artifact path must be a bounded relative path")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise AdmissionError("artifact escapes its root")
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        if not stat.S_ISREG(info.st_mode) or identity in identities:
            raise AdmissionError("artifact alias or non-regular file")
        identities.add(identity)
        size = spec["bytes"]
        if (type(size) is not int or not 0 < size <= MAX_ARTIFACT_BYTES
                or info.st_size != size):
            raise AdmissionError("artifact size differs or exceeds bound")
        if spec["role"] not in DATA_ROLES | MODEL_ROLES | {"quality"}:
            raise AdmissionError("unknown artifact role")
        catalog[key] = _Artifact(path, spec["role"], _digest(spec["sha256"]), size, identity)
    if sum(a.size for a in catalog.values()) > MAX_TOTAL_BYTES:
        raise AdmissionError("total artifact bytes exceed bound")
    retained = [a for a in catalog.values() if a.role not in {"historical", "train", "calibration"}]
    if sum(a.size for a in retained) > MAX_SNAPSHOT_BYTES:
        raise AdmissionError("retained snapshot exceeds bound")
    for artifact in retained:
        if artifact.role not in {"test", "weights", "tokenizer", "features"} and artifact.size > MAX_METADATA_BYTES:
            raise AdmissionError("metadata byte bound exceeded")
    return catalog


def _prepare(root: Path, plan_path: Path, expected_sha256: str):
    raw = _read(plan_path, MAX_PLAN_BYTES)
    if _sha(raw) != _digest(expected_sha256):
        raise AdmissionError("plan differs from its external commitment")
    plan = _object(_json(raw), {"kind", "schema_version", "artifacts", "data", "models"})
    if (plan["kind"] != "evaluation_access_plan" or type(plan["schema_version"]) is not int
            or plan["schema_version"] != 1):
        raise AdmissionError("unsupported access plan")
    catalog = _catalog(root, plan["artifacts"])
    data = _object(plan["data"], DATA_ROLES | {"quality"})
    models = plan["models"]
    if (not isinstance(models, dict) or not 4 <= len(models) <= 8
            or not {"v1", "r2", "issue29", "current_tiny"} <= models.keys()):
        raise AdmissionError("required model comparison is missing")
    referenced = set()

    def binding(key, role):
        if not isinstance(key, str) or key not in catalog or catalog[key].role != role:
            raise AdmissionError("artifact binding has a different role")
        referenced.add(key)
        return catalog[key]

    for role, key in data.items():
        binding(key, role)
    for name, model in models.items():
        if not _ID.fullmatch(name):
            raise AdmissionError("invalid model ID")
        for role, key in _object(model, MODEL_ROLES).items():
            binding(key, role)
    if referenced != catalog.keys():
        raise AdmissionError("unreferenced artifact in plan")
    certificate = catalog[data["quality"]]
    # Reject unknown evidence before opening any dataset, model or Test content.
    if certificate.sha256 not in VERIFIED_GOLD_CERTIFICATES:
        raise AdmissionError("no verified independent Gold evidence for this plan")
    evidence = _object(_json(certificate.authenticate(retain=True)), {
        "kind", "schema_version", "bindings", "audit_completed", "audit_valid",
        "valid_test_count", "oracle6_present",
    })
    if (evidence["kind"] != "independent_gold_evidence"
            or type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1
            or evidence["bindings"] != {role: catalog[data[role]].sha256 for role in DATA_ROLES}):
        raise AdmissionError("Gold evidence does not bind the exact data and policies")
    completed, valid, total, oracle = [evidence[k] for k in (
        "audit_completed", "audit_valid", "valid_test_count", "oracle6_present")]
    if (any(type(n) is not int for n in (completed, valid, total, oracle))
            or not 1000 <= completed <= 100_000 or not 0 <= valid <= completed
            or not 3000 <= total <= 100_000 or not 0 <= oracle <= total
            or valid / completed < .995 or wilson95(valid, completed)[0] < .99
            or oracle / total < .97):
        raise AdmissionError("Gold evidence fails the fixed quality criteria")
    snapshot = {}
    for key, artifact in catalog.items():
        if artifact.role == "test":
            continue
        payload = artifact.authenticate(retain=artifact.role not in {"historical", "train", "calibration"})
        if payload is not None:
            snapshot[key] = payload
    for model in models.values():
        gate = _object(_json(snapshot[model["gate"]]), {
            "kind", "schema_version", "bindings", "safety_threshold", "configuration",
        })
        bound = {role: catalog[model[role]].sha256 for role in MODEL_ROLES - {"gate"}}
        bound.update({role: catalog[data[role]].sha256 for role in {"calibration", "policy"}})
        if (gate["kind"] != "frozen_gate" or type(gate["schema_version"]) is not int
                or gate["schema_version"] != 1 or gate["bindings"] != bound
                or gate["safety_threshold"] != .0025 or not isinstance(gate["configuration"], dict)):
            raise AdmissionError("gate binding or safety criterion differs")
    partition = _json(snapshot[data["partition"]])
    if (not isinstance(partition, dict) or not isinstance(partition.get("populations"), dict)
            or partition["populations"].get("test", {}).get("count") != total):
        raise AdmissionError("partition and Gold population counts differ")
    tokens = _json(snapshot[data["tokens"]])
    # reserve_test authenticates receipt rules/token correspondence before mutation.
    return catalog, data, snapshot, partition, tokens, raw


def _anchor_identity(registry: Path) -> str:
    return _sha(os.path.normcase(str(registry.resolve(strict=True))).encode("utf-8"))


def _anchor_payload(registry: Path, head: str) -> bytes:
    return canonical_json_bytes({"registry_path_sha256": _anchor_identity(registry), "head_sha256": head})


def _locations(registry: Path, anchor: Path) -> tuple[Path, Path]:
    registry = registry.resolve(strict=True)
    anchor = anchor.resolve()
    if anchor.is_relative_to(registry):
        raise AdmissionError("retain the head outside the registry directory")
    return registry, anchor


@contextmanager
def _access_lock(anchor: Path) -> Iterator[None]:
    lock = anchor.with_name(anchor.name + ".access.lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise AdmissionError("evaluation access active or interrupted; do not auto-unlock") from error
    try:
        yield
    finally:
        lock.rmdir()


def _write_once(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("incomplete evidence write")
        stream.flush()
        os.fsync(stream.fileno())


def initialize_anchor(registry: Path, anchor: Path) -> None:
    """Create a separate head once, and only for an explicitly empty registry."""
    registry, anchor = _locations(registry, anchor)
    with _access_lock(anchor):
        inspect_registry(registry, expected_head=EMPTY_HEAD)
        _write_once(anchor, _anchor_payload(registry, EMPTY_HEAD))


class EvaluationAccess:
    """Immutable authenticated bytes; caller explicitly completes its access job."""

    def __init__(self, artifacts: Mapping[str, bytes], reservation_sha256: str, plan_bytes: bytes = b""):
        self.artifacts = MappingProxyType(dict(artifacts))
        self.reservation_sha256 = reservation_sha256
        self.plan_bytes = plan_bytes
        self._result: bytes | None = None
        self._closed = False

    def complete(self, result: bytes) -> None:
        if self._closed:
            raise AdmissionError("access job is closed")
        if self._result is not None:
            raise AdmissionError("access job already has a result")
        if type(result) is not bytes or not 0 < len(result) <= MAX_METADATA_BYTES or not isinstance(_json(result), dict):
            raise AdmissionError("result must be a bounded JSON object")
        self._result = result


@contextmanager
def access_test(*, artifact_root: Path, plan_path: Path, expected_plan_sha256: str,
                registry: Path, anchor: Path,
                preflight: Callable[[Mapping[str, bytes], bytes], None] | None = None) -> Iterator[EvaluationAccess]:
    """Reserve and pin consumption before Test access; finalize every normal exit.

    Abrupt process termination leaves a consumed reservation/lock for explicit
    reconciliation. A terminal write failure raises; it never restores Test use.
    The caller must use the returned bytes, never reread mutable artifact paths.
    """
    root = artifact_root.resolve(strict=True)
    registry, anchor = _locations(registry, anchor)
    if registry.is_relative_to(root) or anchor.is_relative_to(root):
        raise AdmissionError("mutable ledger state must be outside the artifact root")
    with _access_lock(anchor):
        commitment = _object(_json(_read(anchor, 4096)), {"registry_path_sha256", "head_sha256"})
        if commitment["registry_path_sha256"] != _anchor_identity(registry):
            raise AdmissionError("anchor belongs to a different registry")
        old_head = _digest(commitment["head_sha256"])
        inspect_registry(registry, expected_head=old_head)
        catalog, data, snapshot, partition, tokens, plan_bytes = _prepare(root, plan_path, expected_plan_sha256)
        if preflight is not None:
            if preflight(MappingProxyType(dict(snapshot)), plan_bytes) is not None:
                raise AdmissionError("preflight must explicitly accept by returning None")
        try:
            reservation = reserve_test(registry, expected_head=old_head, plan_sha256=expected_plan_sha256,
                                       partition_report=partition, test_tokens=tokens)
        except OSError as error:
            raise AdmissionError("reservation write needs ledger/anchor reconciliation before retry") from error
        access = None
        try:
            write_bytes_atomic(anchor, _anchor_payload(registry, reservation))
            snapshot[data["test"]] = catalog[data["test"]].authenticate(retain=True)
            access = EvaluationAccess(snapshot, reservation, plan_bytes)
            yield access
            if access._result is None:
                raise AdmissionError("access job exited without an explicit result")
            _write_once(registry / ("result-" + reservation + ".json"), access._result)
        except BaseException:
            try:
                terminal = finish_test(registry, expected_head=reservation,
                                       reservation_sha256=reservation, outcome="failed")
                write_bytes_atomic(anchor, _anchor_payload(registry, terminal))
            except BaseException as error:
                raise AdmissionError("consumed Test needs reconciliation; reservation=" + reservation) from error
            raise
        finally:
            if access is not None:
                access._closed = True
        # Never attempt a second terminal record if this write or its anchor fails.
        try:
            terminal = finish_test(registry, expected_head=reservation, reservation_sha256=reservation,
                                   outcome="completed", result_sha256=_sha(access._result))
            write_bytes_atomic(anchor, _anchor_payload(registry, terminal))
        except BaseException as error:
            raise AdmissionError("completion needs reconciliation; reservation=" + reservation) from error
