from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.human_audit import (
    build_calibration_queue_manifest,
    build_queue_manifest,
    read_audit_responses,
    select_audit_records,
)
from sakura_rerank.data.reviewer import ReviewHTTPServer, ReviewStore, _review_order
from sakura_rerank.data.tier_a import TierAError
from tests.test_data_contracts import fixture_record


def _queue() -> tuple[list[dict[str, object]], dict[str, object]]:
    records = []
    for index in range(4):
        record = fixture_record(f"review-{index:03d}")
        record["split"] = "final-holdout"
        records.append(record)
    queue = select_audit_records(records, seed=91, minimum_sample_size=4)
    manifest = build_queue_manifest(records, queue, seed=91, minimum_sample_size=4)
    return queue, manifest


def _calibration_queue() -> tuple[list[dict[str, object]], dict[str, object]]:
    queue, _ = _queue()
    return queue, build_calibration_queue_manifest(
        queue,
        seed=91,
        source_dataset_record_count=4,
        source_dataset_content_sha256="a" * 64,
        teacher_state_content_sha256="b" * 64,
        disagreement_list_content_sha256="c" * 64,
        disagreement_record_count=3,
        one_pass_eligible_record_count=1,
        one_pass_selected_record_count=1,
    )


class ReviewStoreTests(unittest.TestCase):
    def test_calibration_manifest_uses_the_standard_review_store_contract(self) -> None:
        queue, manifest = _calibration_queue()
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(
                queue,
                manifest,
                Path(directory) / "responses.jsonl",
                "reviewer-1",
                "human",
            )
            self.assertEqual(store.state()["selected_record_count"], 4)
            self.assertEqual(store.state()["review_order"], "queue-seed-sha256-v1")

    def test_submit_is_atomic_immutable_and_resumable(self) -> None:
        queue, manifest = _queue()
        expected_first = min(
            (item["stable_id"] for item in queue),
            key=lambda stable_id: (_review_order(91, stable_id), stable_id),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            store = ReviewStore(queue, manifest, path, "reviewer-1", "human")
            self.assertEqual(store.state()["item"]["stable_id"], expected_first)
            result = store.submit(expected_first, "valid", "checked")
            self.assertEqual(result["completed_record_count"], 1)
            responses = read_audit_responses(path)
            self.assertEqual(responses[0]["stable_id"], expected_first)
            self.assertEqual(responses[0]["reviewer_id"], "reviewer-1")
            self.assertEqual(responses[0]["reviewer_kind"], "human")
            self.assertTrue(responses[0]["reviewed_at"].endswith("Z"))
            with self.assertRaisesRegex(TierAError, "immutable"):
                store.submit(expected_first, "ambiguous", "changed")
            resumed = ReviewStore(queue, manifest, path, "reviewer-2", "human", responses)
            self.assertEqual(resumed.state()["completed_record_count"], 1)
            self.assertNotEqual(resumed.state()["item"]["stable_id"], expected_first)

    def test_failed_publication_does_not_advance_memory_state(self) -> None:
        queue, manifest = _queue()
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(
                queue,
                manifest,
                Path(directory) / "responses.jsonl",
                "reviewer-1",
                "human",
            )
            stable_id = store.state()["item"]["stable_id"]
            with patch(
                "sakura_rerank.data.reviewer.publish_audit_responses",
                side_effect=OSError("injected"),
            ):
                with self.assertRaisesRegex(OSError, "injected"):
                    store.submit(stable_id, "valid", "")
            self.assertEqual(store.state()["completed_record_count"], 0)

    def test_rejects_invalid_reviewer_or_noncurrent_item(self) -> None:
        queue, manifest = _queue()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            with self.assertRaisesRegex(TierAError, "reviewer_id"):
                ReviewStore(queue, manifest, path, "invalid reviewer", "human")
            with self.assertRaisesRegex(TierAError, "reviewer_kind"):
                ReviewStore(queue, manifest, path, "reviewer-1", "unknown")
            store = ReviewStore(queue, manifest, path, "reviewer-1", "human")
            current = store.state()["item"]["stable_id"]
            other = next(item["stable_id"] for item in queue if item["stable_id"] != current)
            with self.assertRaisesRegex(TierAError, "current pending"):
                store.submit(other, "valid", "")


class ReviewHTTPServerTests(unittest.TestCase):
    def test_api_requires_token_and_persists_a_review(self) -> None:
        queue, manifest = _queue()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            store = ReviewStore(queue, manifest, path, "reviewer-http", "ai_teacher")
            server = ReviewHTTPServer(0, store, session_token="test-token")
            self.assertEqual(server.server_address[0], "127.0.0.1")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(f"{base}/api/state", timeout=3)
                self.assertEqual(denied.exception.code, 401)

                request = urllib.request.Request(
                    f"{base}/api/state", headers={"X-Review-Token": "test-token"}
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    state = json.loads(response.read())
                    self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])

                body = json.dumps(
                    {
                        "stable_id": state["item"]["stable_id"],
                        "verdict": "wrong_segmentation",
                        "note": "segment boundary checked",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    f"{base}/api/review",
                    data=body,
                    method="POST",
                    headers={
                        "X-Review-Token": "test-token",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    updated = json.loads(response.read())
                self.assertEqual(updated["completed_record_count"], 1)
                self.assertEqual(read_audit_responses(path)[0]["verdict"], "wrong_segmentation")
                self.assertEqual(read_audit_responses(path)[0]["reviewer_kind"], "ai_teacher")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
