from __future__ import annotations

import hashlib
import random
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

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
    exclude_historical_components,
    publish_historical_exclusion_directory,
)

from tests.test_data_contracts import _rehash_snapshots, fixture_record, production_record


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


def tier_a_split_record(
    stable_id: str,
    *,
    article_id: str,
    paragraph: str,
    sentence: str,
    template_cluster_id: str | None = None,
    sentence_shingles: list[str] | None = None,
) -> dict[str, object]:
    """Return a contract-valid, reviewed Tier-A record for exclusion tests."""

    record = production_record()
    record["stable_id"] = stable_id
    source = record["source"]
    source["article_id"] = article_id
    source["page_id"] = stable_id + "-page"
    source["revision_id"] = stable_id + "-revision"
    source["paragraph_hash"] = text_sha256(paragraph)
    source["sentence_hash"] = text_sha256(sentence)
    source["sentence_shingle_hashes"] = (
        sentence_shingle_hashes(sentence)
        if sentence_shingles is None
        else sorted(sentence_shingles)
    )
    source["template_cluster_id"] = template_cluster_id
    exporter = record["candidate_snapshots"]["training_top32"]["exporter_run"]
    exporter.update(
        {
            "verification_status": "verified",
            "exporter_git_sha": "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1",
            "exporter_binary_sha256": (
                "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
            ),
        }
    )
    _rehash_snapshots(record)
    return record


def hashed_shingles(*values: int) -> list[str]:
    return [f"{value:064x}" for value in values]


