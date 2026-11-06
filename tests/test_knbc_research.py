"""Prospective slots preserve whole annotated units, uncertainty and exposure."""
from copy import deepcopy
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.knbc_research import classify_frame, exclude_alias_components, project_member, reserve_remaining
from sakura_rerank.data.knbc_source import ARCHIVE_ROOT
from sakura_rerank.data.reconstruction_graph import isolate_source_scope


def token(surface='仮名', reading='かな', note=''):
    return f'{surface} {reading} {surface} 名詞 6 普通名詞 1 * 0 * 0 '+note


def fixture(*lines):
    slot = dict(index=0, path=ARCHIVE_ROOT+'/corpus1/Z_1/Z_1-1', article='Z_1', family='Z')
    return ('# S-ID:Z_1-1\n'+'\n'.join(lines)+'\nEOS\n').encode(), slot


def reservation_fixture():
    articles = [f'F{i}_1' for i in range(19)]+['F0_2']
    slots = [dict(article=articles[i%20], family=articles[i%20].split('_')[0]) for i in range(100)]
    pilot = dict(slots=slots, selection_sha256=canonical_json_hash(slots))
    name = ARCHIVE_ROOT+'/corpus1/Z_1/Z_1-1'
    inventory = [dict(name=name, archive_name=name, kind='file', bytes=100)]
    return inventory, pilot, {name:'a'*64}


class KnbcResearchTests(unittest.TestCase):
    def test_whole_unit_preserves_inflection_and_empty_observed_context(self):
        raw, slot = fixture('* -1D', '+ -1D', token('書い', 'かい'), token('た', 'た'))
        result = project_member(raw, slot)
        self.assertEqual(result['input']['source_surface'], '書いた')
        self.assertEqual(result['input']['reading'], 'かいた')
        self.assertEqual(result['input']['left_context'], '')
        self.assertEqual(result['input']['surface_end'], 3)
        self.assertFalse(result['gold_admission'])

    def test_correction_outside_selected_unit_still_holds_entire_document(self):
        raw, slot = fixture('* 1D <ER:fixture>', '+ 1D', token(), '* -1D', '+ -1D', token())
        self.assertEqual(project_member(raw, slot)['status'], 'pending_document_correction')

    def test_lemma_ambiguity_is_not_reading_ambiguity(self):
        raw, slot = fixture('* -1D', '+ -1D', token(note='原形曖昧'))
        self.assertEqual(project_member(raw, slot)['status'], 'ready_for_history')
        raw, slot = fixture('* -1D', '+ -1D', token(note='読み曖昧'))
        self.assertEqual(project_member(raw, slot)['status'], 'pending_reading_ambiguity')

    def test_symbol_is_not_trimmed_to_make_a_kana_input(self):
        raw, slot = fixture('* -1D', '+ -1D', token(), token('。', '。'))
        result = project_member(raw, slot)
        self.assertEqual(result['status'], 'pending_non_kana_reading')
        self.assertIsNone(result['input'])
        self.assertIsNotNone(result['source_coverage'])

    def test_conflicting_alternative_is_pending(self):
        raw, slot = fixture('* -1D', '+ -1D', token(), '@ '+token(reading='べつ'))
        self.assertEqual(project_member(raw, slot)['status'], 'pending_alternative_reading_or_surface')

    def test_missing_or_empty_bunsetsu_is_refused(self):
        for lines in [(token(),), ('* 0D', '* -1D', token())]:
            raw, slot = fixture(*lines)
            with self.assertRaises(ValueError): project_member(raw, slot)

    def test_large_reading_is_not_clipped(self):
        raw, slot = fixture('* -1D', token(reading='あ'*129))
        self.assertEqual(project_member(raw, slot)['status'], 'pending_input_extent')

    def test_choice_does_not_change_when_reading_is_invalidated(self):
        raw, slot = fixture('* 1D', token(), '* -1D', token('文字', 'もじ'))
        first = project_member(raw, slot)
        changed = raw.replace('かな'.encode(), b'NIL').replace('もじ'.encode(), b'NIL')
        second = project_member(changed, slot)
        self.assertEqual(first['selected_bunsetsu'], second['selected_bunsetsu'])
        self.assertIsNone(second['input'])

    def test_reservation_is_deterministic_and_does_not_mutate_metadata(self):
        inv, pilot, hashes = reservation_fixture()
        before = deepcopy((inv, pilot, hashes))
        first = reserve_remaining(inv, pilot, hashes)
        self.assertEqual(first, reserve_remaining(list(reversed(inv)), pilot, hashes))
        self.assertEqual((inv, pilot, hashes), before)
        self.assertFalse(first['final_test'])

    def test_pilot_tampering_and_duplicate_paths_are_refused(self):
        inv, pilot, hashes = reservation_fixture()
        with self.assertRaises(ValueError): reserve_remaining(inv+inv, pilot, hashes)
        pilot['slots'][0]['family'] = 'changed'
        with self.assertRaises(ValueError): reserve_remaining(inv, pilot, hashes)

    def test_alias_exposure_propagates_through_new_components(self):
        result = exclude_alias_components({'a':'group1','b':'group1','c':'group2'},
            {'a':'seen','b':'new','c':'unseen'}, {'seen'})
        self.assertEqual(result, {'a','b'})
        with self.assertRaises(ValueError): exclude_alias_components({'a':'g'}, {}, set())

    def test_complete_graph_matches_existing_exclusion_and_component_semantics(self):
        records = []
        for i in range(5):
            source = dict(article_id=str(i%2), template_cluster_id=None, paragraph_hash=str(i)*64,
                sentence_hash=str(i)*64, sentence_shingle_hashes=[str(i)*64])
            records.append(dict(stable_id='node'+str(i), population='historical' if i == 0 else 'evaluation',
                                source=source, input_hash=str(i)*64))
        old_excluded, old_components, _ = isolate_source_scope(records)
        excluded, components, _ = classify_frame(records, set(), set())
        self.assertEqual(set(excluded), set(old_excluded))
        self.assertEqual(components, old_components)
        self.assertEqual(classify_frame(records, set(), set()), classify_frame(list(reversed(records)), set(), set()))

    def test_consumed_source_without_input_excludes_connected_slot(self):
        raw, slot = fixture('* -1D', token())
        value = project_member(raw, slot)
        inp = {k:value['input'][k] for k in ('stable_id', 'population', 'source', 'input_hash')}
        src = value['source_coverage']
        excluded, _, _ = classify_frame([inp, src], set(), {src['stable_id']})
        self.assertEqual(set(excluded), {inp['stable_id']})
        with self.assertRaises(ValueError): classify_frame([inp, src], set(), {'missing-source'})


if __name__ == '__main__': unittest.main()
