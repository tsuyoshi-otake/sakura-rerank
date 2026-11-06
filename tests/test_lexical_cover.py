"""Exact lexical cover must not imply native reachability or guessed readings."""
import itertools
import random
import unittest

from sakura_rerank.data.lexical_cover import Lexicon,TargetSubstrings


def records(values):return [dict(surface=s,readings=sorted(set(r))) for s,r in sorted(values.items())]


def reference(target,reading,entries,copy=False):
    pending=[(0,0,0)];seen={(0,0)}
    while pending:
        a,b,n=pending.pop(0)
        if (a,b)==(len(target),len(reading)):return n
        possibilities=[(s,r) for s,rs in entries.items() for r in rs]
        if copy and a<len(target) and 'ぁ'<=target[a]<='ゖ':possibilities.append((target[a],target[a]))
        for s,r in possibilities:
            key=(a+len(s),b+len(r))
            if target.startswith(s,a) and reading.startswith(r,b) and key not in seen:seen.add(key);pending.append((*key,n+1))
    return None


class LexicalCoverTests(unittest.TestCase):
    def test_substrings_do_not_cross_target_boundaries(self):
        index=TargetSubstrings(['橋を','渡る']);self.assertTrue(index.contains('橋'));self.assertFalse(index.contains('を渡'))

    def test_substring_index_matches_exhaustive_small_language(self):
        strings=[''.join(chars) for n in range(1,5) for chars in itertools.product('abc',repeat=n)]
        rng=random.Random(20261106)
        for _ in range(20):
            targets=rng.sample(strings,8);index=TargetSubstrings(targets)
            for value in strings:self.assertEqual(index.contains(value),any(value in t for t in targets))

    def test_substrings_are_exact_unicode(self):
        index=TargetSubstrings(['カナ','橋']);self.assertFalse(index.contains('かな'));self.assertFalse(index.contains('ｶﾅ'))

    def test_empty_or_separator_substrings_are_rejected(self):
        index=TargetSubstrings(['橋']);self.assertFalse(index.contains(''));self.assertFalse(index.contains('\0'))
        with self.assertRaises(ValueError):TargetSubstrings(['橋\0道'])

    def test_direct_dictionary_pair(self):
        value=Lexicon(records({'橋':['はし']})).cover('橋','はし')
        self.assertEqual(value['status'],'covered');self.assertEqual(value['minimum_units'],1)

    def test_composed_dictionary_pairs_cover_whole_input(self):
        value=Lexicon(records({'橋':['はし'],'道':['みち']})).cover('橋道','はしみち')
        self.assertEqual(value['minimum_units'],2)
        self.assertEqual(value['witness'][-1]['reading_end'],4);self.assertEqual(value['witness'][-1]['target_end'],2)

    def test_direct_pair_is_minimum_even_when_composition_exists(self):
        lexicon=Lexicon(records({'橋':['はし'],'道':['みち'],'橋道':['はしみち']}))
        self.assertEqual(lexicon.cover('橋道','はしみち')['minimum_units'],1)

    def test_dictionary_only_does_not_silently_copy_kana(self):
        lexicon=Lexicon(records({'橋':['はし']}))
        self.assertEqual(lexicon.cover('橋を','はしを')['status'],'absent')
        value=lexicon.cover('橋を','はしを',literal_kana=True);self.assertEqual(value['status'],'covered')
        self.assertEqual(value['witness'][-1]['kind'],'literal_kana')

    def test_fullwidth_katakana_copy_is_explicit(self):
        lexicon=Lexicon([]);self.assertEqual(lexicon.cover('カナ','かな',literal_kana=True)['status'],'covered')

    def test_halfwidth_kana_is_not_normalized(self):
        self.assertEqual(Lexicon([]).cover('ｶﾅ','かな',literal_kana=True)['status'],'absent')

    def test_unknown_kanji_is_not_guessed(self):
        self.assertEqual(Lexicon([]).cover('橋','はし',literal_kana=True)['status'],'absent')

    def test_no_historical_reading_modernization(self):
        value=Lexicon(records({'今日':['きょう']})).cover('今日','けふ',literal_kana=True)
        self.assertEqual(value['status'],'absent')

    def test_no_partial_target_success(self):
        self.assertEqual(Lexicon(records({'橋':['はし']})).cover('橋道','はし')['status'],'absent')

    def test_no_partial_reading_success(self):
        self.assertEqual(Lexicon(records({'橋':['はし']})).cover('橋','はしみち')['status'],'absent')

    def test_multiple_readings_are_preserved(self):
        lexicon=Lexicon(records({'橋':['はし','きょう']}))
        self.assertEqual(lexicon.cover('橋','きょう')['status'],'covered')

    def test_zero_length_tokens_cannot_create_cycles(self):
        for item in ([dict(surface='',readings=['はし'])],[dict(surface='橋',readings=[''])]):
            with self.assertRaises(ValueError):Lexicon(item)

    def test_duplicate_surface_or_readings_are_rejected(self):
        for item in ([dict(surface='橋',readings=['はし'])]*2,[dict(surface='橋',readings=['はし','はし'])]):
            with self.assertRaises(ValueError):Lexicon(item)

    def test_work_bound_is_not_absence(self):
        lexicon=Lexicon(records({'橋':['きょう','はし']}))
        for options in (dict(max_states=1),dict(max_edges=1)):
            value=lexicon.cover('橋','はし',**options);self.assertEqual(value['status'],'work_bound');self.assertIsNone(value['witness'])

    def test_input_and_limit_bounds_are_explicit(self):
        lexicon=Lexicon([])
        for target,reading in [('', 'あ'),('あ',''),('あ'*257,'あ'),('あ','あ'*129)]:
            with self.assertRaises(ValueError):lexicon.cover(target,reading)
        for options in [dict(max_states=0),dict(max_edges=True),dict(literal_kana=1)]:
            with self.assertRaises(ValueError):lexicon.cover('あ','あ',**options)

    def test_exhaustive_cover_matches_independent_breadth_first_search(self):
        entries={'甲':['あ','い'],'乙':['い'],'甲乙':['あい'],'あ':['あ']};lexicon=Lexicon(records(entries))
        for n in range(1,4):
            for target in map(''.join,itertools.product('甲乙あ',repeat=n)):
                for m in range(1,5):
                    for reading in map(''.join,itertools.product('あい',repeat=m)):
                        for copy in (False,True):
                            actual=lexicon.cover(target,reading,literal_kana=copy);expected=reference(target,reading,entries,copy)
                            self.assertEqual(actual['minimum_units'],expected);self.assertEqual(actual['status'],'absent' if expected is None else 'covered')

    def test_cover_has_no_quality_or_runtime_admission(self):
        value=Lexicon(records({'橋':['はし']})).cover('橋','はし')
        self.assertNotIn('training_eligible',value);self.assertNotIn('gold',value);self.assertNotIn('native_reachable',value)


if __name__=='__main__':unittest.main()
