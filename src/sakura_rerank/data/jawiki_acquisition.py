"""Resumable, fail-closed acquisition of the pinned jawiki dump artifact."""

from __future__ import annotations

import email.utils
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..atomic_io import write_bytes_atomic
from .contracts import canonical_json_bytes
from .manifest import (
    LOCAL_ARTIFACT_VERIFIED,
    OFFICIAL_METADATA_VERIFIED,
    OFFICIAL_URL_HOSTS,
    ManifestError,
    load_manifest_document,
    validate_manifest,
)


CHUNK_SIZE = 4 * 1024 * 1024
MAX_RETRY_DELAY_SECONDS = 60.0
MIN_FREE_RESERVE_BYTES = 512 * 1024 * 1024
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


class AcquisitionError(OSError):
    """The pinned artifact could not reach a verified terminal state."""


class RetryableAcquisitionError(AcquisitionError):
    """A bounded retry may safely continue from the explicit partial file."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(message)


class PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow redirects only to HTTPS URLs on the pinned Wikimedia host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> urllib.request.Request | None:
        parsed = urlparse(newurl)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in OFFICIAL_URL_HOSTS
            or parsed.port not in {None, 443}
        ):
            raise AcquisitionError("redirect target is outside the pinned HTTPS host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(PinnedRedirectHandler())


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, min(seconds, MAX_RETRY_DELAY_SECONDS))


def _bounded_path(path: str | Path, root: Path, label: str) -> Path:
    resolved = Path(path).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AcquisitionError(f"{label}: path resolves outside allowed root") from error
    if resolved == root:
        raise AcquisitionError(f"{label}: must identify a file below allowed root")
    return resolved


def _ensure_distinct(paths: Mapping[str, Path]) -> None:
    items = list(paths.items())
    for index, (left_label, left) in enumerate(items):
        for right_label, right in items[index + 1 :]:
            if os.path.normcase(str(left)) == os.path.normcase(str(right)):
                raise AcquisitionError(f"paths: {left_label} and {right_label} collide")
            if left.exists() and right.exists():
                try:
                    same = os.path.samefile(left, right)
                except OSError as error:
                    raise AcquisitionError("paths: existing path identity check failed") from error
                if same:
                    raise AcquisitionError(f"paths: {left_label} and {right_label} alias")


def hash_artifact(path: str | Path, *, expected_size: int) -> dict[str, str]:
    """Measure all required digests in one streaming pass over immutable-size bytes."""

    source = Path(path)
    try:
        before = source.stat()
        if not source.is_file() or source.is_symlink():
            raise AcquisitionError("artifact must be a regular non-symlink file")
        if before.st_size != expected_size:
            raise AcquisitionError("artifact byte size does not match the pinned size")
        digests = {name: hashlib.new(name) for name in ("md5", "sha1", "sha256")}
        observed = 0
        with source.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                observed += len(chunk)
                for digest in digests.values():
                    digest.update(chunk)
        after = source.stat()
    except AcquisitionError:
        raise
    except OSError as error:
        raise AcquisitionError(f"artifact cannot be measured ({type(error).__name__})") from error
    if observed != expected_size or (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ):
        raise AcquisitionError("artifact changed during verification")
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _verify_digests(
    path: Path,
    *,
    expected_size: int,
    expected_md5: str,
    expected_sha1: str,
) -> dict[str, str]:
    measured = hash_artifact(path, expected_size=expected_size)
    if measured["md5"] != expected_md5:
        raise AcquisitionError("artifact MD5 does not match official metadata")
    if measured["sha1"] != expected_sha1:
        raise AcquisitionError("artifact SHA-1 does not match official metadata")
    return measured


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    return int(status)


def _validated_response_length(response: Any, *, start: int, expected_size: int) -> None:
    status = _response_status(response)
    if start == 0 and status != 200:
        raise AcquisitionError("fresh download requires HTTP 200")
    if start > 0 and status != 206:
        raise AcquisitionError("server ignored the resume Range request")
    expected_remaining = expected_size - start
    content_length = response.headers.get("Content-Length")
    if content_length is None or not content_length.isdigit():
        raise AcquisitionError("response is missing a valid Content-Length")
    if int(content_length) != expected_remaining:
        raise AcquisitionError("response Content-Length does not match remaining bytes")
    if start == 0:
        return
    match = _CONTENT_RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
    if match is None:
        raise AcquisitionError("resume response has an invalid Content-Range")
    first, last, total = (int(value) for value in match.groups())
    if first != start or last != expected_size - 1 or total != expected_size:
        raise AcquisitionError("resume Content-Range does not match the pinned artifact")


def _download_once(
    *,
    opener: Any,
    url: str,
    partial: Path,
    expected_size: int,
    timeout_seconds: float,
    progress: Callable[[int, int], None] | None,
    allowed_hosts: frozenset[str],
    require_https: bool,
) -> None:
    start = partial.stat().st_size if partial.exists() else 0
    if start < 0 or start >= expected_size:
        raise AcquisitionError("partial file size is outside the resumable range")
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "sakura-rerank-jawiki-acquisition/1",
            **({"Range": f"bytes={start}-"} if start else {}),
        },
    )
    try:
        response_context = opener.open(request, timeout=timeout_seconds)
        with response_context as response:
            final_url = urlparse(response.geturl())
            if (
                (require_https and final_url.scheme != "https")
                or final_url.hostname not in allowed_hosts
                or (require_https and final_url.port not in {None, 443})
            ):
                raise AcquisitionError("response URL is outside the pinned HTTPS host")
            _validated_response_length(response, start=start, expected_size=expected_size)
            mode = "ab" if partial.exists() else "xb"
            observed = start
            ended_early = False
            with partial.open(mode) as output:
                while True:
                    try:
                        chunk = response.read(CHUNK_SIZE)
                    except http.client.IncompleteRead as error:
                        chunk = error.partial
                        ended_early = True
                    except (TimeoutError, socket.timeout, ConnectionError) as error:
                        raise RetryableAcquisitionError(
                            f"transient response failure ({type(error).__name__})"
                        ) from error
                    if not chunk:
                        break
                    observed += len(chunk)
                    if observed > expected_size:
                        raise AcquisitionError("response exceeded the pinned artifact size")
                    output.write(chunk)
                    if progress is not None:
                        progress(observed, expected_size)
                    if ended_early:
                        break
                output.flush()
                os.fsync(output.fileno())
    except urllib.error.HTTPError as error:
        if error.code == 429 or 500 <= error.code <= 599:
            headers = error.headers or {}
            raise RetryableAcquisitionError(
                f"retryable HTTP status {error.code}",
                retry_after=_retry_after_seconds(headers.get("Retry-After")),
            ) from error
        raise AcquisitionError(f"HTTP status {error.code}") from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise RetryableAcquisitionError(
            f"transient download failure ({type(error).__name__})"
        ) from error
    if ended_early or observed != expected_size:
        raise RetryableAcquisitionError("response ended before the pinned artifact size")


def download_verified(
    *,
    url: str,
    destination: str | Path,
    expected_size: int,
    expected_md5: str,
    expected_sha1: str,
    max_attempts: int = 5,
    timeout_seconds: float = 60.0,
    opener: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    progress: Callable[[int, int], None] | None = None,
    allowed_hosts: frozenset[str] = OFFICIAL_URL_HOSTS,
    require_https: bool = True,
) -> tuple[dict[str, str], bool]:
    """Download to `.part`, verify, and only then atomically publish destination."""

    if max_attempts < 1 or max_attempts > 20:
        raise AcquisitionError("max_attempts must be between 1 and 20")
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise AcquisitionError("timeout_seconds must be in (0, 600]")
    target = Path(destination)
    partial = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    parsed_url = urlparse(url)
    if (
        (require_https and parsed_url.scheme != "https")
        or parsed_url.hostname not in allowed_hosts
        or (require_https and parsed_url.port not in {None, 443})
    ):
        raise AcquisitionError("download URL is outside the allowed host boundary")
    if expected_size < 1:
        raise AcquisitionError("expected_size must be positive")
    if re.fullmatch(r"[0-9a-f]{32}", expected_md5) is None:
        raise AcquisitionError("expected_md5 must be lowercase MD5")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha1) is None:
        raise AcquisitionError("expected_sha1 must be lowercase SHA-1")
    if target.exists():
        measured = _verify_digests(
            target,
            expected_size=expected_size,
            expected_md5=expected_md5,
            expected_sha1=expected_sha1,
        )
        partial.unlink(missing_ok=True)
        return measured, False
    if partial.exists() and (not partial.is_file() or partial.is_symlink()):
        raise AcquisitionError("partial artifact must be a regular non-symlink file")
    if partial.exists() and partial.stat().st_size == expected_size:
        measured = _verify_digests(
            partial,
            expected_size=expected_size,
            expected_md5=expected_md5,
            expected_sha1=expected_sha1,
        )
        os.replace(partial, target)
        return measured, True

    partial_size = partial.stat().st_size if partial.exists() else 0
    required_free = expected_size - partial_size + MIN_FREE_RESERVE_BYTES
    if shutil.disk_usage(target.parent).free < required_free:
        raise AcquisitionError("insufficient free space for artifact plus safety reserve")

    active_opener = opener if opener is not None else _default_opener()
    for attempt in range(1, max_attempts + 1):
        try:
            _download_once(
                opener=active_opener,
                url=url,
                partial=partial,
                expected_size=expected_size,
                timeout_seconds=timeout_seconds,
                progress=progress,
                allowed_hosts=allowed_hosts,
                require_https=require_https,
            )
            break
        except RetryableAcquisitionError as error:
            if attempt == max_attempts:
                raise AcquisitionError(
                    f"download exhausted {max_attempts} bounded attempts"
                ) from error
            delay = error.retry_after
            if delay is None:
                delay = min(2 ** (attempt - 1) + jitter(), MAX_RETRY_DELAY_SECONDS)
            sleep(delay)
    measured = _verify_digests(
        partial,
        expected_size=expected_size,
        expected_md5=expected_md5,
        expected_sha1=expected_sha1,
    )
    os.replace(partial, target)
    return measured, True


def acquire_jawiki(
    source_manifest: str | Path,
    *,
    allowed_root: str | Path,
    destination: str | Path,
    local_manifest_output: str | Path,
    max_attempts: int = 5,
    timeout_seconds: float = 60.0,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Acquire the fixed artifact and publish a local-only verified manifest."""

    root = Path(allowed_root).resolve(strict=True)
    source_path = _bounded_path(source_manifest, root, "source_manifest")
    target = _bounded_path(destination, root, "destination")
    manifest_output = _bounded_path(local_manifest_output, root, "local_manifest_output")
    partial = target.with_name(target.name + ".part")
    _ensure_distinct(
        {
            "source_manifest": source_path,
            "destination": target,
            "partial": partial,
            "local_manifest_output": manifest_output,
        }
    )
    document = load_manifest_document(source_path)
    official = validate_manifest(document, root)
    if official["status"] != OFFICIAL_METADATA_VERIFIED:
        raise ManifestError("acquisition requires an official_metadata_verified source manifest")
    if target.name != official["file_name"]:
        raise AcquisitionError("destination basename must match the pinned artifact")
    measured, downloaded = download_verified(
        url=official["official_url"],
        destination=target,
        expected_size=official["byte_size"],
        expected_md5=official["official_md5"],
        expected_sha1=official["official_sha1"],
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        progress=progress,
    )

    if manifest_output.exists():
        existing = validate_manifest(load_manifest_document(manifest_output), root)
        if (
            existing["status"] == LOCAL_ARTIFACT_VERIFIED
            and existing["local_sha256"] == measured["sha256"]
            and existing["local_path"] == target.relative_to(root).as_posix()
        ):
            return {**existing, "downloaded": downloaded}
        raise AcquisitionError("existing local manifest does not match the verified artifact")

    local_manifest = dict(document)
    local_manifest.update(
        {
            "status": LOCAL_ARTIFACT_VERIFIED,
            "local_path": target.relative_to(root).as_posix(),
            "local_sha256": measured["sha256"],
            "retrieved_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
    validated = validate_manifest(local_manifest, root)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(
        manifest_output,
        canonical_json_bytes(validated) + b"\n",
    )
    return {**validated, "downloaded": downloaded}
