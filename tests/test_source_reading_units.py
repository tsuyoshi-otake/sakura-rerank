"""Original annotations and literal kana define diagnostics, never guessed words."""
import copy
import unittest

from sakura_rerank.data.aozora_ruby_evidence import parse_line
from sakura_rerank.data.contracts import canonical_json_hash,text_sha256
from sakura_rerank.data.source_reading_gate import assess
from sakura_rerank.data.source_reading_units import VIEWS,build


def example(body='前｜橋《きょう》を渡る。',*,target='橋',old_reading='はし',prefix='左側の文章を入力。'):
    text,spans,flags=parse_line(prefix+body)
    start=text.index(target,len(prefix));end=start+len(target)
    row=dict(stable_id='parent',component_id='old-component',corpus='aozora',left_context=text[max(0,start-64):start],
        reading=old_reading,target=target,candidate_request_id='growth-reading-'+canonical_json_hash(old_reading))
    source=dict(origin_kind='frozen_unique_dictionary',revision_sha256='a'*64,paragraph_sha256=text_sha256(text),
        original_row_sha256='b'*64,start=start,end=end)
    paragraph=dict(text=text,spans=spans,line_number=1,source_line_sha256=text_sha256(prefix+body),flags=flags)
    decision=assess(row,source,paragraph,allow_dictionary_only=True)
    return row,source,paragraph,decision


