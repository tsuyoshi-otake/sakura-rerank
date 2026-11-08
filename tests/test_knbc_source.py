"""KNBC source fields are evidence, not corrected labels or IME admission."""
from copy import deepcopy
import unittest

from sakura_rerank.data.knbc_source import ARCHIVE_ROOT, MAX_BYTES, parse_member, reading_kind, reserve_slots


def token(surface='仮名',reading='かな',lemma='仮名',notes=''):
    return f'{surface} {reading} {lemma} 名詞 6 普通名詞 1 * 0 * 0'+(' '+notes if notes else '')


def document(*lines,sid='sample-1'):
    return ('# S-ID:'+sid+'\n* -1D\n+ -1D\n'+'\n'.join(lines or [token()])+'\nEOS\n').encode()


def inventory():
    rows=[]
    for article in ('A_1','B_1','C_1'):
        for name in ('fileinfos',article+'-1',article+'-2'):
            rows.append(dict(name=f'{ARCHIVE_ROOT}/corpus1/{article}/{name}',kind='file',bytes=100))
    return rows


class KnbcSourceTests(unittest.TestCase):
    def test_reservation_replays_from_reversed_metadata(self):
        a=reserve_slots(inventory(),'a'*64,articles=2,slots_per_article=2)
        self.assertEqual(a,reserve_slots(list(reversed(inventory())),'a'*64,articles=2,slots_per_article=2))
        self.assertEqual(len(a['slots']),4)
        self.assertEqual(a['census']['fileinfos_files'],3)

    def test_unclassified_member_forces_explicit_diagnostic_slot(self):
        rows=inventory()+[dict(name=f'{ARCHIVE_ROOT}/corpus1/C_1/2',kind='file',bytes=69)]
        selected=reserve_slots(rows,'a'*64,articles=2,slots_per_article=2)
        self.assertEqual(selected['slots'][0]['role'],'unclassified_member')
        self.assertEqual(selected['slots'][0]['selection_reason'],'metadata_exception_article')
        self.assertEqual(selected['census']['forced_exception_articles'],1)

    def test_missing_slots_are_not_replaced_from_other_articles(self):
        rows=[dict(name=f'{ARCHIVE_ROOT}/corpus1/A_1/A_1-1',kind='file',bytes=10)]
        selected=reserve_slots(rows,'b'*64,articles=1,slots_per_article=2)
        self.assertEqual(selected['slots'][1]['role'],'missing_metadata_slot')

    def test_duplicate_paths_and_oversized_members_rejected(self):
        for rows in (inventory()+[inventory()[0]], [dict(inventory()[1],bytes=MAX_BYTES+1)]):
            with self.subTest(rows=len(rows)),self.assertRaises(ValueError):
                reserve_slots(rows,'c'*64,articles=1,slots_per_article=2)

    def test_selection_bounds_and_unknown_capacity(self):
        rows=[dict(name=f'{ARCHIVE_ROOT}/corpus1/A_1/{i}',kind='file',bytes=10) for i in range(3)]
        with self.assertRaises(ValueError):reserve_slots(rows,'a'*64,articles=1,slots_per_article=2)
        with self.assertRaises(ValueError):reserve_slots(inventory(),'a'*64,articles=21)
        with self.assertRaises(ValueError):reserve_slots(inventory(),'not-a-hash')

    def test_source_surface_reading_and_lemma_stay_separate(self):
        row=parse_member(document(token('行った','いった','行く')))
        t=row['tokens'][0]
        self.assertEqual((t['annotated_surface'],t['annotated_reading'],t['lemma']),('行った','いった','行く'))
        self.assertFalse(row['original_source_surface_verified'])
        self.assertFalse(row['ime_input_boundary_verified'])

    def test_correction_note_does_not_rewrite_surface(self):
        row=parse_member(document(token('誤記','ごき','誤記','"ER:訂正"')))
        self.assertEqual(row['annotation_surface'],'誤記')
        self.assertEqual(row['tokens'][0]['notes'],'"ER:訂正"')
        self.assertIn('provider_correction_marker',row['flags'])

    def test_markers_in_structure_and_alternative_are_not_lost(self):
        raw=document('+ -1D <ER:fixture>',token(),'@ '+token(notes='読み曖昧'))
        row=parse_member(raw)
        self.assertEqual(row['alternative_rows'],1)
        self.assertEqual(set(row['flags']),{'provider_correction_marker','provider_ambiguity_marker','alternative_annotation'})

    def test_source_style_markers_are_only_flags(self):
        row=parse_member(document(token(notes='スラング:fixture')))
        self.assertIn('provider_style_marker',row['flags'])
        self.assertFalse(row['gold_admission'])

    def test_unicode_source_is_not_normalized(self):
        row=parse_member(document(token('Ａ','えー','A')))
        self.assertEqual(row['annotation_surface'],'Ａ')

    def test_no_marker_is_not_admission(self):
        row=parse_member(document())
        self.assertEqual(row['flags'],[])
        for field in ('training_admission','gold_admission','final_test','author_mapping_verified'):
            self.assertFalse(row[field])

    def test_reading_categories_do_not_modify_reading(self):
        for surface,reading,expected in [('仮','か','hiragana'),('仮','カ','kana_projection_possible'),
                ('。','。','literal_symbol'),('英','ABC','unsupported_for_kana_input'),('仮','*','missing')]:
            with self.subTest(reading=reading):
                self.assertEqual(reading_kind(surface,reading),expected)
                self.assertEqual(parse_member(document(token(surface,reading)))['tokens'][0]['annotated_reading'],reading)

    def test_foreign_sid_rejected(self):
        with self.assertRaisesRegex(ValueError,'knbc_foreign_sid'):
            parse_member(document(),expected_sid='different')

    def test_missing_empty_and_multiple_eos(self):
        values=[document().removesuffix(b'EOS\n'),b'# S-ID:sample-1\nEOS\n',document()+b'EOS\n']
        for raw in values:
            with self.subTest(raw=len(raw)),self.assertRaises(ValueError):parse_member(raw)

    def test_orphan_alternative_and_unknown_structure(self):
        for raw in (document('@ '+token()),document('* invalid',token()),document('# comment',token())):
            with self.subTest(raw=len(raw)),self.assertRaises(ValueError):parse_member(raw)

    def test_malformed_columns_and_utf8_rejected(self):
        for raw in (document('unsupported fields'),document(token().replace('名詞 6','名詞 x')),b'\xff'):
            with self.subTest(raw=len(raw)),self.assertRaises((ValueError,UnicodeError)):parse_member(raw)

    def test_byte_line_and_nul_bounds(self):
        for raw in (b'x'*(MAX_BYTES+1),document('x'*16385),document(token()+'\0')):
            with self.subTest(raw=len(raw)),self.assertRaises(ValueError):parse_member(raw)

    def test_metadata_input_is_not_mutated(self):
        rows=inventory(); old=deepcopy(rows)
        reserve_slots(rows,'d'*64,articles=2,slots_per_article=2)
        self.assertEqual(rows,old)


if __name__=='__main__':unittest.main()
