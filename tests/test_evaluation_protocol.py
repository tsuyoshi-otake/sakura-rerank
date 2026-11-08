from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.splitter import (
    SplitError, audit_evaluation_partitions, evaluation_component_keys,
)
from sakura_rerank.test_use_registry import (
    EMPTY_HEAD, TestUseError, finish_test, initialize_registry,
    inspect_registry, reserve_test,
)
from tests.test_data_splitter import split_record


def populations():
    result = {}
    for index, role in enumerate(("historical", "train", "calibration", "test")):
        row = split_record(
            f"example-{role}", article_id=f"article-{role}",
            paragraph=f"paragraph-{role}", sentence=chr(65 + index) * 16,
        )
        row["session"]["left_context"] = f"context-{role}"
        result[role] = [row]
    return result.pop("historical"), result


class EvaluationPartitionTests(unittest.TestCase):
    def test_clean_populations_preserve_all_rows_without_certifying_gold(self):
        history, groups = populations()
        before = deepcopy((history, groups))
        report, tokens = audit_evaluation_partitions(history, groups)
        self.assertTrue(report["leakage_free_for_supplied_records"])
        self.assertFalse(report["gold_quality_certified"])
        self.assertFalse(report["historical_inventory_completeness_certified"])
        self.assertEqual(sum(v["count"] for v in report["populations"].values()), 4)
        self.assertEqual(tokens, sorted(set(tokens)))
        self.assertEqual((history, groups), before)
        text = canonical_json_bytes(report).decode()
        self.assertNotIn("example-test", text)
        self.assertNotIn("context-test", text)

    def test_same_input_across_unrelated_sources_is_detected(self):
        history, groups = populations()
        groups["test"][0]["session"]["left_context"] = history[0]["session"]["left_context"]
        report, _ = audit_evaluation_partitions(history, groups)
        self.assertEqual(report["cross_population_groups"], {
            "article": 0, "paragraph_exact": 0, "template_cluster": 0,
            "sentence_near_duplicate": 0, "bounded_input_exact": 1,
        })
        self.assertFalse(report["leakage_free_for_supplied_records"])
        self.assertEqual(report["affected_new_records"]["test"], 1)

    def test_source_and_input_relations_form_one_transitive_closure(self):
        history, groups = populations()
        train, calibration, test = [groups[name][0] for name in ("train", "calibration", "test")]
        train["source"]["article_id"] = history[0]["source"]["article_id"]
        calibration["session"]["left_context"] = train["session"]["left_context"]
        test["source"]["paragraph_hash"] = calibration["source"]["paragraph_hash"]
        report, _ = audit_evaluation_partitions(history, groups)
        self.assertEqual(report["cross_population_components"], 1)
        self.assertEqual(report["affected_new_records"], {"train": 1, "calibration": 1, "test": 1})

    def test_resampling_membership_uses_the_same_source_input_closure(self):
        history, groups = populations()
        groups["train"][0]["source"]["article_id"] = history[0]["source"]["article_id"]
        groups["test"][0]["session"]["left_context"] = groups["train"][0]["session"]["left_context"]
        records = history + [row for rows in groups.values() for row in rows]
        keys = evaluation_component_keys(records)
        self.assertEqual(keys, evaluation_component_keys(list(reversed(records))))
        self.assertEqual(len(set(keys.values())), 2)
        self.assertEqual(keys[history[0]["stable_id"]], keys[groups["test"][0]["stable_id"]])
        report, _ = audit_evaluation_partitions(history, groups)
        self.assertEqual(report["affected_new_records"], {"train": 1, "calibration": 0, "test": 1})

    def test_order_is_irrelevant_and_relabeling_cannot_refresh_test_identity(self):
        history, groups = populations()
        second = deepcopy(groups["test"][0])
        second["stable_id"] += "-second"
        groups["test"].append(second)
        report, tokens = audit_evaluation_partitions(history, groups)
        reversed_groups = {key: list(reversed(value)) for key, value in reversed(list(groups.items()))}
        self.assertEqual((report, tokens), audit_evaluation_partitions(history, reversed_groups))
        relabeled = deepcopy(groups)
        for row in relabeled["test"]:
            row["gold_index"] = 1
            row["gold_surface"] = row["candidate_snapshots"]["production_top6"]["candidates"][1]["surface"]
        changed_report, changed_tokens = audit_evaluation_partitions(history, relabeled)
        self.assertNotEqual(report["populations"]["test"], changed_report["populations"]["test"])
        self.assertEqual(tokens, changed_tokens)

    def test_missing_history_repeated_ids_conflicting_roles_and_bounds_fail(self):
        history, groups = populations()
        with self.assertRaisesRegex(SplitError, "nonempty"):
            audit_evaluation_partitions([], groups)
        with self.assertRaisesRegex(SplitError, "exactly"):
            audit_evaluation_partitions(history, {"test": groups["test"]})
        repeated = deepcopy(groups)
        repeated["test"][0]["stable_id"] = history[0]["stable_id"]
        with self.assertRaisesRegex(SplitError, "disjoint"):
            audit_evaluation_partitions(history, repeated)
        conflicting = deepcopy(groups)
        conflicting["test"][0]["split"] = "train"
        with self.assertRaisesRegex(SplitError, "contradicts"):
            audit_evaluation_partitions(history, conflicting)
        with patch("sakura_rerank.data.splitter.MAX_COMPONENT_INPUT_RECORDS", 3):
            with self.assertRaisesRegex(SplitError, "bound"):
                audit_evaluation_partitions(history, groups)


class TestConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "registry"
        initialize_registry(self.root)
        self.report, self.tokens = audit_evaluation_partitions(*populations())

    def reserve(self, head=EMPTY_HEAD, **overrides):
        args = dict(expected_head=head, plan_sha256="a" * 64,
                    partition_report=self.report, test_tokens=self.tokens)
        args.update(overrides)
        return reserve_test(self.root, **args)

    def test_success_has_one_terminal_record_and_no_repeat_under_new_plan(self):
        claim = self.reserve()
        self.assertEqual(inspect_registry(self.root, expected_head=claim)["active"], 1)
        done = finish_test(self.root, expected_head=claim, reservation_sha256=claim,
                           outcome="completed", result_sha256="b" * 64)
        summary = inspect_registry(self.root, expected_head=done)
        self.assertEqual((summary["reserved"], summary["completed"], summary["active"]), (1, 1, 0))
        with self.assertRaisesRegex(TestUseError, "consumed"):
            self.reserve(done, plan_sha256="c" * 64)
        with self.assertRaisesRegex(TestUseError, "active last"):
            finish_test(self.root, expected_head=done, reservation_sha256=claim, outcome="failed")

    def test_failure_and_abandonment_do_not_release_population(self):
        claim = self.reserve()
        altered = ["d" * 64]
        receipt = deepcopy(self.report)
        receipt["test_reuse_tokens_sha256"] = hashlib.sha256(canonical_json_bytes(altered)).hexdigest()
        receipt["test_reuse_token_count"] = 1
        with self.assertRaisesRegex(TestUseError, "terminal outcome"):
            self.reserve(claim, partition_report=receipt, test_tokens=altered)
        failed = finish_test(self.root, expected_head=claim, reservation_sha256=claim, outcome="failed")
        with self.assertRaisesRegex(TestUseError, "consumed"):
            self.reserve(failed)
        next_claim = self.reserve(failed, partition_report=receipt, test_tokens=altered)
        self.assertEqual(inspect_registry(self.root, expected_head=next_claim)["failed"], 1)

    def test_overlapping_subset_or_renamed_article_stays_consumed(self):
        claim = self.reserve()
        done = finish_test(self.root, expected_head=claim, reservation_sha256=claim, outcome="failed")
        history, groups = populations()
        groups["test"][0]["stable_id"] = "new-id"
        groups["test"][0]["source"]["revision_id"] = "new-revision"
        report, tokens = audit_evaluation_partitions(history, groups)
        self.assertNotEqual(tokens, self.tokens)
        with self.assertRaisesRegex(TestUseError, "consumed"):
            self.reserve(done, partition_report=report, test_tokens=tokens)

    def test_tampered_receipt_or_tokens_do_not_write_a_claim(self):
        for field, value in (("leakage_free_for_supplied_records", False),
                             ("cross_population_components", 1),
                             ("schema_version", True),
                             ("test_reuse_tokens_sha256", "f" * 64)):
            receipt = deepcopy(self.report)
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(TestUseError):
                self.reserve(partition_report=receipt)
        receipt = deepcopy(self.report)
        receipt["cross_population_groups"]["article"] = 1
        with self.assertRaises(TestUseError):
            self.reserve(partition_report=receipt)
        with self.assertRaises(TestUseError):
            self.reserve(test_tokens=list(reversed(self.tokens)))
        self.assertEqual((self.root / "events.jsonl").read_bytes(), b"")

    def test_history_truncation_edit_and_partial_write_fail_closed(self):
        claim = self.reserve()
        path = self.root / "events.jsonl"
        original = path.read_bytes()
        for corrupted in (b"", original[:-1], original.replace(b'"reserved"', b'"failed"')):
            path.write_bytes(corrupted)
            with self.assertRaises(TestUseError):
                inspect_registry(self.root, expected_head=claim)
        path.write_bytes(original)
        with self.assertRaisesRegex(TestUseError, "external commitment"):
            inspect_registry(self.root, expected_head=EMPTY_HEAD)

    def test_concurrent_reservations_have_exactly_one_winner(self):
        barrier = Barrier(2)
        def attempt():
            barrier.wait(timeout=5)
            try:
                return self.reserve()
            except TestUseError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(inspect_registry(self.root, expected_head=winners[0])["events"], 1)
        self.assertFalse((self.root / "writer.lock").exists())

    def test_stale_writer_lock_is_never_assumed_safe_to_delete(self):
        lock = self.root / "writer.lock"
        lock.mkdir()
        with self.assertRaisesRegex(TestUseError, "do not auto-unlock"):
            self.reserve()
        self.assertTrue(lock.exists())

    def test_fsync_failure_keeps_consumption_evidence(self):
        with patch("sakura_rerank.test_use_registry.os.fsync", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.reserve()
        raw = (self.root / "events.jsonl").read_bytes()
        self.assertTrue(raw)
        actual = hashlib.sha256(raw).hexdigest()
        self.assertEqual(inspect_registry(self.root, expected_head=actual)["active"], 1)
        with self.assertRaisesRegex(TestUseError, "consumed"):
            self.reserve(actual)

    def test_event_capacity_reserves_terminal_slot_and_reinitialization_fails(self):
        with self.assertRaises(FileExistsError):
            initialize_registry(self.root)
        with patch("sakura_rerank.test_use_registry.MAX_EVENTS", 1):
            with self.assertRaisesRegex(TestUseError, "terminal event"):
                self.reserve()
        self.assertEqual((self.root / "events.jsonl").read_bytes(), b"")

    def test_byte_capacity_reserves_space_for_terminal_evidence(self):
        with patch("sakura_rerank.test_use_registry.MAX_LEDGER_BYTES", 4096):
            with self.assertRaisesRegex(TestUseError, "byte bound"):
                self.reserve()
        self.assertEqual((self.root / "events.jsonl").read_bytes(), b"")

    def test_terminal_contract_rejects_missing_results_and_wrong_reservations(self):
        claim = self.reserve()
        for args in (
            dict(outcome="completed"),
            dict(outcome="failed", result_sha256="b" * 64),
            dict(outcome="retry"),
        ):
            with self.assertRaises(TestUseError):
                finish_test(self.root, expected_head=claim, reservation_sha256=claim, **args)
        with self.assertRaisesRegex(TestUseError, "active last"):
            finish_test(self.root, expected_head=claim, reservation_sha256="e" * 64, outcome="failed")
        self.assertEqual(inspect_registry(self.root, expected_head=claim)["events"], 1)


if __name__ == "__main__":
    unittest.main()