class SourceReadingUnitsTests(unittest.TestCase):
    def apply(self,record):return build(*record,parent_dictionary_only=True)

    def test_three_views_preserve_exact_source(self):
        result=self.apply(example());self.assertEqual(tuple(result['views']),VIEWS)
        self.assertEqual(result['views']['original_ruby']['input']['target'],'橋')
        suffix=result['views']['literal_suffix'];self.assertEqual(suffix['input']['target'],'橋を')
        self.assertEqual(suffix['input']['reading'],'きょうを')
        self.assertEqual(suffix['right_stop'],'unannotated_reading')

    def test_supported_run_includes_annotated_neighbors_and_literal_kana(self):
        result=self.apply(example('前あ｜橋《きょう》を｜渡《わた》る。'))['views']['supported_run']
        self.assertEqual(result['input']['target'],'あ橋を渡る');self.assertEqual(result['input']['reading'],'あきょうをわたる')
        self.assertEqual(result['added_left_characters'],1);self.assertEqual(result['added_right_characters'],3)

    def test_suffix_stops_before_another_annotation(self):
        result=self.apply(example('前｜橋《きょう》｜渡《わた》る。'))['views']
        self.assertEqual(result['literal_suffix']['input']['target'],'橋')
        self.assertEqual(result['supported_run']['input']['target'],'橋渡る')

    def test_kanji_without_reading_is_a_barrier_not_a_guessed_reading(self):
        value=self.apply(example())['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋を');self.assertEqual(value['left_stop'],'unannotated_reading')

    def test_punctuation_is_not_swallowed_or_used_as_reading(self):
        value=self.apply(example('前｜橋《きょう》、かな。'))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋');self.assertEqual(value['right_stop'],'literal_boundary')

    def test_halfwidth_kana_is_not_normalized(self):
        value=self.apply(example('前｜橋《きょう》ｶﾅ。'))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋')

    def test_fullwidth_katakana_projection_preserves_target(self):
        value=self.apply(example('前｜橋《キョウ》カナ。'))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋カナ');self.assertEqual(value['input']['reading'],'きょうかな')

    def test_historical_kana_is_not_modernized(self):
        value=self.apply(example('前｜橋《けふ》を。'))['views']['literal_suffix']
        self.assertEqual(value['input']['reading'],'けふを')

    def test_editor_note_neighbor_is_a_barrier(self):
        value=self.apply(example('前｜橋《きょう》｜字《ママ》かな。'))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋');self.assertEqual(value['right_stop'],'unresolved_annotation')

    def test_long_neighbor_annotation_is_not_guessed_or_truncated(self):
        value=self.apply(example('前｜橋《きょう》｜字《'+'あ'*33+'》かな。'))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋');self.assertEqual(value['right_stop'],'unresolved_annotation')

    def test_unresolved_zero_width_annotation_blocks_extension(self):
        row,source,p,decision=example('前｜橋《きょう》かな。')
        p['spans'].append(dict(start=source['end'],end=source['end'],reading='あ',kind='unresolved_base',base_sha256=text_sha256('')))
        decision=assess(row,source,p,allow_dictionary_only=True)
        value=self.apply((row,source,p,decision))['views']['supported_run']
        self.assertEqual(value['input']['target'],'橋');self.assertEqual(value['right_stop'],'unresolved_annotation')

    def test_orphan_marker_holds_changed_extents_only(self):
        result=self.apply(example('前｜橋《きょう》かな。｜'))['views']
        self.assertIsNotNone(result['original_ruby']['input'])
        for name in ('literal_suffix','supported_run'):
            self.assertIsNone(result[name]['input']);self.assertIn('annotation_parse_uncertainty',result[name]['lineage']['pending_reasons'])

    def test_native_bound_is_terminal_without_clipping(self):
        value=self.apply(example('前｜橋《きょう》'+'あ'*129+'。'))['views']['supported_run']
        self.assertIsNone(value['input']);self.assertEqual(len(value['hypothesis']['reading']),132)
        self.assertIn('native_reading_bound',value['lineage']['pending_reasons'])

    def test_surface_bound_is_distinct_from_reading_bound(self):
        value=self.apply(example('前｜橋《きょう》｜'+'字'*256+'《あ》。'))['views']['supported_run']
        self.assertIsNone(value['input']);self.assertEqual(value['lineage']['pending_reasons'],['native_surface_bound'])

    def test_native_one_character_does_not_pass_preparation_bound(self):
        value=self.apply(example('前｜橋《き》。'))['views']['original_ruby']
        self.assertEqual(value['input']['reading'],'き');self.assertFalse(value['preparation_bounds']['reading'])
        self.assertFalse(value['within_preparation_bounds']);self.assertFalse(value['lineage']['training_eligible'])

    def test_long_native_diagnostic_does_not_relax_training_length(self):
        value=self.apply(example('前｜橋《きょう》'+'あ'*40+'。'))['views']['supported_run']
        self.assertIsNotNone(value['input']);self.assertFalse(value['preparation_bounds']['reading']);self.assertFalse(value['preparation_bounds']['target'])

    def test_changed_start_recomputes_prefix_without_right_context(self):
        row,source,p,d=example('あ｜橋《きょう》を。',prefix='あ'*9)
        value=self.apply((row,source,p,d))['views']['supported_run']
        self.assertEqual(value['hypothesis']['start'],0);self.assertEqual(value['input']['left_context'],'')
        self.assertFalse(value['preparation_bounds']['prefix'])

    def test_parents_and_paragraph_are_not_modified(self):
        record=example();before=copy.deepcopy(record);self.apply(record);self.assertEqual(record,before)

    def test_views_have_distinct_ids_even_when_ranges_match(self):
        views=self.apply(example('前｜橋《きょう》。'))['views']
        self.assertEqual(len({v['input']['stable_id'] for v in views.values()}),3)
        self.assertEqual(len({v['input']['candidate_request_id'] for v in views.values()}),1)

    def test_lineage_binds_parent_component_and_original_source(self):
        record=example();value=self.apply(record)['views']['supported_run']
        self.assertEqual(value['lineage']['parent_original_row_sha256'],record[1]['original_row_sha256'])
        self.assertEqual(value['input']['component_id'],record[0]['component_id'])
        self.assertEqual(value['lineage']['candidate_input_sha256'],canonical_json_hash(value['input']))

    def test_forged_parent_decision_is_rejected(self):
        row,source,p,d=example();d['evidence_sha256']='0'*64
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_missing_annotation_is_not_inferred(self):
        row,source,p,_=example();p['spans']=[];d=assess(row,source,p,allow_dictionary_only=True)
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_a_new_view_does_not_certify_ime_or_independence(self):
        for value in self.apply(example())['views'].values():
            self.assertFalse(value['ime_gold']);self.assertFalse(value['grammatical_boundary_verified'])
            self.assertFalse(value['lineage']['independent_gold_eligible']);self.assertFalse(value['lineage']['independent_evaluation_eligible'])


if __name__=='__main__':unittest.main()
