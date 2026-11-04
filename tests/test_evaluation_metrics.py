from __future__ import annotations

import hashlib
import math
import unittest
from dataclasses import replace
from fractions import Fraction

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_metrics import (
    EvaluationCase, EvaluationError, EvaluationRun, Observation, evaluate_runs,
)
from sakura_rerank.evaluation_statistics import (
    clopper_pearson95, holm_adjust, mcnemar_exact, paired_component_bootstrap, wilson95,
)


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def case(i, candidates=("a", "b"), gold="a", component=None):
    return EvaluationCase(key(i), key(i if component is None else component), candidates, gold)


def evaluate(cases, observations, *, completed=True):
    return evaluate_runs(cases, {"model": EvaluationRun(observations, completed)},
                         comparisons=[("model", "baseline")], bootstrap_replicates=200)


class FixedCohortMetricsTests(unittest.TestCase):
    def test_counts_denominators_failures_and_duplicate_surface(self):
        cases = [case(0, ("a", "b", "c")), case(1, ("b", "a", "c")),
                 case(2, ("b", "c", "a")), case(3), case(4, ("b", "a")),
                 case(5, ("a", "a", "b")), case(6, ("b", "a")), case(7, ("b", "a"))]
        observations = {key(i): Observation("applied", (1, 0, 2)) for i in (0, 1, 2, 5)}
        observations.update({key(3): Observation("unavailable", None, False),
                             key(4): Observation("timeout"), key(6): Observation("abstained")})
        report = evaluate(cases, observations)
        result = report["models"]["model"]
        self.assertEqual((report["record_count"], report["baseline_correct"], report["baseline_errors"]), (8, 3, 5))
        self.assertEqual([result[k] for k in ("correction_success", "baseline_correct_destroyed", "wrong_to_different_wrong", "effective_changes", "correction_failure")], [1, 1, 1, 3, 2])
        self.assertEqual(result["gate_applied_count"], 4)
        self.assertEqual(result["inference_attempts"], 6)
        self.assertEqual(result["attempt_status_unknown"], 1)
        self.assertFalse(result["complete"])
        self.assertEqual(result["terminal_counts"]["missing"], 1)
        for name, numerator, denominator in (
            ("accuracy", 3, 8), ("harm_rate", 1, 3), ("overwrite_coverage", 3, 8),
            ("application_to_error_targets", 2, 5), ("correction_precision", 1, 3),
            ("correction_recall", 1, 5),
        ):
            self.assertEqual(result[name]["numerator"], numerator)
            self.assertEqual(result[name]["denominator"], denominator)
        self.assertEqual(result["baseline_gain"], 0)
        self.assertAlmostEqual(result["mrr_at_6"], 2/3)
        self.assertEqual(sum(result["terminal_counts"].values()), 8)
        self.assertFalse(report["release_eligible"])
        payload = canonical_json_bytes(report)
        self.assertNotIn(key(0).encode(), payload)
        self.assertNotIn(b'"gold"', payload)

    def test_missing_gold_candidate_and_top32_only_gold_stay_in_denominator(self):
        cases = [case(0, gold="absent"), case(1, ("b", "c", "d", "e", "f", "g", "a"))]
        result = evaluate(cases, {key(i): Observation("abstained") for i in (0, 1)})
        self.assertEqual(result["observed_candidate_oracle"]["6"]["value"], 0)
        self.assertEqual(result["observed_candidate_oracle"]["10"]["value"], 0.5)
        self.assertEqual(result["models"]["model"]["mrr_at_6"], 0)
        self.assertIsNone(result["models"]["model"]["harm_rate"]["value"])
        self.assertIsNone(result["paired_component_intervals"]["ratios"]["model-harm"]["ci95"])

    def test_protected_spelling_is_not_normalized_into_a_success(self):
        sample = case(0, ("高橋", "髙橋"), "高橋")
        report = evaluate([sample], {sample.case_key: Observation("applied", (1, 0))})
        self.assertEqual(report["models"]["model"]["baseline_correct_destroyed"], 1)
        self.assertEqual(report["models"]["model"]["accuracy"]["numerator"], 0)

    def test_zero_denominators_and_zero_harm_are_not_perfect_safety(self):
        report = evaluate([case(0)], {key(0): Observation("applied", (0, 1))})
        result = report["models"]["model"]
        self.assertIsNone(result["correction_precision"]["value"])
        self.assertIsNone(result["correction_recall"]["value"])
        self.assertIsNone(result["relative_error_reduction"])
        self.assertEqual(result["rescue_harm_ratio"]["status"], "undefined")
        self.assertEqual(result["harm_clopper_pearson95_row_assumption"]["upper_one_sided"], 0.95)
        self.assertTrue(report["paired_component_intervals"]["ratios"]["model-harm"]["degenerate"])
        self.assertFalse(report["release_eligible"])
        rescue = evaluate([case(0, ("b", "a"))], {key(0): Observation("applied", (1, 0))})
        self.assertEqual(rescue["models"]["model"]["rescue_harm_ratio"]["status"], "positive_infinity")
        canonical_json_bytes(rescue)  # No JSON infinity or NaN.

    def test_all_terminal_failures_preserve_local_output_and_full_denominator(self):
        statuses = ["abstained", "timeout", "stale", "malformed", "missing", "error", "unavailable"]
        cases = [case(i) for i in range(len(statuses))]
        observations = {key(i): Observation(status, None, status != "unavailable") for i, status in enumerate(statuses)}
        result = evaluate(cases, observations, completed=False)["models"]["model"]
        self.assertEqual(result["accuracy"]["value"], 1)
        self.assertEqual(result["effective_changes"], 0)
        self.assertFalse(result["complete"])
        self.assertEqual(result["record_count"], 7)

    def test_permutation_and_model_order_do_not_change_results(self):
        cases = [case(0), case(1, ("b", "a"))]
        outputs = {key(i): Observation("applied", (1, 0)) for i in range(2)}
        runs = {"one": EvaluationRun(outputs, True), "two": EvaluationRun(outputs, True)}
        family = [("one", "baseline"), ("two", "baseline"), ("one", "two")]
        first = evaluate_runs(cases, runs, comparisons=family, bootstrap_replicates=200)
        second = evaluate_runs(list(reversed(cases)), dict(reversed(list(runs.items()))),
                               comparisons=list(reversed(family)), bootstrap_replicates=200)
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(first["paired_comparisons"]["one__vs__two"]["accuracy_difference"], 0)

    def test_invalid_alignment_ranking_and_statuses_fail(self):
        good = case(0)
        bad_observations = [Observation("unknown"), Observation("timeout", (0, 1)),
                            Observation("applied", (0, 0)), Observation("applied", (0, 2)),
                            Observation("applied", (False, 1)), Observation("unavailable"),
                            Observation("timeout", None, False)]
        for observation in bad_observations:
            with self.subTest(observation=observation), self.assertRaises(EvaluationError):
                evaluate([good], {good.case_key: observation})
        with self.assertRaises(EvaluationError):
            evaluate([good, good], {})
        with self.assertRaises(EvaluationError):
            evaluate([good], {key(1): Observation("abstained")})
        with self.assertRaises(EvaluationError):
            evaluate([replace(good, candidates=())], {})
        with self.assertRaises(EvaluationError):
            evaluate([], {})
        with self.assertRaises(EvaluationError):
            evaluate_runs([good], {"one": EvaluationRun({}, True)}, comparisons=[("one", "baseline"), ("baseline", "one")])
        with self.assertRaisesRegex(EvaluationError, "model-minus-baseline"):
            evaluate_runs([good], {"one": EvaluationRun({}, True), "two": EvaluationRun({}, True)},
                          comparisons=[("one", "two")])


