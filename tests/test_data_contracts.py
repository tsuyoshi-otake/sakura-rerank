from __future__ import annotations

import copy
import unittest
from pathlib import Path

from sakura_rerank.data.contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_json_hash,
    canonical_jsonl_bytes,
    read_jsonl,
    sentence_shingle_hashes,
    text_sha256,
    validate_record,
)


def fixture_record(stable_id: str = "fixture-example-001") -> dict[str, object]:
    reading = "fixture-reading"
    candidates = [
        {
            "surface": f"fixture_surface_{index:02d}",
            "cost": 100 + index,
            "source_category": "fixture",
        }
        for index in range(6)
    ]

    def snapshot(limit: int) -> dict[str, object]:
        values = copy.deepcopy(candidates[:limit])
        payload = {
            "limit": limit,
            "source": "fixture_full_reading_nbest",
            "sakura_input_head": "8e966dff456e4e7165e025f97c1f73327ff3f550",
            "dictionary_sha256": "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad",
            "reading": reading,
            "candidates": values,
        }
        return {**payload, "content_sha256": canonical_json_hash(payload)}

    return {
        "schema_version": 1,
        "record_type": "training_example",
        "stable_id": stable_id,
        "is_fixture": True,
        "source": {
            "corpus": "fixture",
            "snapshot_date": "2026-08-11",
            "article_id": "fixture-article-001",
            "page_id": "fixture-page-001",
            "revision_id": "fixture-revision-001",
            "paragraph_hash": text_sha256("fixture paragraph"),
            "sentence_hash": text_sha256("fixture sentence"),
            "sentence_shingle_hashes": sentence_shingle_hashes("fixture sentence"),
            "template_cluster_id": "fixture-template-001",
        },
        "session": {
            "session_id": "fixture-session-001",
            "left_context": "fixture left context",
            "left_context_policy": "sakura_input_committed_same_session",
        },
        "reading": reading,
        "gold_surface": "fixture_surface_00",
        "candidate_snapshots": {
            "training_top32": snapshot(32),
            "production_top6": snapshot(6),
        },
        "gold_index": 0,
        "oracle": {"k": 6, "hit": True},
        "split": "train",
        "tier": "C",
        "human_audit": {
            "status": "not_applicable",
            "dictionary_unique_reading": False,
            "forward_conversion_matches": False,
            "noise_free": False,
        },
        "training_eligible": False,
    }


class ContractValidationTests(unittest.TestCase):
    def test_checked_in_fixture_is_valid_and_is_not_training_data(self) -> None:
        path = Path(__file__).parent / "fixtures" / "data-contract.fixture.jsonl"
        records = read_jsonl(path)

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["is_fixture"])
        self.assertFalse(records[0]["training_eligible"])

    def test_requires_page_revision_and_leakage_provenance(self) -> None:
        record = fixture_record()
        del record["source"]["revision_id"]

        with self.assertRaisesRegex(ContractError, "source"):
            validate_record(record)

    def test_bounds_same_session_context_and_reading(self) -> None:
        record = fixture_record()
        record["session"]["left_context"] = "x" * 65
        with self.assertRaises(ContractError):
            validate_record(record)

        record = fixture_record()
        record["reading"] = "x" * 129
        with self.assertRaises(ContractError):
            validate_record(record)

    def test_rejects_fake_candidate_provenance_for_non_fixture_data(self) -> None:
        record = fixture_record()
        record["is_fixture"] = False
        record["source"]["corpus"] = "jawiki"

        with self.assertRaisesRegex(ContractError, "provenance|source"):
            validate_record(record)

    def test_rejects_inconsistent_top6_prefix(self) -> None:
        record = fixture_record()
        record["candidate_snapshots"]["production_top6"]["candidates"][0]["surface"] = (
            "different_fixture_surface"
        )
        snapshot = record["candidate_snapshots"]["production_top6"]
        payload = {key: snapshot[key] for key in (
            "limit",
            "source",
            "sakura_input_head",
            "dictionary_sha256",
            "reading",
            "candidates",
        )}
        snapshot["content_sha256"] = canonical_json_hash(payload)

        with self.assertRaisesRegex(ContractError, "prefix"):
            validate_record(record)

    def test_rejects_wrong_snapshot_content_hash(self) -> None:
        record = fixture_record()
        record["candidate_snapshots"]["training_top32"]["content_sha256"] = "0" * 64

        with self.assertRaisesRegex(ContractError, "content"):
            validate_record(record)

    def test_tier_a_requires_forward_verified_human_audit(self) -> None:
        record = fixture_record()
        record["tier"] = "A"
        record["human_audit"]["status"] = "accepted"
        record["training_eligible"] = False

        with self.assertRaisesRegex(ContractError, "human_audit"):
            validate_record(record)

    def test_canonical_serialization_is_key_order_independent(self) -> None:
        left = {"b": [2, 1], "a": {"z": False, "y": 1}}
        right = {"a": {"y": 1, "z": False}, "b": [2, 1]}

        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(canonical_json_hash(left), canonical_json_hash(right))

        record = fixture_record()
        self.assertTrue(canonical_jsonl_bytes([record]).endswith(b"\n"))
