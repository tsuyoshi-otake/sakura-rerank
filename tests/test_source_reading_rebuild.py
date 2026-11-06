"""Only exact bound source-reading conflicts yield append-only derived inputs."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from sakura_rerank.data.contracts import canonical_json_hash,text_sha256
from sakura_rerank.data.source_reading_gate import assess,prepare,load_prepared
from sakura_rerank.data.source_reading_rebuild import rebuild


def example(observed='きょう',reading='はし',name='parent-a'):
    left='左側の文章を入力';text=left+'橋を渡る'
    row=dict(stable_id=name,component_id='existing-component',corpus='aozora',left_context=left,reading=reading,target='橋',
        candidate_request_id='growth-reading-'+canonical_json_hash(reading))
    source=dict(origin_kind='frozen_unique_dictionary',revision_sha256='a'*64,paragraph_sha256=text_sha256(text),
        original_row_sha256=canonical_json_hash(['original',name]),start=len(left),end=len(left)+1)
    paragraph=dict(text=text,spans=[dict(start=len(left),end=len(left)+1,reading=observed,kind='explicit',base_sha256=text_sha256('橋'))],
        line_number=1,source_line_sha256=text_sha256(text),flags=dict(orphan_marker=False))
    decision=assess(row,source,paragraph,allow_dictionary_only=True)
    return row,source,paragraph,decision


class SourceReadingRebuildTests(unittest.TestCase):
    def apply(self,record):
        return rebuild(*record,parent_dictionary_only=True)

    def test_original_full_reading_replaces_only_derived_reading(self):
        original=example();result=self.apply(original)
        self.assertEqual(result['input']['reading'],'きょう')
        for key in ('target','left_context','component_id','corpus'):
            self.assertEqual(result['input'][key],original[0][key])
        self.assertNotEqual(result['input']['stable_id'],original[0]['stable_id'])
        self.assertEqual(result['input']['candidate_request_id'],'growth-reading-'+canonical_json_hash('きょう'))

    def test_parent_and_source_are_not_mutated(self):
        record=example();before=copy.deepcopy(record);self.apply(record)
        self.assertEqual(record,before)

    def test_identity_is_deterministic_and_parent_sensitive(self):
        a=self.apply(example());b=self.apply(example());c=self.apply(example(name='parent-b'))
        self.assertEqual(a,b)
        self.assertNotEqual(a['input']['stable_id'],c['input']['stable_id'])

    def test_lineage_binds_parent_decision_original_and_child(self):
        row,source,p,decision=example();result=self.apply((row,source,p,decision));lineage=result['lineage']
        self.assertEqual(lineage['parent_decision_sha256'],canonical_json_hash(decision))
        self.assertEqual(lineage['parent_original_row_sha256'],source['original_row_sha256'])
        self.assertEqual(lineage['rebuilt_input_sha256'],canonical_json_hash(result['input']))
        self.assertEqual(result['source']['original_row_sha256'],result['lineage_sha256'])

    def test_katakana_mapping_is_exact(self):
        self.assertEqual(self.apply(example(observed='キョウ'))['input']['reading'],'きょう')

    def test_historical_kana_is_not_modernized(self):
        self.assertEqual(self.apply(example(observed='けふ'))['input']['reading'],'けふ')

    def test_one_character_reading_stays_pending(self):
        result=self.apply(example(observed='き'))
        self.assertEqual(result['status'],'pending_rebuilt_reading_bounds')
        self.assertIsNone(result['input']);self.assertIsNone(result['source'])
        self.assertEqual(result['lineage']['rebuilt_reading_characters'],1)

    def test_unmodified_reading_is_not_a_repair(self):
        with self.assertRaises(ValueError):self.apply(example(observed='はし'))

    def test_scope_difference_is_not_rebuilt(self):
        row,source,p,_=example();p['spans'][0]['end']+=1;p['spans'][0]['base_sha256']=text_sha256('橋を')
        d=assess(row,source,p,allow_dictionary_only=True)
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_missing_annotation_is_not_inferred(self):
        row,source,p,_=example();p['spans']=[];d=assess(row,source,p,allow_dictionary_only=True)
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_halfwidth_and_nonphonetic_annotations_are_not_normalized(self):
        for observed in ('ｷｮｳ','ママ','text'):
            with self.subTest(observed=observed),self.assertRaises(ValueError):self.apply(example(observed=observed))

    def test_parser_uncertainty_is_not_repaired(self):
        row,source,p,_=example();p['spans'][0]['kind']='unresolved_base';d=assess(row,source,p,allow_dictionary_only=True)
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_forged_parent_decision_is_rejected(self):
        row,source,p,d=example();d['evidence_sha256']='0'*64
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_parent_policy_is_bound(self):
        with self.assertRaises(ValueError):rebuild(*example(),parent_dictionary_only=False)

    def test_annotation_origin_is_not_silently_repaired(self):
        row,source,p,_=example();source['origin_kind']='original_ruby';d=assess(row,source,p,allow_dictionary_only=True)
        with self.assertRaises(ValueError):self.apply((row,source,p,d))

    def test_source_revision_changes_derivation_identity(self):
        record=example();a=self.apply(record)
        row,source,p,_=example();source['revision_sha256']='b'*64;d=assess(row,source,p,allow_dictionary_only=True)
        b=self.apply((row,source,p,d))
        self.assertNotEqual(a['input']['stable_id'],b['input']['stable_id'])

    def test_rebuilt_input_passes_strict_default_preparation(self):
        original=example();result=self.apply(original)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'pool'
            prepare([(result['input'],result['source'],original[2])],root,source_binding_sha256='c'*64,expected_rows=1)
            digest=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
            pool=load_prepared(root,digest,purpose='candidate_generation')
            self.assertEqual(pool['rows'][0]['input'],result['input'])
            self.assertFalse(pool['manifest']['policy']['allow_dictionary_only'])
            self.assertEqual(pool['manifest']['terminal_counts'],{'ready_original_annotation':1})

    def test_new_identity_does_not_grant_independence_or_gold(self):
        result=self.apply(example())
        for key in ('training_eligible','independent_gold_eligible','independent_evaluation_eligible'):
            self.assertFalse(result['lineage'][key])


if __name__=='__main__':unittest.main()
