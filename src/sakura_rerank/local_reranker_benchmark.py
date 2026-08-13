"""Reproducible local Japanese cross-encoder comparison.

The public benchmark uses MTEB's own reranking evaluator.  Production-style
latency is measured separately at ONNX batch size one; the two numbers must
never be conflated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sakura_rerank.atomic_io import write_bytes_atomic


SCHEMA_VERSION = 1
ONNX_FILE = "onnx/model_qint8_avx2.onnx"
TASKS = {
    "JQaRARerankingLite": {
        "dataset": "mteb/JQaRARerankingLite",
        "revision": "d23d3ad479f74824ed126052e810eac47e685558",
        "split": "test",
        "pairs": 91_353,
        "main_score": "ndcg_at_10",
    },
    "JaCWIRRerankingLite": {
        "dataset": "mteb/JaCWIRRerankingLite",
        "revision": "b7c738193fb9b20c97c2b5d9a8fa3f3d28503dc0",
        "split": "test",
        "pairs": 161_744,
        "main_score": "ndcg_at_10",
    },
}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repository: str
    revision: str
    parameters: int
    onnx_sha256: str
    onnx_bytes: int


MODELS = {
    "tiny": ModelSpec(
        key="tiny",
        repository="hotchpotch/japanese-reranker-tiny-v2",
        revision="ba95175a4d53058816b971f31929f10c5cad8560",
        parameters=29_400_000,
        onnx_sha256="649a18583e21ad532e420a4ded4c9c4ff7ce882aa84af2bf2180ec4d4f679e38",
        onnx_bytes=29_634_681,
    ),
    "xsmall": ModelSpec(
        key="xsmall",
        repository="hotchpotch/japanese-reranker-xsmall-v2",
        revision="de99fd2f16c7b5df1df1bcc1d9ad2c16d88ce93a",
        parameters=36_800_000,
        onnx_sha256="34d4657df53c875f970dbf87e584a21d59e6cfcd9368f9828d69a09ed152168f",
        onnx_bytes=37_367_189,
    ),
}

LATENCY_FIXTURES = (
    ("日本の首都はどこですか", "東京は日本の首都であり、最大の都市圏を形成する。"),
    ("機械学習とは", "機械学習はデータから規則性を学ぶ計算手法の総称である。"),
    ("桜の開花時期", "桜の開花時期は地域やその年の気候によって異なる。"),
    ("Windowsで動く検索モデル", "ONNX Runtime は Windows CPU 上でも推論を実行できる。"),
    ("日本語の情報検索", "検索結果を関連度順に並べ直す処理をリランキングと呼ぶ。"),
    ("富士山の高さ", "富士山の標高は三千七百七十六メートルである。"),
    ("料理の保存方法", "食品は種類に応じて冷蔵、冷凍、常温を使い分ける。"),
    ("台風への備え", "避難経路と非常用品を事前に確認することが重要である。"),
)


class BenchmarkError(RuntimeError):
    """A benchmark artifact or environment violated the fixed contract."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: Iterable[float], proportion: float) -> float:
    snapshot = sorted(values)
    if not snapshot:
        raise BenchmarkError("latency summary requires at least one successful run")
    index = max(0, math.ceil(proportion * len(snapshot)) - 1)
    return snapshot[index]


def latency_summary(values: Iterable[float]) -> dict[str, float | int]:
    snapshot = tuple(values)
    return {
        "successful_runs": len(snapshot),
        "mean_ms": round(statistics.fmean(snapshot), 6),
        "p50_ms": round(percentile(snapshot, 0.50), 6),
        "p95_ms": round(percentile(snapshot, 0.95), 6),
        "p99_ms": round(percentile(snapshot, 0.99), 6),
        "max_ms": round(max(snapshot), 6),
    }


def _session_options() -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return options


