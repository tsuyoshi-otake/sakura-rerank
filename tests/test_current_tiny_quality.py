from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.current_tiny_quality import (
    QualitySummaryError,
    summarize_raw_report,
)


def raw_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "long",
        "cases": 2,
        "acceptance_eligible": True,
        "exploratory": False,
        "slice_counts": {"chat": 2},
        "baseline": {"evaluated": 2, "correct": 1},
        "neural": {
            "eligible": 2,
            "attempted": 2,
            "applied": 1,
            "fallback": 1,
            "correct": 2,
        },
        "comparisons": {"wins": 1, "losses": 0, "ties": 1},
        "rows": [
            {
                "id": "secret-id",
                "slice": "chat",
                "reading": "秘密の読み",
                "expected": "秘密の正解",
                "baseline_top1": "別候補",
                "baseline_correct": False,
                "eligible": True,
                "eligibility": "eligible",
                "neural_status": "applied",
                "worker_error": None,
                "neural_top1": "秘密の正解",
                "neural_correct": True,
                "comparison": "win",
            },
            {
                "id": "secret-id-2",
                "slice": "chat",
                "reading": "もう一つの読み",
                "expected": "正解",
                "baseline_top1": "正解",
                "baseline_correct": True,
                "eligible": True,
                "eligibility": "eligible",
                "neural_status": "worker-fallback",
                "worker_error": "worker reported failure status 2",
                "neural_top1": "正解",
                "neural_correct": True,
                "comparison": "tie",
            },
        ],
    }


class QualitySummaryTests(unittest.TestCase):
    def test_recomputes_aggregates_without_copying_row_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            path.write_text(
                json.dumps(raw_report(), ensure_ascii=False), encoding="utf-8"
            )

            summary = summarize_raw_report(path)

            self.assertEqual(summary["baseline"], {"evaluated": 2, "correct": 1})
            self.assertEqual(summary["comparisons"]["wins"], 1)
            self.assertEqual(
                summary["worker_error_counts"],
                {"none": 1, "worker-status-2": 1},
            )
            serialized = json.dumps(summary, ensure_ascii=False)
            for secret in ("秘密の読み", "秘密の正解", "secret-id"):
                self.assertNotIn(secret, serialized)

    def test_rejects_an_inconsistent_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            report = raw_report()
            report["baseline"] = {"evaluated": 2, "correct": 2}
            path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(QualitySummaryError, "aggregate"):
                summarize_raw_report(path)


if __name__ == "__main__":
    unittest.main()
