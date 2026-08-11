from __future__ import annotations

import copy
import unittest
from pathlib import Path

from sakura_rerank.data.contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    VERIFIED_RESEARCH_EXPORTER_IDENTITIES,
    ContractError,
    candidate_fingerprint,
    canonical_json_bytes,
    canonical_json_hash,
    canonical_jsonl_bytes,
    read_jsonl,
    sentence_shingle_hashes,
    text_sha256,
    validate_record,
)


def _candidate(
    index: int,
    reading: str,
    *,
    is_fixture: bool,
) -> dict[str, object]:
    surface = f"fixture_surface_{index:02d}"
    local_cost = 100 + index
    segment_category = "fixture" if is_fixture else "system_dictionary"
    return {
        "rank": index,
        "surface": surface,
        "local_cost": local_cost,
        "source_category": segment_category,
        "fingerprint": candidate_fingerprint(surface, local_cost),
        "system_entry_index": None if is_fixture else index,
        "segments": [
            {
                "reading_start": 0,
                "reading_end": len(reading.encode("utf-8")),
                "text_start": 0,
                "text_end": len(surface.encode("utf-8")),
                "left_id": 0,
                "right_id": 0,
                "flags": 0,
                "source_category": segment_category,
            }
        ],
    }


def _snapshot_hash(
    snapshot: dict[str, object], converter_provenance: dict[str, object]
) -> str:
    payload = {
        "limit": snapshot["limit"],
        "source": snapshot["source"],
        "feature_contract_version": snapshot["feature_contract_version"],
        "converter_provenance": converter_provenance,
        "reading": snapshot["reading"],
        "candidates": snapshot["candidates"],
    }
    if "exporter_run" in snapshot:
        payload["exporter_run"] = snapshot["exporter_run"]
    return canonical_json_hash(payload)


def _rehash_snapshots(record: dict[str, object]) -> None:
    provenance = record["converter_provenance"]
    for snapshot in record["candidate_snapshots"].values():
        snapshot["content_sha256"] = _snapshot_hash(snapshot, provenance)


def fixture_record(stable_id: str = "fixture-example-001") -> dict[str, object]:
    reading = "fixture-reading"
    candidates = [_candidate(index, reading, is_fixture=True) for index in range(2)]
    provenance = {
        "kind": "contract_fixture",
        "sakura_input_head": None,
        "dictionary_sha256": None,
        "feature_contract_version": 1,
    }

    def snapshot(limit: int) -> dict[str, object]:
        value: dict[str, object] = {
            "limit": limit,
            "source": "fixture_full_reading_nbest",
            "feature_contract_version": 1,
            "reading": reading,
            "candidates": copy.deepcopy(candidates[:limit]),
        }
        if limit == 32:
            value["exporter_run"] = {
                "contract_version": 1,
                "verification_status": "fixture",
                "exporter_git_sha": None,
                "exporter_binary_sha256": None,
                "requested_limit": 32,
                "effective_converter_bound": None,
                "returned_count": len(value["candidates"]),
                "result_status": "search_exhausted",
            }
        value["content_sha256"] = _snapshot_hash(value, provenance)
        return value

    return {
        "schema_version": 3,
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
        "converter_provenance": provenance,
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
        "tier_a_verification": {
            "contract_version": 2,
            "status": "not_applicable",
            "verification_source": "not_applicable",
            "dictionary_unique_reading": False,
            "forward_conversion_matches": False,
            "normalized_gold_matches": False,
            "exact_dictionary_path_covers_reading": False,
        },
        "sampled_human_audit": {
            "selection": "not_sampled",
            "status": "not_reviewed",
            "noise_free": None,
            "reviewer_id": None,
            "reviewed_at": None,
        },
        "training_eligible": False,
    }


