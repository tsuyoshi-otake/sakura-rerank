from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.corpus_v4 import (
    ADJUDICATION_REVIEWER_ID,
    GATE_A_REVIEWER_ID,
    MAX_BATCH_ITEMS,
    SCREEN_REVIEWER_ID,
    V4_QUEUE_RECORD_TYPE,
    V4_SCHEMA_VERSION,
    V4_VERDICT_RECORD_TYPE,
    analyze_stage0_dev_rules,
    build_stage3_calibration_queue,
    build_stage2_batches,
    build_gate_a_teacher_batches,
    build_teacher_batches,
    discover_teacher_disagreements,
    finalize_gate_a_teacher_responses,
    partition_stage2,
    publish_partition_directory,
    publish_gate_a_teacher_evidence,
    publish_teacher_queue_directory,
    read_teacher_queue_directory,
    scan_verdict_directory,
    select_stage3_ids,
    stage0_probe_report,
    stage3_one_pass_only_ids,
    stage3_human_audit_items,
    validate_gate_a_teacher_queue_binding,
)
from sakura_rerank.data.tier_a import TierAError
from tests.test_data_contracts import _rehash_snapshots, production_record


def records(count: int = 45) -> list[dict[str, object]]:
    result = []
    for index in range(count):
        item = production_record()
        item["stable_id"] = f"v4-{index:04d}"
        exporter = item["candidate_snapshots"]["training_top32"]["exporter_run"]
        exporter["verification_status"] = "verified"
        exporter["exporter_git_sha"] = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
        exporter["exporter_binary_sha256"] = "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
        _rehash_snapshots(item)
        item["split"] = "train"
        result.append(item)
    return result


def verdict(batch: dict[str, object], *, nonvalid: set[str] = set(), reviewer: str = SCREEN_REVIEWER_ID) -> dict[str, object]:
    return {
        "schema_version": V4_SCHEMA_VERSION,
        "record_type": V4_VERDICT_RECORD_TYPE,
        "batch_index": batch["batch_index"],
        "reviewer_kind": "ai_teacher",
        "reviewer_id": reviewer,
        "verdicts": [
            {"stable_id": item["stable_id"], "verdict": "extraction_noise" if item["stable_id"] in nonvalid else "valid", "note": ""}
            for item in batch["items"]
        ],
    }