def load_model(spec: ModelSpec, cache_dir: Path) -> Any:
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(
        spec.repository,
        revision=spec.revision,
        device="cpu",
        cache_folder=str(cache_dir),
        backend="onnx",
        model_kwargs={
            "file_name": ONNX_FILE,
            "provider": "CPUExecutionProvider",
            "session_options": _session_options(),
        },
    )
    model_path = getattr(model.model, "model_path", None)
    if model_path is None:
        raise BenchmarkError("ONNX runtime did not expose the loaded model path")
    path = Path(model_path)
    if path.stat().st_size != spec.onnx_bytes or sha256_file(path) != spec.onnx_sha256:
        raise BenchmarkError("downloaded ONNX identity does not match the pinned model")
    providers = model.model.model.get_providers()
    if providers != ["CPUExecutionProvider"]:
        raise BenchmarkError(f"unexpected ONNX providers: {providers!r}")
    # MTEB 2.4.2 builds ModelMeta from ``name_or_path``. Optimum 2.1's ORT
    # wrapper omits that otherwise informational Transformers attribute.
    model.model.name_or_path = spec.repository
    return model


def _model_identity(spec: ModelSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "repository": spec.repository,
        "revision": spec.revision,
        "parameters": spec.parameters,
        "onnx_file": ONNX_FILE,
        "onnx_sha256": spec.onnx_sha256,
        "onnx_bytes": spec.onnx_bytes,
    }


