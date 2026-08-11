"""Benchmark the released Sakura Input Tiny worker through protocol v1.

The benchmark deliberately treats the worker as a black box.  It measures the
same framed stdio boundary used by the engine, never logs candidate text, and
owns bounded cleanup of every worker process it starts.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import mmap
import os
import platform
import queue
import statistics
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sakura_rerank.audit import collect_environment, file_record, write_json_atomic


SCHEMA_VERSION = "sakura-rerank.current-tiny-benchmark.v1"
REQUEST_MAGIC = 0x524E_4B53
RESPONSE_MAGIC = 0x534E_4B53
PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 32 * 1024
MAX_CANDIDATES = 6
MAX_CANDIDATE_BYTES = 3 * 1024
STATUS_SUCCESS = 0
STATUS_FAILURE = 2


class BenchmarkError(RuntimeError):
    """The worker or its response violated the benchmark contract."""


@dataclass(frozen=True)
class Candidate:
    fingerprint: int
    local_cost: int
    text: str


@dataclass(frozen=True)
class WorkerResponse:
    request_id: int
    status: int
    tier: int
    scores: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class FixtureGroup:
    name: str
    character_length: int
    differing_positions: tuple[int, ...]
    candidates: tuple[Candidate, ...]

    def public_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "character_length": self.character_length,
            "candidate_count": len(self.candidates),
            "candidate_utf8_bytes": [
                len(candidate.text.encode("utf-8")) for candidate in self.candidates
            ],
            "differing_position_count": len(self.differing_positions),
            "expected_max_ort_calls_from_source_contract": len(
                self.differing_positions
            ),
        }


def _stable_fingerprint(bucket: str, index: int, text: str) -> int:
    value = f"{bucket}\0{index}\0{text}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "little")


def _fixture_group(
    name: str, character_length: int, differing_positions: Iterable[int]
) -> FixtureGroup:
    positions = tuple(differing_positions)
    if not positions or any(position >= character_length for position in positions):
        raise ValueError("fixture differing positions are outside the surface")
    symbols = "あいうえおか"
    candidates: list[Candidate] = []
    for index, symbol in enumerate(symbols):
        characters = ["さ"] * character_length
        for position in positions:
            characters[position] = symbol
        text = "".join(characters)
        candidates.append(
            Candidate(
                fingerprint=_stable_fingerprint(name, index, text),
                local_cost=1_000 + index * 10,
                text=text,
            )
        )
    return FixtureGroup(name, character_length, positions, tuple(candidates))


def benchmark_fixtures() -> tuple[FixtureGroup, ...]:
    """Return fixed synthetic workloads spanning the requested length buckets."""

    return (
        _fixture_group("chars-3-to-9", 8, (7,)),
        _fixture_group("chars-10-to-30", 16, (3, 7, 11, 15)),
        _fixture_group("chars-31-to-128", 32, (3, 7, 11, 15, 19, 23, 27, 31)),
    )


def fixture_hash(fixtures: Iterable[FixtureGroup]) -> str:
    private_contract = [
        {
            "name": fixture.name,
            "surfaces": [candidate.text for candidate in fixture.candidates],
            "costs": [candidate.local_cost for candidate in fixture.candidates],
        }
        for fixture in fixtures
    ]
    encoded = json.dumps(
        private_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def encode_request(
    request_id: int, candidates: Iterable[Candidate], *, context: bytes = b""
) -> bytes:
    snapshot = tuple(candidates)
    if not 0 <= request_id <= 0xFFFF_FFFF_FFFF_FFFF:
        raise BenchmarkError("request ID is outside u64")
    if len(context) > 1_024:
        raise BenchmarkError("context exceeds protocol v1 bound")
    if not 1 <= len(snapshot) <= MAX_CANDIDATES:
        raise BenchmarkError("candidate count exceeds protocol v1 bound")

    payload = bytearray()
    payload.extend(struct.pack("<IHHQII", REQUEST_MAGIC, PROTOCOL_VERSION, 0, request_id, len(context), len(snapshot)))
    payload.extend(context)
    fingerprints: set[int] = set()
    for candidate in snapshot:
        text = candidate.text.encode("utf-8")
        if not text or len(text) > MAX_CANDIDATE_BYTES:
            raise BenchmarkError("candidate text exceeds protocol v1 bound")
        if not 0 <= candidate.fingerprint <= 0xFFFF_FFFF_FFFF_FFFF:
            raise BenchmarkError("candidate fingerprint is outside u64")
        if candidate.fingerprint in fingerprints:
            raise BenchmarkError("candidate fingerprints must be unique")
        if not 0 <= candidate.local_cost <= 0xFFFF_FFFF:
            raise BenchmarkError("candidate local cost is outside u32")
        fingerprints.add(candidate.fingerprint)
        payload.extend(
            struct.pack(
                "<QII",
                candidate.fingerprint,
                candidate.local_cost,
                len(text),
            )
        )
        payload.extend(text)
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise BenchmarkError("request exceeds protocol v1 frame bound")
    return struct.pack("<I", len(payload)) + payload


def decode_response(payload: bytes) -> WorkerResponse:
    header = struct.Struct("<IHHQHHI")
    if len(payload) < header.size:
        raise BenchmarkError("worker response is truncated")
    magic, version, status, request_id, tier, reserved, count = header.unpack_from(
        payload
    )
    if magic != RESPONSE_MAGIC or version != PROTOCOL_VERSION or reserved != 0:
        raise BenchmarkError("worker response header is invalid")
    if status not in (STATUS_SUCCESS, STATUS_FAILURE):
        raise BenchmarkError("worker returned an unknown status")
    if count > MAX_CANDIDATES:
        raise BenchmarkError("worker returned too many scores")
    expected_bytes = header.size + count * struct.calcsize("<Qf")
    if len(payload) != expected_bytes:
        raise BenchmarkError("worker response length does not match score count")

    scores: list[tuple[int, float]] = []
    cursor = header.size
    for _ in range(count):
        fingerprint, score = struct.unpack_from("<Qf", payload, cursor)
        cursor += struct.calcsize("<Qf")
        if not math.isfinite(score):
            raise BenchmarkError("worker returned a non-finite score")
        scores.append((fingerprint, score))
    if status == STATUS_SUCCESS and not scores:
        raise BenchmarkError("successful worker response has no scores")
    if status == STATUS_FAILURE and scores:
        raise BenchmarkError("failed worker response unexpectedly has scores")
    return WorkerResponse(request_id, status, tier, tuple(scores))


def _read_exact(stream: Any, byte_count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < byte_count:
        chunk = stream.read(byte_count - len(chunks))
        if not chunk:
            raise EOFError("worker response stream ended")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_response(stream: Any) -> WorkerResponse:
    length = struct.unpack("<I", _read_exact(stream, 4))[0]
    if length == 0 or length > MAX_FRAME_BYTES:
        raise BenchmarkError("worker response frame length is invalid")
    return decode_response(_read_exact(stream, length))


def _process_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0


def _worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = "-1"
    return environment


class WorkerClient:
    """One sequential worker connection with timeout and cleanup ownership."""

    def __init__(self, worker: Path, model_directory: Path) -> None:
        self._closed = False
        self._responses: queue.Queue[WorkerResponse | BaseException] = queue.Queue()
        self._process = subprocess.Popen(
            [os.fspath(worker), "--stdio", "--model-dir", os.fspath(model_directory)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=_worker_environment(),
            creationflags=_process_creation_flags(),
        )
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise BenchmarkError("worker pipes were not created")
        self._reader = threading.Thread(
            target=self._read_loop,
            name="current-tiny-benchmark-response",
            daemon=False,
        )
        self._reader.start()

    @property
    def pid(self) -> int:
        return self._process.pid

    def _read_loop(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                self._responses.put(_read_response(self._process.stdout))
        except BaseException as error:
            self._responses.put(error)

    def score(
        self,
        request_id: int,
        candidates: Iterable[Candidate],
        *,
        timeout_seconds: float,
    ) -> WorkerResponse:
        if self._closed or self._process.stdin is None:
            raise BenchmarkError("worker connection is closed")
        snapshot = tuple(candidates)
        frame = encode_request(request_id, snapshot)
        try:
            self._process.stdin.write(frame)
            self._process.stdin.flush()
        except OSError as error:
            raise BenchmarkError("unable to write worker request") from error
        try:
            response = self._responses.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise BenchmarkError("worker response timed out") from error
        if isinstance(response, BaseException):
            raise BenchmarkError("worker response stream failed") from response
        if response.request_id != request_id:
            raise BenchmarkError("worker response request ID does not match")
        expected = {candidate.fingerprint for candidate in snapshot}
        actual = {fingerprint for fingerprint, _ in response.scores}
        if response.status == STATUS_SUCCESS and actual != expected:
            raise BenchmarkError("worker response fingerprints do not match")
        return response

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        if self._process.stdout is not None:
            try:
                self._process.stdout.close()
            except OSError:
                pass
        reader = getattr(self, "_reader", None)
        if reader is not None:
            reader.join(timeout=2)
            if reader.is_alive():
                raise BenchmarkError("worker response reader did not stop")

    def __enter__(self) -> WorkerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _windows_memory_snapshot(process_id: int) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"supported": False, "reason": "Windows-only measurement"}

    from ctypes import wintypes

    process_query_information = 0x0400
    process_vm_read = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.QueryWorkingSet.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD]
    psapi.QueryWorkingSet.restype = wintypes.BOOL

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
            ("private_usage", ctypes.c_size_t),
        ]

    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        process_query_information | process_vm_read, False, process_id
    )
    if not handle:
        return {
            "supported": False,
            "reason": f"OpenProcess failed with Windows error {ctypes.get_last_error()}",
        }
    try:
        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            raise BenchmarkError(
                f"GetProcessMemoryInfo failed with Windows error {ctypes.get_last_error()}"
            )

        pointer_bytes = ctypes.sizeof(ctypes.c_size_t)
        buffer_bytes = 1 << 20
        working_set_values: Any = None
        for _ in range(8):
            raw = ctypes.create_string_buffer(buffer_bytes)
            if psapi.QueryWorkingSet(handle, raw, buffer_bytes):
                entry_count = ctypes.c_size_t.from_buffer_copy(raw).value
                required = (entry_count + 1) * pointer_bytes
                if required <= buffer_bytes:
                    array_type = ctypes.c_size_t * (entry_count + 1)
                    working_set_values = array_type.from_buffer_copy(raw, 0)
                    break
            buffer_bytes *= 2
        if working_set_values is None:
            raise BenchmarkError(
                f"QueryWorkingSet failed with Windows error {ctypes.get_last_error()}"
            )
        private_pages = sum(
            1 for flags in working_set_values[1:] if ((int(flags) >> 8) & 1) == 0
        )
        return {
            "supported": True,
            "working_set_bytes": int(counters.working_set_size),
            "peak_working_set_bytes": int(counters.peak_working_set_size),
            "private_commit_bytes": int(counters.private_usage),
            "private_working_set_bytes": private_pages * mmap.PAGESIZE,
            "private_working_set_method": "QueryWorkingSet non-shared resident pages",
        }
    finally:
        kernel32.CloseHandle(handle)


def percentile_nearest_rank(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile of no values")
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def latency_summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = list(values)
    if not samples:
        return {"count": 0}
    return {
        "count": len(samples),
        "min_ms": round(min(samples), 6),
        "mean_ms": round(statistics.fmean(samples), 6),
        "p50_ms": round(percentile_nearest_rank(samples, 0.50), 6),
        "p95_ms": round(percentile_nearest_rank(samples, 0.95), 6),
        "p99_ms": round(percentile_nearest_rank(samples, 0.99), 6),
        "max_ms": round(max(samples), 6),
    }


def _probe_once(worker: Path, model_directory: Path, timeout_seconds: float) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter_ns()
    completed = subprocess.run(
        [os.fspath(worker), "--probe", "--model-dir", os.fspath(model_directory)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        env=_worker_environment(),
        creationflags=_process_creation_flags(),
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    if completed.returncode != 0:
        raise BenchmarkError(f"worker probe exited with code {completed.returncode}")
    try:
        metadata = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkError("worker probe did not return valid JSON") from error
    return elapsed_ms, metadata


def _status_name(status: int) -> str:
    return "success" if status == STATUS_SUCCESS else "worker-failure"


def _maximum_memory(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [sample for sample in samples if sample.get("supported")]
    if not snapshots:
        return {"supported": False, "sample_count": 0}
    numeric_fields = (
        "working_set_bytes",
        "peak_working_set_bytes",
        "private_commit_bytes",
        "private_working_set_bytes",
    )
    result: dict[str, Any] = {
        "supported": True,
        "sample_count": len(snapshots),
        "private_working_set_method": snapshots[0]["private_working_set_method"],
    }
    for field in numeric_fields:
        result[f"max_{field}"] = max(int(sample[field]) for sample in snapshots)
    return result


def run_benchmark(
    *,
    worker: Path,
    model_directory: Path,
    runs: int,
    warmup_per_bucket: int,
    cold_samples: int,
    probe_samples: int,
    timeout_seconds: float,
    expected_worker_sha256: str | None = None,
    expected_model_sha256: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    if runs <= 0 or warmup_per_bucket < 0 or cold_samples <= 0 or probe_samples <= 0:
        raise BenchmarkError("run and sample counts are outside their allowed range")
    worker = worker.resolve(strict=True)
    model_directory = model_directory.resolve(strict=True)
    model = model_directory / "model.onnx"
    manifest = model_directory / "manifest.json"
    vocabulary = model_directory / "vocab.txt"
    worker_record = file_record(worker, display_path=worker.name)
    model_record = file_record(model, display_path=model.name)
    if expected_worker_sha256 and worker_record["sha256"] != expected_worker_sha256:
        raise BenchmarkError("worker SHA-256 does not match the pinned baseline")
    if expected_model_sha256 and model_record["sha256"] != expected_model_sha256:
        raise BenchmarkError("model SHA-256 does not match the pinned baseline")

    fixtures = benchmark_fixtures()
    probe_latencies: list[float] = []
    probe_metadata: list[dict[str, Any]] = []
    for _ in range(probe_samples):
        elapsed, metadata = _probe_once(worker, model_directory, timeout_seconds)
        probe_latencies.append(elapsed)
        probe_metadata.append(metadata)
    if any(metadata != probe_metadata[0] for metadata in probe_metadata[1:]):
        raise BenchmarkError("worker probe metadata changed between samples")

    cold_latencies: list[float] = []
    cold_statuses: dict[str, int] = {}
    cold_memory: list[dict[str, Any]] = []
    cold_tiers: set[int] = set()
    for sample in range(cold_samples):
        started = time.perf_counter_ns()
        with WorkerClient(worker, model_directory) as client:
            response = client.score(
                sample + 1,
                fixtures[0].candidates,
                timeout_seconds=timeout_seconds,
            )
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            cold_latencies.append(elapsed_ms)
            name = _status_name(response.status)
            cold_statuses[name] = cold_statuses.get(name, 0) + 1
            cold_tiers.add(response.tier)
            cold_memory.append(_windows_memory_snapshot(client.pid))

    per_bucket_latencies: dict[str, list[float]] = {
        fixture.name: [] for fixture in fixtures
    }
    per_bucket_statuses: dict[str, dict[str, int]] = {
        fixture.name: {} for fixture in fixtures
    }
    warm_memory: list[dict[str, Any]] = []
    warm_tiers: set[int] = set()
    next_request_id = cold_samples + 1
    with WorkerClient(worker, model_directory) as client:
        for fixture in fixtures:
            for _ in range(warmup_per_bucket):
                response = client.score(
                    next_request_id,
                    fixture.candidates,
                    timeout_seconds=timeout_seconds,
                )
                next_request_id += 1
                warm_tiers.add(response.tier)
        warm_memory.append(_windows_memory_snapshot(client.pid))

        memory_interval = max(1, runs // 10)
        for index in range(runs):
            fixture = fixtures[index % len(fixtures)]
            started = time.perf_counter_ns()
            response = client.score(
                next_request_id,
                fixture.candidates,
                timeout_seconds=timeout_seconds,
            )
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            next_request_id += 1
            warm_tiers.add(response.tier)
            per_bucket_latencies[fixture.name].append(elapsed_ms)
            statuses = per_bucket_statuses[fixture.name]
            name = _status_name(response.status)
            statuses[name] = statuses.get(name, 0) + 1
            if (index + 1) % memory_interval == 0 or index + 1 == runs:
                warm_memory.append(_windows_memory_snapshot(client.pid))
            if progress is not None:
                progress(index + 1, runs)

    aggregate_latencies = [
        latency
        for fixture in fixtures
        for latency in per_bucket_latencies[fixture.name]
    ]
    bucket_records = {}
    for fixture in fixtures:
        bucket_records[fixture.name] = {
            "fixture": fixture.public_record(),
            "request_payload_bytes": len(encode_request(1, fixture.candidates)),
            "outcomes": per_bucket_statuses[fixture.name],
            "latency": latency_summary(per_bucket_latencies[fixture.name]),
        }

    environment = collect_environment()
    environment.update(
        {
            "architecture": platform.architecture()[0],
            "logical_processor_count": os.cpu_count(),
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "constraints": {
            "production_device": "Windows CPU",
            "gpu_visible_to_child": False,
            "concurrent_request_batch": 1,
            "request_processing": "sequential",
            "ort_mask_row_batch_max_from_source_contract": 6,
            "ort_intra_threads_from_source_contract": 1,
            "ort_inter_threads_from_source_contract": 1,
            "percentile_method": "nearest-rank",
            "raw_candidate_text_recorded": False,
        },
        "artifacts": {
            "worker": worker_record,
            "model": model_record,
            "manifest": file_record(manifest, display_path=manifest.name),
            "vocabulary": file_record(vocabulary, display_path=vocabulary.name),
        },
        "protocol": {
            "version": PROTOCOL_VERSION,
            "context_bytes": 0,
            "reading_field_present": False,
            "candidate_count": MAX_CANDIDATES,
        },
        "fixture": {
            "kind": "fixed-synthetic-no-user-data",
            "sha256": fixture_hash(fixtures),
            "groups": [fixture.public_record() for fixture in fixtures],
        },
        "configuration": {
            "probe_samples": probe_samples,
            "cold_samples": cold_samples,
            "warmup_per_bucket": warmup_per_bucket,
            "measured_warm_runs": runs,
            "response_timeout_seconds": timeout_seconds,
        },
        "probe_startup": {
            "metadata": probe_metadata[0],
            "latency": latency_summary(probe_latencies),
        },
        "cold_process_to_first_response": {
            "outcomes": cold_statuses,
            "tiers": sorted(cold_tiers),
            "latency": latency_summary(cold_latencies),
            "memory": _maximum_memory(cold_memory),
        },
        "warm_worker_roundtrip": {
            "tiers": sorted(warm_tiers),
            "aggregate_latency": latency_summary(aggregate_latencies),
            "buckets": bucket_records,
            "memory": _maximum_memory(warm_memory),
        },
        "limitations": [
            "Black-box protocol v1 cannot separate tokenization, ORT inference, score fusion, and IPC latency.",
            (
                "Synthetic fixed surfaces characterize bounded worker workloads; "
                "they are not a quality corpus or live-user trace."
            ),
            (
                "Expected ORT call counts are inferred from the exact current "
                "scorer source and one-character tokenizer contract."
            ),
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the released Sakura Input Tiny worker"
    )
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=10_000)
    parser.add_argument("--warmup-per-bucket", type=int, default=10)
    parser.add_argument("--cold-samples", type=int, default=5)
    parser.add_argument("--probe-samples", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--expect-worker-sha256")
    parser.add_argument("--expect-model-sha256")
    parser.add_argument("--progress-every", type=int, default=1_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.progress_every < 0:
        raise SystemExit("--progress-every must be non-negative")

    def progress(completed: int, total: int) -> None:
        if arguments.progress_every and (
            completed % arguments.progress_every == 0 or completed == total
        ):
            print(f"warm worker requests: {completed}/{total}", flush=True)

    try:
        report = run_benchmark(
            worker=arguments.worker,
            model_directory=arguments.model_dir,
            runs=arguments.runs,
            warmup_per_bucket=arguments.warmup_per_bucket,
            cold_samples=arguments.cold_samples,
            probe_samples=arguments.probe_samples,
            timeout_seconds=arguments.timeout_seconds,
            expected_worker_sha256=arguments.expect_worker_sha256,
            expected_model_sha256=arguments.expect_model_sha256,
            progress=progress,
        )
        write_json_atomic(arguments.output, report)
    except (BenchmarkError, OSError, ValueError) as error:
        print(f"current Tiny benchmark failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