def production_record(candidate_count: int = 2) -> dict[str, object]:
    """Build an unverified production counterexample, never exporter evidence."""

    record = fixture_record("validator-production-example")
    record["is_fixture"] = False
    record["source"]["corpus"] = "jawiki"
    record["source"]["snapshot_date"] = "2026-08-01"
    record["converter_provenance"] = {
        "kind": "sakura_input_converter_export",
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "feature_contract_version": 1,
    }
    candidates = [
        _candidate(index, record["reading"], is_fixture=False)
        for index in range(candidate_count)
    ]
    for snapshot in record["candidate_snapshots"].values():
        snapshot["source"] = "sakura_converter_full_reading_nbest"
        snapshot["candidates"] = copy.deepcopy(candidates[: snapshot["limit"]])
    record["candidate_snapshots"]["training_top32"]["exporter_run"] = {
        "contract_version": 1,
        "verification_status": "unverified",
        "exporter_git_sha": None,
        "exporter_binary_sha256": None,
        "requested_limit": 32,
        "effective_converter_bound": 32,
        "returned_count": candidate_count,
        "result_status": "truncated" if candidate_count == 32 else "search_exhausted",
    }
    record["tier"] = "A"
    record["tier_a_verification"] = {
        "contract_version": 2,
        "status": "passed",
        "verification_source": "sakura_converter_forward_verification",
        "dictionary_unique_reading": True,
        "forward_conversion_matches": True,
        "normalized_gold_matches": True,
        "exact_dictionary_path_covers_reading": True,
    }
    record["training_eligible"] = True
    _rehash_snapshots(record)
    return record


