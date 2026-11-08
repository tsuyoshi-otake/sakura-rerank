"""Synthetic contracts for train-only planning, never source-label certification."""
from collections import Counter
import unittest

from sakura_rerank.data.contrast_capacity import (
    balanced_selections, candidate_evidence, profile, review_flags, validate_population,
)


def row(index, target, *, reading="はし", corpus="jawiki", document=None, context=None):
    return dict(stable_id=f"row-{index:04d}", population="train", corpus=corpus,
                independent_gold_eligible=False, label_kind="source_exact_weak_supervision",
                reading=reading, target=target, left_context=context or f"これは合成の文脈{index}。",
                source={"article_id": document or f"document-{index}"})


def candidate(surface, source="system_dictionary"):
    return dict(surface=surface, segments=[dict(source_category=source)])


def snapshot(surfaces):
    candidates = [candidate(s) if isinstance(s, str) else s for s in surfaces]
    return dict(candidate_snapshots=dict(training_top32=dict(candidates=candidates),
                                        production_top6=dict(candidates=candidates[:6])))


class ContrastCapacityTests(unittest.TestCase):
    def quartet(self):
        rows = [row(i, "橋" if i < 2 else "箸", corpus="jawiki" if i < 2 else "aozora") for i in range(4)]
        return rows, {r["stable_id"]: f"component-{i}" for i, r in enumerate(rows)}

    def test_document_and_component_independence_are_separate(self):
        rows, components = self.quartet()
        components[rows[1]["stable_id"]] = components[rows[0]["stable_id"]]
        result, witnesses = profile(rows, components)
        self.assertEqual(result["four_document_witnessed_readings"], 1)
        self.assertEqual(result["four_component_witnessed_readings"], 0)
        self.assertEqual(witnesses["component"], [])
        self.assertEqual(result["quality_evidence"]["contextual_reading"], {"unresolved": 4})

    def test_context_identity_blocks_a_quartet(self):
        rows, components = self.quartet()
        rows[1]["left_context"] = rows[0]["left_context"]
        result, _ = profile(rows, components)
        self.assertEqual(result["four_document_witnessed_readings"], 0)
        self.assertEqual(result["input_conflicts"]["duplicate_groups"], 1)

    def test_identical_inputs_with_different_labels_are_counted(self):
        rows, components = self.quartet()
        rows[2]["left_context"] = rows[0]["left_context"]
        result, _ = profile(rows, components)
        self.assertEqual(result["input_conflicts"]["contradictory_groups"], 1)
        self.assertEqual(result["input_conflicts"]["unavoidable_source_disagreements"], 1)

    def test_reverse_order_has_same_profile_and_witnesses(self):
        rows, components = self.quartet()
        self.assertEqual(profile(rows, components), profile(rows[::-1], components))

    def test_normalization_warning_does_not_replace_literal_forms(self):
        rows, components = self.quartet()
        for i, r in enumerate(rows):
            r["target"] = "Ａ" if i < 2 else "A"
        before = [r["target"] for r in rows]
        result, _ = profile(rows, components)
        self.assertEqual(result["multiple_form_readings"], 1)
        self.assertEqual(result["component_witness_normalized_form_warnings"], 1)
        self.assertEqual([r["target"] for r in rows], before)
        self.assertEqual(result["in_sample_reading_majority_rows"], 2)

    def test_adjacent_kanji_and_quotes_are_flags_not_rejections(self):
        r = row(0, "橋", context="これは合成「複合")
        self.assertEqual(set(review_flags(r)), {"kanji_adjacency", "quote_delimiter_visible"})
        result, _ = profile([r], {r["stable_id"]: "component"})
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["quality_evidence"]["ime_input_boundary"], {"unresolved": 1})

    def test_evaluation_and_duplicate_ids_are_rejected(self):
        rows, components = self.quartet()
        rows[0]["population"] = "evaluation"
        with self.assertRaisesRegex(ValueError, "train_contract"):
            validate_population(rows, components)
        rows[0]["population"] = "train"
        with self.assertRaisesRegex(ValueError, "train_contract"):
            validate_population(rows + rows[:1], components)

    def test_bounds_and_missing_components_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "population_bound"):
            validate_population([], {})
        rows, components = self.quartet()
        with self.assertRaisesRegex(ValueError, "train_contract"):
            validate_population(rows, {})
        rows[0]["reading"] = "あ" * 33
        with self.assertRaisesRegex(ValueError, "train_contract"):
            validate_population(rows, components)

    def test_single_form_has_no_contrast(self):
        rows, components = self.quartet()
        for r in rows:
            r["target"] = "橋"
        result, _ = profile(rows, components)
        self.assertEqual(result["single_form_rows"], 4)
        self.assertEqual(result["four_component_witnessed_readings"], 0)

    def test_more_than_32_forms_is_explicitly_unresolved(self):
        rows = [row(i, str(i)) for i in range(33)]
        components = {r["stable_id"]: r["stable_id"] for r in rows}
        result, _ = profile(rows, components)
        self.assertEqual(result["selector_counts"]["component"]["too_many_types"], 1)
        self.assertEqual(result["four_component_witnessed_readings"], 0)

    def test_balanced_planning_is_atomic_deterministic_and_nonduplicating(self):
        rows, components = self.quartet()
        control, contrast, reserved, result = balanced_selections(rows, components, {"jawiki": 2, "aozora": 2})
        self.assertEqual(len(control), 4)
        self.assertEqual(len(set(contrast)), 4)
        self.assertEqual(len(reserved), 1)
        self.assertEqual(result["reserved_rows"], 4)
        self.assertEqual((control, contrast, reserved, result),
                         balanced_selections(rows[::-1], components, {"jawiki": 2, "aozora": 2}))

    def test_quota_excess_skips_the_whole_quartet(self):
        rows, components = self.quartet()
        _, chosen, reserved, result = balanced_selections(rows, components, {"jawiki": 1, "aozora": 2})
        self.assertEqual(reserved, [])
        self.assertEqual(result["groups_over_quota"], 1)
        self.assertEqual(len(chosen), 3)
        by_id = {r["stable_id"]: r for r in rows}
        self.assertEqual(Counter(by_id[s]["corpus"] for s in chosen), {"jawiki": 1, "aozora": 2})

    def test_shortage_publishes_no_partial_selection(self):
        rows, components = self.quartet()
        control, contrast, reserved, result = balanced_selections(rows, components, {"jawiki": 3, "aozora": 2})
        self.assertEqual((control, contrast, reserved), ([], [], []))
        self.assertEqual(result["status"], "insufficient_quantity")

    def test_invalid_quotas_fail(self):
        rows, components = self.quartet()
        for quotas in ({"jawiki": 2}, {"jawiki": 0, "aozora": 2}, {"jawiki": True, "aozora": 2}):
            with self.assertRaisesRegex(ValueError, "quota_bound"):
                balanced_selections(rows, components, quotas)

    def test_candidate_presence_and_training_eligibility_differ(self):
        result = candidate_evidence("対象", snapshot([str(i) for i in range(6)] + ["対象"]))
        self.assertTrue(result["presence"]["10"])
        self.assertFalse(result["presence"]["6"])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["unique_target_rank"], 7)

    def test_singleton_duplicate_and_fallback_are_not_training_eligible(self):
        for candidates in (["橋"], ["橋", "橋"], [candidate("橋", "reading"), "箸"]):
            self.assertFalse(candidate_evidence("橋", snapshot(candidates))["eligible"])

    def test_missing_acquisition_keeps_zero_presence_and_distinct_terminal(self):
        result = candidate_evidence("橋", None)
        self.assertEqual(result["status"], "acquisition_missing")
        self.assertFalse(any(result["presence"].values()))
        self.assertIsNone(result["unique_target_rank"])

    def test_truncation_is_not_silently_admitted(self):
        result = candidate_evidence("橋", snapshot(["橋", "長" * 33]))
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "target_or_candidate_truncation")
        self.assertTrue(result["presence"]["1"])

    def test_real_top6_prefix_must_match(self):
        value = snapshot(["橋", "箸"])
        value["candidate_snapshots"]["production_top6"]["candidates"] = [candidate("別")]
        with self.assertRaisesRegex(ValueError, "prefix_differs"):
            candidate_evidence("橋", value)


if __name__ == "__main__":
    unittest.main()
