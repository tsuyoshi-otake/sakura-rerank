from __future__ import annotations

import hashlib
import time
import unittest

from sakura_rerank.data.contracts import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sentence_shingle_hashes,
    text_sha256,
)
from sakura_rerank.data.splitter import (
    SplitError,
    _UnionFind,
    _union_near_duplicates,
    assign_splits,
)

from tests.test_data_contracts import fixture_record


def split_record(
    stable_id: str,
    *,
    article_id: str,
    paragraph: str,
    sentence: str,
    template_cluster_id: str | None = None,
    split: str | None = None,
) -> dict[str, object]:
    record = fixture_record(stable_id)
    record["split"] = split
    source = record["source"]
    source["article_id"] = article_id
    source["page_id"] = stable_id + "-page"
    source["revision_id"] = stable_id + "-revision"
    source["paragraph_hash"] = text_sha256(paragraph)
    source["sentence_hash"] = text_sha256(sentence)
    source["sentence_shingle_hashes"] = sentence_shingle_hashes(sentence)
    source["template_cluster_id"] = template_cluster_id
    return record


def leakage_fixture() -> list[dict[str, object]]:
    records = [
        split_record(
            "fixture-000",
            article_id="article-a",
            paragraph="exact paragraph shared by two pages",
            sentence="independent sentence zero",
        ),
        split_record(
            "fixture-001",
            article_id="article-a",
            paragraph="article a second paragraph",
            sentence="independent sentence one",
        ),
        split_record(
            "fixture-002",
            article_id="article-b",
            paragraph="exact paragraph shared by two pages",
            sentence="independent sentence two",
        ),
        split_record(
            "fixture-003",
            article_id="article-c",
            paragraph="near duplicate paragraph three",
            sentence="near duplicate sentence with stable wording",
        ),
        split_record(
            "fixture-004",
            article_id="article-d",
            paragraph="near duplicate paragraph four",
            sentence="near duplicate sentence with stable wording!",
        ),
        split_record(
            "fixture-005",
            article_id="article-e",
            paragraph="template paragraph five",
            sentence="template sentence five",
            template_cluster_id="template-cluster-1",
        ),
        split_record(
            "fixture-006",
            article_id="article-f",
            paragraph="template paragraph six",
            sentence="template sentence six",
            template_cluster_id="template-cluster-1",
        ),
    ]
    for index in range(7, 19):
        records.append(
            split_record(
                f"fixture-{index:03d}",
                article_id=f"article-{index}",
                paragraph=f"independent paragraph {index}",
                sentence=chr(ord("a") + index) * 16,
            )
        )
    return records


class SplitterTests(unittest.TestCase):
    def test_all_leakage_relations_stay_in_one_split(self) -> None:
        output, report = assign_splits(leakage_fixture(), seed=20260811)
        by_id = {record["stable_id"]: record["split"] for record in output}

        self.assertEqual(by_id["fixture-000"], by_id["fixture-001"])
        self.assertEqual(by_id["fixture-000"], by_id["fixture-002"])
        self.assertEqual(by_id["fixture-003"], by_id["fixture-004"])
        self.assertEqual(by_id["fixture-005"], by_id["fixture-006"])
        self.assertGreaterEqual(report["sentence_near_duplicate_cluster_count"], 1)
        self.assertEqual(
            report["cross_split_leakage"],
            {
                "article": 0,
                "paragraph_exact": 0,
                "sentence_near_duplicate": 0,
                "template_cluster": 0,
            },
        )
        self.assertEqual(report["record_count"], len(output))
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(sum(report["split_counts"].values()), len(output))
        self.assertTrue(
            all(
                report["split_counts"][split] > 0
                for split in ("train", "dev", "final-holdout")
            )
        )
        self.assertEqual(
            set(report["split_content_sha256"]),
            {"train", "dev", "final-holdout"},
        )
        for split in ("train", "dev", "final-holdout"):
            expected = hashlib.sha256(
                canonical_jsonl_bytes(
                    [record for record in output if record["split"] == split]
                )
            ).hexdigest()
            self.assertEqual(report["split_content_sha256"][split], expected)

    def test_same_input_and_seed_are_byte_identical(self) -> None:
        first_output, first_report = assign_splits(leakage_fixture(), seed=17)
        second_output, second_report = assign_splits(leakage_fixture(), seed=17)

        self.assertEqual(
            canonical_jsonl_bytes(first_output),
            canonical_jsonl_bytes(second_output),
        )
        self.assertEqual(
            canonical_json_bytes(first_report),
            canonical_json_bytes(second_report),
        )
        self.assertEqual(
            first_report["split_content_sha256"],
            second_report["split_content_sha256"],
        )

    def test_identical_signature_join_is_bounded_for_10000_records(self) -> None:
        signature = ["a" * 64, "b" * 64, "c" * 64]
        records = [
            {"source": {"sentence_shingle_hashes": signature}}
            for _ in range(10_000)
        ]
        union_find = _UnionFind(len(records))

        started = time.perf_counter()
        pair_count, signature_count, comparison_count, near_union = (
            _union_near_duplicates(records, union_find, threshold=0.8)
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(pair_count, 10_000 * 9_999 // 2)
        self.assertEqual(signature_count, 1)
        self.assertEqual(comparison_count, 0)
        self.assertEqual(len(near_union.groups()), 1)
        self.assertLess(elapsed, 5.0)

    def test_existing_assignment_is_immutable_and_conflicts_fail(self) -> None:
        records = leakage_fixture()
        records[0]["split"] = "final-holdout"
        output, _ = assign_splits(records, seed=1)
        by_id = {record["stable_id"]: record["split"] for record in output}
        self.assertEqual(by_id["fixture-001"], "final-holdout")
        self.assertEqual(by_id["fixture-002"], "final-holdout")

        conflicting = leakage_fixture()[:2]
        conflicting[0]["split"] = "train"
        conflicting[1]["split"] = "dev"
        with self.assertRaisesRegex(SplitError, "conflicts"):
            assign_splits(conflicting, seed=1)