class ContractValidationTests(unittest.TestCase):
    def test_checked_in_fixture_is_valid_and_cannot_claim_production_identity(self) -> None:
        path = Path(__file__).parent / "fixtures" / "data-contract.fixture.jsonl"
        records = read_jsonl(path)

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["is_fixture"])
        self.assertFalse(records[0]["training_eligible"])
        self.assertIsNone(records[0]["converter_provenance"]["sakura_input_head"])
        self.assertIsNone(records[0]["converter_provenance"]["dictionary_sha256"])
        self.assertEqual(
            records[0]["candidate_snapshots"]["training_top32"]["exporter_run"][
                "verification_status"
            ],
            "fixture",
        )

    def test_requires_page_revision_and_converter_provenance(self) -> None:
        record = fixture_record()
        del record["source"]["revision_id"]
        with self.assertRaisesRegex(ContractError, "source"):
            validate_record(record)

        record = fixture_record()
        del record["converter_provenance"]
        with self.assertRaisesRegex(ContractError, "record"):
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

    def test_production_record_is_fail_closed_to_pinned_head_and_dictionary(self) -> None:
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(production_record())

        for field, value in (
            ("sakura_input_head", "a" * 40),
            ("dictionary_sha256", "b" * 64),
        ):
            with self.subTest(field=field):
                record = production_record()
                record["converter_provenance"][field] = value
                _rehash_snapshots(record)
                with self.assertRaisesRegex(ContractError, "pinned"):
                    validate_record(record)

        record = production_record()
        record["source"]["snapshot_date"] = "2026-07-01"
        with self.assertRaisesRegex(ContractError, "pinned jawiki"):
            validate_record(record)

    def test_rejects_fixture_provenance_for_production_and_training(self) -> None:
        record = production_record()
        record["converter_provenance"] = {
            "kind": "contract_fixture",
            "sakura_input_head": None,
            "dictionary_sha256": None,
            "feature_contract_version": 1,
        }
        _rehash_snapshots(record)
        with self.assertRaisesRegex(ContractError, "converter|provenance"):
            validate_record(record)

        record = production_record()
        candidate = record["candidate_snapshots"]["training_top32"]["candidates"][0]
        candidate["source_category"] = "fixture"
        candidate["segments"][0]["source_category"] = "fixture"
        _rehash_snapshots(record)
        with self.assertRaisesRegex(ContractError, "fixture|provenance"):
            validate_record(record)

    def test_training_rejects_missing_gold_and_single_candidate(self) -> None:
        record = production_record()
        record["gold_surface"] = "gold-not-in-candidates"
        record["gold_index"] = None
        record["oracle"]["hit"] = False
        with self.assertRaisesRegex(ContractError, "gold candidate"):
            validate_record(record)

        record = production_record()
        for snapshot in record["candidate_snapshots"].values():
            snapshot["candidates"] = snapshot["candidates"][:1]
        record["candidate_snapshots"]["training_top32"]["exporter_run"][
            "returned_count"
        ] = 1
        _rehash_snapshots(record)
        with self.assertRaisesRegex(ContractError, "at least two"):
            validate_record(record)

        record = production_record()
        record["gold_surface"] = None
        with self.assertRaisesRegex(ContractError, "gold_surface"):
            validate_record(record)

    def test_tier_a_automatic_verification_is_separate_from_sampled_audit(self) -> None:
        unsampled = production_record()
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(unsampled)

        pending = production_record()
        pending["sampled_human_audit"] = {
            "selection": "selected",
            "status": "pending",
            "noise_free": None,
            "reviewer_id": None,
            "reviewed_at": None,
        }
        pending["training_eligible"] = False
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(pending)

        pending["training_eligible"] = True
        with self.assertRaisesRegex(ContractError, "human audit"):
            validate_record(pending)

        accepted = production_record()
        accepted["sampled_human_audit"] = {
            "selection": "selected",
            "status": "accepted",
            "noise_free": True,
            "reviewer_id": "reviewer-001",
            "reviewed_at": "2026-08-11T06:00:00Z",
        }
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(accepted)

    def test_tier_a_requires_converter_derived_exact_dictionary_gold_path(self) -> None:
        control = production_record()
        gold = control["candidate_snapshots"]["training_top32"]["candidates"][0]
        self.assertEqual(
            {segment["source_category"] for segment in gold["segments"]},
            {"system_dictionary"},
        )
        self.assertTrue(
            control["tier_a_verification"]["exact_dictionary_path_covers_reading"]
        )
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(control)

        for fallback in (
            "reading_fallback",
            "katakana_fallback",
            "generated_literal",
        ):
            with self.subTest(fallback=fallback):
                record = production_record()
                for snapshot in record["candidate_snapshots"].values():
                    candidate = snapshot["candidates"][0]
                    candidate["source_category"] = fallback
                    candidate["system_entry_index"] = None
                    candidate["segments"][0]["source_category"] = fallback
                _rehash_snapshots(record)
                with self.assertRaisesRegex(ContractError, "gold path"):
                    validate_record(record)

    def test_tier_a_rejects_mixed_fallback_but_allows_system_user_mix(self) -> None:
        def set_mixed_segments(record: dict[str, object], second_source: str) -> None:
            reading_end = len(record["reading"].encode("utf-8"))
            text_end = len(record["gold_surface"].encode("utf-8"))
            reading_midpoint = reading_end // 2
            text_midpoint = text_end // 2
            segments = [
                {
                    "reading_start": 0,
                    "reading_end": reading_midpoint,
                    "text_start": 0,
                    "text_end": text_midpoint,
                    "left_id": 1,
                    "right_id": 1,
                    "flags": 0,
                    "source_category": "system_dictionary",
                },
                {
                    "reading_start": reading_midpoint,
                    "reading_end": reading_end,
                    "text_start": text_midpoint,
                    "text_end": text_end,
                    "left_id": 2,
                    "right_id": 2,
                    "flags": 0,
                    "source_category": second_source,
                },
            ]
            for snapshot in record["candidate_snapshots"].values():
                candidate = snapshot["candidates"][0]
                candidate["source_category"] = "mixed"
                candidate["system_entry_index"] = None
                candidate["segments"] = copy.deepcopy(segments)
            _rehash_snapshots(record)

        fallback = production_record()
        set_mixed_segments(fallback, "reading_fallback")
        with self.assertRaisesRegex(ContractError, "gold path"):
            validate_record(fallback)

        exact = production_record()
        set_mixed_segments(exact, "user_dictionary")
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(exact)

    def test_tier_a_rejects_missing_or_false_exact_path_coverage(self) -> None:
        missing = production_record()
        del missing["tier_a_verification"]["exact_dictionary_path_covers_reading"]
        with self.assertRaisesRegex(ContractError, "verification fields"):
            validate_record(missing)

        false = production_record()
        false["tier_a_verification"]["exact_dictionary_path_covers_reading"] = False
        with self.assertRaisesRegex(ContractError, "passed requires"):
            validate_record(false)

    def test_top32_requires_separate_verified_exporter_and_complete_run_evidence(self) -> None:
        self.assertEqual(
            VERIFIED_RESEARCH_EXPORTER_IDENTITIES,
            frozenset(
                {
                    (
                        "e6242eecb33e7872954229d7faafef2950a11740",
                        "a720f01d763b7129c5a64afdd7e0ac291c7c0efeac63503a0c37ffacddb9a4fd",
                    )
                }
            ),
        )

        base_head_only = production_record(candidate_count=32)
        del base_head_only["candidate_snapshots"]["training_top32"]["exporter_run"]
        _rehash_snapshots(base_head_only)
        with self.assertRaisesRegex(ContractError, "snapshot identity"):
            validate_record(base_head_only)

        unverified_top32 = production_record(candidate_count=32)
        with self.assertRaisesRegex(ContractError, "top-32 remains blocked"):
            validate_record(unverified_top32)

        bounded_to_18 = production_record(candidate_count=18)
        run = bounded_to_18["candidate_snapshots"]["training_top32"]["exporter_run"]
        run["effective_converter_bound"] = 18
        _rehash_snapshots(bounded_to_18)
        with self.assertRaisesRegex(ContractError, "top-32 contract bound"):
            validate_record(bounded_to_18)

        unexplained_short_result = production_record()
        run = unexplained_short_result["candidate_snapshots"]["training_top32"]["exporter_run"]
        run["result_status"] = "truncated"
        _rehash_snapshots(unexplained_short_result)
        with self.assertRaisesRegex(ContractError, "search_exhausted"):
            validate_record(unexplained_short_result)

        claimed_verified_without_identity = production_record()
        run = claimed_verified_without_identity["candidate_snapshots"]["training_top32"]["exporter_run"]
        run["verification_status"] = "verified"
        _rehash_snapshots(claimed_verified_without_identity)
        with self.assertRaisesRegex(ContractError, "Git SHA or binary SHA-256"):
            validate_record(claimed_verified_without_identity)

    def test_rejects_inconsistent_top6_prefix(self) -> None:
        record = fixture_record()
        snapshot = record["candidate_snapshots"]["production_top6"]
        candidate = snapshot["candidates"][0]
        candidate["surface"] = "different_fixture_surface"
        candidate["segments"][0]["text_end"] = len(
            candidate["surface"].encode("utf-8")
        )
        candidate["fingerprint"] = candidate_fingerprint(
            candidate["surface"], candidate["local_cost"]
        )
        _rehash_snapshots(record)

        with self.assertRaisesRegex(ContractError, "prefix"):
            validate_record(record)

    def test_rejects_wrong_snapshot_content_hash(self) -> None:
        record = fixture_record()
        record["candidate_snapshots"]["training_top32"]["content_sha256"] = "0" * 64

        with self.assertRaisesRegex(ContractError, "content"):
            validate_record(record)

    def test_converter_feature_contract_rejects_guessed_or_inconsistent_values(self) -> None:
        validated = validate_record(fixture_record())
        snapshot = validated["candidate_snapshots"]["training_top32"]
        self.assertEqual(snapshot["feature_contract_version"], 1)
        self.assertEqual(
            set(snapshot["candidates"][0]),
            {
                "rank",
                "surface",
                "local_cost",
                "source_category",
                "fingerprint",
                "system_entry_index",
                "segments",
            },
        )
        self.assertEqual(
            set(snapshot["candidates"][0]["segments"][0]),
            {
                "reading_start",
                "reading_end",
                "text_start",
                "text_end",
                "left_id",
                "right_id",
                "flags",
                "source_category",
            },
        )

        mutations = {
            "missing segment": lambda candidate: candidate.pop("segments"),
            "unknown guessed feature": lambda candidate: candidate.__setitem__("guessed_pos", 1),
            "wrong rank": lambda candidate: candidate.__setitem__("rank", 4),
            "wrong fingerprint": lambda candidate: candidate.__setitem__("fingerprint", "0" * 16),
            "broken boundary": lambda candidate: candidate["segments"][0].__setitem__(
                "reading_end", 1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = fixture_record()
                candidate = record["candidate_snapshots"]["training_top32"]["candidates"][0]
                mutate(candidate)
                _rehash_snapshots(record)
                with self.assertRaises(ContractError):
                    validate_record(record)

        record = fixture_record()
        record["candidate_snapshots"]["training_top32"]["feature_contract_version"] = 2
        _rehash_snapshots(record)
        with self.assertRaisesRegex(ContractError, "feature contract"):
            validate_record(record)

    def test_canonical_serialization_is_key_order_independent(self) -> None:
        left = {"b": [2, 1], "a": {"z": False, "y": 1}}
        right = {"a": {"y": 1, "z": False}, "b": [2, 1]}

        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(canonical_json_hash(left), canonical_json_hash(right))
        self.assertTrue(canonical_jsonl_bytes([fixture_record()]).endswith(b"\n"))
