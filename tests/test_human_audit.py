from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.contracts import canonical_jsonl_bytes
from sakura_rerank.data.human_audit import (
    apply_audit_responses,
    build_quality_report,
    build_queue_manifest,
    publish_audit_application,
    publish_audit_queue,
    read_audit_responses,
    select_audit_records,
    validate_queue_manifest,
    wilson_lower_bound,
)
from sakura_rerank.data.tier_a import TierAError
from tests.test_data_contracts import fixture_record


def _records(count: int, *, holdout: int) -> list[dict[str, object]]:
    result = []
    for index in range(count):
        record = fixture_record(f"audit-{index:05d}")
        record["split"] = "final-holdout" if index < holdout else "train"
        result.append(record)
    return result


def _response(
    stable_id: str, verdict: str = "valid", reviewer_kind: str = "human"
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "record_type": "tier_a_audit_response",
        "stable_id": stable_id,
        "verdict": verdict,
        "reviewer_id": "reviewer-1",
        "reviewer_kind": reviewer_kind,
        "reviewed_at": "2026-08-12T12:00:00+09:00",
        "note": "",
    }


class HumanAuditTests(unittest.TestCase):
    def test_selection_includes_holdout_and_is_deterministic_and_stratified(self) -> None:
        records = _records(12, holdout=4)
        first = select_audit_records(records, seed=27, minimum_sample_size=8)
        second = select_audit_records(list(reversed(records)), seed=27, minimum_sample_size=8)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        selected = {item["stable_id"] for item in first}
        self.assertTrue({f"audit-{index:05d}" for index in range(4)} <= selected)

    def test_queue_manifest_is_text_free_and_published_as_a_pair(self) -> None:
        records = _records(5, holdout=3)
        queue = select_audit_records(records, seed=1, minimum_sample_size=4)
        manifest = build_queue_manifest(records, queue, seed=1, minimum_sample_size=4)
        self.assertNotIn("fixture left context", json.dumps(manifest))
        self.assertFalse(manifest["raw_text_in_manifest"])
        validate_queue_manifest(manifest, queue)
        extended = dict(manifest)
        extended["raw_reading"] = "must not enter the manifest"
        with self.assertRaisesRegex(TierAError, "aggregate-only"):
            validate_queue_manifest(extended, queue)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "queue.jsonl"
            report = root / "manifest.json"
            publish_audit_queue(output, report, queue, manifest)
            self.assertEqual(output.read_bytes(), canonical_jsonl_bytes(queue))
            self.assertTrue(report.is_file())

    def test_response_reader_rejects_duplicate_ids_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            response = _response("audit-00001")
            path.write_text(
                "\n".join(json.dumps(response) for _ in range(2)) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TierAError, "duplicate"):
                read_audit_responses(path)
            response["raw_text"] = "must not be accepted"
            path.write_text(json.dumps(response) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "fields"):
                read_audit_responses(path)

    def test_quality_gate_requires_both_precision_and_reviewed_holdout(self) -> None:
        queue = [
            {
                "stable_id": f"audit-{index:05d}",
                "split": "final-holdout",
                "stratum": "reading-03-09/candidates-02-06/local-correct",
            }
            for index in range(3_000)
        ]
        passed = build_quality_report(queue, [_response(item["stable_id"]) for item in queue])
        self.assertTrue(passed["gate_a_human_audit_pass"])
        self.assertEqual(
            passed["final_holdout_valid_stratum_counts"],
            {"reading-03-09/candidates-02-06/local-correct": 3_000},
        )
        failed_responses = [
            _response(item["stable_id"], "wrong_gold_surface" if index < 16 else "valid")
            for index, item in enumerate(queue)
        ]
        failed = build_quality_report(queue, failed_responses)
        self.assertFalse(failed["gate_a_human_audit_pass"])
        self.assertFalse(failed["checks"]["label_precision"])
        incomplete = build_quality_report(queue, failed_responses[:999])
        self.assertFalse(incomplete["checks"]["minimum_completed"])
        self.assertFalse(incomplete["checks"]["minimum_final_holdout_valid"])

        teacher_responses = [
            _response(item["stable_id"], reviewer_kind="ai_teacher") for item in queue
        ]
        teacher_default = build_quality_report(queue, teacher_responses)
        self.assertFalse(teacher_default["gate_a_human_audit_pass"])
        self.assertFalse(teacher_default["gate_a_owner_authorized_audit_pass"])
        teacher_authorized = build_quality_report(
            queue, teacher_responses, allow_ai_teacher=True
        )
        self.assertFalse(teacher_authorized["gate_a_human_audit_pass"])
        self.assertTrue(teacher_authorized["gate_a_owner_authorized_audit_pass"])
        self.assertEqual(teacher_authorized["reviewer_kind_counts"]["ai_teacher"], 3_000)

    def test_wilson_lower_bound_matches_known_all_success_case(self) -> None:
        self.assertAlmostEqual(wilson_lower_bound(1_000, 1_000), 0.9961732415, places=9)
        self.assertEqual(wilson_lower_bound(0, 0), 0.0)

    def test_selection_rejects_a_corpus_smaller_than_the_required_sample(self) -> None:
        with self.assertRaisesRegex(TierAError, "fewer records"):
            select_audit_records(_records(2, holdout=1), seed=1, minimum_sample_size=3)

    def test_apply_is_fail_closed_for_pending_and_removes_rejected(self) -> None:
        records = _records(4, holdout=3)
        queue = select_audit_records(records, seed=2, minimum_sample_size=3)
        responses = [
            _response(queue[0]["stable_id"], "valid"),
            _response(queue[1]["stable_id"], "ambiguous"),
        ]
        output, report = apply_audit_responses(records, queue, responses)
        by_id = {record["stable_id"]: record for record in output}
        self.assertEqual(report["accepted_record_count"], 1)
        self.assertEqual(report["rejected_record_count"], 1)
        self.assertEqual(report["pending_record_count"], 1)
        self.assertNotIn(queue[1]["stable_id"], by_id)
        self.assertEqual(by_id[queue[0]["stable_id"]]["sampled_human_audit"]["status"], "accepted")
        self.assertEqual(by_id[queue[2]["stable_id"]]["sampled_human_audit"]["status"], "pending")
        self.assertFalse(by_id[queue[2]["stable_id"]]["training_eligible"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish_audit_application(root / "clean.jsonl", root / "report.json", output, report)
            self.assertTrue((root / "clean.jsonl").is_file())

    def test_application_rejects_queue_or_responses_outside_dataset(self) -> None:
        records = _records(2, holdout=1)
        queue = select_audit_records(records, seed=2, minimum_sample_size=1)
        foreign = copy.deepcopy(queue[0])
        foreign["stable_id"] = "foreign-id"
        with self.assertRaisesRegex(TierAError, "outside the dataset"):
            apply_audit_responses(records, [foreign], [])
        with self.assertRaisesRegex(TierAError, "outside the queue"):
            apply_audit_responses(records, queue, [_response("foreign-id")])

    def test_application_never_mislabels_ai_teacher_as_human(self) -> None:
        records = _records(2, holdout=1)
        queue = select_audit_records(records, seed=2, minimum_sample_size=1)
        teacher_response = _response(
            queue[0]["stable_id"], reviewer_kind="ai_teacher"
        )
        with self.assertRaisesRegex(TierAError, "human responses only"):
            apply_audit_responses(records, queue, [teacher_response])


if __name__ == "__main__":
    unittest.main()
