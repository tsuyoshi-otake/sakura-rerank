from __future__ import annotations

import importlib.util
import math
import unittest

from sakura_rerank.research_tiny import (
    CONTEXT_LENGTH,
    EMBEDDING_DIM,
    HIDDEN_DIM,
    READING_LENGTH,
    SURFACE_LENGTH,
    VOCAB_SIZE,
    build_model,
    canonical_json_bytes,
    candidate_features,
    character_ids,
    model_parameter_count,
    ranking_metrics,
)


class ResearchTinyTests(unittest.TestCase):
    def test_character_hash_is_bounded_padded_and_deterministic(self) -> None:
        first, length = character_ids("かな漢字", 8)
        second, second_length = character_ids("かな漢字", 8)
        self.assertEqual((first, length), (second, second_length))
        self.assertEqual(length, 4)
        self.assertEqual(len(first), 8)
        self.assertTrue(all(0 <= value < VOCAB_SIZE for value in first))
        self.assertEqual(first[4:], [0, 0, 0, 0])

    def test_candidate_features_keep_local_order_signal(self) -> None:
        candidates = [
            {"local_cost": 10, "segments": [{}], "surface": "東京", "source_category": "system_dictionary"},
            {"local_cost": 30, "segments": [{}, {}], "surface": "東亰", "source_category": "mixed"},
        ]
        values = candidate_features("とうきょう", candidates)
        self.assertEqual(values[0][0], 0)
        self.assertEqual(values[1][0], -1)
        self.assertEqual(values[0][-1], 1)
        self.assertEqual(values[1][-1], 0)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch is an optional training dependency")
    def test_model_is_approximately_two_million_parameters_and_shapes_scores(self) -> None:
        import torch

        model = build_model()
        count = model_parameter_count(model)
        self.assertGreaterEqual(count, 1_800_000)
        self.assertLessEqual(count, 2_100_000)
        scores = model(
            torch.zeros((2, CONTEXT_LENGTH), dtype=torch.int64),
            torch.ones(2, dtype=torch.int64),
            torch.zeros((2, READING_LENGTH), dtype=torch.int64),
            torch.ones(2, dtype=torch.int64),
            torch.zeros((2, 6, SURFACE_LENGTH), dtype=torch.int64),
            torch.ones((2, 6), dtype=torch.int64),
            torch.zeros((2, 6, 6), dtype=torch.float32),
            torch.ones((2, 6), dtype=torch.bool),
        )
        self.assertEqual(tuple(scores.shape), (2, 6))

    def test_metrics_keep_oracle_misses_in_denominator(self) -> None:
        scores = [[3, 2, 1, 0, -1, -2], [0, 1, 2, 3, 4, 5], [1, 0, 0, 0, 0, 0]]
        result = ranking_metrics(scores, [0, 5, -1])
        self.assertEqual(result["record_count"], 3)
        self.assertEqual(result["oracle_count"], 2)
        self.assertEqual(result["top1_correct"], 2)
        self.assertAlmostEqual(result["top1_accuracy"], 2 / 3)
        self.assertEqual(result["rescue_count"], 1)
        self.assertEqual(result["harm_count"], 0)
        self.assertIsNone(result["rescue_harm_ratio"])

    def test_canonical_json_rejects_non_finite_numbers(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json_bytes({"invalid": math.inf})


if __name__ == "__main__":
    unittest.main()
