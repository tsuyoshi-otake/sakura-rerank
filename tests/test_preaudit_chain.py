from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from sakura_rerank.data.preaudit_chain import (
    DataValidationError,
    validate_pre_audit_chain_manifest,
)


def _sha(number: int) -> str:
    return f"{number:064x}"


def _manifest(*, variant: str = "A") -> dict[str, object]:
    source_content = _sha(3)
    tier_a_content = _sha(5)
    split_content = _sha(13)
    holdout_content = _sha(9)
    return {
        "schema_version": 1,
        "manifest_kind": "tier_a_pre_audit_chain",
        "variant": variant,
        "status": "pre_audit_ready",
        "raw_text_in_manifest": False,
        "partition": {
            "report_sha256": _sha(1),
            "stage4_stable_id_exclusion": {
                "format_version": 1,
                "canonicalization": "utf8_lf_sorted_unique_stable_id_jsonl_v1",
                "count": 5_595,
                "content_sha256": _sha(2),
                "raw_stable_ids_in_report": False,
            },
        },
        "source_spans": {
            "manifest_sha256": _sha(4),
            "record_count": 20_000,
            "content_sha256": source_content,
            "extractor_git_sha": "a" * 40,
            "cleaner_version": "conservative_wikitext_v4",
        },
        "tier_a": {
            "report_sha256": _sha(6),
            "record_count": 18_000,
            "content_sha256": tier_a_content,
            "source_span_content_sha256": source_content,
        },
        "split": {
            "report_sha256": _sha(7),
            "seed": 20260813,
            "ratios": {"train": 0.7, "dev": 0.1, "final_holdout": 0.2},
            "record_count": 18_000,
            "tier_a_content_sha256": tier_a_content,
            "content_sha256": split_content,
            "split_counts": {"train": 12_600, "dev": 1_800, "final_holdout": 3_600},
            "split_content_sha256": {
                "train": _sha(8),
                "dev": _sha(10),
                "final_holdout": holdout_content,
            },
            "near_duplicate_threshold": 0.8,
            "cross_split_leakage_count": 0,
        },
        "human_audit": {
            "queue_manifest_sha256": _sha(11),
            "seed": 20260813,
            "minimum_sample_size": 3_000,
            "dataset_record_count": 18_000,
            "dataset_content_sha256": split_content,
            "queue_record_count": 3_600,
            "final_holdout_count": 3_600,
            "queue_content_sha256": _sha(12),
            "final_holdout_content_sha256": holdout_content,
        },
    }


