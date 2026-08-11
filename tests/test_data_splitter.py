from __future__ import annotations

import unittest

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_jsonl_bytes, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.splitter import SplitError, assign_splits

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
                sentence=f"independent sentence {index}",
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
        self.assertEqual(sum(report["split_counts"].values()), len(output))

    def test_same_input_and_seed_are_byte_identical(self) -> None:
        first_output, first_report = assign_splits(leakage_fixture(), seed=17)
        second_output, second_report = assign_splits(leakage_fixture(), seed=17)

        self.assertEqual(canonical_jsonl_bytes(first_output), canonical_jsonl_bytes(second_output))
        self.assertEqual(canonical_json_bytes(first_report), canonical_json_bytes(second_report))

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
