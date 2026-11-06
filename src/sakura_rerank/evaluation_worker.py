"""Bounded spawned evaluation workers; no dataset paths, retries or raw logs."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import importlib.metadata
import inspect
import json
import math
import multiprocessing as mp
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import platform
import time
from types import MappingProxyType
from typing import Callable, Mapping

from .data.contracts import canonical_json_bytes

MAX_SHARED_BYTES = 1024 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
STATUS = {0: "unavailable", 1: "complete", 2: "malformed", 3: "error", 4: "stale", 5: "timeout"}


class WorkerError(RuntimeError):
    """A sanitized execution/lifecycle failure; never includes model/input text."""


class StaleResult(WorkerError):
    """Adapter observed an invalid response identity/fingerprint."""


class _WindowsJob:
    """Own the worker and native descendants, including after a parent crash."""

    def __init__(self, pid: int):
        if os.name != "nt":
            raise WorkerError("bounded evaluator execution requires Windows")
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                ("active_limit", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_longlong * 4), ("faults", w.DWORD),
                ("total", w.DWORD), ("active", w.DWORD), ("terminated", w.DWORD)]
        self._accounting = Accounting
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([w.LPVOID, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self._api, name)
            function.argtypes, function.restype = args, result
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise WorkerError("cannot create worker process job")
        try:
            limits = Extended()
            limits.basic.flags = 0x2000 | 0x8  # kill-on-close; no breakaway; <=4 processes.
            limits.basic.active_limit = 4
            if not self._api.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise WorkerError("cannot set worker job limits")
            process = self._api.OpenProcess(0x0100 | 0x0001, False, pid)
            if not process:
                raise WorkerError("cannot open owned worker for containment")
            try:
                if not self._api.AssignProcessToJobObject(self._handle, process):
                    raise WorkerError("cannot contain owned worker")
            finally:
                self._api.CloseHandle(process)
        except BaseException:
            self._api.CloseHandle(self._handle)
            self._handle = None
            raise

    def _active(self) -> int:
        value = self._accounting()
        if not self._api.QueryInformationJobObject(self._handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise WorkerError("cannot inspect worker job termination")
        return value.active

    def close(self, grace: float) -> dict:
        if self._handle is None:
            return {"active_remaining": 0, "terminated_processes": 0}
        try:
            active = self._active()
            if active and not self._api.TerminateJobObject(self._handle, 1):
                raise WorkerError("cannot terminate owned process tree")
            deadline = time.monotonic() + grace
            while self._active():
                if time.monotonic() >= deadline:
                    raise WorkerError("owned process tree did not terminate in time")
                time.sleep(.01)
            return {"active_remaining": 0, "terminated_processes": active}
        finally:
            self._api.CloseHandle(self._handle)
            self._handle = None


@dataclass(frozen=True)
class Adapter:
    factory: Callable
    validate: Callable

    def identity(self) -> dict:
        result = {}
        for name in ("factory", "validate"):
            function = getattr(self, name)
            path = inspect.getsourcefile(function)
            if path is None or "<locals>" in function.__qualname__:
                raise WorkerError("adapter must be an importable source function")
            result[name] = {"symbol": function.__module__ + ":" + function.__qualname__,
                            "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        return result


def runtime_identity() -> dict:
    root = Path(__file__).parent
    files = ("evaluation_worker.py", "evaluation_runner.py", "evaluation_payload.py",
             "evaluation_admission.py", "evaluation_metrics.py", "evaluation_statistics.py",
             "source_model_inputs.py", "research_tiny.py", "research_tiny_r2.py", "data/contracts.py", "current_tiny.py",
             "native_snapshot.py", "native_paths.py", "native_path_inputs.py")
    versions = {}
    for package in ("numpy", "onnxruntime"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {"python": platform.python_version(), "system": platform.system(),
            "packages": versions,
            "sources": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files}}


def validate_gru(artifacts: Mapping[str, bytes], feature_width: int) -> None:
    from .evaluation_payload import document
    from .research_tiny import VOCAB_SIZE
    tokenizer = document(artifacts["tokenizer"])
    features = document(artifacts["features"])
    if (any(type(tokenizer.get(key)) is not int for key in ("version", "vocab_size", "context_length", "reading_length", "surface_length"))
            or tokenizer != {"kind": "tiny_character_hash", "version": 1, "vocab_size": VOCAB_SIZE,
                     "context_length": 64, "reading_length": 32, "surface_length": 32, "truncation": "prefix"}):
        raise WorkerError("unsupported GRU tokenizer contract")
    if (type(feature_width) is not int or feature_width not in (6, 7)
            or type(features.get("version")) is not int or type(features.get("width")) is not int or features != {
        "kind": "tiny_candidate_features", "version": 1, "width": feature_width,
        "cost_gap_scale": 1000 if feature_width == 7 else None,
    }):
        raise WorkerError("unsupported GRU feature contract")


def cpu_session(weights: bytes, feature_width: int):
    """Shared CPU/batch-one ONNX boundary; each adapter owns its input semantics."""
    import onnxruntime as ort
    from .source_model_inputs import INPUT_NAMES
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.log_severity_level = 4
    session = ort.InferenceSession(weights, sess_options=options, providers=["CPUExecutionProvider"])
    if (session.get_providers() != ["CPUExecutionProvider"]
            or [v.name for v in session.get_inputs()] != list(INPUT_NAMES)
            or session.get_inputs()[6].shape[-1] != feature_width
            or [v.name for v in session.get_outputs()] != ["scores"]):
        raise WorkerError("unsupported GRU ONNX signature")
    return session


def cpu_scores(session, feed):
    import numpy as np
    value = session.run(["scores"], feed)[0]
    if not isinstance(value, np.ndarray) or value.shape != (1, 6) or value.dtype != np.float32:
        return ()
    return tuple(float(v) for v in value[0])


def gru_factory(artifacts: Mapping[str, bytes], feature_width: int):
    from .research_tiny import character_ids
    from .source_model_inputs import encode_snapshot, model_feed
    validate_gru(artifacts, feature_width)
    session = cpu_session(artifacts["weights"], feature_width)

    class Scorer:
        def score(self, request):
            candidates = request["candidates"]
            snapshot = {"reading": request["reading"], "candidate_snapshots": {
                "production_top6": {"candidates": candidates}, "training_top32": {"candidates": candidates}}}
            arrays, _ = encode_snapshot(snapshot)
            ids, length = character_ids(request["left_context"], 64)
            arrays["context_ids"][0] = ids
            arrays["context_lengths"][0] = length
            return cpu_scores(session, model_feed(arrays, 0, feature_width))

        def close(self):
            pass  # The isolated process owns the ORT session lifetime.

    return Scorer()


def default_adapters() -> dict[str, Adapter]:
    from .current_tiny import current_factory, native_current_factory, validate_current
    from .native_path_inputs import native_gru_factory
    return {"tiny-gru-onnx-v1": Adapter(gru_factory, validate_gru),
            "current-tiny-protocol-v1": Adapter(current_factory, validate_current),
            "current-tiny-native-population-v1": Adapter(native_current_factory, validate_current),
            "native-path-tiny-gru-v1": Adapter(native_gru_factory, validate_gru)}


def _quiet_child() -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    # Also silence native ORT diagnostics, not only Python exception messages.
    for fd in (1, 2):
        with open(os.devnull, "wb") as stream:
            os.dup2(stream.fileno(), fd)


def _model_child(input_name, output_name, descriptor, adapter, expected_identity, expected_runtime, width, progress, contained):
    _quiet_child()
    if not contained.wait(120):
        return  # Parent failed before containment; no adapter may run.
    import numpy as np
    source = output = scorer = None
    states = scores = None
    try:
        source = SharedMemory(input_name)
        output = SharedMemory(output_name)
        if adapter.identity() != expected_identity or runtime_identity() != expected_runtime:
            raise WorkerError("adapter source changed before worker execution")
        requests = json.loads(bytes(source.buf[:descriptor["requests"]]))
        artifacts = MappingProxyType({name: bytes(source.buf[start:end]) for name, (start, end) in descriptor["artifacts"].items()})
        count = len(requests)
        states = np.ndarray((count,), dtype=np.int64, buffer=output.buf)
        scores = np.ndarray((count, 6), dtype=np.float64, buffer=output.buf, offset=count * 8)
        scorer = adapter.factory(artifacts, width)
        for i, request in enumerate(requests):
            progress[0] = i
            try:
                values = scorer.score(request)
                if (not isinstance(values, (tuple, list)) or len(values) != 6
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                    states[i] = 2
                    progress[1] = 2
                    return
                scores[i] = values
                states[i] = 1  # Commit only after all six values are present.
            except StaleResult:
                states[i], progress[1] = 4, 4
                return
            except BaseException:
                states[i], progress[1] = 3, 3
                return
        progress[1] = 1
    except BaseException:
        progress[1] = 3
    finally:
        progress[0] = -3  # Cleanup is bounded separately from startup/requests.
        try:
            if scorer is not None:
                scorer.close()
        except BaseException:
            progress[1] = 3
        states = scores = None
        for memory in (output, source):
            if memory is not None:
                memory.close()


def _stop(process, grace: float, job=None) -> dict:
    forced = False
    containment = job.close(grace) if job is not None else None
    if containment is not None:
        process.join(grace)
    if process.is_alive():
        forced = True
        process.terminate()
        process.join(grace)
    if process.is_alive():
        process.kill()
        process.join(grace)
    if process.is_alive():
        raise WorkerError("owned worker did not terminate")
    result = {"pid": process.pid, "exit_code": process.exitcode,
              "forced": forced or bool(containment and containment["terminated_processes"]),
              "exited": True, "job": containment}
    process.close()
    return result


def _release(memory) -> None:
    if memory is not None:
        memory.close()
        memory.unlink()


def execute_model(requests: list[dict], artifacts: Mapping[str, bytes], adapter: Adapter,
                  width: int, limits: Mapping[str, float], *, deadline: float,
                  expected_identity: dict | None = None, expected_runtime: dict | None = None) -> dict:
    """One bounded process; preserve the entire supplied request denominator."""
    import numpy as np
    if os.name != "nt":
        raise WorkerError("bounded evaluator execution requires Windows")
    expected_identity = adapter.identity() if expected_identity is None else expected_identity
    expected_runtime = runtime_identity() if expected_runtime is None else expected_runtime
    if adapter.identity() != expected_identity or runtime_identity() != expected_runtime:
        raise WorkerError("frozen execution identity changed")
    raw = canonical_json_bytes(requests)
    descriptor = {"requests": len(raw), "artifacts": {}}
    end = len(raw)
    for name, payload in artifacts.items():
        descriptor["artifacts"][name] = (end, end + len(payload))
        end += len(payload)
    if not 1 <= len(requests) <= 100_000 or end > MAX_SHARED_BYTES:
        raise WorkerError("model execution byte or row bound exceeded")
    source = output = process = job = None
    states = scores = None
    ctx = mp.get_context("spawn")
    progress = ctx.RawArray("q", [-2, 0])
    contained = ctx.Event()
    reason = "complete"
    receipt = None
    try:
        source = SharedMemory(create=True, size=end)
        output = SharedMemory(create=True, size=len(requests) * 56)
        source.buf[:len(raw)] = raw
        for name, (start, stop) in descriptor["artifacts"].items():
            source.buf[start:stop] = artifacts[name]
        output.buf[:] = b"\0" * output.size
        process = ctx.Process(target=_model_child, args=(source.name, output.name, descriptor, adapter,
                              expected_identity, expected_runtime, width, progress, contained), daemon=False)
        started = time.monotonic()
        phase, phase_started = -2, started
        process.start()
        job = _WindowsJob(process.pid)
        contained.set()
        while process.is_alive():
            now = time.monotonic()
            current = progress[0]
            if current != phase:
                phase, phase_started = current, now
            phase_limit = limits["startup_seconds"] if phase == -2 else limits["shutdown_seconds"] if phase == -3 else limits["request_seconds"]
            end_time = min(deadline, started + limits["model_seconds"], phase_started + phase_limit)
            if now >= end_time:
                reason = "timeout"
                break
            process.join(min(.05, end_time - now))
        receipt = _stop(process, limits["shutdown_seconds"], job)
        process = None
        active = progress[0]
        states = np.ndarray((len(requests),), dtype=np.int64, buffer=output.buf)
        scores = np.ndarray((len(requests), 6), dtype=np.float64, buffer=output.buf, offset=len(requests)*8)
        if reason == "timeout" and 0 <= active < len(requests) and states[active] == 0:
            states[active] = 5
        elif (receipt["exit_code"] != 0 or progress[1] != 1) and 0 <= active < len(requests) and states[active] == 0:
            states[active] = 3
        if reason == "complete" and (progress[1] != 1 or receipt["exit_code"] != 0):
            reason = "worker_failure"
        if any(int(value) not in STATUS for value in states):
            raise WorkerError("invalid worker terminal state")
        values = [tuple(float(v) for v in row) if state == 1 else None for row, state in zip(scores, states)]
        result = {"states": [STATUS[int(v)] for v in states], "scores": values,
                  "complete": reason == "complete" and bool(np.all(states == 1)),
                  "terminal": reason, "process": receipt,
                  "request_count": len(requests), "attempted": int(np.count_nonzero(states))}
        return result
    finally:
        try:
            if process is not None:
                _stop(process, limits["shutdown_seconds"], job)
        finally:
            states = scores = None
            try:
                _release(output)
            finally:
                _release(source)


def _metrics_child(input_name, size, output_name, length, contained):
    _quiet_child()
    if not contained.wait(120):
        return
    source = output = None
    try:
        source = SharedMemory(input_name)
        output = SharedMemory(output_name)
        from .evaluation_runner import score_sealed_outputs
        raw = canonical_json_bytes(score_sealed_outputs(json.loads(bytes(source.buf[:size]))))
        if len(raw) > MAX_RESULT_BYTES:
            raise WorkerError("aggregate result exceeds byte bound")
        output.buf[:len(raw)] = raw
        length.value = len(raw)
    except BaseException:
        length.value = -1
    finally:
        for memory in (output, source):
            if memory is not None:
                memory.close()


def execute_metrics(payload: dict, timeout: float, grace: float) -> tuple[dict, dict]:
    if os.name != "nt":
        raise WorkerError("bounded evaluator execution requires Windows")
    raw = canonical_json_bytes(payload)
    if len(raw) > MAX_SHARED_BYTES or timeout <= 0:
        raise WorkerError("metrics work bound exceeded")
    source = output = process = job = None
    try:
        source = SharedMemory(create=True, size=len(raw))
        output = SharedMemory(create=True, size=MAX_RESULT_BYTES)
        source.buf[:len(raw)] = raw
        ctx = mp.get_context("spawn")
        length = ctx.RawValue("q", 0)
        contained = ctx.Event()
        process = ctx.Process(target=_metrics_child, args=(source.name, len(raw), output.name, length, contained))
        process.start()
        job = _WindowsJob(process.pid)
        contained.set()
        process.join(timeout)
        timed_out = process.is_alive()
        receipt = _stop(process, grace, job)
        process = None
        if timed_out or receipt["exit_code"] != 0 or not 1 <= length.value <= MAX_RESULT_BYTES:
            raise WorkerError("metrics worker failed or timed out")
        return json.loads(bytes(output.buf[:length.value])), receipt
    finally:
        try:
            if process is not None:
                _stop(process, grace, job)
        finally:
            try:
                _release(output)
            finally:
                _release(source)
