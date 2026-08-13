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

    def test_v5_gate_a_evidence_is_bound_aggregate_only_and_fails_closed(self) -> None:
        quality_path = REPORTS / "issue-15-tier-a-owner-authorized-audit-v5.json"
        quality_bytes = quality_path.read_bytes()
        quality = load_report("issue-15-tier-a-owner-authorized-audit-v5.json")
        evidence = load_report("issue-15-v5-admissibility-gate-a-evidence.json")

        self.assertEqual(quality["schema_version"], 2)
        self.assertEqual(quality["report_kind"], "tier_a_audit_quality")
        self.assertEqual(quality["selected_record_count"], 3_576)
        self.assertEqual(quality["completed_record_count"], 3_576)
        self.assertEqual(quality["pending_record_count"], 0)
        self.assertEqual(quality["valid_record_count"], 3_402)
        self.assertEqual(quality["invalid_record_count"], 174)
        self.assertEqual(
            quality["verdict_counts"],
            {
                "valid": 3_402,
                "ambiguous": 166,
                "wrong_reading": 0,
                "wrong_segmentation": 2,
                "wrong_gold_surface": 0,
                "extraction_noise": 6,
            },
        )
        self.assertEqual(quality["reviewer_kind_counts"], {"ai_teacher": 3_576, "human": 0})
        self.assertAlmostEqual(quality["point_precision"], 0.9513422818791947)
        self.assertAlmostEqual(quality["wilson_95_lower_bound"], 0.9437934216764428)
        self.assertTrue(quality["checks"]["minimum_completed"])
        self.assertTrue(quality["checks"]["minimum_final_holdout_valid"])
        self.assertTrue(quality["checks"]["accepted_reviewer_provenance"])
        self.assertFalse(quality["checks"]["label_precision"])
        self.assertTrue(quality["ai_teacher_authorized_by_owner"])
        self.assertFalse(quality["gate_a_human_audit_pass"])
        self.assertFalse(quality["gate_a_owner_authorized_audit_pass"])
        self.assertFalse(quality["raw_text_in_report"])

        self.assertEqual(
            set(evidence),
            {
                "schema_version",
                "report_kind",
                "status",
                "issue",
                "partition",
                "split",
                "audit_queue",
                "gate_a",
                "raw_text_in_report",
                "raw_stable_ids_in_report",
                "raw_notes_in_report",
            },
        )
        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["report_kind"], "tier_a_v5_admissibility_gate_a_evidence")
        self.assertEqual(evidence["status"], "gate_a_failed")
        self.assertEqual(evidence["issue"], 15)

        partition = evidence["partition"]
        self.assertEqual(
            sum(bucket["record_count"] for bucket in partition["buckets"].values()),
            partition["source_dataset_record_count"],
        )
        for pass_evidence in partition["passes"].values():
            self.assertEqual(pass_evidence["record_count"], partition["source_dataset_record_count"])
            self.assertEqual(
                sum(pass_evidence["verdict_counts"].values()),
                pass_evidence["record_count"],
            )
        self.assertEqual(
            partition["buckets"]["eligible_unanimous_valid"]["record_count"],
            17_880,
        )
        self.assertFalse(partition["raw_text_in_report"])
        self.assertFalse(partition["raw_stable_ids_in_report"])
        self.assertFalse(partition["raw_notes_in_report"])

        split = evidence["split"]
        self.assertEqual(split["dataset_record_count"], 17_880)
        self.assertEqual(sum(split["counts"].values()), split["dataset_record_count"])
        self.assertAlmostEqual(sum(split["ratios"].values()), 1.0)
        self.assertEqual(split["seed"], 20260811)
        self.assertEqual(split["counts"]["final_holdout"], 3_576)
        self.assertTrue(all(value == 0 for value in split["cross_split_leakage"].values()))

        audit = evidence["audit_queue"]
        self.assertEqual(audit["seed"], 20260812)
        self.assertEqual(audit["dataset_record_count"], split["dataset_record_count"])
        self.assertEqual(audit["dataset_content_sha256"], split["dataset_content_sha256"])
        self.assertEqual(audit["record_count"], audit["final_holdout_count"])
        self.assertEqual(audit["record_count"], split["counts"]["final_holdout"])
        self.assertGreaterEqual(audit["record_count"], audit["minimum_sample_size"])
        self.assertFalse(audit["raw_text_in_manifest"])

        gate = evidence["gate_a"]
        self.assertEqual(gate["record_count"], audit["record_count"])
        self.assertEqual(gate["batch_size_limit"], 40)
        self.assertEqual(gate["batch_count"], 90)
        tracked_quality = gate["quality_report"]
        self.assertEqual(tracked_quality["file"], "reports/issue-15-tier-a-owner-authorized-audit-v5.json")
        self.assertEqual(tracked_quality["bytes"], len(quality_bytes))
        self.assertEqual(tracked_quality["sha256"], hashlib.sha256(quality_bytes).hexdigest())
        self.assertEqual(tracked_quality["completed_record_count"], quality["completed_record_count"])
        self.assertEqual(tracked_quality["pending_record_count"], quality["pending_record_count"])
        self.assertEqual(tracked_quality["valid_record_count"], quality["valid_record_count"])
        self.assertEqual(tracked_quality["invalid_record_count"], quality["invalid_record_count"])
        self.assertEqual(tracked_quality["point_precision"], quality["point_precision"])
        self.assertEqual(
            tracked_quality["wilson_95_lower_bound"], quality["wilson_95_lower_bound"]
        )
        self.assertFalse(tracked_quality["human_pass"])
        self.assertFalse(tracked_quality["owner_authorized_ai_pass"])
        self.assertEqual(quality["queue_content_sha256"], audit["content_sha256"])

        self.assertFalse(evidence["raw_text_in_report"])
        self.assertFalse(evidence["raw_stable_ids_in_report"])
        self.assertFalse(evidence["raw_notes_in_report"])
        forbidden = {
            "text",
            "surface",
            "reading",
            "left_context",
            "note",
            "reviewer_id",
            "stable_id",
            "rows",
        }
        self.assertTrue(forbidden.isdisjoint(object_keys(quality)))
        self.assertTrue(forbidden.isdisjoint(object_keys(evidence)))

    def test_v4_context_bound_ablation_is_pinned_consistent_and_aggregate_only(self) -> None:
        report = load_report("issue-15-context-bound-ablation-v4.json")

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["report_kind"], "tier_a_context_bound_ablation")
        self.assertEqual(report["status"], "decision_recorded")
        self.assertEqual(report["issue"], 15)
        self.assertEqual(report["measured_at"], "2026-08-13")

        evidence_paths = {
            "source_span_manifest_file_sha256": MANIFESTS
            / "jawiki-tier-a-source-spans-expanded-v4-verified.json",
            "gate_a_queue_manifest_file_sha256": ROOT
            / "data/generated/tier-a-expanded-v4-a-audit-queue.manifest.json",
            "gate_a_quality_report_file_sha256": REPORTS
            / "issue-15-tier-a-owner-authorized-audit-v4.json",
            "owner_calibration_import_report_file_sha256": ROOT
            / "data/generated/v4-owner-calibration-import.report.json",
            "owner_calibration_result_report_file_sha256": ROOT
            / "data/generated/v4-owner-calibration-result.report.json",
        }
        self.assertEqual(set(report["evidence"]), set(evidence_paths))
        for field, path in evidence_paths.items():
            self.assertEqual(report["evidence"][field], hashlib.sha256(path.read_bytes()).hexdigest())

        context = report["context_contract"]
        self.assertEqual(context["adopted_left_context_max_unicode_scalars"], 64)
        self.assertEqual(context["current_production_transmitted_raw_context_bytes"], 0)
        self.assertEqual(context["dormant_session_context_max_utf8_bytes"], 256)
        self.assertEqual(
            context["current_sakura_input_head"],
            "8555bbcd5b1773dd7fff3780049528894fcea1b5",
        )
        self.assertEqual(
            context["dataset_pinned_sakura_input_head"],
            "8e966dff456e4e7165e025f97c1f73327ff3f550",
        )

        gate_a = report["gate_a_ambiguous_analysis"]
        self.assertEqual(gate_a["record_count"], 119)
        source_expansion = gate_a["same_paragraph_source_expansion"]
        self.assertEqual(
            source_expansion["additional_source_available_count"]
            + source_expansion["no_additional_source_available_count"],
            gate_a["record_count"],
        )
        self.assertEqual(source_expansion["expected_resolved_by_bound_increase_count"], 0)
        self.assertEqual(sum(gate_a["semantic_categories"].values()), gate_a["record_count"])
        lengths = gate_a["left_context_length"]
        self.assertEqual(
            lengths["below_current_bound_count"] + lengths["at_current_bound_count"],
            gate_a["record_count"],
        )
        self.assertLessEqual(lengths["empty_count"], lengths["at_most_8_count"])
        self.assertLessEqual(lengths["at_most_8_count"], lengths["below_current_bound_count"])

        calibration = report["owner_calibration_analysis"]
        self.assertEqual(calibration["reviewed_record_count"], 300)
        self.assertEqual(calibration["ambiguous_record_count"], 125)
        self.assertEqual(calibration["wrong_segmentation_record_count"], 31)
        self.assertLessEqual(
            calibration["ambiguous_left_context_length"]["at_current_bound_count"],
            calibration["ambiguous_record_count"],
        )

        self.assertFalse(report["decision"]["increase_left_context_bound"])
        self.assertEqual(
            report["decision"]["next_intervention"],
            "disjoint_source_pool_plus_historical_component_exclusion_plus_two_complete_blind_teacher_passes",
        )
        self.assertFalse(report["raw_text_in_report"])
        self.assertFalse(report["raw_stable_ids_in_report"])
        self.assertFalse(report["raw_notes_in_report"])
        self.assertTrue(
            {"text", "surface", "reading", "left_context", "note", "stable_id", "rows"}.isdisjoint(
                object_keys(report)
            )
        )

    def test_v5_source_reproduction_is_bound_identical_and_aggregate_only(self) -> None:
        report = load_report("issue-15-source-reproduction-v5-slot120.json")
        manifest_path = MANIFESTS / "jawiki-tier-a-source-spans-v5-slot120-verified.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)

        self.assertEqual(
            set(report),
            {
                "schema_version",
                "report_kind",
                "status",
                "issue",
                "source_span_manifest",
                "reproductions",
                "raw_text_in_report",
                "raw_stable_ids_in_report",
            },
        )
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["report_kind"], "jawiki_tier_a_source_span_reproduction")
        self.assertEqual(report["status"], "reproduced")
        self.assertEqual(report["issue"], 15)
        self.assertEqual(
            report["source_span_manifest"],
            {
                "file": "manifests/jawiki-tier-a-source-spans-v5-slot120-verified.json",
                "bytes": len(manifest_bytes),
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            },
        )
        self.assertEqual(manifest["verification_status"], "verified")

        reproductions = report["reproductions"]
        self.assertEqual([item["label"] for item in reproductions], ["a", "b"])
        for item in reproductions:
            self.assertEqual(item["record_count"], manifest["record_count"])
            self.assertEqual(item["content_sha256"], manifest["content_sha256"])
            self.assertGreater(item["artifact_bytes"], 0)
            self.assertGreater(item["generation_report_bytes"], 0)
            self.assertRegex(item["generation_report_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {key: value for key, value in reproductions[0].items() if key != "label"},
            {key: value for key, value in reproductions[1].items() if key != "label"},
        )

        self.assertFalse(report["raw_text_in_report"])
        self.assertFalse(report["raw_stable_ids_in_report"])
        self.assertTrue(
            {
                "text",
                "surface",
                "reading",
                "left_context",
                "stable_id",
                "article",
                "paragraph",
                "rows",
                "notes",
            }.isdisjoint(object_keys(report))
        )


if __name__ == "__main__":
    unittest.main()
