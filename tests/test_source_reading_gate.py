"""Source contradictions cannot enter new reconstruction preparation."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash, text_sha256
from sakura_rerank.data.source_reading_gate import assess, prepare, load_prepared, policy


def fixture(name='row-a', *, observed='はし', origin='frozen_unique_dictionary'):
    left='左側の文章を入力'
    text=left+'橋を渡る'
    row=dict(stable_id=name,component_id='component-a',corpus='aozora',left_context=left,reading='はし',target='橋',
             candidate_request_id='growth-reading-'+canonical_json_hash('はし'))
    source=dict(origin_kind=origin,revision_sha256='a'*64,paragraph_sha256=text_sha256(text),
                original_row_sha256=canonical_json_hash(['original',name]),start=len(left),end=len(left)+1)
    paragraph=dict(text=text,spans=[dict(start=len(left),end=len(left)+1,reading=observed,kind='explicit',base_sha256=text_sha256('橋'))],
                   line_number=4,source_line_sha256=text_sha256(text),flags=dict(orphan_marker=False))
    return row,source,paragraph


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_json(path, value):
    path.write_bytes(canonical_json_bytes(value)+b'\n')


def replace_rows(root, name, values):
    data=b''.join(canonical_json_bytes(v)+b'\n' for v in values)
    path=root/name
    path.write_bytes(gzip.compress(data,mtime=0))
    manifest=json.loads((root/'manifest.json').read_bytes())
    manifest['artifacts'][name]=dict(sha256=digest(path),bytes=path.stat().st_size,decoded_bytes=len(data))
    replace_json(root/'manifest.json',manifest)


class SourceReadingEvidenceTests(unittest.TestCase):
    def test_exact_match_is_only_source_preparation(self):
        d=assess(*fixture())
        self.assertEqual(d['terminal'],'ready_original_annotation')
        self.assertTrue(d['candidate_preparation_allowed'])
        self.assertFalse(d['training_eligible'])
        self.assertFalse(d['independent_gold_eligible'])

    def test_conflict_is_held_even_with_weak_dictionary_permission(self):
        d=assess(*fixture(observed='きょう'),allow_dictionary_only=True)
        self.assertEqual(d['terminal'],'pending_reading_conflict')
        self.assertFalse(d['candidate_preparation_allowed'])

    def test_no_annotation_requires_explicit_weak_policy(self):
        row,source,p=fixture();p['spans']=[]
        self.assertEqual(assess(row,source,p)['terminal'],'pending_annotation_missing')
        self.assertEqual(assess(row,source,p,allow_dictionary_only=True)['terminal'],'ready_dictionary_only_weak')

    def test_missing_claimed_original_ruby_cannot_downgrade_to_dictionary(self):
        row,source,p=fixture(origin='original_ruby');p['spans']=[]
        self.assertFalse(assess(row,source,p,allow_dictionary_only=True)['candidate_preparation_allowed'])

    def test_scope_difference_is_pending_not_inferred_reading(self):
        row,source,p=fixture();p['spans'][0]['end']+=1;p['spans'][0]['base_sha256']=text_sha256('橋を')
        self.assertEqual(assess(row,source,p,allow_dictionary_only=True)['terminal'],'pending_annotation_scope')

    def test_unresolved_parse_and_nonphonetic_are_pending(self):
        row,source,p=fixture();p['spans'][0]['kind']='unresolved_base'
        self.assertEqual(assess(row,source,p)['terminal'],'pending_annotation_parse')
        self.assertEqual(assess(*fixture(observed='ママ'))['terminal'],'pending_annotation_reading')

    def test_orphan_marker_without_overlap_is_pending(self):
        row,source,p=fixture();p['spans']=[];p['flags']['orphan_marker']=True
        self.assertEqual(assess(row,source,p,allow_dictionary_only=True)['terminal'],'pending_annotation_parse')

    def test_only_original_katakana_mapping_is_permitted(self):
        self.assertEqual(assess(*fixture(observed='ハシ'))['terminal'],'ready_original_annotation')
        self.assertEqual(assess(*fixture(observed='ﾊｼ'))['terminal'],'pending_annotation_reading')

    def test_adjacency_is_not_a_rejection_rule(self):
        row,source,p=fixture();p['text']=row['left_context']+'橋梁';source['paragraph_sha256']=text_sha256(p['text'])
        self.assertTrue(assess(row,source,p)['candidate_preparation_allowed'])

    def test_wrong_span_context_and_source_hash_fail(self):
        for field,value in (('start',0),('paragraph_sha256','0'*64),('original_row_sha256','bad')):
            row,source,p=fixture();source[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):assess(row,source,p)
        row,source,p=fixture();row['left_context']='別の左側の文章です'
        with self.assertRaises(ValueError):assess(row,source,p)

    def test_aozora_cannot_silently_drop_annotation_structure(self):
        row,source,p=fixture()
        with self.assertRaises(ValueError):assess(row,source,p['text'],allow_dictionary_only=True)

    def test_wikipedia_missing_evidence_remains_explicit(self):
        row,source,p=fixture();row['corpus']='jawiki'
        self.assertEqual(assess(row,source,p['text'])['terminal'],'pending_annotation_missing')
        d=assess(row,source,p['text'],allow_dictionary_only=True)
        self.assertEqual(d['reading_evidence'],'wikipedia_no_original_reading_annotation')
        self.assertEqual(d['terminal'],'ready_dictionary_only_weak')

    def test_input_request_and_boolean_policy_are_strict(self):
        row,source,p=fixture();row['candidate_request_id']='wrong'
        with self.assertRaises(ValueError):assess(row,source,p)
        with self.assertRaises(ValueError):policy(1)

    def test_raw_records_are_never_modified(self):
        record=fixture();original=copy.deepcopy(record)
        assess(*record)
        self.assertEqual(record,original)


class SourceReadingPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.parent=Path(self.tmp.name)
        self.root=self.parent/'pool'

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        records=[fixture(),fixture('row-b',observed='きょう')]
        result=prepare(records,self.root,source_binding_sha256='b'*64,expected_rows=2)
        return result,records

    def load(self, purpose='candidate_generation'):
        return load_prepared(self.root,digest(self.root/'manifest.json'),purpose=purpose)

    def test_pending_target_never_reaches_candidate_or_numeric_consumer(self):
        manifest,records=self.build()
        self.assertEqual((manifest['input_rows'],manifest['preparable_rows'],manifest['pending_rows']),(2,1,1))
        for purpose in ('candidate_generation','numeric_verification'):
            result=self.load(purpose)
            self.assertEqual([r['input'] for r in result['rows']],[records[0][0]])
            self.assertEqual(len(result['decisions']),2)
            self.assertFalse(result['decisions'][1]['candidate_preparation_allowed'])

    def test_training_and_gold_purposes_are_rejected(self):
        self.build()
        for purpose in ('training','gold','final_test','calibration'):
            with self.subTest(purpose=purpose),self.assertRaises(ValueError):self.load(purpose)

    def test_explicit_weak_policy_round_trips_without_quality_promotion(self):
        row,source,p=fixture();p['spans']=[]
        prepare([(row,source,p)],self.root,source_binding_sha256='b'*64,expected_rows=1,allow_dictionary_only=True)
        result=self.load()
        self.assertEqual(result['manifest']['terminal_counts'],{'ready_dictionary_only_weak':1})
        self.assertFalse(result['manifest']['training_eligible'])

    def test_wrong_manifest_or_payload_hash_is_rejected(self):
        self.build()
        with self.assertRaises(ValueError):load_prepared(self.root,'0'*64,purpose='candidate_generation')
        with (self.root/'prepared-rows.jsonl.gz').open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):self.load()

    def test_pending_injection_fails_even_after_payload_hash_is_rebound(self):
        _,records=self.build();result=self.load()
        injected=dict(input=records[1][0],decision_sha256=canonical_json_hash(result['decisions'][1]))
        replace_rows(self.root,'prepared-rows.jsonl.gz',[injected])
        with self.assertRaises(ValueError):self.load()

    def test_claiming_a_pending_decision_is_ready_is_rejected(self):
        self.build()
        with gzip.open(self.root/'decisions.jsonl.gz','rb') as f:entries=[json.loads(line) for line in f]
        entries[1]['decision']['terminal']='ready_original_annotation'
        entries[1]['decision']['candidate_preparation_allowed']=True
        previous='0'*64
        for entry in entries:
            entry['previous_sha256']=previous
            previous=canonical_json_hash({k:v for k,v in entry.items() if k!='entry_sha256'})
            entry['entry_sha256']=previous
        replace_rows(self.root,'decisions.jsonl.gz',entries)
        manifest=json.loads((self.root/'manifest.json').read_bytes());manifest['decision_chain_head']=previous
        replace_json(self.root/'manifest.json',manifest)
        with self.assertRaises(ValueError):self.load()

    def test_admission_flags_cannot_be_enabled_by_rebinding_manifest(self):
        self.build();path=self.root/'manifest.json';manifest=json.loads(path.read_bytes());manifest['training_eligible']=True
        replace_json(path,manifest)
        with self.assertRaises(ValueError):self.load()

    def test_changing_original_label_is_rejected(self):
        self.build();result=self.load();result['rows'][0]['input']['target']='箸'
        replace_rows(self.root,'prepared-rows.jsonl.gz',result['rows'])
        with self.assertRaises(ValueError):self.load()

    def test_partial_batch_failure_publishes_nothing(self):
        def broken():
            yield fixture()
            raise OSError('synthetic source failure')
        with self.assertRaises(OSError):prepare(broken(),self.root,source_binding_sha256='b'*64,expected_rows=2)
        self.assertEqual(list(self.parent.iterdir()),[])

    def test_duplicate_or_wrong_count_publishes_nothing(self):
        for records,n in (([fixture(),fixture()],2),([fixture()],2),([fixture(),fixture('other')],1)):
            with self.assertRaises(ValueError):prepare(records,self.root,source_binding_sha256='b'*64,expected_rows=n)
            self.assertEqual(list(self.parent.iterdir()),[])

    def test_all_pending_publishes_no_trusted_pool(self):
        with self.assertRaises(ValueError):prepare([fixture(observed='きょう')],self.root,source_binding_sha256='b'*64,expected_rows=1)
        self.assertEqual(list(self.parent.iterdir()),[])

    def test_existing_destination_is_preserved(self):
        self.root.mkdir();sentinel=self.root/'user';sentinel.write_bytes(b'keep')
        with self.assertRaises(ValueError):prepare([fixture()],self.root,source_binding_sha256='b'*64,expected_rows=1)
        self.assertEqual(sentinel.read_bytes(),b'keep')

    def test_failed_publication_removes_only_owned_staging(self):
        sentinel=self.parent/'user';sentinel.write_bytes(b'keep')
        with patch.object(Path,'rename',side_effect=OSError('synthetic rename failure')):
            with self.assertRaises(OSError):prepare([fixture()],self.root,source_binding_sha256='b'*64,expected_rows=1)
        self.assertEqual(list(self.parent.iterdir()),[sentinel])

    def test_extra_file_and_missing_rows_are_not_complete_pools(self):
        self.build();extra=self.root/'partial';extra.write_bytes(b'pending')
        with self.assertRaises(ValueError):self.load()
        extra.unlink();replace_rows(self.root,'prepared-rows.jsonl.gz',[])
        with self.assertRaises(ValueError):self.load()


if __name__=='__main__':
    unittest.main()
