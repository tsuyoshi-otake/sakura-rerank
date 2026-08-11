from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def load_report(name: str) -> dict[str, Any]:
    value = json.loads((REPORTS / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must contain a JSON object")
    return value


def object_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from object_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from object_keys(child)


class GeneratedReportTests(unittest.TestCase):
    def test_current_state_audit_is_pinned_and_consistent(self) -> None:
        audit = load_report("current-state-audit.json")

        self.assertEqual(
            audit["sakura_input"]["head"],
            "8e966dff456e4e7165e025f97c1f73327ff3f550",
        )
        self.assertTrue(audit["sakura_input"]["dirty"])
        self.assertEqual(audit["sakura_input"]["dirty_path_count"], 31)
        self.assertTrue(audit["all_artifact_checks_passed"])
        self.assertTrue(all(audit["checks"].values()))
        self.assertEqual(audit["dictionary"]["header"]["entry_count"], 472_825)
        self.assertEqual(
            audit["dictionary"]["categories"]["entry_count"], 472_825
        )

    def test_benchmark_contains_exactly_ten_thousand_text_free_runs(self) -> None:
        benchmark = load_report("current-tiny-benchmark.json")
        warm = benchmark["warm_worker_roundtrip"]
        buckets = warm["buckets"]

        self.assertEqual(benchmark["configuration"]["measured_warm_runs"], 10_000)
        self.assertEqual(warm["aggregate_latency"]["count"], 10_000)
        self.assertEqual(
            sum(bucket["latency"]["count"] for bucket in buckets.values()),
            10_000,
        )
        self.assertEqual(
            sum(bucket["outcomes"].get("success", 0) for bucket in buckets.values()),
            10_000,
        )
        self.assertFalse(benchmark["constraints"]["raw_candidate_text_recorded"])
        self.assertGreater(
            warm["memory"]["max_private_working_set_bytes"], 100 * 1024 * 1024
        )
        self.assertTrue(
            {"text", "surface", "candidate_text"}.isdisjoint(object_keys(benchmark))
        )

    def test_quality_summary_is_text_free_and_not_gate_evidence(self) -> None:
        summary = load_report("current-tiny-quality-summary.json")

        self.assertFalse(summary["gate_status"]["gate_a_b_eligible"])
        self.assertFalse(summary["gate_status"]["production_change_authorized"])
        self.assertEqual([run["mode"] for run in summary["runs"]], ["all-normal", "long"])
        for run in summary["runs"]:
            self.assertEqual(run["baseline"], {"evaluated": 600, "correct": 545})
            self.assertEqual(run["neural"]["correct"], 545)
            self.assertEqual(run["neural"]["applied"], 192)
            self.assertEqual(run["neural"]["fallback"], 408)
            self.assertEqual(run["comparisons"], {"wins": 0, "losses": 0, "ties": 600})
            self.assertFalse(run["raw_row_text_recorded_in_summary"])

        forbidden = {
            "rows",
            "id",
            "reading",
            "expected",
            "baseline_top1",
            "neural_top1",
            "candidate_text",
            "surface",
        }
        self.assertTrue(forbidden.isdisjoint(object_keys(summary)))

        audit_bytes = (REPORTS / "current-state-audit.json").read_bytes()
        self.assertEqual(
            summary["inputs"]["current_state_audit"]["sha256"],
            hashlib.sha256(audit_bytes).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
