"""Strict, content-addressed manifests for fixed jawiki snapshots.

The validator deliberately has no network behavior. A verified manifest is
accepted only when its local file is present, inside the caller-provided root,
and matches both the recorded byte size and SHA-256 values. When upstream
metadata is unavailable, callers can record a blocked report instead of
inventing a value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_KIND = "jawiki_snapshot"
VERIFIED_STATUS = "verified"
BLOCKED_STATUS = "blocked"
OFFICIAL_URL_HOSTS = frozenset({"dumps.wikimedia.org"})

MANIFEST_FIELDS = (
    "schema_version",
    "manifest_kind",
    "status",
    "snapshot_date",
    "file_name",
    "official_url",
    "byte_size",
    "official_sha256",
    "local_path",
    "local_sha256",
    "retrieved_at",
    "license",
    "extractor",
    "preprocessing_git_sha",
)
BLOCKABLE_FIELDS = frozenset(
    {
        "snapshot_date",
        "file_name",
        "official_url",
        "byte_size",
        "official_sha256",
        "local_path",
        "local_sha256",
        "retrieved_at",
        "license",
        "extractor.name",
        "extractor.version",
        "preprocessing_git_sha",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_NAME_RE = re.compile(r"^[^\x00\r\n]+$")
_PLACEHOLDERS = frozenset({"", "unknown", "tbd", "todo", "n/a", "none", "null"})


class ManifestError(ValueError):
    """A manifest is malformed or does not match its local artifact."""


class ManifestBlockedError(ManifestError):
    """Upstream metadata is explicitly unavailable and must not be guessed."""

    def __init__(self, fields: Sequence[str], reasons: Mapping[str, str] | None = None):
        normalized = tuple(sorted(set(fields)))
        self.fields = normalized
        self.reasons = dict(reasons or {})
        super().__init__(
            "manifest metadata blocked for: " + ", ".join(normalized)
        )

    @property
    def report(self) -> dict[str, Any]:
        return make_blocked_report(self.fields, self.reasons)


def _error(field: str, message: str) -> None:
    raise ManifestError(f"{field}: {message}")


def _require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _error(field, "must be a string")
    if not allow_empty and not value.strip():
        _error(field, "must not be empty")
    if "\x00" in value or "\r" in value or "\n" in value:
        _error(field, "contains a forbidden control character")
    return value


def _require_sha256(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if _SHA256_RE.fullmatch(value) is None:
        _error(field, "must be a lowercase SHA-256 hex digest")
    return value


def _reject_unknown_keys(value: Mapping[str, Any], allowed: Iterable[str], field: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _error(field, "contains unknown fields")


def _contains_latest(value: str) -> bool:
    parts = [part for part in re.split(r"[/\\?#=&]+", value.lower()) if part]
    return "latest" in parts


def _validate_snapshot_date(value: Any) -> str:
    value = _require_string(value, "snapshot_date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        _error("snapshot_date", "must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        _error("snapshot_date", "is not a calendar date")
    if _contains_latest(value):
        _error("snapshot_date", "mutable latest aliases are forbidden")
    return value


def _validate_file_name(value: Any) -> str:
    value = _require_string(value, "file_name")
    if _SAFE_NAME_RE.fullmatch(value) is None:
        _error("file_name", "contains a forbidden character")
    if value in {".", ".."} or "/" in value or "\\" in value:
        _error("file_name", "must be a single relative file name")
    if _contains_latest(value):
        _error("file_name", "mutable latest aliases are forbidden")
    return value


def _validate_official_url(value: Any, file_name: str) -> str:
    value = _require_string(value, "official_url")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_URL_HOSTS:
        _error("official_url", "must be an HTTPS URL on the official dump host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        _error("official_url", "must not contain credentials, query, or fragment")
    if _contains_latest(parsed.path):
        _error("official_url", "mutable latest aliases are forbidden")
    if "jawiki" not in parsed.path.lower().split("/"):
        _error("official_url", "must identify a jawiki dump path")
    if PurePosixPath(unquote(parsed.path)).name != file_name:
        _error("official_url", "path basename must match file_name")
    return value


def _validate_local_path(value: Any, file_name: str, allowed_root: Path) -> Path:
    value = _require_string(value, "local_path")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        _error("local_path", "must be relative")
    if "\\" in value:
        _error("local_path", "must use canonical POSIX separators")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _error("local_path", "contains an unsafe path component")
    if _contains_latest(value):
        _error("local_path", "mutable latest aliases are forbidden")
    if parts[-1] != file_name:
        _error("local_path", "basename must match file_name")

    root = allowed_root.resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        _error("local_path", "resolves outside the allowed root")
    return candidate


def _validate_timestamp(value: Any) -> str:
    value = _require_string(value, "retrieved_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _error("retrieved_at", "must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error("retrieved_at", "must include a timezone")
    return value


def _validate_non_placeholder(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if value.strip().lower() in _PLACEHOLDERS:
        _error(field, "placeholder values are not accepted")
    return value


def validate_manifest(
    manifest: Mapping[str, Any],
    allowed_root: str | Path,
    *,
    check_local_file: bool = True,
) -> dict[str, Any]:
    """Validate and return a verified manifest.

    ``allowed_root`` is the only directory from which ``local_path`` may
    resolve. The default also hashes the local file, so a metadata-only
    document cannot accidentally be treated as a reproducible snapshot.
    """

    if not isinstance(manifest, Mapping):
        raise ManifestError("manifest: must be a JSON object")
    if manifest.get("status") == BLOCKED_STATUS:
        report = validate_blocked_report(manifest)
        raise ManifestBlockedError(
            [item["field"] for item in report["blocked_fields"]],
            {item["field"]: item["reason"] for item in report["blocked_fields"]},
        )
    _reject_unknown_keys(manifest, MANIFEST_FIELDS, "manifest")
    missing = [field for field in MANIFEST_FIELDS if field not in manifest]
    if missing:
        _error("manifest", "missing required fields")
    if isinstance(manifest["schema_version"], bool) or manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        _error("schema_version", "unsupported schema version")
    if manifest["manifest_kind"] != MANIFEST_KIND:
        _error("manifest_kind", "must identify a jawiki snapshot")
    if manifest["status"] != VERIFIED_STATUS:
        _error("status", "must be verified or represented as a blocked report")

    snapshot_date = _validate_snapshot_date(manifest["snapshot_date"])
    file_name = _validate_file_name(manifest["file_name"])
    official_url = _validate_official_url(manifest["official_url"], file_name)

    byte_size = manifest["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size <= 0:
        _error("byte_size", "must be a positive integer")
    official_sha256 = _require_sha256(manifest["official_sha256"], "official_sha256")
    local_sha256 = _require_sha256(manifest["local_sha256"], "local_sha256")
    if official_sha256 != local_sha256:
        _error("local_sha256", "does not match official_sha256")

    root = Path(allowed_root)
    local_path = _validate_local_path(manifest["local_path"], file_name, root)
    retrieved_at = _validate_timestamp(manifest["retrieved_at"])
    license_name = _validate_non_placeholder(manifest["license"], "license")

    extractor = manifest["extractor"]
    if not isinstance(extractor, Mapping):
        _error("extractor", "must be an object")
    _reject_unknown_keys(extractor, {"name", "version"}, "extractor")
    if set(extractor) != {"name", "version"}:
        _error("extractor", "name and version are required")
    extractor_name = _validate_non_placeholder(extractor["name"], "extractor.name")
    extractor_version = _validate_non_placeholder(extractor["version"], "extractor.version")

    preprocessing_git_sha = _require_string(
        manifest["preprocessing_git_sha"], "preprocessing_git_sha"
    )
    if _GIT_SHA_RE.fullmatch(preprocessing_git_sha) is None:
        _error("preprocessing_git_sha", "must be a lowercase Git SHA-1")

    if check_local_file:
        if not local_path.exists() or not local_path.is_file():
            _error("local_path", "file does not exist")
        actual_size = local_path.stat().st_size
        if actual_size != byte_size:
            _error("byte_size", "does not match the local file")
        actual_sha256 = sha256_file(local_path)
        if actual_sha256 != local_sha256:
            _error("local_sha256", "does not match the local file")

    # Return a fresh JSON-compatible object so callers cannot mutate the input
    # through a retained nested mapping after validation.
    return json.loads(
        json.dumps(
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "manifest_kind": MANIFEST_KIND,
                "status": VERIFIED_STATUS,
                "snapshot_date": snapshot_date,
                "file_name": file_name,
                "official_url": official_url,
                "byte_size": byte_size,
                "official_sha256": official_sha256,
                "local_path": manifest["local_path"],
                "local_sha256": local_sha256,
                "retrieved_at": retrieved_at,
                "license": license_name,
                "extractor": {"name": extractor_name, "version": extractor_version},
                "preprocessing_git_sha": preprocessing_git_sha,
            }
        )
    )


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 of a file without loading it into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def make_blocked_report(
    fields: Iterable[str], reasons: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Build a non-verified report for metadata that could not be confirmed."""

    normalized = sorted(set(fields))
    if not normalized or any(field not in BLOCKABLE_FIELDS for field in normalized):
        raise ManifestError("blocked_fields: contains an unsupported or empty field list")
    reasons = reasons or {}
    entries: list[dict[str, str]] = []
    for field in normalized:
        reason = _require_string(
            reasons.get(field, "official metadata was not independently verified"),
            f"blocked_fields.{field}",
        )
        entries.append({"field": field, "reason": reason})
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "status": BLOCKED_STATUS,
        "blocked_fields": entries,
    }


