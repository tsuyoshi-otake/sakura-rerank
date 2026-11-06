"""Synthetic projection/policy contracts; no installed model or real Test reads."""
import json
import unittest
from unittest.mock import patch

from sakura_rerank import current_tiny as current
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_metrics import EvaluationCase, EvaluationError, EvaluationRun, Observation, evaluate_runs
from sakura_rerank.evaluation_runner import _product_observations
from sakura_rerank.evaluation_worker import default_adapters
from tests.test_evaluation_runner import key


def facts(count=3, **changes):
    return {"source_head": current.HEAD, "baseline_index": 0, "direct_count": count,
            "evidence_tags": [1]*count, "schedule_eligible": True, "selection_allowed": True, **changes}


class CurrentProjectionTests(unittest.TestCase):
    def test_native_hash_zero_inputs_and_padding(self):
        import numpy as np
        rows = [{"surface": "A東😀", "local_cost": 10}, {"surface": "B", "local_cost": 20}]
        feed = current.protocol_feed(rows)
        self.assertEqual(list(feed), ["context_ids", "context_lengths", "reading_ids", "reading_lengths",
                                     "candidate_ids", "candidate_lengths", "features", "candidate_mask"])
        self.assertEqual(feed["candidate_ids"][0, 0, :3].tolist(), [11031, 7816, 2033])
        for name in ("context_ids", "context_lengths", "reading_ids", "reading_lengths"):
            self.assertFalse(feed[name].any())
        self.assertEqual(feed["candidate_lengths"].tolist(), [[3, 1, 0, 0, 0, 0]])
        self.assertEqual(feed["candidate_mask"].tolist(), [[True, True, False, False, False, False]])
        self.assertEqual(feed["features"][0, :2, 0].tolist(), [-0., -1.])
        self.assertTrue(np.signbit(feed["features"][0, 0, 0]))
        self.assertTrue(np.signbit(feed["features"][0, 0, 1]))
        self.assertFalse(feed["features"][0, :, [2, 4, 5]].any())
        self.assertFalse(feed["features"][0, 2:].any())

    def test_clipped_costs_and_untruncated_length_feature(self):
        import numpy as np
        rows = [{"surface": "😀"*256, "local_cost": -(2**63)}, {"surface": "x", "local_cost": 2**63-1},
                {"surface": "y", "local_cost": 2**31-1}]
        feed = current.protocol_feed(rows)
        self.assertEqual(feed["features"][0, :3, 0].tolist(), [-0., -1., -1.])
        self.assertEqual(feed["candidate_lengths"][0, 0], 32)
        self.assertEqual(feed["features"][0, 0, 3], 8.)
        self.assertEqual(feed["features"][0, 1, 1], np.float32(-.2))
        rows[0]["local_cost"] = 2**63-2
        same = current.protocol_feed(rows)
        self.assertTrue(np.signbit(same["features"][0, :3, 0]).all())
        self.assertFalse(same["features"][0, :3, 0].any())

    def test_invalid_projection_never_truncates_invalid_input_into_validity(self):
        base = [{"surface": "A", "local_cost": 1}, {"surface": "B", "local_cost": 2}]
        bad = [base[:1], base*4, [{**base[0], "local_cost": True}, base[1]],
               [{**base[0], "local_cost": 2**63}, base[1]], [{**base[0], "surface": "x"*257}, base[1]],
               [{**base[0], "surface": "\ud800"}, base[1]], [{**base[0], "surface": ""}, base[1]]]
        for value in bad:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(current.ProductContractError):
                current.protocol_feed(value)

    def test_current_model_pin_rejects_toy_or_corrupt_weights_before_session(self):
        artifacts = {"weights": b"not-a-model", "tokenizer": canonical_json_bytes(current.TOKENIZER),
                     "features": canonical_json_bytes(current.FEATURES), "gate": b"{}"}
        with patch("sakura_rerank.evaluation_worker.cpu_session", side_effect=AssertionError("session opened")):
            with self.assertRaises(current.ProductContractError):
                current.current_factory(artifacts, 6)
        for field in ("tokenizer", "features"):
            changed = dict(artifacts)
            value = json.loads(changed[field]); value["version"] = True
            changed[field] = canonical_json_bytes(value)
            with self.assertRaises(current.ProductContractError):
                current.validate_current(changed, 6)
        self.assertIs(default_adapters()["current-tiny-protocol-v1"].factory, current.current_factory)


