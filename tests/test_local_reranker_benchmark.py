from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.local_reranker_benchmark import (
    BenchmarkError,
    MODELS,
    TASKS,
    build_partial_quality_from_cached_task,
    build_comparison,
    canonical_json_bytes,
    latency_summary,
)


def quality(key: str, *, partial: bool = False) -> dict[str, object]:
    spec = MODELS[key]
    return {
        "schema_version": 1,
        "report_kind": "local_reranker_jmteb_quality",
        "model": {
            "key": key,
            "repository": spec.repository,
            "revision": spec.revision,
            "parameters": spec.parameters,
            "onnx_file": "onnx/model_qint8_avx2.onnx",
            "onnx_sha256": spec.onnx_sha256,
            "onnx_bytes": spec.onnx_bytes,
        },
        "tasks": [
            {
                "task": name,
                "dataset_revision": TASKS[name]["revision"],
                "split": TASKS[name]["split"],
                "pairs": TASKS[name]["pairs"],
                "main_score": TASKS[name]["main_score"],
                "score": score,
            }
            for name, score in zip(sorted(TASKS), (0.7, 0.8), strict=True)
            if not partial or name == "JQaRARerankingLite"
        ],
        "status": "partial_user_skipped_after_timeout" if partial else "complete",
        "incomplete_tasks": (
            [{"task": "JaCWIRRerankingLite", "score_reported": False}]
            if partial
            else []
        ),
        "raw_text_in_report": False,
    }


def latency(key: str) -> dict[str, object]:
    value = quality(key)
    value["report_kind"] = "local_reranker_windows_cpu_latency"
    value.pop("tasks")
    value["environment"] = {
        "platform": "Windows-test",
        "machine": "AMD64",
        "processor": "test",
        "python": "3.13.13",
    }
    value["inference"] = {
        "provider": "CPUExecutionProvider",
        "gpu_disabled": True,
        "batch_size": 1,
        "ort_intra_op_threads": 1,
        "ort_inter_op_threads": 1,
        "warmup_runs": 100,
        "measured_runs": 10_000,
        "failure_count": 0,
        "fixture_content_sha256": "a" * 64,
    }
    value["latency"] = latency_summary([1.0, 2.0, 3.0])
    return value


class StatisticsTests(unittest.TestCase):
    def test_latency_summary_uses_nearest_rank(self) -> None:
        summary = latency_summary(range(1, 101))
        self.assertEqual(summary["p50_ms"], 50)
        self.assertEqual(summary["p95_ms"], 95)
        self.assertEqual(summary["p99_ms"], 99)


class ComparisonTests(unittest.TestCase):
    def test_builds_aggregate_only_bound_comparison(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            inputs = []
            for key in MODELS:
                for name, value in (
                    ("quality", quality(key, partial=key == "xsmall")),
                    ("latency", latency(key)),
                ):
                    path = root / f"{key}-{name}.json"
                    path.write_bytes(canonical_json_bytes(value))
                    inputs.append(path)
            output = root / "comparison.json"

            result = build_comparison(inputs, output)

            self.assertEqual(result["status"], "research_only")
            self.assertFalse(result["decision"]["sakura_input_improvement_proven"])
            self.assertEqual(
                result["benchmark"]["common_comparison_tasks"],
                ["JQaRARerankingLite"],
            )
            self.assertEqual(result["common_task_comparison"]["xsmall_minus_tiny_ndcg_at_10"], 0)
            serialized = output.read_text(encoding="utf-8")
            for forbidden in ("query", "document", "left_context", "stable_id"):
                self.assertNotIn(f'"{forbidden}"', serialized)

    def test_rejects_noncanonical_or_incomplete_inputs(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            path = root / "tiny-quality.json"
            path.write_text(json.dumps(quality("tiny")), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkError, "canonical"):
                build_comparison([path], root / "out.json")

    def test_builds_partial_quality_from_pinned_cached_task(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            cached = root / "JQaRARerankingLite.json"
            cached.write_text(
                json.dumps(
                    {
                        "dataset_revision": TASKS["JQaRARerankingLite"]["revision"],
                        "task_name": "JQaRARerankingLite",
                        "mteb_version": "2.4.2",
                        "scores": {"test": [{"ndcg_at_10": 0.73347}]},
                        "evaluation_time": 2139.8772826194763,
                    }
                ),
                encoding="utf-8",
            )
            output = root / "partial.json"

            result = build_partial_quality_from_cached_task(
                MODELS["xsmall"],
                cached,
                output,
                skipped_task="JaCWIRRerankingLite",
                timeout_seconds=3600,
            )

            self.assertEqual(result["tasks"][0]["score"], 0.73347)
            self.assertFalse(result["incomplete_tasks"][0]["score_reported"])
            self.assertEqual(output.read_bytes(), canonical_json_bytes(result))


if __name__ == "__main__":
    unittest.main()
