import copy
import unittest

from sakura_rerank.data.annotation_contrast import boundary_observation, char_class, profile


def row(index, target):
    left = f"これは原文の合成文脈{index}。"
    return dict(stable_id=f"observed-{index}", source_id=str(index), author_id=str(index),
        source=dict(article_id=f"work-{index}"), population="train", corpus="aozora",
        label_kind="source_annotated_weak_supervision", training_eligible=False, independent_gold_eligible=False,
        reading="はし", raw_annotation_reading="ハシ", target=target, left_context=left,
        paragraph_start=len(left), paragraph_end=len(left)+len(target), annotation_kind="explicit")


class AnnotationContrastTests(unittest.TestCase):
    def fixture(self):
        rows = [row(i, "橋" if i < 2 else "箸") for i in range(4)]
        components = {r["stable_id"]: f"component-{i}" for i, r in enumerate(rows)}
        observations = {r["stable_id"]: boundary_observation(r, r["left_context"]+r["target"]+"を確認。") for r in rows}
        return rows, components, observations

    def test_adjacency_is_unresolved_and_never_extends_original_input(self):
        value = row(0, "走")
        before = copy.deepcopy(value)
        observed = boundary_observation(value, value["left_context"]+"走る。")
        self.assertIn("right_hiragana_after_kanji", observed["flags"])
        self.assertEqual(observed["ime_input_unit"], "unresolved")
        self.assertEqual(value, before)

    def test_historical_marker_is_observation_not_reading_normalization(self):
        value = row(0, "居")
        value["raw_annotation_reading"] = "ヰル"
        observed = boundary_observation(value, value["left_context"]+value["target"])
        self.assertIn("explicit_historical_kana_marker", observed["flags"])
        self.assertEqual(observed["classes"]["right"], "paragraph_boundary")
        self.assertEqual(value["raw_annotation_reading"], "ヰル")

    def test_source_position_and_context_mismatch_fail_closed(self):
        value = row(0, "橋")
        for text in (value["left_context"]+"箸", "別"+value["left_context"]+"橋"):
            with self.assertRaises(ValueError):
                boundary_observation(value, text)

    def test_character_classes_and_bound(self):
        self.assertEqual([char_class(c) for c in ("", "橋", "あ", "ア", " ", "。", "A")],
            ["paragraph_boundary", "kanji_range", "hiragana", "katakana", "whitespace", "punctuation", "other"])
        with self.assertRaises(ValueError):
            char_class("ab")

    def test_contrast_counts_do_not_certify_ime_units(self):
        rows, components, observations = self.fixture()
        result, groups = profile(rows, components, observations)
        self.assertEqual(result["four_component_witnessed_readings"], 1)
        self.assertEqual(result["ime_input_unit_unresolved"], 4)
        self.assertEqual(len(groups["component"][0]["stable_ids"]), 4)
        self.assertEqual((result, groups), profile(rows[::-1], components, observations))

    def test_document_capacity_is_not_component_capacity(self):
        rows, components, observations = self.fixture()
        components[rows[1]["stable_id"]] = components[rows[0]["stable_id"]]
        result, _ = profile(rows, components, observations)
        self.assertEqual(result["four_document_witnessed_readings"], 1)
        self.assertEqual(result["four_component_witnessed_readings"], 0)

    def test_missing_observation_admission_and_evaluation_are_rejected(self):
        rows, components, observations = self.fixture()
        with self.assertRaises(ValueError):
            profile(rows, components, {})
        for field, value in (("training_eligible", True), ("independent_gold_eligible", True), ("population", "evaluation")):
            altered = copy.deepcopy(rows); altered[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                profile(altered, components, observations)

    def test_empty_candidate_supported_view_is_explicit(self):
        result, groups = profile([], {}, {})
        self.assertEqual(result["rows"], 0)
        self.assertEqual(groups, dict(document=[], component=[]))


if __name__ == "__main__":
    unittest.main()
