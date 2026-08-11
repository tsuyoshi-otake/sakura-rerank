from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.data.jawiki_acquisition as acquisition
from sakura_rerank.data.jawiki_acquisition import (
    AcquisitionError,
    PinnedRedirectHandler,
    download_verified,
)


@contextmanager
def artifact_server(payload: bytes, mode: str = "normal"):
    state: dict[str, object] = {"requests": 0, "ranges": []}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            state["requests"] = int(state["requests"]) + 1
            range_header = self.headers.get("Range")
            ranges = state["ranges"]
            assert isinstance(ranges, list)
            ranges.append(range_header)
            if mode == "retry":
                self.send_response(503)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.com/not-pinned")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return

            if mode == "ignore_range" or range_header is None:
                start = 0
                status = 200
            else:
                start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                status = 206
            body = payload[start:]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            if status == 206:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )
            self.send_header("Connection", "close")
            self.end_headers()
            if mode == "interrupt_once" and int(state["requests"]) == 1:
                self.wfile.write(body[: acquisition.CHUNK_SIZE])
                self.wfile.flush()
                self.close_connection = True
                return
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/artifact", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("HTTP fixture thread did not terminate")


def identity(payload: bytes) -> dict[str, object]:
    return {
        "expected_size": len(payload),
        "expected_md5": hashlib.md5(payload).hexdigest(),
        "expected_sha1": hashlib.sha1(payload).hexdigest(),
    }


def local_options() -> dict[str, object]:
    return {
        "allowed_hosts": frozenset({"127.0.0.1"}),
        "require_https": False,
        "timeout_seconds": 5.0,
        "sleep": lambda _: None,
        "jitter": lambda: 0.0,
    }


class JawikiAcquisitionTests(unittest.TestCase):
    def test_fresh_download_is_verified_before_publication(self) -> None:
        payload = b"fixed artifact fixture" * 1024
        with tempfile.TemporaryDirectory() as directory, artifact_server(payload) as (
            url,
            state,
        ):
            target = Path(directory) / "artifact.bz2"
            measured, downloaded = download_verified(
                url=url,
                destination=target,
                **identity(payload),
                **local_options(),
            )
            self.assertTrue(downloaded)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(measured["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertFalse(Path(str(target) + ".part").exists())
            self.assertEqual(state["requests"], 1)

    def test_resume_requires_exact_content_range(self) -> None:
        payload = b"resume fixture" * 2048
        with tempfile.TemporaryDirectory() as directory, artifact_server(payload) as (
            url,
            state,
        ):
            target = Path(directory) / "artifact.bz2"
            prefix = payload[:4096]
            Path(str(target) + ".part").write_bytes(prefix)
            download_verified(
                url=url,
                destination=target,
                **identity(payload),
                **local_options(),
            )
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(state["ranges"], [f"bytes={len(prefix)}-"])

    def test_interrupted_response_resumes_on_next_bounded_attempt(self) -> None:
        payload = b"x" * (acquisition.CHUNK_SIZE + 8192)
        with tempfile.TemporaryDirectory() as directory, artifact_server(
            payload, "interrupt_once"
        ) as (url, state):
            target = Path(directory) / "artifact.bz2"
            download_verified(
                url=url,
                destination=target,
                max_attempts=2,
                **identity(payload),
                **local_options(),
            )
            self.assertEqual(target.stat().st_size, len(payload))
            self.assertEqual(state["requests"], 2)
            self.assertEqual(state["ranges"], [None, f"bytes={acquisition.CHUNK_SIZE}-"])

    def test_server_ignoring_range_never_appends_duplicate_bytes(self) -> None:
        payload = b"range fixture" * 1024
        with tempfile.TemporaryDirectory() as directory, artifact_server(
            payload, "ignore_range"
        ) as (url, _):
            target = Path(directory) / "artifact.bz2"
            partial = Path(str(target) + ".part")
            prefix = payload[:100]
            partial.write_bytes(prefix)
            with self.assertRaisesRegex(AcquisitionError, "ignored the resume"):
                download_verified(
                    url=url,
                    destination=target,
                    **identity(payload),
                    **local_options(),
                )
            self.assertEqual(partial.read_bytes(), prefix)
            self.assertFalse(target.exists())

    def test_cross_host_redirect_is_rejected_before_following(self) -> None:
        payload = b"redirect fixture"
        opener = urllib.request.build_opener(PinnedRedirectHandler())
        with tempfile.TemporaryDirectory() as directory, artifact_server(
            payload, "redirect"
        ) as (url, _):
            target = Path(directory) / "artifact.bz2"
            with self.assertRaisesRegex(AcquisitionError, "outside the pinned"):
                download_verified(
                    url=url,
                    destination=target,
                    opener=opener,
                    **identity(payload),
                    **local_options(),
                )
            self.assertFalse(target.exists())

    def test_retry_exhaustion_has_an_explicit_terminal_error(self) -> None:
        payload = b"retry fixture"
        delays: list[float] = []
        options = local_options()
        options["sleep"] = delays.append
        with tempfile.TemporaryDirectory() as directory, artifact_server(
            payload, "retry"
        ) as (url, state):
            with self.assertRaisesRegex(AcquisitionError, "exhausted 3"):
                download_verified(
                    url=url,
                    destination=Path(directory) / "artifact.bz2",
                    max_attempts=3,
                    **identity(payload),
                    **options,
                )
            self.assertEqual(state["requests"], 3)
            self.assertEqual(delays, [0.0, 0.0])

    def test_digest_mismatch_keeps_only_explicit_partial(self) -> None:
        payload = b"digest fixture" * 1024
        wrong = identity(payload)
        wrong["expected_md5"] = "0" * 32
        with tempfile.TemporaryDirectory() as directory, artifact_server(payload) as (
            url,
            _,
        ):
            target = Path(directory) / "artifact.bz2"
            with self.assertRaisesRegex(AcquisitionError, "MD5"):
                download_verified(
                    url=url,
                    destination=target,
                    **wrong,
                    **local_options(),
                )
            self.assertFalse(target.exists())
            self.assertEqual(Path(str(target) + ".part").read_bytes(), payload)

    def test_existing_verified_artifact_uses_no_network(self) -> None:
        payload = b"existing fixture" * 1024

        class FailOpener:
            def open(self, *_: object, **__: object) -> object:
                raise AssertionError("network must not be used")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact.bz2"
            target.write_bytes(payload)
            measured, downloaded = download_verified(
                url="https://dumps.wikimedia.org/pinned",
                destination=target,
                opener=FailOpener(),
                **identity(payload),
            )
            self.assertFalse(downloaded)
            self.assertEqual(measured["sha256"], hashlib.sha256(payload).hexdigest())

    def test_failed_atomic_replace_leaves_verified_bytes_as_partial(self) -> None:
        payload = b"publication fixture" * 1024
        with tempfile.TemporaryDirectory() as directory, artifact_server(payload) as (
            url,
            _,
        ):
            target = Path(directory) / "artifact.bz2"
            with patch.object(acquisition.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError, "injected"):
                    download_verified(
                        url=url,
                        destination=target,
                        **identity(payload),
                        **local_options(),
                    )
            self.assertFalse(target.exists())
            self.assertEqual(Path(str(target) + ".part").read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
