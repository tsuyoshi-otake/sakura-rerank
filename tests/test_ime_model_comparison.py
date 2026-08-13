from __future__ import annotations

import unittest

from sakura_rerank.ime_model_comparison import (
    ImeComparisonError,
    QUERY_ADAPTER,
    build_external_query,
    canonical_json_bytes,
)


class ImeModelComparisonTests(unittest.TestCase):
    def test_external_query_adapter_is_fixed_and_preserves_context_and_reading(self) -> None:
        self.assertEqual(QUERY_ADAPTER, "left_context_lf_reading_label_reading_v1")
        self.assertEqual(build_external_query("今日は", "とうきょう"), "今日は\n読み:とうきょう")
        self.assertEqual(build_external_query("", "とうきょう"), "\n読み:とうきょう")

    def test_external_query_rejects_missing_reading(self) -> None:
        with self.assertRaises(ImeComparisonError):
            build_external_query("context", "")

    def test_canonical_json_is_compact_sorted_and_lf_terminated(self) -> None:
        self.assertEqual(canonical_json_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')


if __name__ == "__main__":
    unittest.main()