def run_quality(spec: ModelSpec, cache_dir: Path, output: Path) -> dict[str, Any]:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from mteb import __version__ as mteb_version
    from mteb import evaluate, get_tasks
    from mteb.cache import ResultCache
    from mteb.models import CrossEncoderWrapper, ModelMeta
    from sentence_transformers import __version__ as sentence_transformers_version

    model = load_model(spec, cache_dir)
    # MTEB 2.4.2's automatic CrossEncoder metadata path assumes a model-card
    # ``tags`` list and crashes on these otherwise valid cards when it is null.
    # Build the same wrapper with hub metadata disabled; all benchmark-critical
    # identities remain pinned and recorded by this module.
    wrapped = CrossEncoderWrapper.__new__(CrossEncoderWrapper)
    wrapped.model = model
    wrapped.mteb_model_meta = ModelMeta.from_cross_encoder(
        model, revision=spec.revision, compute_metadata=False
    )
    wrapped.mteb_model_meta.n_parameters = spec.parameters
    tasks = get_tasks(tasks=list(TASKS))
    measured = {
        task.metadata.name: {
            "dataset": task.metadata.dataset["path"],
            "revision": task.metadata.dataset["revision"],
            "split": task.metadata.eval_splits[0],
            "pairs": task.metadata.n_samples[task.metadata.eval_splits[0]],
            "main_score": task.metadata.main_score,
        }
        for task in tasks
    }
    if measured != TASKS:
        raise BenchmarkError("installed MTEB task metadata differs from the pinned contract")
    started = time.perf_counter()
    result = evaluate(
        wrapped,
        tasks,
        cache=ResultCache(output.parent / f"mteb-cache-{spec.key}"),
        # The per-model cache is content-addressed by the pinned model revision.
        # This makes an interrupted multi-task run resumable without redoing a
        # fully published task result; incomplete tasks have no cache artifact.
        overwrite_strategy="only-missing",
        encode_kwargs={"batch_size": 32, "show_progress_bar": True},
        show_progress_bar=True,
    )
    elapsed = time.perf_counter() - started
    task_results = []
    for task_result in result.task_results:
        contract = TASKS[task_result.task_name]
        split_scores = task_result.scores[contract["split"]]
        if len(split_scores) != 1:
            raise BenchmarkError("benchmark expected exactly one score record per task split")
        scores = split_scores[0]
        value = scores.get(contract["main_score"])
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BenchmarkError("MTEB result lacks a finite main score")
        task_results.append(
            {
                "task": task_result.task_name,
                "dataset_revision": task_result.dataset_revision,
                "split": contract["split"],
                "pairs": contract["pairs"],
                "main_score": contract["main_score"],
                "score": round(float(value), 10),
                "evaluation_time_seconds": round(float(task_result.evaluation_time), 6),
            }
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "local_reranker_jmteb_quality",
        "model": _model_identity(spec),
        "software": {
            "mteb": mteb_version,
            "sentence_transformers": sentence_transformers_version,
        },
        "inference": {
            "backend": "onnxruntime",
            "provider": "CPUExecutionProvider",
            "gpu_disabled": True,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "evaluation_batch_size": 32,
        },
        "tasks": sorted(task_results, key=lambda item: item["task"]),
        "wall_time_seconds": round(elapsed, 6),
        "raw_text_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def build_partial_quality_from_cached_task(
    spec: ModelSpec,
    cached_result: Path,
    output: Path,
    *,
    skipped_task: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Publish aggregate evidence for a valid completed task after a user stop.

    MTEB publishes each task result atomically.  This adapter deliberately reads
    only the completed task artifact and never invents a score for the task that
    did not finish.
    """
    if skipped_task not in TASKS or timeout_seconds < 1:
        raise BenchmarkError("partial quality requires a known skipped task and timeout")
    try:
        raw = cached_result.read_bytes()
        cached = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkError("cached MTEB task result is unreadable") from error
    task_name = cached.get("task_name")
    if task_name not in TASKS or task_name == skipped_task:
        raise BenchmarkError("cached MTEB task identity is inconsistent with the skip")
    contract = TASKS[task_name]
    if (
        cached.get("dataset_revision") != contract["revision"]
        or cached.get("mteb_version") != "2.4.2"
    ):
        raise BenchmarkError("cached MTEB task provenance differs from the pinned contract")
    split_scores = cached.get("scores", {}).get(contract["split"])
    if not isinstance(split_scores, list) or len(split_scores) != 1:
        raise BenchmarkError("cached MTEB task has an unexpected score shape")
    score = split_scores[0].get(contract["main_score"])
    evaluation_time = cached.get("evaluation_time")
    if (
        not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not isinstance(evaluation_time, (int, float))
        or not math.isfinite(evaluation_time)
    ):
        raise BenchmarkError("cached MTEB task lacks finite aggregate measurements")
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "local_reranker_jmteb_quality",
        "status": "partial_user_skipped_after_timeout",
        "model": _model_identity(spec),
        "software": {"mteb": "2.4.2", "sentence_transformers": "5.1.1"},
        "inference": {
            "backend": "onnxruntime",
            "provider": "CPUExecutionProvider",
            "gpu_disabled": True,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "evaluation_batch_size": 32,
        },
        "tasks": [
            {
                "task": task_name,
                "dataset_revision": contract["revision"],
                "split": contract["split"],
                "pairs": contract["pairs"],
                "main_score": contract["main_score"],
                "score": round(float(score), 10),
                "evaluation_time_seconds": round(float(evaluation_time), 6),
            }
        ],
        "incomplete_tasks": [
            {
                "task": skipped_task,
                "status": "user_approved_skip_after_timeout",
                "timeout_seconds": timeout_seconds,
                "score_reported": False,
            }
        ],
        "source_task_result": {
            "file": cached_result.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "raw_text_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def run_latency(
    spec: ModelSpec,
    cache_dir: Path,
    output: Path,
    *,
    warmup_runs: int,
    measured_runs: int,
) -> dict[str, Any]:
    if warmup_runs < 1 or measured_runs < 10_000:
        raise BenchmarkError("latency requires warmup and at least 10,000 measured runs")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    model = load_model(spec, cache_dir)
    for index in range(warmup_runs):
        model.predict([LATENCY_FIXTURES[index % len(LATENCY_FIXTURES)]], batch_size=1, show_progress_bar=False)
    timings: list[float] = []
    failures = 0
    started = time.perf_counter()
    for index in range(measured_runs):
        pair = LATENCY_FIXTURES[index % len(LATENCY_FIXTURES)]
        before = time.perf_counter_ns()
        try:
            scores = model.predict([pair], batch_size=1, show_progress_bar=False)
            if len(scores) != 1 or not math.isfinite(float(scores[0])):
                raise BenchmarkError("model returned an invalid score")
        except Exception:
            failures += 1
        else:
            timings.append((time.perf_counter_ns() - before) / 1_000_000)
    wall = time.perf_counter() - started
    if failures or len(timings) != measured_runs:
        raise BenchmarkError(f"latency run had {failures} failures in {measured_runs} requests")
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "local_reranker_windows_cpu_latency",
        "model": _model_identity(spec),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "inference": {
            "backend": "onnxruntime",
            "provider": "CPUExecutionProvider",
            "gpu_disabled": True,
            "batch_size": 1,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "failure_count": failures,
            "fixture_count": len(LATENCY_FIXTURES),
            "fixture_content_sha256": hashlib.sha256(
                canonical_json_bytes(LATENCY_FIXTURES)
            ).hexdigest(),
        },
        "latency": latency_summary(timings),
        "wall_time_seconds": round(wall, 6),
        "raw_text_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def _read_report(path: Path, kind: str) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkError(f"invalid JSON report: {path}") from error
    if raw != canonical_json_bytes(value):
        raise BenchmarkError(f"report is not canonical JSON plus LF: {path}")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("report_kind") != kind:
        raise BenchmarkError(f"unexpected report contract: {path}")
    return value


def build_comparison(inputs: list[Path], output: Path) -> dict[str, Any]:
    quality: dict[str, dict[str, Any]] = {}
    latency: dict[str, dict[str, Any]] = {}
    bindings = []
    for path in inputs:
        raw = json.loads(path.read_text(encoding="utf-8"))
        kind = raw.get("report_kind")
        parsed = _read_report(path, str(kind))
        key = parsed["model"]["key"]
        target = quality if kind == "local_reranker_jmteb_quality" else latency
        if kind not in {
            "local_reranker_jmteb_quality",
            "local_reranker_windows_cpu_latency",
        } or key in target:
            raise BenchmarkError("comparison inputs are incomplete, duplicate, or unknown")
        target[key] = parsed
        bindings.append(
            {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    if set(quality) != set(MODELS) or set(latency) != set(MODELS):
        raise BenchmarkError("comparison requires quality and latency for both models")
    completed_task_sets = [
        {item["task"] for item in quality[key]["tasks"]} for key in MODELS
    ]
    common_tasks = set.intersection(*completed_task_sets)
    if common_tasks != {"JQaRARerankingLite"}:
        raise BenchmarkError("comparison requires JQaRA-lite as the sole common task")
    models = []
    latency_environment: dict[str, Any] | None = None
    latency_fixture_sha256: str | None = None
    for key in MODELS:
        q = quality[key]
        l = latency[key]
        expected_model = _model_identity(MODELS[key])
        if q["model"] != expected_model or l["model"] != expected_model:
            raise BenchmarkError("quality or latency model identity differs from the pin")
        if q.get("raw_text_in_report") is not False or l.get("raw_text_in_report") is not False:
            raise BenchmarkError("input reports must be aggregate-only")
        inference = l.get("inference", {})
        if (
            inference.get("provider") != "CPUExecutionProvider"
            or inference.get("gpu_disabled") is not True
            or inference.get("batch_size") != 1
            or inference.get("ort_intra_op_threads") != 1
            or inference.get("ort_inter_op_threads") != 1
            or inference.get("warmup_runs", 0) < 1
            or inference.get("measured_runs", 0) < 10_000
            or inference.get("failure_count") != 0
        ):
            raise BenchmarkError("latency report does not satisfy the fixed CPU contract")
        if latency_environment is None:
            latency_environment = l.get("environment")
            latency_fixture_sha256 = inference.get("fixture_content_sha256")
        elif (
            l.get("environment") != latency_environment
            or inference.get("fixture_content_sha256") != latency_fixture_sha256
        ):
            raise BenchmarkError("latency reports did not use the same environment and fixtures")
        task_scores = {item["task"]: item["score"] for item in q["tasks"]}
        if len(task_scores) != len(q["tasks"]):
            raise BenchmarkError("quality report contains duplicate tasks")
        for item in q["tasks"]:
            contract = TASKS.get(item["task"])
            if contract is None or any(
                item.get(field) != contract[expected]
                for field, expected in (
                    ("dataset_revision", "revision"),
                    ("split", "split"),
                    ("pairs", "pairs"),
                    ("main_score", "main_score"),
                )
            ):
                raise BenchmarkError("quality task differs from the pinned task contract")
            if not isinstance(item.get("score"), (int, float)) or not math.isfinite(item["score"]):
                raise BenchmarkError("quality task score must be finite")
        models.append(
            {
                "model": q["model"],
                "quality": {
                    "tasks": task_scores,
                    "status": q.get("status", "complete"),
                    "incomplete_tasks": q.get("incomplete_tasks", []),
                },
                "latency_batch_one_ms": l["latency"],
                "latency_measured_runs": l["inference"]["measured_runs"],
                "latency_failures": l["inference"]["failure_count"],
            }
        )
    by_key = {item["model"]["key"]: item for item in models}
    tiny = by_key["tiny"]
    xsmall = by_key["xsmall"]
    tiny_score = tiny["quality"]["tasks"]["JQaRARerankingLite"]
    xsmall_score = xsmall["quality"]["tasks"]["JQaRARerankingLite"]
    tiny_latency = tiny["latency_batch_one_ms"]
    xsmall_latency = xsmall["latency_batch_one_ms"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "local_japanese_reranker_comparison",
        "status": "research_only",
        "benchmark": {
            "suite": "JMTEB-lite Japanese core reranking",
            "tasks": TASKS,
            "common_comparison_tasks": sorted(common_tasks),
            "quality_metric": "NDCG@10",
            "quality_evaluator": "mteb==2.4.2",
            "latency_contract": "Windows CPU, GPU disabled, batch one, ORT 1+1 threads",
            "environment": latency_environment,
            "fixture_content_sha256": latency_fixture_sha256,
            "software": {
                "python": "3.13.13",
                "mteb": "2.4.2",
                "sentence_transformers": "5.1.1",
                "onnxruntime": "1.23.2",
                "optimum": "2.1.0",
                "optimum_onnx": "0.1.0",
                "polars_lts_cpu": "1.33.1",
            },
            "reference_repositories": {
                "mteb_git_sha": "57dbbfcc5cd07210f95c02bdbf23ffe86a302c95",
                "jmteb_git_sha": "526d5fc00b1682675405ae00fb3594843e53ae5d",
            },
        },
        "inputs": sorted(bindings, key=lambda item: item["file"]),
        "models": models,
        "common_task_comparison": {
            "task": "JQaRARerankingLite",
            "xsmall_minus_tiny_ndcg_at_10": round(xsmall_score - tiny_score, 10),
            "xsmall_over_tiny_p50_latency_ratio": round(
                xsmall_latency["p50_ms"] / tiny_latency["p50_ms"], 6
            ),
            "xsmall_over_tiny_p99_latency_ratio": round(
                xsmall_latency["p99_ms"] / tiny_latency["p99_ms"], 6
            ),
        },
        "decision": {
            "sakura_input_improvement_proven": False,
            "gate_b_evidence": False,
            "production_change_authorized": False,
            "reason": (
                "General information-retrieval quality and standalone pair latency do "
                "not measure Sakura Input conversion accuracy or end-to-end latency."
            ),
        },
        "raw_text_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("quality", "latency"):
        child = subparsers.add_parser(command)
        child.add_argument("--model", choices=sorted(MODELS), required=True)
        child.add_argument("--cache-dir", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
        if command == "latency":
            child.add_argument("--warmup-runs", type=int, default=100)
            child.add_argument("--measured-runs", type=int, default=10_000)
    partial = subparsers.add_parser("partial-quality")
    partial.add_argument("--model", choices=sorted(MODELS), required=True)
    partial.add_argument("--cached-task-result", type=Path, required=True)
    partial.add_argument("--skipped-task", choices=sorted(TASKS), required=True)
    partial.add_argument("--timeout-seconds", type=int, required=True)
    partial.add_argument("--output", type=Path, required=True)
    comparison = subparsers.add_parser("compare")
    comparison.add_argument("--input", type=Path, action="append", required=True)
    comparison.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "quality":
            run_quality(MODELS[arguments.model], arguments.cache_dir, arguments.output)
        elif arguments.command == "latency":
            run_latency(
                MODELS[arguments.model],
                arguments.cache_dir,
                arguments.output,
                warmup_runs=arguments.warmup_runs,
                measured_runs=arguments.measured_runs,
            )
        elif arguments.command == "partial-quality":
            build_partial_quality_from_cached_task(
                MODELS[arguments.model],
                arguments.cached_task_result,
                arguments.output,
                skipped_task=arguments.skipped_task,
                timeout_seconds=arguments.timeout_seconds,
            )
        else:
            build_comparison(arguments.input, arguments.output)
    except (BenchmarkError, OSError, ValueError) as error:
        print(f"local reranker benchmark failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