class CorpusV4Tests(unittest.TestCase):
    def test_gate_a_adapter_preserves_standard_queue_rows_and_uses_40_item_batches(self) -> None:
        source = records(88)
        queue = stage3_human_audit_items(
            source, [item["stable_id"] for item in source]
        )
        batches = build_gate_a_teacher_batches(queue)

        self.assertEqual([len(batch["items"]) for batch in batches], [40, 40, 8])
        flattened = [item for batch in batches for item in batch["items"]]
        self.assertEqual([item["stable_id"] for item in flattened], [item["stable_id"] for item in queue])
        for original, adapted in zip(queue, flattened, strict=True):
            expected = dict(original)
            expected["schema_version"] = 2
            expected["record_type"] = V4_QUEUE_RECORD_TYPE
            self.assertEqual(adapted, expected)

        with tempfile.TemporaryDirectory() as directory:
            manifest = publish_teacher_queue_directory(
                Path(directory) / "gate-a",
                batches,
                stage="gate_a",
                reviewer_kind="ai_teacher",
                reviewer_id=GATE_A_REVIEWER_ID,
            )
        self.assertEqual(manifest["stage"], "gate_a")

    def test_gate_a_finalizer_requires_complete_bound_verdicts_and_canonical_responses(self) -> None:
        queue = stage3_human_audit_items(
            records(41), [f"v4-{index:04d}" for index in range(41)]
        )
        batches = build_gate_a_teacher_batches(queue)
        verdicts = {
            batch["batch_index"]: verdict(batch, reviewer=GATE_A_REVIEWER_ID)
            for batch in reversed(batches)
        }
        responses = finalize_gate_a_teacher_responses(
            batches, verdicts, reviewed_at="2026-08-13T12:34:56+09:00"
        )

        self.assertEqual([response["stable_id"] for response in responses], sorted(item["stable_id"] for item in queue))
        self.assertTrue(all(response["schema_version"] == 2 for response in responses))
        self.assertTrue(all(response["record_type"] == "tier_a_audit_response" for response in responses))
        self.assertTrue(all(response["reviewer_kind"] == "ai_teacher" for response in responses))
        self.assertTrue(all(response["reviewer_id"] == GATE_A_REVIEWER_ID for response in responses))
        self.assertTrue(all(response["reviewed_at"] == "2026-08-13T12:34:56+09:00" for response in responses))

        missing = dict(verdicts)
        del missing[0]
        with self.assertRaisesRegex(TierAError, "cover every batch exactly"):
            finalize_gate_a_teacher_responses(
                batches, missing, reviewed_at="2026-08-13T12:34:56+09:00"
            )
        extra = dict(verdicts)
        extra[99] = verdicts[0]
        with self.assertRaisesRegex(TierAError, "cover every batch exactly"):
            finalize_gate_a_teacher_responses(
                batches, extra, reviewed_at="2026-08-13T12:34:56+09:00"
            )
        wrong_identity = dict(verdicts)
        wrong_identity[0] = verdict(batches[0], reviewer=SCREEN_REVIEWER_ID)
        with self.assertRaisesRegex(TierAError, "provenance"):
            finalize_gate_a_teacher_responses(
                batches, wrong_identity, reviewed_at="2026-08-13T12:34:56+09:00"
            )
        with self.assertRaisesRegex(TierAError, "needs timezone"):
            finalize_gate_a_teacher_responses(
                batches, verdicts, reviewed_at="2026-08-13T12:34:56"
            )
        with self.assertRaisesRegex(TierAError, "outside the bound"):
            finalize_gate_a_teacher_responses(
                batches, verdicts, reviewed_at="2" * 65
            )

    def test_gate_a_binding_and_pair_publication_are_fail_closed(self) -> None:
        queue = stage3_human_audit_items(
            records(41), [f"v4-{index:04d}" for index in range(41)]
        )
        batches = build_gate_a_teacher_batches(queue)
        verdicts = {
            batch["batch_index"]: verdict(batch, reviewer=GATE_A_REVIEWER_ID)
            for batch in batches
        }
        responses = finalize_gate_a_teacher_responses(
            batches, verdicts, reviewed_at="2026-08-13T12:34:56+09:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher_queue = root / "teacher"
            manifest = publish_teacher_queue_directory(
                teacher_queue,
                batches,
                stage="gate_a",
                reviewer_kind="ai_teacher",
                reviewer_id=GATE_A_REVIEWER_ID,
            )
            loaded, loaded_manifest = read_teacher_queue_directory(teacher_queue)
            self.assertEqual(
                validate_gate_a_teacher_queue_binding(queue, loaded, loaded_manifest),
                batches,
            )
            changed = copy.deepcopy(queue)
            changed[0]["left_context"] = "changed"
            with self.assertRaisesRegex(TierAError, "bind"):
                validate_gate_a_teacher_queue_binding(changed, loaded, loaded_manifest)
            wrong_manifest = dict(manifest)
            wrong_manifest["stage"] = "stage1"
            with self.assertRaisesRegex(TierAError, "provenance"):
                validate_gate_a_teacher_queue_binding(queue, loaded, wrong_manifest)

            response_path = root / "responses.jsonl"
            report_path = root / "report.json"
            response_sha, report_sha, report = publish_gate_a_teacher_evidence(
                response_path, report_path, queue, responses
            )
            self.assertEqual(response_sha, hashlib.sha256(response_path.read_bytes()).hexdigest())
            self.assertEqual(report_sha, hashlib.sha256(report_path.read_bytes()).hexdigest())
            self.assertFalse(report["gate_a_human_audit_pass"])
            self.assertEqual(report["reviewer_kind_counts"], {"human": 0, "ai_teacher": 41})

            wrong_responses = copy.deepcopy(responses)
            wrong_responses[0]["reviewer_id"] = SCREEN_REVIEWER_ID
            with self.assertRaisesRegex(TierAError, "provenance"):
                publish_gate_a_teacher_evidence(
                    root / "bad.jsonl", root / "bad.json", queue, wrong_responses
                )
            with self.assertRaisesRegex(TierAError, "provenance"):
                publish_gate_a_teacher_evidence(
                    root / "short.jsonl", root / "short.json", queue, responses[:-1]
                )

    def test_gate_a_pair_publication_rolls_back_on_second_replace_failure(self) -> None:
        queue = stage3_human_audit_items(records(1), ["v4-0000"])
        batches = build_gate_a_teacher_batches(queue)
        responses = finalize_gate_a_teacher_responses(
            batches,
            {0: verdict(batches[0], reviewer=GATE_A_REVIEWER_ID)},
            reviewed_at="2026-08-13T12:34:56+09:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response_path = root / "responses.jsonl"
            report_path = root / "report.json"
            response_path.write_bytes(b"old-response\n")
            report_path.write_bytes(b"old-report\n")
            original_replace = os.replace
            calls = 0

            def fail_second_replace(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected")
                original_replace(source, destination)

            with patch(
                "sakura_rerank.atomic_io.os.replace", side_effect=fail_second_replace
            ):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_gate_a_teacher_evidence(
                        response_path, report_path, queue, responses
                    )
            self.assertEqual(response_path.read_bytes(), b"old-response\n")
            self.assertEqual(report_path.read_bytes(), b"old-report\n")

    def test_stage0_is_aggregate_only_and_batches_are_complete_stable_and_bounded(self) -> None:
        source = records()
        report = stage0_probe_report(source)
        self.assertFalse(report["raw_text_in_report"])
        self.assertEqual(report["input_record_count"], 45)
        batches = build_teacher_batches(list(reversed(source)))
        self.assertEqual([len(batch["items"]) for batch in batches], [40, 5])
        self.assertEqual([item["stable_id"] for batch in batches for item in batch["items"]], sorted(item["stable_id"] for item in source))
        self.assertTrue(all(len(batch["items"]) <= MAX_BATCH_ITEMS for batch in batches))

    def test_stage0_dev_analysis_adopts_only_zero_false_fire_rules(self) -> None:
        items = build_teacher_batches(records(3))[0]["items"]
        items[0]["left_context"] = "noise |"
        items[1]["left_context"] = "noise \u25bd"
        items[2]["left_context"] = "ordinary ("
        outcomes = {
            items[0]["stable_id"]: "extraction_noise",
            items[1]["stable_id"]: "extraction_noise",
            items[2]["stable_id"]: "valid",
        }
        report = analyze_stage0_dev_rules(items, outcomes)
        evidence = report["candidate_rule_evidence"]
        self.assertTrue(evidence["adopted_bare_pipe"]["adopted"])
        self.assertTrue(evidence["adopted_decorative_corruption"]["adopted"])
        self.assertFalse(evidence["unbalanced_bracket"]["adopted"])
        self.assertEqual(evidence["unbalanced_bracket"]["valid_false_fires"], 1)
        self.assertFalse(report["raw_text_in_report"])

    def test_queue_directory_is_immutable_validated_and_rejects_extras(self) -> None:
        batches = build_teacher_batches(records(3))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "stage1"
            manifest = publish_teacher_queue_directory(queue, batches, stage="stage1", reviewer_kind="ai_teacher", reviewer_id=SCREEN_REVIEWER_ID)
            loaded, loaded_manifest = read_teacher_queue_directory(queue)
            self.assertEqual(loaded, batches)
            self.assertEqual(loaded_manifest, manifest)
            with self.assertRaisesRegex(TierAError, "immutable"):
                publish_teacher_queue_directory(queue, batches, stage="stage1", reviewer_kind="ai_teacher", reviewer_id=SCREEN_REVIEWER_ID)
            (queue / "foreign.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "unexpected"):
                read_teacher_queue_directory(queue)

    def test_failed_directory_publish_leaves_no_partial_target(self) -> None:
        batches = build_teacher_batches(records(1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "stage1"
            with patch("sakura_rerank.data.corpus_v4.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    publish_teacher_queue_directory(target, batches, stage="stage1", reviewer_kind="ai_teacher", reviewer_id=SCREEN_REVIEWER_ID)
            self.assertFalse(target.exists())

    def test_resumable_scan_only_skips_missing_and_rejects_malformed_or_extra(self) -> None:
        batches = build_teacher_batches(records(2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, output = root / "queue", root / "out"
            publish_teacher_queue_directory(queue, batches, stage="stage1", reviewer_kind="ai_teacher", reviewer_id=SCREEN_REVIEWER_ID)
            output.mkdir()
            complete, pending = scan_verdict_directory(queue, output)
            self.assertEqual(complete, {})
            self.assertEqual(pending, [0])
            payload = verdict(batches[0])
            payload["verdicts"] = list(reversed(payload["verdicts"]))
            (output / "verdicts-000.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "batch 000.*order"):
                scan_verdict_directory(queue, output)
            (output / "verdicts-000.json").write_text(json.dumps(verdict(batches[0])), encoding="utf-8")
            (output / "unexpected.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "unexpected"):
                scan_verdict_directory(queue, output)

    def test_stage2_is_note_free_and_partition_quarantines_ambiguous(self) -> None:
        source = records(3)
        first = build_teacher_batches(source)
        flagged = {first[0]["items"][0]["stable_id"], first[0]["items"][1]["stable_id"]}
        first_result = {0: verdict(first[0], nonvalid=flagged)}
        second = build_stage2_batches(first, first_result)
        self.assertEqual([item["stable_id"] for item in second[0]["items"]], sorted(flagged))
        second_payload = verdict(second[0], reviewer=ADJUDICATION_REVIEWER_ID)
        second_payload["verdicts"][0]["verdict"] = "ambiguous"
        second_payload["verdicts"][1]["verdict"] = "extraction_noise"
        output, report = partition_stage2(
            source,
            first,
            first_result,
            second,
            {0: second_payload},
            external_verdicts={},
            stage0_hit_ids=[],
        )
        self.assertEqual(len(output["retained"]), 1)
        self.assertEqual(len(output["ambiguous_quarantine"]), 1)
        self.assertEqual(len(output["excluded"]), 1)
        self.assertFalse(report["raw_text_in_report"])

    def test_partition_unions_both_passes_prior_review_and_stage0_with_ambiguity_override(self) -> None:
        source = records(5)
        first = build_teacher_batches(source)
        ids = [item["stable_id"] for item in first[0]["items"]]
        first_result = {0: verdict(first[0], nonvalid={ids[0], ids[1]})}
        second = build_stage2_batches(first, first_result)
        second_result = {
            0: verdict(
                second[0],
                nonvalid={ids[0]},
                reviewer=ADJUDICATION_REVIEWER_ID,
            )
        }
        output, report = partition_stage2(
            source,
            first,
            first_result,
            second,
            second_result,
            external_verdicts={ids[2]: "wrong_reading", ids[4]: "ambiguous"},
            stage0_hit_ids=[ids[3], ids[4]],
        )
        self.assertEqual(
            [row["stable_id"] for row in output["excluded"]],
            [ids[0], ids[2], ids[3]],
        )
        self.assertEqual(output["retained"], [])
        self.assertEqual(
            [row["stable_id"] for row in output["ambiguous_quarantine"]],
            [ids[1], ids[4]],
        )
        self.assertEqual(report["exclusion_reason_counts"]["union"], 3)
        self.assertEqual(
            report["partition_policy"],
            "precision_first_quarantine_one_pass_recovery_v1",
        )
        self.assertEqual(
            report["quarantine_reason_counts"],
            {
                "ambiguous_outcome": 1,
                "stage1_nonvalid_stage2_valid": 1,
                "union": 2,
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "partition"
            published = publish_partition_directory(target, output, report)
            self.assertEqual(published["stage4_stable_id_exclusion"]["count"], 5)
            self.assertTrue((target / "stage4-stable-id-exclusion.jsonl").is_file())

    def test_stage3_selects_all_disagreements_plus_exactly_one_hundred_and_converts(self) -> None:
        source = records(130)
        disagreements = sorted(item["stable_id"] for item in source)[:3]
        one_pass = sorted(item["stable_id"] for item in source)[3:]
        picked, sampled = select_stage3_ids(disagreements, one_pass, seed=9)
        self.assertEqual(len(picked), 103)
        self.assertEqual(len(sampled), 100)
        self.assertTrue(set(disagreements) <= set(picked))
        queue_items = stage3_human_audit_items(source, picked)
        self.assertEqual([item["stable_id"] for item in queue_items], sorted(picked))
        self.assertEqual(queue_items[0]["record_type"], "tier_a_human_audit_item")

        first = {item["stable_id"]: "extraction_noise" for item in source}
        second = {item["stable_id"]: "valid" for item in source}
        self.assertEqual(stage3_one_pass_only_ids(first, second), sorted(first))
        strata = {
            item["stable_id"]: item["stratum"]
            for item in stage3_human_audit_items(source, sorted(first))
        }
        disagreement_rows = [
            {
                "stable_id": identifier,
                "stratum": strata[identifier],
                "verdict_a": "valid",
                "verdict_b": "ambiguous",
            }
            for identifier in disagreements
        ]
        queue, manifest, selected = build_stage3_calibration_queue(
            source,
            disagreement_rows,
            first,
            second,
            seed=9,
        )
        self.assertEqual(len(queue), 103)
        self.assertEqual(len(selected), 100)
        self.assertEqual(manifest["record_count"], 103)
        self.assertEqual(manifest["one_pass_selected_record_count"], 100)

    def test_discovery_deduplicates_identical_handoff_rows_but_rejects_conflicts(self) -> None:
        row = {"stable_id": "v4-0001", "stratum": "reading-03-09/candidates-17-32/local-correct", "verdict_a": "valid", "verdict_b": "ambiguous"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("teacher-disagreements-final.jsonl", "teacher-disagreements-rerun.jsonl"):
                (root / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(discover_teacher_disagreements(root), [row])
            conflicting = dict(row)
            conflicting["verdict_b"] = "wrong_reading"
            (root / "teacher-disagreements-rerun.jsonl").write_text(json.dumps(conflicting) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "conflicting"):
                discover_teacher_disagreements(root)


if __name__ == "__main__":
    unittest.main()
