"""Synthetic exact source extents, terminal failures and interpretation limits."""
import unittest

from sakura_rerank.data.tatoeba_input_units import VIEWS,build_source_units,kana_projection,score_units


class TatoebaInputUnitTests(unittest.TestCase):
    def test_okurigana_is_inside_whole_and_literal_run_not_ruby(self):
        row=build_source_units('走る。','[走|はし]る。')
        self.assertEqual(row['views']['whole_source']['parts'][0]['reading'],'はしる。')
        self.assertEqual(row['views']['literal_runs']['parts'][0]['target'],'走る')
        self.assertEqual(row['views']['ruby_fragments']['parts'][0]['target'],'走')

    def test_literal_runs_preserve_quotes_punctuation_and_every_source_character(self):
        row=build_source_units('「学校へ、行く。」','「[学校|がっこう]へ、[行|い]く。」')
        parts=row['views']['literal_runs']['parts']
        self.assertEqual([p['target'] for p in parts if p['kind']=='convert'],['学校へ','行く'])
        self.assertEqual(''.join(p['text'] if p['kind']=='literal' else p['target'] for p in parts),row['target'])

    def test_katakana_input_projection_does_not_change_surface(self):
        row=build_source_units('カレーを食べる。','カレーを[食|タ]べる。')
        self.assertEqual(row['target'],'カレーを食べる。')
        self.assertEqual(row['reading'],'かれーをたべる。')
        self.assertGreater(row['projected_units'],0)

    def test_projection_rejects_guessed_expansion_or_unsupported_characters(self):
        self.assertEqual(kana_projection('キャー'),'きゃー')
        self.assertEqual(kana_projection('ヴ'),'ゔ')
        for value in ('','ヷ','ｶﾅ','か\u3099','ゝ','abc','123','漢字'):
            self.assertIsNone(kana_projection(value))

    def test_unannotated_han_latin_digit_space_are_not_given_readings(self):
        for value in ('漢字','abc','123','あ い'):
            row=build_source_units(value,value)
            self.assertEqual(row['status'],'unsupported_source_or_reading')
            self.assertTrue(all(not row['views'][name]['parts'] for name in VIEWS))

    def test_wrong_reading_can_match_source_without_certifying_gold(self):
        row=build_source_units('今日。','[今日|あした]。')
        self.assertFalse(row['ime_gold'])
        self.assertFalse(row['grammatical_boundary_verified'])
        self.assertEqual(row['views']['whole_source']['status'],'ready')

    def test_source_mismatch_never_repairs_surface(self):
        row=build_source_units('Ａ','A')
        self.assertEqual(row['status'],'source_mismatch')
        self.assertTrue(all(not value['parts'] for value in row['views'].values()))

    def test_malformed_annotation_keeps_explicit_terminal(self):
        row=build_source_units('字','[字|]')
        self.assertEqual(row['status'],'empty_or_missing_ruby')
        self.assertEqual(set(row['views']),set(VIEWS))

    def test_non_bmp_offsets_are_codepoints_not_bytes(self):
        row=build_source_units('あ𠮷。','あ[𠮷|よし]。')
        part=row['views']['ruby_fragments']['parts'][0]
        self.assertEqual((part['start'],part['end']),(1,2))

    def test_full_reading_limit_does_not_discard_other_view_status(self):
        sentence='あ'*70+'、'+'い'*70
        row=build_source_units(sentence,sentence)
        self.assertEqual(row['views']['whole_source']['status'],'input_bound')
        self.assertEqual(row['views']['literal_runs']['status'],'ready')

    def test_part_bound_is_explicit(self):
        sentence='あ、'*33
        row=build_source_units(sentence,sentence)
        self.assertEqual(row['views']['literal_runs']['status'],'part_bound')

    def test_literal_only_has_no_invented_conversion_request(self):
        row=build_source_units('。','。')
        self.assertEqual(row['views']['whole_source']['status'],'no_phonetic_input')

    def test_control_characters_are_pending(self):
        row=build_source_units('あ\t','あ\t')
        self.assertEqual(row['status'],'source_bound_or_control')

    def test_missing_result_is_unmeasured_not_a_source_miss(self):
        row=build_source_units('橋。','[橋|はし]。')
        self.assertEqual(score_units(row,{})['whole_source']['status'],'unmeasured')

    def test_all_component_presence_is_not_whole_rank(self):
        row=build_source_units('橋、道。','[橋|はし]、[道|みち]。')
        snapshots={}
        for view in row['views'].values():
            for part in view['parts']:
                if part['kind']=='convert':snapshots[part['request_id']]=[]
        for part in row['views']['literal_runs']['parts']:
            if part['kind']=='convert':snapshots[part['request_id']]=[{'surface':part['target']}]
        scores=score_units(row,snapshots)
        self.assertTrue(scores['literal_runs']['all_parts_present']['1'])
        self.assertFalse(scores['whole_source']['all_parts_present']['32'])


if __name__=='__main__':unittest.main()