def validate_blocked_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a structured blocker report without accepting it as a manifest."""

    if not isinstance(report, Mapping):
        raise ManifestError("blocked report: must be a JSON object")
    expected = {"schema_version", "manifest_kind", "status", "blocked_fields"}
    _reject_unknown_keys(report, expected, "blocked report")
    if set(report) != expected:
        _error("blocked report", "all blocker fields are required")
    if isinstance(report["schema_version"], bool) or report["schema_version"] != MANIFEST_SCHEMA_VERSION:
        _error("blocked report.schema_version", "unsupported schema version")
    if report["manifest_kind"] != MANIFEST_KIND:
        _error("blocked report.manifest_kind", "must identify a jawiki snapshot")
    if report["status"] != BLOCKED_STATUS:
        _error("blocked report.status", "must be blocked")
    blocked_fields = report["blocked_fields"]
    if not isinstance(blocked_fields, list) or not blocked_fields:
        _error("blocked_fields", "must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(blocked_fields):
        field_name = f"blocked_fields[{index}]"
        if not isinstance(item, Mapping):
            _error(field_name, "must be an object")
        _reject_unknown_keys(item, {"field", "reason"}, field_name)
        if set(item) != {"field", "reason"}:
            _error(field_name, "field and reason are required")
        field = _require_string(item["field"], f"{field_name}.field")
        if field not in BLOCKABLE_FIELDS or field in seen:
            _error(f"{field_name}.field", "is not a unique blockable manifest field")
        reason = _require_string(item["reason"], f"{field_name}.reason")
        seen.add(field)
        normalized.append({"field": field, "reason": reason})
    normalized.sort(key=lambda item: item["field"])
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "status": BLOCKED_STATUS,
        "blocked_fields": normalized,
    }


def load_manifest_document(path: str | Path) -> dict[str, Any]:
    """Load a JSON object without deciding whether it is verified or blocked."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(
            f"manifest file: cannot read JSON ({type(error).__name__})"
        ) from error
    if not isinstance(value, dict):
        raise ManifestError("manifest file: top-level value must be an object")
    return value


def validate_manifest_document(
    document: Mapping[str, Any],
    allowed_root: str | Path,
    *,
    check_local_file: bool = True,
) -> dict[str, Any]:
    """Validate either a verified manifest or raise a structured blocker."""

    if document.get("status") == BLOCKED_STATUS:
        report = validate_blocked_report(document)
        raise ManifestBlockedError(
            [item["field"] for item in report["blocked_fields"]],
            {item["field"]: item["reason"] for item in report["blocked_fields"]},
        )
    return validate_manifest(document, allowed_root, check_local_file=check_local_file)
