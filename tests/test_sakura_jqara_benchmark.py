from __future__ import annotations

import unittest

from sakura_rerank.sakura_jqara_benchmark import (
    CONTEXT_LENGTH,
    FEATURE_DIM,
    READING_LENGTH,
    SURFACE_LENGTH,
    TOP_K,
    SakuraJQaRAError,
    SCORED_PAIR_COUNT,
    build_pair_inputs,
    canonical_json_bytes,
)


class SakuraJQaRABenchmarkTests(unittest.TestCase):
    def test_pair_adapter_has_one_real_candidate_and_no_rank_feature(self) -> None:
        inputs = build_pair_inputs([("日本の首都", "東京は日本の首都である")])
        self.assertEqual(inputs["context_ids"].shape, (1, CONTEXT_LENGTH))
        self.assertEqual(inputs["reading_ids"].shape, (1, READING_LENGTH))
        self.assertEqual(inputs["candidate_ids"].shape, (1, TOP_K, SURFACE_LENGTH))
        self.assertEqual(inputs["features"].shape, (1, TOP_K, FEATURE_DIM))
        self.assertEqual(inputs["candidate_mask"].tolist(), [[True, False, False, False, False, False]])
        self.assertEqual(inputs["features"].sum(), 0)
        self.assertEqual(inputs["candidate_lengths"][0, 1:].sum(), 0)

    def test_pair_adapter_rejects_empty_or_malformed_pairs(self) -> None:
        for pairs in ([('', 'document')], [('query', '')], [('query',)]):
            with self.subTest(pairs=pairs), self.assertRaises(SakuraJQaRAError):
                build_pair_inputs(pairs)  # type: ignore[arg-type]

    def test_canonical_report_bytes_are_sorted_compact_and_lf_terminated(self) -> None:
        self.assertEqual(canonical_json_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')
        self.assertEqual(SCORED_PAIR_COUNT, 98_941)


if __name__ == "__main__":
    unittest.main()