class EvaluationStatisticsTests(unittest.TestCase):
    def test_binomial_bounds_closed_forms_and_safety_boundary(self):
        self.assertIsNone(clopper_pearson95(0, 0)["two_sided"])
        for n in (1, 10, 1196, 1197, 10_000):
            interval = clopper_pearson95(0, n)
            self.assertAlmostEqual(interval["two_sided"][1], 1-0.025**(1/n), places=13)
            self.assertAlmostEqual(interval["upper_one_sided"], 1-0.05**(1/n), places=13)
            self.assertEqual(interval["two_sided"][0], 0)
        self.assertGreater(clopper_pearson95(0, 1196)["upper_one_sided"], 0.0025)
        self.assertLess(clopper_pearson95(0, 1197)["upper_one_sided"], 0.0025)
        self.assertLess(clopper_pearson95(16, 10_000)["upper_one_sided"], 0.0025)
        self.assertGreater(clopper_pearson95(17, 10_000)["upper_one_sided"], 0.0025)

    def test_mcnemar_matches_exact_rational_small_counts(self):
        for left in range(12):
            for right in range(12):
                n = left+right
                expected = min(Fraction(1), 2*sum(Fraction(math.comb(n, i), 2**n) for i in range(min(left, right)+1)))
                self.assertAlmostEqual(mcnemar_exact(left, right), float(expected), places=13)

    def test_wilson_and_holm_boundaries(self):
        self.assertIsNone(wilson95(0, 0))
        self.assertAlmostEqual(wilson95(0, 1)[1], 0.7934506856227626)
        self.assertEqual(holm_adjust({"a": 0.01, "b": 0.03, "c": 0.04}), {"a": 0.03, "b": 0.06, "c": 0.06})
        for values in ((True, 1), (-1, 5), (3, 2), (0, 100001)):
            with self.assertRaises(ValueError):
                wilson95(*values)
        with self.assertRaises(ValueError):
            holm_adjust({"a": math.nan})

    def test_bootstrap_keeps_components_and_models_paired(self):
        components = ["left"]*10+["right"]*10
        rows = [[1, 1, 1]]*10+[[1, -1, -1]]*10
        result = paired_component_bootstrap(components, rows, {"a": (1, 0), "b": (2, 0)}, replicates=1000)
        self.assertEqual(result["ratios"]["a"], result["ratios"]["b"])
        self.assertEqual(result["ratios"]["a"]["ci95"], [-1, 1])
        independent = paired_component_bootstrap([str(i) for i in range(20)], rows, {"a": (1, 0)}, replicates=1000)
        self.assertGreater(independent["ratios"]["a"]["ci95"][0], -1)
        self.assertLess(independent["ratios"]["a"]["ci95"][1], 1)

    def test_undefined_bootstrap_draws_are_not_discarded_for_an_interval(self):
        result = paired_component_bootstrap(["one", "two"], [[1, 0], [1, 1]], {"ratio": (0, 1)}, replicates=200)
        self.assertGreater(result["ratios"]["ratio"]["invalid_replicates"], 0)
        self.assertIsNone(result["ratios"]["ratio"]["ci95"])
        with self.assertRaises(ValueError):
            paired_component_bootstrap(["one"], [[1]], {"x": (0, 0)}, replicates=True)


if __name__ == "__main__":
    unittest.main()