class ProductPolicyTests(unittest.TestCase):
    def test_strongest_native_group_and_stable_ties(self):
        self.assertEqual(current.protected_choice([100., -4., 200., -3.], [3, 1, 4, 1]), 3)
        self.assertEqual(current.protected_choice([100., -4., 200., -4.], [3, 1, 4, 1]), 1)
        self.assertEqual(current.protected_choice([100., -4., 200., -3.], [3, 2, 1, 1]), 1)
        self.assertIsNone(current.protected_choice([1., 2.], [20, 10]))
        self.assertIsNone(current.protected_choice([1.], [1]))
        self.assertEqual(current.protected_choice([float("nan"), 1.], [4, 1]), 1)
        self.assertIsNone(current.protected_choice([float("nan"), 1.], [1, 1]))
        with self.assertRaises(current.ProductContractError):
            current.protected_choice([1., 2.], [1, 99])

    def test_policy_facts_require_explicit_native_evidence(self):
        value = facts()
        self.assertEqual(current.validate_policy_facts(value, 3), value)
        self.assertTrue(current.eligible(value))
        for field in value:
            invalid = dict(value); invalid.pop(field)
            with self.assertRaises(current.ProductContractError):
                current.validate_policy_facts(invalid, 3)
        for changed in ({"source_head": "0"*40}, {"baseline_index": True}, {"baseline_index": 3},
                        {"direct_count": 0}, {"selection_allowed": 1}, {"schedule_eligible": None},
                        {"evidence_tags": ["system_dictionary"]*3}, {"evidence_tags": [1, 1, True]},
                        {"evidence_tags": [1, 1, 99]}, {"evidence_tags": [1]}):
            with self.assertRaises(current.ProductContractError):
                current.validate_policy_facts({**value, **changed}, 3)
        for changes in ({"selection_allowed": False}, {"schedule_eligible": False}, {"direct_count": 1}):
            self.assertFalse(current.eligible(facts(**changes)))

    def test_shipped_choice_has_no_invented_margin_against_local_preference(self):
        value = facts(evidence_tags=[1, 2, 1])
        a, b = _product_observations([10., -2., 30., 0., 0., 0.], "complete", value, None)
        self.assertEqual(a, b)
        self.assertEqual(a["ranking"], [1, 0, 2])
        _, gated = _product_observations([10., -2., 30., 0., 0., 0.], "complete", value, 0.)
        self.assertEqual(gated["status"], "abstained")

    def test_gate_uses_authenticated_local_index_and_never_padded_scores(self):
        value = facts(baseline_index=1)
        a, b = _product_observations([5., 4., 3., 100., 100., 100.], "complete", value, 1.)
        self.assertEqual(a["ranking"], [0, 1, 2])
        self.assertEqual(b["status"], "abstained")
        _, b = _product_observations([5., 4., 3., 100., 100., 100.], "complete", value, .99)
        self.assertEqual(b["ranking"][0], 0)
        value = facts(direct_count=2, evidence_tags=[1, 1, 2])
        a, _ = _product_observations([0., 1., 999., 0., 0., 0.], "complete", value, None)
        self.assertEqual(a["ranking"], [1, 0])

    def test_ineligible_and_failed_outcomes_preserve_attempt_semantics(self):
        a, b = _product_observations(None, "not_eligible", facts(), None)
        self.assertEqual(a, {"status": "not_eligible", "ranking": None, "attempted": False})
        self.assertEqual(a, b)
        for state in ("timeout", "stale", "malformed", "error", "unavailable"):
            a, _ = _product_observations(None, state, facts(), None)
            self.assertEqual(a["status"], state)
            self.assertEqual(a["attempted"], state != "unavailable")


class LocalBaselineMetricTests(unittest.TestCase):
    def evaluate(self, rows, observations):
        return evaluate_runs(rows, {"model": EvaluationRun(observations, True)},
                             comparisons=[("model", "baseline")], bootstrap_replicates=100)

    def test_local_selection_outside_model_prefix_is_not_lost(self):
        row = EvaluationCase(key(1), key(2), tuple(str(i) for i in range(10)), "8", 8, 6)
        report = self.evaluate([row], {row.case_key: Observation("not_eligible", attempted=False)})
        self.assertEqual(report["baseline_correct"], 1)
        self.assertEqual(report["observed_candidate_oracle"]["1"]["numerator"], 0)
        self.assertEqual(report["observed_candidate_oracle"]["6"]["numerator"], 0)
        result = report["models"]["model"]
        self.assertEqual(result["accuracy"]["numerator"], 1)
        self.assertEqual(result["mrr_at_6"], 1.)
        self.assertEqual(result["inference_attempts"], 0)
        self.assertEqual(result["effective_changes"], 0)

    def test_local_selection_is_in_cohort_hash_and_harm_denominator(self):
        row = EvaluationCase(key(1), key(2), ("a", "b", "c"), "b", 1, 2)
        report = self.evaluate([row], {row.case_key: Observation("applied", (0, 1))})
        self.assertEqual(report["models"]["model"]["baseline_correct_destroyed"], 1)
        old = EvaluationCase(row.case_key, row.component_key, row.candidates, row.gold)
        original = self.evaluate([old], {row.case_key: Observation("abstained")})
        self.assertNotEqual(report["cohort_sha256"], original["cohort_sha256"])

    def test_invalid_local_metadata_and_ineligible_attempt_fail(self):
        base = EvaluationCase(key(1), key(2), ("a", "b"), "a")
        for baseline, count in ((True, None), (2, None), (0, True), (0, 3), (0, 0)):
            row = EvaluationCase(base.case_key, base.component_key, base.candidates, base.gold, baseline, count)
            with self.assertRaises(EvaluationError):
                self.evaluate([row], {row.case_key: Observation("abstained")})
        with self.assertRaises(EvaluationError):
            self.evaluate([base], {base.case_key: Observation("not_eligible", attempted=True)})

    def test_converter_reference_preserves_actual_fallback_output(self):
        rows = [EvaluationCase(key(1), key(3), ("a", "b"), "a", 1, 2),
                EvaluationCase(key(2), key(3), ("a", "b"), "b", 1, 2)]
        runs = {"model": EvaluationRun({r.case_key: Observation("not_eligible", attempted=False) for r in rows}, True)}
        local = evaluate_runs(rows, runs, comparisons=[("model", "baseline")], bootstrap_replicates=100)
        original = evaluate_runs(rows, runs, comparisons=[("model", "baseline")], bootstrap_replicates=100,
                                 reference_baseline="converter_top1")
        a, b = local["models"]["model"], original["models"]["model"]
        self.assertEqual(a["baseline_correct_destroyed"], 0)
        self.assertEqual((b["baseline_correct_destroyed"], b["correction_success"]), (1, 1))
        self.assertEqual(a["prediction_sha256"], b["prediction_sha256"])
        self.assertEqual(a["accuracy"], b["accuracy"])
        self.assertEqual(a["inference_attempts"], 0)
        self.assertEqual(local["cohort_sha256"], original["cohort_sha256"])


if __name__ == "__main__":
    unittest.main()