class PreAuditChainTests(unittest.TestCase):
    def test_tracked_v4_manifests_are_ready_and_independent(self) -> None:
        manifests_dir = Path(__file__).parents[1] / "manifests"
        tracked_manifests = [
            json.loads(
                (manifests_dir / f"tier-a-v4-{variant.lower()}-pre-audit-chain-verified.json").read_text(
                    encoding="utf-8"
                )
            )
            for variant in ("A", "B")
        ]
        returned_manifests = [
            validate_pre_audit_chain_manifest(manifest) for manifest in tracked_manifests
        ]

        self.assertEqual([manifest["variant"] for manifest in returned_manifests], ["A", "B"])
        for manifest, returned_manifest in zip(tracked_manifests, returned_manifests, strict=True):
            self.assertEqual(returned_manifest["status"], "pre_audit_ready")
            self.assertEqual(returned_manifest["human_audit"]["queue_record_count"], 3_487)
            self.assertEqual(returned_manifest["split"]["cross_split_leakage_count"], 0)
            self.assertIsNot(returned_manifest, manifest)
            self.assertIsNot(returned_manifest["split"], manifest["split"])
            self.assertIsNot(returned_manifest["human_audit"], manifest["human_audit"])

        self.assertIsNot(tracked_manifests[0], tracked_manifests[1])
        self.assertIsNot(returned_manifests[0], returned_manifests[1])
        self.assertIsNot(returned_manifests[0]["split"], returned_manifests[1]["split"])

    def test_happy_path_accepts_each_reproducibility_variant_and_deep_copies(self) -> None:
        first = _manifest(variant="A")
        second = _manifest(variant="B")

        normalized_first = validate_pre_audit_chain_manifest(first)
        normalized_second = validate_pre_audit_chain_manifest(second)

        self.assertEqual(normalized_first["variant"], "A")
        self.assertEqual(normalized_second["variant"], "B")
        self.assertEqual(normalized_first, first)
        self.assertIsNot(normalized_first, first)
        self.assertIsNot(normalized_first["split"], first["split"])

    def test_rejects_cross_stage_count_and_hash_mismatches(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        tier_count = _manifest()
        tier_count["split"]["record_count"] = 17_999  # type: ignore[index]
        cases.append(("tier_a.record_count", tier_count))
        source_hash = _manifest()
        source_hash["tier_a"]["source_span_content_sha256"] = _sha(99)  # type: ignore[index]
        cases.append(("source_spans.content_sha256", source_hash))
        split_input_hash = _manifest()
        split_input_hash["split"]["tier_a_content_sha256"] = _sha(99)  # type: ignore[index]
        cases.append(("tier_a.content_sha256", split_input_hash))
        audit_dataset_hash = _manifest()
        audit_dataset_hash["human_audit"]["dataset_content_sha256"] = _sha(99)  # type: ignore[index]
        cases.append(("split.content_sha256", audit_dataset_hash))
        holdout_hash = _manifest()
        holdout_hash["human_audit"]["final_holdout_content_sha256"] = _sha(99)  # type: ignore[index]
        cases.append(("final_holdout", holdout_hash))

        for expected, manifest in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(DataValidationError, expected):
                    validate_pre_audit_chain_manifest(manifest)

    def test_rejects_invalid_leakage_ratios_and_queue_count(self) -> None:
        leakage = _manifest()
        leakage["split"]["cross_split_leakage_count"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "leakage"):
            validate_pre_audit_chain_manifest(leakage)

        ratios = _manifest()
        ratios["split"]["ratios"] = {"train": 0.6, "dev": 0.1, "final_holdout": 0.2}  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "sum exactly"):
            validate_pre_audit_chain_manifest(ratios)

        queue_count = _manifest()
        queue_count["human_audit"]["queue_record_count"] = 3_599  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "queue_record_count"):
            validate_pre_audit_chain_manifest(queue_count)

        sample_too_large = _manifest()
        sample_too_large["human_audit"]["minimum_sample_size"] = 3_601  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "minimum_sample_size"):
            validate_pre_audit_chain_manifest(sample_too_large)

    def test_rejects_raw_text_unknown_fields_and_noncanonical_exclusion(self) -> None:
        raw_text = _manifest()
        raw_text["raw_text"] = "not permitted"
        with self.assertRaisesRegex(DataValidationError, "manifest"):
            validate_pre_audit_chain_manifest(raw_text)

        nested_unknown = _manifest()
        nested_unknown["source_spans"]["raw_text"] = "not permitted"  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "source_spans"):
            validate_pre_audit_chain_manifest(nested_unknown)

        raw_identifiers = _manifest()
        raw_identifiers["partition"]["stage4_stable_id_exclusion"]["raw_stable_ids_in_report"] = True  # type: ignore[index]
        with self.assertRaisesRegex(DataValidationError, "raw_stable_ids"):
            validate_pre_audit_chain_manifest(raw_identifiers)

    def test_schema_is_valid_json_and_describes_the_contract_constants(self) -> None:
        schema_path = Path(__file__).parents[1] / "manifests" / "tier-a-pre-audit-chain.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(
            schema["properties"]["manifest_kind"]["const"], "tier_a_pre_audit_chain"
        )
        self.assertFalse(schema["properties"]["raw_text_in_manifest"]["const"])
        self.assertEqual(
            schema["properties"]["source_spans"]["properties"]["cleaner_version"]["const"],
            "conservative_wikitext_v4",
        )


if __name__ == "__main__":
    unittest.main()
