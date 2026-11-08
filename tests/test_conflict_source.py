"""Contracts prevent a descriptive source audit from becoming label admission."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('conflict_metrics_test', Path('research/issue-31-conflict-source/conflict_metrics.py'))
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


class ConflictSourceTests(unittest.TestCase):
    def test_single_label_duplicates_are_not_conflicts(self):
        self.assertEqual(metrics.census(['a', 'a'], [1, 1])['minimum_source_mismatches'], 0)

    def test_all_conflict_rows_remain_in_denominator(self):
        result = metrics.census(['a']*4 + ['b'], [1, 1, 1, 2, 3])
        self.assertEqual((result['rows'], result['conflicting_rows'], result['maximum_source_matches']), (5, 4, 4))

    def test_tied_labels_do_not_pick_a_new_label(self):
        result = metrics.census(['a']*4, [0, 1, 0, 1])
        self.assertEqual(result['minimum_source_mismatches'], 2)
        self.assertNotIn('accepted_label', result)

    def test_mixture_cost_is_not_sum_of_source_costs(self):
        result = metrics.mixture(['a']*4, [0, 0, 1, 1], ['common_wikipedia']*2 + ['dictionary_aozora']*2)
        self.assertEqual(result['separate_source_minimum_mismatches'], 0)
        self.assertEqual(result['additional_mixture_mismatches'], 2)

    def test_empty_population_rejected(self):
        with self.assertRaises(ValueError): metrics.census([], [])

    def test_misaligned_population_rejected(self):
        with self.assertRaises(ValueError): metrics.census(['a'], [])

    def test_invalid_label_rejected(self):
        for label in (-1, 6, True, 1.0):
            with self.subTest(label=label), self.assertRaises(ValueError): metrics.census(['a'], [label])

    def test_unknown_stratum_rejected(self):
        with self.assertRaises(ValueError): metrics.mixture(['a'], [0], ['test'])

    def test_notation_literal_and_canonical(self):
        self.assertEqual(metrics.notation_class(['が', 'か\u3099']), 'nfc')
        self.assertEqual(metrics.notation_class(['字', '字']), 'literal')

    def test_width_kana_case_are_separate_diagnostics(self):
        self.assertEqual(metrics.notation_class(['Ａ', 'A']), 'nfkc')
        self.assertEqual(metrics.notation_class(['カナ', 'かな']), 'kana')
        self.assertEqual(metrics.notation_class(['US', 'us']), 'case')
        self.assertEqual(metrics.notation_class(['Ａカ', 'aか']), 'kana_case')

    def test_homophones_do_not_become_accepted(self):
        self.assertEqual(metrics.notation_class(['橋', '箸']), 'distinct_after_all_mechanical_folds')

    def test_notation_whole_group_not_one_matching_pair(self):
        self.assertEqual(metrics.notation_class(['Ａ', 'A', 'B']), 'distinct_after_all_mechanical_folds')

    def test_bad_notation_input_rejected(self):
        with self.assertRaises(ValueError): metrics.notation_class([])
        with self.assertRaises(ValueError): metrics.transformed('', 'literal')
        with self.assertRaises(ValueError): metrics.transformed('A', 'unknown')

    def test_adjacency_is_not_an_input_unit_verdict(self):
        result = metrics.source_observation('甲乙あ', 1, 2, '乙', '甲')
        self.assertEqual(result['classes']['left'], 'kanji_range')
        self.assertEqual(result['classes']['right'], 'hiragana')
        self.assertEqual(result['ime_input_unit'], 'unresolved')
        self.assertNotIn('accepted', result)

    def test_exact_span_and_bounded_left_are_required(self):
        for start, end, target, left in ((0, 2, '乙', ''), (1, 2, '乙', ''), (-1, 2, '乙', '甲')):
            with self.assertRaises(ValueError): metrics.source_observation('甲乙あ', start, end, target, left)
        result = metrics.source_observation('あ'*80+'字', 80, 81, '字', 'あ'*64)
        self.assertTrue(result['exact_left_prefix'])

    def test_context_lengths_are_prespecified(self):
        self.assertEqual(metrics.CONTEXT_LENGTHS, (0, 1, 2, 4, 8, 16, 32, 64))


if __name__ == '__main__':
    unittest.main()
