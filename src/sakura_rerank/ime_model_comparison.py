"""Compare three local rerankers on the frozen Sakura IME dev benchmark."""

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
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sakura_rerank.atomic_io import write_bytes_atomic
from sakura_rerank.data.contracts import validate_record
from sakura_rerank.local_reranker_benchmark import MODELS, ModelSpec, load_model
from sakura_rerank.research_tiny import (
    DATASET_CONTENT_SHA256,
    DEV_COUNT,
    TOP_K,
    ranking_metrics,
)


SCHEMA_VERSION = 1
QUERY_ADAPTER = "left_context_lf_reading_label_reading_v1"


class ImeComparisonError(RuntimeError):
    """The fixed cross-model IME comparison contract was violated."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_external_query(left_context: str, reading: str) -> str:
    if not isinstance(left_context, str) or not isinstance(reading, str) or not reading:
        raise ImeComparisonError("external query requires text context and non-empty reading")
    return f"{left_context}\n読み:{reading}"


def load_dev_examples(source: Path) -> list[dict[str, Any]]:
    if sha256_file(source) != DATASET_CONTENT_SHA256:
        raise ImeComparisonError("frozen split identity differs from the pinned dataset")
    examples = []
    with source.open("r", encoding="utf-8", newline="") as rows:
        for line in rows:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ImeComparisonError("frozen split contains invalid JSON") from error
            if raw.get("split") != "dev":
                continue
            record = validate_record(raw)
            if record["is_fixture"] or not record["training_eligible"]:
                raise ImeComparisonError("dev benchmark accepts eligible non-fixture rows only")
            candidates = record["candidate_snapshots"]["production_top6"]["candidates"]
            if not 2 <= len(candidates) <= TOP_K:
                raise ImeComparisonError("dev candidate count is outside the top-6 contract")
            gold_index = record["gold_index"]
            examples.append(
                {
                    "query": build_external_query(
                        record["session"]["left_context"], record["reading"]
                    ),
                    "documents": [candidate["surface"] for candidate in candidates],
                    "gold": gold_index if gold_index is not None and gold_index < len(candidates) else -1,
                }
            )
    if len(examples) != DEV_COUNT:
        raise ImeComparisonError("frozen dev count differs from the pinned contract")
    return examples


def _model_identity(spec: ModelSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "repository": spec.repository,
        "revision": spec.revision,
        "parameters": spec.parameters,
        "onnx_file": "onnx/model_qint8_avx2.onnx",
        "onnx_sha256": spec.onnx_sha256,
        "onnx_bytes": spec.onnx_bytes,
    }


def _percentile(values: Sequence[float], proportion: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]


def _score_examples(model: Any, examples: Sequence[Mapping[str, Any]], batch_size: int) -> Any:
    import numpy as np

    pairs: list[tuple[str, str]] = []
    spans = []
    for example in examples:
        start = len(pairs)
        pairs.extend((example["query"], document) for document in example["documents"])
        spans.append((start, len(pairs)))
    flat_scores = np.asarray(
        model.predict(pairs, batch_size=batch_size, show_progress_bar=True), dtype=np.float32
    ).reshape(-1)
    if len(flat_scores) != len(pairs) or not np.isfinite(flat_scores).all():
        raise ImeComparisonError("external model returned invalid quality scores")
    scores = np.full((len(examples), TOP_K), -10_000.0, dtype=np.float32)
    for index, (start, end) in enumerate(spans):
        scores[index, : end - start] = flat_scores[start:end]
    return scores


def run_external_model(
    spec: ModelSpec,
    source: Path,
    cache_dir: Path,
    output: Path,
    *,
    quality_batch_size: int = 32,
    warmup_runs: int = 100,
    measured_runs: int = 10_000,
) -> dict[str, Any]:
    if quality_batch_size < 1 or warmup_runs < 1 or measured_runs < 10_000:
        raise ImeComparisonError("comparison requires bounded batches and 10,000 measured runs")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import numpy as np
    import onnxruntime as ort
    import sentence_transformers

    examples = load_dev_examples(source)
    model = load_model(spec, cache_dir)
    quality_started = time.perf_counter()
    scores = _score_examples(model, examples, quality_batch_size)
    quality_seconds = time.perf_counter() - quality_started
    gold = np.asarray([example["gold"] for example in examples], dtype=np.int64)
    quality = ranking_metrics(scores, gold)

    def score_request(example: Mapping[str, Any]) -> None:
        pairs = [(example["query"], document) for document in example["documents"]]
        values = np.asarray(
            model.predict(pairs, batch_size=len(pairs), show_progress_bar=False)
        ).reshape(-1)
        if len(values) != len(pairs) or not np.isfinite(values).all():
            raise ImeComparisonError("external model returned invalid request scores")

    for index in range(warmup_runs):
        score_request(examples[index % DEV_COUNT])
    timings = []
    failures = 0
    for index in range(measured_runs):
        before = time.perf_counter_ns()
        try:
            score_request(examples[index % DEV_COUNT])
        except Exception:
            failures += 1
        else:
            timings.append((time.perf_counter_ns() - before) / 1_000_000)
    if failures or len(timings) != measured_runs:
        raise ImeComparisonError("external request benchmark contained failures")
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_ime_external_reranker_benchmark",
        "status": "research_only_dev",
        "model": _model_identity(spec),
        "dataset": {
            "file": source.name,
            "sha256": DATASET_CONTENT_SHA256,
            "split": "dev",
            "record_count": DEV_COUNT,
            "candidate_limit": TOP_K,
            "final_holdout_used": False,
        },
        "adapter": {
            "kind": QUERY_ADAPTER,
            "query": "left_context + LF + Japanese reading label + reading",
            "document": "candidate_surface",
            "candidate_order_feature_used": False,
            "single_predeclared_adapter": True,
        },
        "quality": {
            key: round(value, 10) if isinstance(value, float) else value
            for key, value in quality.items()
        },
        "quality_evaluation_seconds": round(quality_seconds, 6),
        "latency_ms_per_conversion_request": {
            "mean": round(statistics.fmean(timings), 6),
            "p50": round(_percentile(timings, 0.50), 6),
            "p95": round(_percentile(timings, 0.95), 6),
            "p99": round(_percentile(timings, 0.99), 6),
            "max": round(max(timings), 6),
        },
        "contract": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "gpu_disabled": True,
            "provider": ["CPUExecutionProvider"],
            "request_batch_size": 1,
            "candidates_scored_per_request": "2..6",
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "quality_batch_size": quality_batch_size,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "failure_count": failures,
        },
        "software": {
            "python": platform.python_version(),
            "onnxruntime": ort.__version__,
            "sentence_transformers": sentence_transformers.__version__,
        },
        "gate_b_evidence": False,
        "production_change_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def _read_report(path: Path, kind: str) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImeComparisonError(f"invalid comparison report: {path}") from error
    if raw != canonical_json_bytes(report) or report.get("report_kind") != kind:
        raise ImeComparisonError(f"unexpected comparison report contract: {path}")
    return report


def build_comparison(
    sakura_report_path: Path,
    external_report_paths: Iterable[Path],
    output: Path,
) -> dict[str, Any]:
    sakura = _read_report(sakura_report_path, "sakura_rerank_tiny_onnx_dev_benchmark")
    external_paths = list(external_report_paths)
    if len(external_paths) != 2:
        raise ImeComparisonError("comparison requires exactly two external reports")
    external = [
        _read_report(path, "sakura_ime_external_reranker_benchmark")
        for path in external_paths
    ]
    if {report["model"]["key"] for report in external} != {"tiny", "xsmall"}:
        raise ImeComparisonError("comparison requires pinned Tiny and XSmall models")
    if any(
        report["dataset"]["sha256"] != DATASET_CONTENT_SHA256
        or report["dataset"]["record_count"] != DEV_COUNT
        or report["dataset"]["final_holdout_used"] is not False
        or report["contract"]["measured_runs"] != 10_000
        or report["contract"]["failure_count"] != 0
        for report in external
    ):
        raise ImeComparisonError("external reports do not share the frozen benchmark contract")
    if (
        sakura["quality"]["record_count"] != DEV_COUNT
        or sakura["contract"]["measured_runs"] != 10_000
        or sakura["contract"]["failure_count"] != 0
        or sakura["contract"]["final_holdout_used"] is not False
    ):
        raise ImeComparisonError("Sakura report does not share the frozen benchmark contract")
    models = [
        {
            "key": "sakura",
            "model": sakura["model"],
            "parameters": 1_861_377,
            "input_adapter": "native_sakura_ime_features",
            "quality": sakura["quality"],
            "latency_ms_per_conversion_request": sakura["latency_ms"],
        }
    ]
    for report in sorted(external, key=lambda item: item["model"]["key"]):
        models.append(
            {
                "key": report["model"]["key"],
                "model": report["model"],
                "parameters": report["model"]["parameters"],
                "input_adapter": report["adapter"]["kind"],
                "quality": report["quality"],
                "latency_ms_per_conversion_request": report[
                    "latency_ms_per_conversion_request"
                ],
            }
        )
    bindings = [sakura_report_path, *external_paths]
    comparison = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_ime_three_model_comparison",
        "status": "research_only_dev",
        "benchmark": {
            "dataset_content_sha256": DATASET_CONTENT_SHA256,
            "split": "dev",
            "record_count": DEV_COUNT,
            "candidate_limit": TOP_K,
            "metrics": ["top1_accuracy", "mrr", "ndcg_at_6", "rescue_count", "harm_count"],
            "latency_unit": "one complete 2..6-candidate conversion request",
            "final_holdout_used": False,
        },
        "models": models,
        "inputs": [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in bindings
        ],
        "decision": {
            "best_dev_top1_model": max(models, key=lambda item: item["quality"]["top1_accuracy"])[
                "key"
            ],
            "gate_b_evidence": False,
            "production_change_authorized": False,
            "reason": "Dev-only comparison; Gate A failed and the frozen final holdout was not used.",
        },
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(comparison), create_parent=True)
    return comparison


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-external")
    run.add_argument("model", choices=sorted(MODELS))
    run.add_argument("source", type=Path)
    run.add_argument("cache", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--quality-batch-size", type=int, default=32)
    run.add_argument("--warmup-runs", type=int, default=100)
    run.add_argument("--measured-runs", type=int, default=10_000)
    build = commands.add_parser("build")
    build.add_argument("sakura_report", type=Path)
    build.add_argument("external_reports", type=Path, nargs=2)
    build.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "run-external":
            run_external_model(
                MODELS[arguments.model],
                arguments.source,
                arguments.cache,
                arguments.output,
                quality_batch_size=arguments.quality_batch_size,
                warmup_runs=arguments.warmup_runs,
                measured_runs=arguments.measured_runs,
            )
        else:
            build_comparison(
                arguments.sakura_report,
                arguments.external_reports,
                arguments.output,
            )
    except (ImeComparisonError, OSError, ValueError, KeyError) as error:
        print(f"IME model comparison failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
