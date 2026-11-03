"""Re-measure the frozen v1 ONNX exports with the revision-2 timing scope.

v1's benchmark (``research_tiny.benchmark_onnx``) started its timer before
calling ``feed(i)``, and ``feed`` indexed eight dev arrays of the lazily loaded
.npz on every call, so each timed run also re-read those arrays.  This one-off
measurement builds the feeds before timing, exactly like
``research_tiny_r2.benchmark_onnx``, so v1 and r2 latencies are comparable.
Output: aggregate timings and hashes only.

Usage: python -I v1_latency_same_scope.py <output.json>
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402

EXP = Path(__file__).resolve().parent
REPO = EXP.parents[2]
V1 = EXP.parents[0] / "sakura-rerank-tiny-v1-research"
V1_MANIFEST = REPO / "manifests" / "sakura-rerank-tiny-v1-research-prototype.json"
V1_REPORT = REPO / "reports" / "sakura-rerank-tiny-v1-research-prototype.json"
NAMES = ("context_ids", "context_lengths", "reading_ids", "reading_lengths",
         "candidate_ids", "candidate_lengths", "features", "candidate_mask")
DEV_COUNT = 1_788
WARMUP, MEASURED = 100, 10_000
TIMING_SCOPE = "inference_session_run_only_inputs_prebuilt"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(model: Path, expected_sha256: str, feed_for, *, published_method: bool = False) -> dict[str, object]:
    """Time batch-one runs.  ``published_method`` repeats v1's loop exactly:
    the clock starts before ``feed_for`` builds the inputs and stops after the
    result check."""
    if sha(model) != expected_sha256:
        raise SystemExit(f"{model.name} differs from the v1 manifest")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    for index in range(WARMUP):
        session.run(["scores"], feed_for(index % DEV_COUNT))
    timings, failures = [], 0
    for index in range(MEASURED):
        feed = None if published_method else feed_for(index % DEV_COUNT)
        before = time.perf_counter_ns()
        try:
            result = session.run(["scores"], feed_for(index % DEV_COUNT) if published_method else feed)[0]
            elapsed = time.perf_counter_ns() - before
            if result.shape != (1, 6) or not np.isfinite(result).all():
                raise RuntimeError("invalid score tensor")
            if published_method:
                elapsed = time.perf_counter_ns() - before
        except Exception:
            failures += 1
        else:
            timings.append(elapsed / 1_000_000)
    if failures or len(timings) != MEASURED:
        raise SystemExit("benchmark contained failures")
    ordered = sorted(timings)

    def percentile(proportion: float) -> float:
        return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]

    return {
        "model": {"file": model.name, "bytes": model.stat().st_size, "sha256": expected_sha256},
        "latency_ms": {"mean": round(statistics.fmean(timings), 6), "p50": round(percentile(0.50), 6),
                       "p95": round(percentile(0.95), 6), "p99": round(percentile(0.99), 6),
                       "max": round(max(timings), 6)},
        "provider": session.get_providers(),
    }


def main() -> None:
    target = Path(sys.argv[1])
    if target.exists():
        raise SystemExit("refusing to overwrite")
    manifest = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    published = json.loads(V1_REPORT.read_text(encoding="utf-8"))["windows_cpu_batch_one"]
    with np.load(V1 / "train-dev-cache.npz", allow_pickle=False) as cache:
        dev = {name: np.array(cache[f"dev_{name}"]) for name in NAMES}
        feeds = [{name: dev[name][index:index + 1] for name in NAMES} for index in range(DEV_COUNT)]
        exports = {label: (V1 / manifest["exports"][label]["file"], manifest["exports"][label]["sha256"])
                   for label in ("fp32", "int8")}
        measured = {label: measure(*exports[label], feeds.__getitem__) for label in ("fp32", "int8")}
        # v1's own feed: index the lazily loaded archive on every call.
        published_method = measure(
            *exports["fp32"],
            lambda index: {name: cache[f"dev_{name}"][index:index + 1] for name in NAMES},
            published_method=True,
        )
    report = {
        "schema_version": 1,
        "report_kind": "sakura_rerank_tiny_v1_latency_same_scope_as_r2",
        "status": "research_only_gate_a_failed",
        "issue": 21,
        "timing_scope": TIMING_SCOPE,
        "contract": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "onnxruntime": ort.__version__,
            "gpu_disabled": True,
            "batch_size": 1,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "warmup_runs": WARMUP,
            "measured_runs": MEASURED,
            "failure_count": 0,
            "final_holdout_used": False,
        },
        "v1_model_manifest_sha256": sha(V1_MANIFEST),
        "fp32": measured["fp32"],
        "int8": measured["int8"],
        "published_v1_benchmark": {
            "report_sha256": sha(V1_REPORT),
            "timing_scope": "session_run_plus_eight_lazy_npz_dev_array_reads_per_run",
            "platform": published["contract"]["platform"],
            "fp32_latency_ms": published["fp32"]["latency_ms"],
            "int8_latency_ms": published["int8"]["latency_ms"],
            # The same loop re-run now, on this machine, isolates the scope
            # difference from the platform difference.
            "fp32_latency_ms_remeasured_with_published_method": published_method["latency_ms"],
        },
        "script_sha256": sha(Path(__file__)),
        "final_holdout_used": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    data = (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")
    target.write_bytes(data)
    print(json.dumps({label: report[label]["latency_ms"] for label in ("fp32", "int8")}))


if __name__ == "__main__":
    main()
