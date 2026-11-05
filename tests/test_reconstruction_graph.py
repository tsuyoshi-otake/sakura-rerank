"""Complete neutral metadata must not weaken real-input or leakage contracts."""
from copy import deepcopy
import unittest

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.reconstruction_graph import build_source_graph,isolate_source_scope,validate_source_record
from sakura_rerank.data.relation_witnesses import build_witness_graph


def record(identifier,population,signatures,*,article=None,paragraph=None):
    source=dict(article_id=article or identifier,paragraph_hash=paragraph or f'{len(identifier):064x}',sentence_hash=f'{len(signatures):064x}',
        sentence_shingle_hashes=[f'{i:064x}' for i in signatures],template_cluster_id=None)
    row=dict(stable_id=identifier,population=population,source=source)
    if population in ('train','evaluation'): row['input_hash']='a'*64
    return row


class ReconstructionGraphTest(unittest.TestCase):
    def test_legacy_typed_edges_components_and_audits_match(self):
        rows=[record('history','historical',range(10),paragraph='1'*64),
            record('coverage','source_coverage',range(11),article='new',paragraph='2'*64),
            record('target','train',range(11),article='new',paragraph='2'*64),
            record('isolated','train',range(100,110),paragraph='3'*64)]
        rows[-1]['input_hash']='b'*64;original=deepcopy(rows)
        old=build_witness_graph(rows);new=build_source_graph(rows[::-1])
        self.assertEqual(rows,original)
        self.assertEqual((old.records,old.left,old.right,old.kinds,old.audit),(new.records,new.left,new.right,new.kinds,new.audit))
        self.assertEqual(isolate_annotations(rows),isolate_source_scope(rows[::-1]))

    def test_complete_515_signature_neutral_preserves_near_history_edge(self):
        rows=[record('history','historical',range(512),paragraph='1'*64),
            record('neutral','source_coverage',range(515),article='new',paragraph='2'*64),
            record('target','train',range(800,810),article='new',paragraph='2'*64)]
        original=deepcopy(rows)
        with self.assertRaises(ValueError): build_witness_graph(rows)
        graph=build_source_graph(rows)
        self.assertGreater(graph.audit['distinct_near_signature_pairs'],0)
        excluded,_,_=isolate_source_scope(rows)
        self.assertEqual(excluded,{'target':'historical_relation'})
        self.assertEqual(rows,original)
        self.assertEqual(len(next(r for r in graph.records if r['stable_id']=='neutral')['source']['sentence_shingle_hashes']),515)

    def test_real_input_and_new_source_upper_bounds_fail_closed(self):
        with self.assertRaises(ValueError): validate_source_record(record('train','train',range(513)))
        with self.assertRaises(ValueError): validate_source_record(record('history','historical',range(513)))
        validate_source_record(record('neutral','source_coverage',range(1024)))
        with self.assertRaises(ValueError): validate_source_record(record('neutral','source_coverage',range(1025)))

    def test_neutral_extra_inputs_bad_hashes_and_duplicate_order_rejected(self):
        source=record('neutral','source_coverage',range(515))
        changed=deepcopy(source);changed['input_hash']='a'*64
        with self.assertRaises(ValueError): validate_source_record(changed)
        for values in (source['source']['sentence_shingle_hashes'][::-1],['not-a-hash'],['0'*64,'0'*64],[]):
            changed=deepcopy(source);changed['source']['sentence_shingle_hashes']=values
            with self.subTest(count=len(values)),self.assertRaises(ValueError): validate_source_record(changed)
        with self.assertRaises(ValueError): build_source_graph([source,source])


if __name__=='__main__': unittest.main()
