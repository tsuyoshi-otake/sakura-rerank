"""A consumed source remains exposed even when no usable input could be made."""
import unittest

from sakura_rerank.data.reconstruction_graph import build_source_graph, isolate_source_scope
from sakura_rerank.data.source_exposure import exposed_source_inputs


def source(key, text='a', input_hash=None):
    row=dict(stable_id=key,population='source_coverage' if input_hash is None else 'evaluation',
             source=dict(article_id=key,paragraph_hash=text*64,sentence_hash=text*64,
                         sentence_shingle_hashes=[text*64],template_cluster_id=None))
    if input_hash is not None:row['input_hash']=input_hash*64
    return row


class SourceExposureTests(unittest.TestCase):
    def test_consumed_source_without_reading_still_excludes_related_new_input(self):
        rows=[source('old'),source('new',input_hash='c')]
        self.assertEqual(isolate_source_scope(rows)[0],{})
        self.assertEqual(exposed_source_inputs(build_source_graph(rows),['old']),{'new'})

    def test_unconsumed_neutral_inventory_is_not_automatically_exposed(self):
        graph=build_source_graph([source('inventory'),source('new',input_hash='c')])
        self.assertEqual(exposed_source_inputs(graph,[]),set())

    def test_unrelated_source_and_existing_history_keep_their_roles(self):
        rows=[source('old'),source('new','b','c'),source('past','a','d')]
        rows[2]['population']='historical'
        self.assertEqual(exposed_source_inputs(build_source_graph(rows),['old']),set())

    def test_transitive_input_relations_propagate_and_order_does_not_matter(self):
        rows=[source('old'),source('first','a','c'),source('second','b','c')]
        for ordered in (rows,list(reversed(rows))):
            self.assertEqual(exposed_source_inputs(build_source_graph(ordered),['old']),{'first','second'})

    def test_missing_duplicate_or_non_neutral_exposure_is_rejected(self):
        graph=build_source_graph([source('old'),source('new',input_hash='c')])
        for ids in (['missing'],['old','old'],['new']):
            with self.assertRaises(ValueError):exposed_source_inputs(graph,ids)


if __name__=='__main__':unittest.main()
