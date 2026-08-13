from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MANIFESTS = ROOT / "manifests"


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
    def test_verified_top32_snapshot_is_pinned_consistent_and_text_free(self) -> None:
        snapshot = json.loads(
            (MANIFESTS / "jawiki-research-top32-snapshot-verified.json").read_text(
                encoding="utf-8"
            )
        )
        source = json.loads(
            (MANIFESTS / "jawiki-tier-a-source-spans-verified.json").read_text(
                encoding="utf-8"
            )
        )
        dictionary = json.loads(
            (MANIFESTS / "system-dictionary-index-verified.json").read_text(
                encoding="utf-8"
            )
        )
        exporter_bytes = (MANIFESTS / "research-exporter-verified.json").read_bytes()

        self.assertEqual(snapshot["verification_status"], "verified")
        self.assertEqual(snapshot["record_count"], snapshot["request_record_count"])
        self.assertEqual(
            snapshot["record_count"],
            snapshot["search_exhausted_record_count"] + snapshot["truncated_record_count"],
        )
        self.assertEqual(snapshot["source_span_content_sha256"], source["content_sha256"])
        self.assertEqual(snapshot["source_span_extractor_git_sha"], source["extractor_git_sha"])
        self.assertEqual(
            snapshot["dictionary_index_content_sha256"], dictionary["content_sha256"]
        )
        self.assertEqual(snapshot["dictionary_indexer_git_sha"], dictionary["indexer_git_sha"])
        self.assertEqual(snapshot["dictionary_sha256"], dictionary["dictionary_sha256"])
        self.assertEqual(snapshot["sakura_input_head"], dictionary["sakura_input_head"])
        self.assertEqual(
            snapshot["exporter_identity_manifest_sha256"],
            hashlib.sha256(exporter_bytes).hexdigest(),
        )
        self.assertGreaterEqual(snapshot["reproduction_run_count"], 2)
        self.assertFalse(snapshot["raw_text_in_manifest"])
        forbidden = {"text", "surface", "reading", "candidate", "stable_id", "rows"}
        self.assertTrue(forbidden.isdisjoint(object_keys(snapshot)))

    def test_jawiki_local_artifact_report_is_pinned_and_text_free(self) -> None:
        report = load_report("jawiki-local-artifact-verification.json")

        self.assertEqual(report["status"], "local_artifact_verified")
        self.assertEqual(report["byte_size"], 4_827_732_824)
        self.assertEqual(report["official_md5"], "b51bab6d1cc23efddc4363e78b5526c6")
        self.assertEqual(
            report["official_sha1"], "6c917b51d6f6b53a34eaebcb2a675c0769054343"
        )
        self.assertEqual(
            report["local_sha256"],
            "4822a58b180fc0057ce6f64325f11c34fe6396fb5ed2e4a04eaf7a9658acc12d",
        )
        self.assertEqual(
            report["acquisition_git_sha"],
            "22f7ce953b6bb3480dbb2f16cb3b9b3089baa23f",
        )
        self.assertTrue(report["fresh_download_completed"])
        self.assertTrue(report["network_free_revalidation_passed"])
        self.assertFalse(report["partial_residue_present"])
        self.assertFalse(report["artifact_committed"])
        source_bytes = (
            ROOT / "manifests" / "jawiki-20260801-pages-articles-multistream.json"
        ).read_bytes()
        self.assertEqual(
            report["source_manifest"],
            {
                "byte_size": len(source_bytes),
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
        )
        forbidden = {"text", "surface", "reading", "local_path", "article"}
        self.assertTrue(forbidden.isdisjoint(object_keys(report)))

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

    def test_teacher_audit_is_provenanced_text_free_and_fail_closed(self) -> None:
        report = load_report("issue-15-tier-a-teacher-audit-120.json")

        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["report_kind"], "tier_a_audit_quality")
        self.assertEqual(report["reviewer_kind_counts"], {"ai_teacher": 120, "human": 0})
        self.assertEqual(report["valid_record_count"], 115)
        self.assertEqual(report["invalid_record_count"], 5)
        self.assertFalse(report["gate_a_human_audit_pass"])
        self.assertFalse(report["gate_a_owner_authorized_audit_pass"])
        self.assertFalse(report["checks"]["label_precision"])
        self.assertTrue(report["ai_teacher_authorized_by_owner"])
        self.assertFalse(report["raw_text_in_report"])
        self.assertTrue(
            {"text", "surface", "reading", "left_context", "note", "reviewer_id"}.isdisjoint(
                object_keys(report)
            )
        )

    def test_v4_owner_authorized_audit_is_complete_text_free_and_fails_gate(self) -> None:
        report = load_report("issue-15-tier-a-owner-authorized-audit-v4.json")

        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["report_kind"], "tier_a_audit_quality")
        self.assertEqual(report["selected_record_count"], 3_487)
        self.assertEqual(report["completed_record_count"], 3_487)
        self.assertEqual(report["pending_record_count"], 0)
        self.assertEqual(report["valid_record_count"], 3_304)
        self.assertEqual(report["invalid_record_count"], 183)
        self.assertEqual(
            report["verdict_counts"],
            {
                "valid": 3_304,
                "wrong_reading": 15,
                "wrong_segmentation": 6,
                "wrong_gold_surface": 4,
                "ambiguous": 119,
                "extraction_noise": 39,
            },
        )
        self.assertEqual(report["reviewer_kind_counts"], {"ai_teacher": 3_487, "human": 0})
        self.assertEqual(
            report["queue_content_sha256"],
            "5843a969a050f19e897b0d0f8dc2c173d4fedb759bcc7b04ba142c8d9ffebaa2",
        )
        self.assertEqual(
            report["response_content_sha256"],
            "6e36955e6d678d0cc45d1997a233e670c1d372a1ae322fc807f1a70418c2f25b",
        )
        self.assertAlmostEqual(report["point_precision"], 0.9475193576139949)
        self.assertAlmostEqual(report["wilson_95_lower_bound"], 0.9396131571026306)
        self.assertTrue(report["checks"]["minimum_completed"])
        self.assertTrue(report["checks"]["minimum_final_holdout_valid"])
        self.assertTrue(report["checks"]["accepted_reviewer_provenance"])
        self.assertFalse(report["checks"]["label_precision"])
        self.assertTrue(report["ai_teacher_authorized_by_owner"])
        self.assertFalse(report["gate_a_human_audit_pass"])
        self.assertFalse(report["gate_a_owner_authorized_audit_pass"])
        self.assertFalse(report["raw_text_in_report"])
        self.assertTrue(
            {"text", "surface", "reading", "left_context", "note", "reviewer_id", "stable_id"}.isdisjoint(
                object_keys(report)
            )
        )


if __name__ == "__main__":
    unittest.main()
