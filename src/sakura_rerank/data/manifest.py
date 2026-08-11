"""Strict, staged manifests for one immutable jawiki multistream artifact.

The validator deliberately performs no network access.  Official metadata can
therefore be recorded and reviewed before the multi-gigabyte dump is fetched.
Once a local artifact is declared, all three integrity values are checked:
Wikimedia's MD5 and SHA-1 plus a separately calculated local SHA-256.
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


MANIFEST_SCHEMA_VERSION = 2
MANIFEST_KIND = "jawiki_snapshot"
ARTIFACT_KIND = "pages_articles_multistream_xml_bz2"
OFFICIAL_METADATA_VERIFIED = "official_metadata_verified"
LOCAL_ARTIFACT_VERIFIED = "local_artifact_verified"
PREPROCESSING_VERIFIED = "preprocessing_verified"
BLOCKED_STATUS = "blocked"
VERIFIED_STATUSES = frozenset(
    {
        OFFICIAL_METADATA_VERIFIED,
        LOCAL_ARTIFACT_VERIFIED,
        PREPROCESSING_VERIFIED,
    }
)
OFFICIAL_URL_HOSTS = frozenset({"dumps.wikimedia.org"})
LICENSE_URL = "https://dumps.wikimedia.org/legal.html"
PINNED_SNAPSHOT_DATE = "2026-08-01"
PINNED_FILE_NAME = "jawiki-20260801-pages-articles-multistream.xml.bz2"
PINNED_OFFICIAL_URL = (
    "https://dumps.wikimedia.org/jawiki/20260801/"
    "jawiki-20260801-pages-articles-multistream.xml.bz2"
)
PINNED_DUMP_STATUS_URL = "https://dumps.wikimedia.org/jawiki/20260801/dumpstatus.json"
PINNED_MD5_URL = (
    "https://dumps.wikimedia.org/jawiki/20260801/jawiki-20260801-md5sums.txt"
)
PINNED_SHA1_URL = (
    "https://dumps.wikimedia.org/jawiki/20260801/jawiki-20260801-sha1sums.txt"
)
PINNED_BYTE_SIZE = 4_827_732_824
PINNED_OFFICIAL_MD5 = "b51bab6d1cc23efddc4363e78b5526c6"
PINNED_OFFICIAL_SHA1 = "6c917b51d6f6b53a34eaebcb2a675c0769054343"

MANIFEST_FIELDS = (
    "schema_version",
    "manifest_kind",
    "status",
    "artifact_kind",
    "snapshot_date",
    "file_name",
    "official_url",
    "byte_size",
    "official_md5",
    "official_sha1",
    "metadata_sources",
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
        "artifact_kind",
        "file_name",
        "official_url",
        "byte_size",
        "official_md5",
        "official_sha1",
        "metadata_sources.dump_status_url",
        "metadata_sources.md5_url",
        "metadata_sources.sha1_url",
        "metadata_sources.confirmed_at",
        "local_path",
        "local_sha256",
        "retrieved_at",
        "license.summary",
        "license.url",
        "extractor.name",
        "extractor.version",
        "preprocessing_git_sha",
    }
)

_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_NAME_RE = re.compile(r"^[^\x00\r\n]+$")
_PLACEHOLDERS = frozenset({"", "unknown", "tbd", "todo", "n/a", "none", "null"})
_MAX_MANIFEST_STRING_CHARS = 4096


class ManifestError(ValueError):
    """A manifest is malformed or does not match its declared artifact state."""


class ManifestBlockedError(ManifestError):
    """Metadata is explicitly unavailable and must not be guessed."""

    def __init__(self, fields: Sequence[str], reasons: Mapping[str, str] | None = None):
        normalized = tuple(sorted(set(fields)))
        self.fields = normalized
        self.reasons = dict(reasons or {})
        super().__init__("manifest metadata blocked for: " + ", ".join(normalized))

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
    if len(value) > _MAX_MANIFEST_STRING_CHARS:
        _error(field, "exceeds the bounded character length")
    return value


def _require_digest(value: Any, field: str, pattern: re.Pattern[str], name: str) -> str:
    value = _require_string(value, field)
    if pattern.fullmatch(value) is None:
        _error(field, f"must be a lowercase {name} hex digest")
    return value


def _require_md5(value: Any, field: str) -> str:
    return _require_digest(value, field, _MD5_RE, "MD5")


def _require_sha1(value: Any, field: str) -> str:
    return _require_digest(value, field, _SHA1_RE, "SHA-1")


def _require_sha256(value: Any, field: str) -> str:
    return _require_digest(value, field, _SHA256_RE, "SHA-256")


def _reject_unknown_keys(value: Mapping[str, Any], allowed: Iterable[str], field: str) -> None:
    if set(value) - set(allowed):
        _error(field, "contains unknown fields")


def _decoded(value: str) -> str:
    """Decode every nested percent-encoding layer within the bounded input."""

    decoded = value
    # Each changing unquote removes at least two input characters, so the
    # bounded input length is also a strict upper bound on decode iterations.
    for _ in range(len(value) + 1):
        next_value = unquote(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    raise AssertionError("percent decoding did not converge within the input bound")


def _contains_latest(value: str) -> bool:
    return "latest" in _decoded(value).casefold()


def _reject_latest(value: str, field: str) -> None:
    if _contains_latest(value):
        _error(field, "mutable latest aliases are forbidden")


def _validate_snapshot_date(value: Any) -> tuple[str, str]:
    value = _require_string(value, "snapshot_date")
    _reject_latest(value, "snapshot_date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        _error("snapshot_date", "must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        _error("snapshot_date", "is not a calendar date")
    return value, value.replace("-", "")


def _expected_file_name(compact_date: str) -> str:
    return f"jawiki-{compact_date}-pages-articles-multistream.xml.bz2"


def _validate_file_name(value: Any, compact_date: str) -> str:
    value = _require_string(value, "file_name")
    _reject_latest(value, "file_name")
    if _SAFE_NAME_RE.fullmatch(value) is None:
        _error("file_name", "contains a forbidden character")
    if value in {".", ".."} or "/" in value or "\\" in value:
        _error("file_name", "must be a single relative file name")
    expected = _expected_file_name(compact_date)
    if value != expected:
        _error(
            "file_name",
            "must match snapshot_date and the recombined pages-articles multistream artifact",
        )
    return value


def _parse_official_url(value: Any, field: str) -> tuple[str, list[str]]:
    value = _require_string(value, field)
    _reject_latest(value, field)
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_URL_HOSTS:
        _error(field, "must be an HTTPS URL on the official dump host")
    try:
        port = parsed.port
    except ValueError:
        _error(field, "contains an invalid port")
    if parsed.username or parsed.password or port or parsed.query or parsed.fragment:
        _error(field, "must not contain credentials, a port, query, or fragment")
    decoded_path = _decoded(parsed.path)
    _reject_latest(decoded_path, field)
    parts = [part for part in PurePosixPath(decoded_path).parts if part != "/"]
    return value, parts


def _validate_official_url(value: Any, compact_date: str, file_name: str) -> str:
    value, parts = _parse_official_url(value, "official_url")
    if parts != ["jawiki", compact_date, file_name]:
        _error(
            "official_url",
            "path must use the matching jawiki snapshot directory and file_name",
        )
    return value


def _validate_metadata_url(value: Any, field: str, expected_parts: list[str]) -> str:
    value, parts = _parse_official_url(value, field)
    if parts != expected_parts:
        _error(field, "does not match the fixed snapshot metadata path")
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


def _validate_metadata_sources(value: Any, compact_date: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _error("metadata_sources", "must be an object")
    expected = {"dump_status_url", "md5_url", "sha1_url", "confirmed_at"}
    _reject_unknown_keys(value, expected, "metadata_sources")
    if set(value) != expected:
        _error("metadata_sources", "all official metadata sources are required")
    prefix = ["jawiki", compact_date]
    normalized = {
        "dump_status_url": _validate_metadata_url(
            value["dump_status_url"],
            "metadata_sources.dump_status_url",
            prefix + ["dumpstatus.json"],
        ),
        "md5_url": _validate_metadata_url(
            value["md5_url"],
            "metadata_sources.md5_url",
            prefix + [f"jawiki-{compact_date}-md5sums.txt"],
        ),
        "sha1_url": _validate_metadata_url(
            value["sha1_url"],
            "metadata_sources.sha1_url",
            prefix + [f"jawiki-{compact_date}-sha1sums.txt"],
        ),
        "confirmed_at": _validate_timestamp(
            value["confirmed_at"], "metadata_sources.confirmed_at"
        ),
    }
    pinned_urls = {
        "dump_status_url": PINNED_DUMP_STATUS_URL,
        "md5_url": PINNED_MD5_URL,
        "sha1_url": PINNED_SHA1_URL,
    }
    for field, pinned_url in pinned_urls.items():
        if normalized[field] != pinned_url:
            _error(
                f"metadata_sources.{field}",
                "does not match the pinned official metadata URL",
            )
    return normalized


def _validate_license(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _error("license", "must be an object")
    _reject_unknown_keys(value, {"summary", "url"}, "license")
    if set(value) != {"summary", "url"}:
        _error("license", "summary and url are required")
    summary = _require_string(value["summary"], "license.summary")
    if summary.strip().lower() in _PLACEHOLDERS:
        _error("license.summary", "placeholder values are not accepted")
    url = _require_string(value["url"], "license.url")
    if url != LICENSE_URL:
        _error("license.url", "must reference the official Wikimedia dump license guide")
    return {"summary": summary, "url": url}


def _validate_local_path(value: Any, file_name: str, allowed_root: Path) -> Path:
    value = _require_string(value, "local_path")
    _reject_latest(value, "local_path")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        _error("local_path", "must be relative")
    if "\\" in value:
        _error("local_path", "must use canonical POSIX separators")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _error("local_path", "contains an unsafe path component")
    if parts[-1] != file_name:
        _error("local_path", "basename must match file_name")

    root = allowed_root.resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        _error("local_path", "resolves outside the allowed root")
    return candidate


def _validate_extractor(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _error("extractor", "must be an object")
    _reject_unknown_keys(value, {"name", "version"}, "extractor")
    if set(value) != {"name", "version"}:
        _error("extractor", "name and version are required")
    result: dict[str, str] = {}
    for key in ("name", "version"):
        item = _require_string(value[key], f"extractor.{key}")
        if item.strip().lower() in _PLACEHOLDERS:
            _error(f"extractor.{key}", "placeholder values are not accepted")
        result[key] = item
    return result


def validate_manifest(
    manifest: Mapping[str, Any],
    allowed_root: str | Path,
) -> dict[str, Any]:
    """Validate one official-metadata, local-artifact, or preprocessing state."""

    if not isinstance(manifest, Mapping):
        raise ManifestError("manifest: must be a JSON object")
    if manifest.get("status") == BLOCKED_STATUS:
        report = validate_blocked_report(manifest)
        raise ManifestBlockedError(
            [item["field"] for item in report["blocked_fields"]],
            {item["field"]: item["reason"] for item in report["blocked_fields"]},
        )
    _reject_unknown_keys(manifest, MANIFEST_FIELDS, "manifest")
    if set(manifest) != set(MANIFEST_FIELDS):
        _error("manifest", "all manifest fields are required, using null for later stages")
    if (
        isinstance(manifest["schema_version"], bool)
        or manifest["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
        _error("schema_version", "unsupported schema version")
    if manifest["manifest_kind"] != MANIFEST_KIND:
        _error("manifest_kind", "must identify a jawiki snapshot")
    status = manifest["status"]
    if status not in VERIFIED_STATUSES:
        _error("status", "unsupported manifest stage")
    if manifest["artifact_kind"] != ARTIFACT_KIND:
        _error("artifact_kind", "must identify the recombined multistream XML artifact")

    snapshot_date, compact_date = _validate_snapshot_date(manifest["snapshot_date"])
    if snapshot_date != PINNED_SNAPSHOT_DATE:
        _error("snapshot_date", "does not match the pinned 2026-08-01 snapshot")
    file_name = _validate_file_name(manifest["file_name"], compact_date)
    if file_name != PINNED_FILE_NAME:
        _error("file_name", "does not match the pinned multistream artifact")
    official_url = _validate_official_url(
        manifest["official_url"], compact_date, file_name
    )
    if official_url != PINNED_OFFICIAL_URL:
        _error("official_url", "does not match the pinned official artifact URL")
    byte_size = manifest["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size <= 0:
        _error("byte_size", "must be a positive integer")
    if byte_size != PINNED_BYTE_SIZE:
        _error("byte_size", "does not match confirmed official metadata")
    official_md5 = _require_md5(manifest["official_md5"], "official_md5")
    if official_md5 != PINNED_OFFICIAL_MD5:
        _error("official_md5", "does not match confirmed official metadata")
    official_sha1 = _require_sha1(manifest["official_sha1"], "official_sha1")
    if official_sha1 != PINNED_OFFICIAL_SHA1:
        _error("official_sha1", "does not match confirmed official metadata")
    metadata_sources = _validate_metadata_sources(
        manifest["metadata_sources"], compact_date
    )
    license_info = _validate_license(manifest["license"])

    local_path_value = manifest["local_path"]
    local_sha256_value = manifest["local_sha256"]
    retrieved_at_value = manifest["retrieved_at"]
    extractor_value = manifest["extractor"]
    preprocessing_git_sha_value = manifest["preprocessing_git_sha"]

    local_path: Path | None = None
    local_sha256: str | None = None
    retrieved_at: str | None = None
    extractor: dict[str, str] | None = None
    preprocessing_git_sha: str | None = None

    if status == OFFICIAL_METADATA_VERIFIED:
        if any(
            value is not None
            for value in (
                local_path_value,
                local_sha256_value,
                retrieved_at_value,
                extractor_value,
                preprocessing_git_sha_value,
            )
        ):
            _error("status", "official-metadata-only state requires all local stages to be null")
    else:
        local_path = _validate_local_path(
            local_path_value, file_name, Path(allowed_root)
        )
        local_sha256 = _require_sha256(local_sha256_value, "local_sha256")
        retrieved_at = _validate_timestamp(retrieved_at_value, "retrieved_at")
        if status == LOCAL_ARTIFACT_VERIFIED:
            if extractor_value is not None or preprocessing_git_sha_value is not None:
                _error("status", "local-artifact state requires preprocessing fields to be null")
        else:
            extractor = _validate_extractor(extractor_value)
            preprocessing_git_sha = _require_string(
                preprocessing_git_sha_value, "preprocessing_git_sha"
            )
            if _GIT_SHA_RE.fullmatch(preprocessing_git_sha) is None:
                _error("preprocessing_git_sha", "must be a lowercase Git SHA-1")

        _verify_local_artifact(
            local_path,
            byte_size=byte_size,
            official_md5=official_md5,
            official_sha1=official_sha1,
            local_sha256=local_sha256,
        )

    normalized = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "status": status,
        "artifact_kind": ARTIFACT_KIND,
        "snapshot_date": snapshot_date,
        "file_name": file_name,
        "official_url": official_url,
        "byte_size": byte_size,
        "official_md5": official_md5,
        "official_sha1": official_sha1,
        "metadata_sources": metadata_sources,
        "local_path": local_path_value,
        "local_sha256": local_sha256,
        "retrieved_at": retrieved_at,
        "license": license_info,
        "extractor": extractor,
        "preprocessing_git_sha": preprocessing_git_sha,
    }
    return json.loads(json.dumps(normalized, ensure_ascii=False, sort_keys=True))


def hash_file(path: str | Path, algorithm: str, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""

    return hash_file_many(path, (algorithm,), chunk_size=chunk_size)[algorithm]


def hash_file_many(
    path: str | Path,
    algorithms: Sequence[str],
    *,
    chunk_size: int = 1024 * 1024,
) -> dict[str, str]:
    """Calculate distinct digests together in one stable-size streaming pass."""

    if not algorithms or len(algorithms) != len(set(algorithms)):
        raise ManifestError("hash algorithms must be non-empty and unique")
    digests = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}
    source = Path(path)
    before = source.stat()
    observed = 0
    with source.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            observed += len(chunk)
            for digest in digests.values():
                digest.update(chunk)
    after = source.stat()
    if observed != before.st_size or (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ):
        _error("local_path", "file changed during digest verification")
    return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    return hash_file(path, "sha256", chunk_size=chunk_size)


def _verify_local_artifact(
    path: str | Path,
    *,
    byte_size: int,
    official_md5: str,
    official_sha1: str,
    local_sha256: str,
) -> None:
    """Verify the local file against distinct official and local digests."""

    local_path = Path(path)
    if not local_path.exists() or not local_path.is_file():
        _error("local_path", "file does not exist")
    if local_path.stat().st_size != byte_size:
        _error("byte_size", "does not match the local file")
    measured = hash_file_many(local_path, ("md5", "sha1", "sha256"))
    if measured["md5"] != official_md5:
        _error("official_md5", "does not match the local file")
    if measured["sha1"] != official_sha1:
        _error("official_sha1", "does not match the local file")
    if measured["sha256"] != local_sha256:
        _error("local_sha256", "does not match the local file")


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
    if (
        isinstance(report["schema_version"], bool)
        or report["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
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
) -> dict[str, Any]:
    """Validate either a staged manifest or raise a structured blocker."""

    if document.get("status") == BLOCKED_STATUS:
        report = validate_blocked_report(document)
        raise ManifestBlockedError(
            [item["field"] for item in report["blocked_fields"]],
            {item["field"]: item["reason"] for item in report["blocked_fields"]},
        )
    return validate_manifest(document, allowed_root)
