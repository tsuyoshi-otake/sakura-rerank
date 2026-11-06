"""Reservation cannot learn from text; consumption cannot invent IME evidence."""
import copy
import unittest

from sakura_rerank.data.tatoeba_consumption import consume_slot, reserve_metadata_slots


def metadata(number, named=True):
    return dict(sentence_id=number,
                sentence=dict(line=number, raw_line_sha256='a'*64, owner_token='b'*64),
                transcription=dict(line=number, raw_line_sha256='c'*64,
                                   editor_token='d'*64 if named else None,
                                   stratum='named_editor' if named else 'no_editor'))


class TatoebaConsumptionTests(unittest.TestCase):
    def test_selection_order_and_exclusion_are_fixed_before_decode(self):
        rows = [metadata(i) for i in range(1, 31)]
        result = reserve_metadata_slots(rows, [1, 2], count=5, seed='fixed')
        self.assertEqual(result, reserve_metadata_slots(reversed(rows), [2, 1], count=5, seed='fixed'))
        self.assertEqual(len({r['sentence_id'] for r in result}), 5)
        self.assertTrue({r['sentence_id'] for r in result}.isdisjoint({1, 2}))

    def test_text_or_scores_in_metadata_are_rejected(self):
        for key in ('text', 'reading', 'score'):
            row = metadata(1)
            row[key] = 'not allowed'
            with self.assertRaisesRegex(ValueError, 'metadata_fields'):
                reserve_metadata_slots([row], [], count=1, seed='fixed')

    def test_complete_stream_is_checked_after_enough_eligible_rows(self):
        rows = [metadata(1), metadata(2), metadata(2)]
        with self.assertRaisesRegex(ValueError, 'population_identity'):
            reserve_metadata_slots(rows, [], count=1, seed='fixed')

    def test_missing_exposure_ids_and_insufficient_capacity_fail(self):
        for previous, count in (([2], 1), ([1], 1)):
            with self.assertRaises(ValueError):
                reserve_metadata_slots([metadata(1)], previous, count=count, seed='fixed')

    def test_editor_stratum_and_hashes_are_not_trusted_blindly(self):
        for target, value in (('stratum', 'no_editor'), ('raw_line_sha256', 'bad')):
            row = metadata(1)
            row['transcription'][target] = value
            with self.assertRaises(ValueError):
                reserve_metadata_slots([row], [], count=1, seed='fixed')

    def test_boolean_ids_bounds_and_unbounded_seed_are_rejected(self):
        row = metadata(1)
        row['sentence_id'] = True
        with self.assertRaises(ValueError):
            reserve_metadata_slots([row], [], count=1, seed='fixed')
        for count, seed in ((0, 'x'), (10001, 'x'), (True, 'x'), (1, 'x'*129)):
            with self.assertRaises(ValueError):
                reserve_metadata_slots([metadata(1)], [], count=count, seed=seed)

    def test_continuous_range_preserves_okurigana_and_source_positions(self):
        row = consume_slot(metadata(1), '「学校へ、行く。」', '「[学校|がっこう]へ、[行|い]く。」',
                           snapshot='fixed-snapshot', slot=0)
        self.assertEqual(row['status'], 'ready_source_hypothesis')
        self.assertEqual([p['target'] for p in row['inputs']], ['学校へ', '行く'])
        self.assertEqual([(p['start'], p['end']) for p in row['inputs']], [(1, 4), (5, 7)])
        self.assertTrue(all(p['left_context'] == '' for p in row['inputs']))
        self.assertFalse(row['session_context_available'])

    def test_owner_editor_and_unknown_creator_remain_separate(self):
        row = consume_slot(metadata(1), '橋。', '[橋|はし]。', snapshot='fixed', slot=0)
        self.assertEqual(row['provenance']['administrative_owner_token'], 'b'*64)
        self.assertEqual(row['provenance']['transcription_editor_token'], 'd'*64)
        self.assertIsNone(row['provenance']['original_author_token'])
        self.assertIsNone(row['provenance']['translation_lineage'])
        self.assertEqual(row['provenance']['imported_human_verdicts'], 0)
        self.assertFalse(row['ime_gold'])
        self.assertFalse(row['calibration_admitted'])
        self.assertFalse(row['final_test'])

    def test_wrong_reading_is_a_hypothesis_without_quality_admission(self):
        row = consume_slot(metadata(1), '今日。', '[今日|あした]。', snapshot='fixed', slot=0)
        self.assertEqual(row['status'], 'ready_source_hypothesis')
        self.assertFalse(row['provenance']['independent_reading_verified'])
        self.assertFalse(row['ime_gold'])

    def test_source_failure_retains_slot_and_coverage_without_requests(self):
        for transcript in ('[橋|]', '[違|はし]', None):
            row = consume_slot(metadata(1), '橋。', transcript, snapshot='fixed', slot=7)
            self.assertEqual(row['slot'], 7)
            self.assertIsNotNone(row['source_coverage'])
            self.assertEqual(row['inputs'], [])

    def test_unsupported_source_is_not_trimmed_to_an_easy_subspan(self):
        row = consume_slot(metadata(1), '橋へ A。', '[橋|はし]へ A。', snapshot='fixed', slot=0)
        self.assertEqual(row['status'], 'unsupported_source_or_reading')
        self.assertTrue(row['source_exact'])
        self.assertEqual(row['inputs'], [])

    def test_input_bound_keeps_terminal_and_does_not_chunk_or_refill(self):
        row = consume_slot(metadata(1), 'あ'*129, 'あ'*129, snapshot='fixed', slot=0)
        self.assertEqual(row['status'], 'input_bound')
        self.assertEqual(row['inputs'], [])

    def test_kana_projection_does_not_change_source_surface(self):
        row = consume_slot(metadata(1), 'カレー。', 'カレー。', snapshot='fixed', slot=0)
        self.assertEqual(row['inputs'][0]['reading'], 'かれー')
        self.assertEqual(row['inputs'][0]['target'], 'カレー')

    def test_no_mutation_and_identity_binds_snapshot(self):
        original = metadata(1)
        before = copy.deepcopy(original)
        one = consume_slot(original, '橋。', '[橋|はし]。', snapshot='one', slot=0)
        two = consume_slot(original, '橋。', '[橋|はし]。', snapshot='two', slot=0)
        self.assertEqual(original, before)
        self.assertNotEqual(one['stable_id'], two['stable_id'])


if __name__ == '__main__':
    unittest.main()