class SplitterTests(unittest.TestCase):
    def test_historical_exclusion_covers_every_direct_relation(self) -> None:
        historical = [
            tier_a_split_record(
                "historical-article",
                article_id="article-shared",
                paragraph="historical article paragraph",
                sentence="historical article sentence",
            ),
            tier_a_split_record(
                "historical-paragraph",
                article_id="article-paragraph-history",
                paragraph="paragraph-shared",
                sentence="historical paragraph sentence",
            ),
            tier_a_split_record(
                "historical-template",
                article_id="article-template-history",
                paragraph="historical template paragraph",
                sentence="historical template sentence",
                template_cluster_id="template-shared",
            ),
            tier_a_split_record(
                "historical-near",
                article_id="article-near-history",
                paragraph="historical near paragraph",
                sentence="historical near sentence",
                sentence_shingles=hashed_shingles(1, 2, 3, 4),
            ),
        ]
        candidates = [
            tier_a_split_record(
                "candidate-article",
                article_id="article-shared",
                paragraph="candidate article paragraph",
                sentence="candidate article sentence",
            ),
            tier_a_split_record(
                "candidate-paragraph",
                article_id="article-paragraph-candidate",
                paragraph="paragraph-shared",
                sentence="candidate paragraph sentence",
            ),
            tier_a_split_record(
                "candidate-template",
                article_id="article-template-candidate",
                paragraph="candidate template paragraph",
                sentence="candidate template sentence",
                template_cluster_id="template-shared",
            ),
            tier_a_split_record(
                "candidate-near",
                article_id="article-near-candidate",
                paragraph="candidate near paragraph",
                sentence="candidate near sentence",
                sentence_shingles=hashed_shingles(1, 2, 3, 4),
            ),
            tier_a_split_record(
                "candidate-eligible",
                article_id="article-eligible",
                paragraph="eligible paragraph",
                sentence="eligible sentence",
            ),
        ]

        eligible, excluded, report = exclude_historical_components(historical, candidates)

        self.assertEqual([record["stable_id"] for record in eligible], ["candidate-eligible"])
        self.assertEqual(
            [record["stable_id"] for record in excluded],
            [
                "candidate-article",
                "candidate-near",
                "candidate-paragraph",
                "candidate-template",
            ],
        )
        self.assertEqual(report["historical_input"]["count"], 4)
        self.assertEqual(report["candidate_input"]["count"], 5)
        self.assertEqual(report["eligible"]["count"], 1)
        self.assertEqual(report["excluded"]["count"], 4)
        self.assertEqual(report["raw_text"], False)
        self.assertEqual(report["raw_ids"], False)
        self.assertNotIn("candidate-eligible", canonical_json_bytes(report).decode("utf-8"))

    def test_historical_exclusion_follows_transitive_components(self) -> None:
        historical = [
            tier_a_split_record(
                "historical-root",
                article_id="transitive-article",
                paragraph="transitive history paragraph",
                sentence="transitive history sentence",
            )
        ]
        candidates = [
            tier_a_split_record(
                "candidate-bridge",
                article_id="transitive-article",
                paragraph="transitive bridge paragraph",
                sentence="transitive bridge sentence",
            ),
            tier_a_split_record(
                "candidate-transitive",
                article_id="transitive-other-article",
                paragraph="transitive bridge paragraph",
                sentence="transitive other sentence",
            ),
            tier_a_split_record(
                "candidate-disconnected",
                article_id="disconnected-article",
                paragraph="disconnected paragraph",
                sentence="disconnected sentence",
            ),
        ]

        eligible, excluded, report = exclude_historical_components(historical, candidates)

        self.assertEqual(
            [record["stable_id"] for record in eligible], ["candidate-disconnected"]
        )
        self.assertEqual(
            [record["stable_id"] for record in excluded],
            ["candidate-bridge", "candidate-transitive"],
        )
        self.assertEqual(report["historical_touching_component_count"], 1)
        self.assertEqual(report["excluded_component_count"], 1)
        self.assertEqual(report["eligible_component_count"], 1)

    def test_historical_exclusion_rejects_overlap_duplicates_and_malformed_inputs(self) -> None:
        historical = [
            tier_a_split_record(
                "historical-reject",
                article_id="historical-reject-article",
                paragraph="historical reject paragraph",
                sentence="historical reject sentence",
            )
        ]
        candidate = tier_a_split_record(
            "candidate-reject",
            article_id="candidate-reject-article",
            paragraph="candidate reject paragraph",
            sentence="candidate reject sentence",
        )

        with self.assertRaisesRegex(SplitError, "disjoint"):
            exclude_historical_components(historical, [deepcopy(historical[0])])
        with self.assertRaisesRegex(SplitError, "contract validation"):
            exclude_historical_components(historical, [candidate, deepcopy(candidate)])
        malformed = deepcopy(candidate)
        malformed["reading"] = "x" * 129
        with self.assertRaisesRegex(SplitError, "contract validation"):
            exclude_historical_components(historical, [malformed])
        with self.assertRaisesRegex(SplitError, "finite number"):
            exclude_historical_components(historical, [candidate], near_duplicate_threshold=True)

    def test_historical_exclusion_is_deterministic_at_threshold_boundary(self) -> None:
        historical = [
            tier_a_split_record(
                "historical-boundary",
                article_id="boundary-history",
                paragraph="boundary history paragraph",
                sentence="boundary history sentence",
                sentence_shingles=hashed_shingles(1, 2, 3, 4),
            ),
            tier_a_split_record(
                "historical-independent",
                article_id="independent-history",
                paragraph="independent history paragraph",
                sentence="independent history sentence",
            ),
        ]
        candidates = [
            tier_a_split_record(
                "candidate-boundary",
                article_id="boundary-candidate",
                paragraph="boundary candidate paragraph",
                sentence="boundary candidate sentence",
                sentence_shingles=hashed_shingles(1, 2, 3, 4, 5),
            ),
            tier_a_split_record(
                "candidate-independent",
                article_id="independent-candidate",
                paragraph="independent candidate paragraph",
                sentence="independent candidate sentence",
            ),
        ]

        eligible, excluded, report = exclude_historical_components(
            historical, candidates, near_duplicate_threshold=0.8
        )
        reordered_eligible, reordered_excluded, reordered_report = (
            exclude_historical_components(
                list(reversed(historical)),
                list(reversed(candidates)),
                near_duplicate_threshold=0.8,
            )
        )
        above_eligible, above_excluded, _ = exclude_historical_components(
            historical, candidates, near_duplicate_threshold=0.800001
        )

        self.assertEqual([record["stable_id"] for record in eligible], ["candidate-independent"])
        self.assertEqual([record["stable_id"] for record in excluded], ["candidate-boundary"])
        self.assertEqual(
            canonical_jsonl_bytes(eligible), canonical_jsonl_bytes(reordered_eligible)
        )
        self.assertEqual(
            canonical_jsonl_bytes(excluded), canonical_jsonl_bytes(reordered_excluded)
        )
        self.assertEqual(
            canonical_json_bytes(report), canonical_json_bytes(reordered_report)
        )
        self.assertEqual(
            [record["stable_id"] for record in above_eligible],
            ["candidate-boundary", "candidate-independent"],
        )
        self.assertEqual(above_excluded, [])

    def test_historical_exclusion_publication_is_input_bound_atomic_and_immutable(self) -> None:
        historical = [
            tier_a_split_record(
                "historical-published",
                article_id="published-shared",
                paragraph="published historical paragraph",
                sentence="published historical sentence",
            )
        ]
        candidates = [
            tier_a_split_record(
                "candidate-published-excluded",
                article_id="published-shared",
                paragraph="published excluded paragraph",
                sentence="published excluded sentence",
            ),
            tier_a_split_record(
                "candidate-published-eligible",
                article_id="published-independent",
                paragraph="published eligible paragraph",
                sentence="published eligible sentence",
            ),
        ]
        historical_hash = hashlib.sha256(canonical_jsonl_bytes(historical)).hexdigest()
        candidate_hash = hashlib.sha256(canonical_jsonl_bytes(candidates)).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "historical-exclusion"
            report = publish_historical_exclusion_directory(
                target,
                historical,
                candidates,
                expected_historical_record_count=1,
                expected_historical_content_sha256=historical_hash,
                expected_candidate_record_count=2,
                expected_candidate_content_sha256=candidate_hash,
            )
            self.assertEqual(
                (target / "eligible.jsonl").read_bytes(),
                canonical_jsonl_bytes([candidates[1]]),
            )
            self.assertEqual(
                (target / "excluded.jsonl").read_bytes(),
                canonical_jsonl_bytes([candidates[0]]),
            )
            self.assertEqual(
                (target / "report.json").read_bytes(),
                canonical_json_bytes(report) + b"\n",
            )
            with self.assertRaisesRegex(SplitError, "immutable"):
                publish_historical_exclusion_directory(
                    target,
                    historical,
                    candidates,
                    expected_historical_record_count=1,
                    expected_historical_content_sha256=historical_hash,
                    expected_candidate_record_count=2,
                    expected_candidate_content_sha256=candidate_hash,
                )

            with self.assertRaisesRegex(SplitError, "expected commitment"):
                publish_historical_exclusion_directory(
                    root / "wrong-input",
                    historical,
                    candidates,
                    expected_historical_record_count=1,
                    expected_historical_content_sha256="0" * 64,
                    expected_candidate_record_count=2,
                    expected_candidate_content_sha256=candidate_hash,
                )

            failed = root / "failed"
            with patch("sakura_rerank.data.splitter.os.replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_historical_exclusion_directory(
                        failed,
                        historical,
                        candidates,
                        expected_historical_record_count=1,
                        expected_historical_content_sha256=historical_hash,
                        expected_candidate_record_count=2,
                        expected_candidate_content_sha256=candidate_hash,
                    )
            self.assertFalse(failed.exists())

    def test_legacy_assign_splits_output_and_report_are_unchanged(self) -> None:
        output, report = assign_splits(leakage_fixture(), seed=20260811)

        self.assertEqual(
            hashlib.sha256(canonical_jsonl_bytes(output)).hexdigest(),
            "52cb844831bb4ed1c8b35fd0b951e4431200c9c416a9c59bffe155862b48e7da",
        )
        self.assertEqual(
            hashlib.sha256(canonical_json_bytes(report)).hexdigest(),
            "db4777735c8c06cfae16286c92ccdbe31829a83ca323d52843ea508962055701",
        )

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
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(
            report["sentence_signature_join_algorithm"],
            "exact_length_rarity_prefix_v1",
        )
        self.assertLessEqual(
            report["sentence_signature_comparison_count"],
            report["sentence_signature_total_pair_count"],
        )
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

    def test_exact_prefix_join_matches_brute_force_random_oracle(self) -> None:
        generator = random.Random(20260811)
        universe = [f"shingle-{index:03d}" for index in range(80)]
        signatures: list[list[str]] = []
        for index in range(30):
            base = set(generator.sample(universe, generator.randint(5, 12)))
            signatures.append(sorted(base))
            signatures.append(sorted(base))
            removable = sorted(base)[index % len(base)]
            signatures.append(sorted(base - {removable}))
            addition = next(item for item in universe if item not in base)
            signatures.append(sorted(base | {addition}))
        records = [
            {"source": {"sentence_shingle_hashes": signature}}
            for signature in signatures
        ]

        def partition(union_find: _UnionFind) -> set[frozenset[int]]:
            return {
                frozenset(indexes) for indexes in union_find.groups().values()
            }

        for threshold in (0.5, 0.8, 1.0):
            with self.subTest(threshold=threshold):
                actual_union = _UnionFind(len(records))
                _, _, _, actual_near = _union_near_duplicates(
                    records, actual_union, threshold=threshold
                )

                expected = _UnionFind(len(records))
                sets = [set(signature) for signature in signatures]
                for right in range(len(sets)):
                    for left in range(right):
                        intersection = len(sets[left] & sets[right])
                        union = len(sets[left] | sets[right])
                        if intersection / union >= threshold:
                            expected.union(left, right)

                self.assertEqual(partition(actual_near), partition(expected))

    def test_frequent_shingle_does_not_create_quadratic_candidates(self) -> None:
        common = "globally-frequent-shingle"
        records = [
            {
                "source": {
                    "sentence_shingle_hashes": sorted(
                        [common, *(f"unique-{index:05d}-{part}" for part in range(4))]
                    )
                }
            }
            for index in range(10_000)
        ]
        union_find = _UnionFind(len(records))

        started = time.perf_counter()
        pair_count, signature_count, comparison_count, near_union = (
            _union_near_duplicates(records, union_find, threshold=0.8)
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(pair_count, 0)
        self.assertEqual(signature_count, 10_000)
        self.assertLess(comparison_count, 10_000)
        self.assertEqual(len(near_union.groups()), 10_000)
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
