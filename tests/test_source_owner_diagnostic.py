"""Administrative-owner sensitivity cannot silently remove legacy authorship."""
from array import array
import copy
import unittest

from sakura_rerank.data.relation_witnesses import WitnessGraph,component_labels
from sakura_rerank.data.source_owner_diagnostic import administrative_owner_omissions


def fixture():
    records=[dict(stable_id=key,source=dict(article_id=article,template_cluster_id=group)) for key,article,group in (
        ('old1','legacy:1','real-author'),('old2','legacy:2','real-author'),
        ('new1','tatoeba:1','tatoeba-owner:'+'a'*64),('new2','tatoeba:2','tatoeba-owner:'+'a'*64))]
    return WitnessGraph(records,left=array('I',[0,2,0]),right=array('I',[1,3,2]),kinds=array('B',[1,1,2]))


class SourceOwnerDiagnosticTests(unittest.TestCase):
    def test_only_selected_owner_edge_is_omitted(self):
        graph=fixture();mask=administrative_owner_omissions(graph,{'new1','new2'})
        self.assertEqual(list(mask),[0,1,0])
        labels=component_labels(graph,omitted=mask)
        self.assertEqual(labels[0],labels[1])
        self.assertEqual(labels[0],labels[2])
        self.assertNotEqual(labels[0],labels[3])

    def test_diagnostic_does_not_mutate_records_or_edges(self):
        graph=fixture();before=copy.deepcopy(graph)
        administrative_owner_omissions(graph,{'new1','new2'})
        self.assertEqual(graph,before)

    def test_incomplete_selection_cannot_drop_whole_group(self):
        with self.assertRaisesRegex(ValueError,'unselected_group_member'):
            administrative_owner_omissions(fixture(),{'new1'})

    def test_missing_ids_or_empty_scope_are_rejected(self):
        for ids in (set(),{'missing'}):
            with self.assertRaises(ValueError):administrative_owner_omissions(fixture(),ids)

    def test_source_namespace_and_group_identity_are_required(self):
        for field,value in (('article_id','legacy:3'),('template_cluster_id','real-author')):
            graph=fixture();graph.records[2]['source'][field]=value
            with self.assertRaises(ValueError):administrative_owner_omissions(graph,{'new1','new2'})

    def test_owner_edge_cannot_bridge_distinct_owner_groups(self):
        graph=fixture();graph.records[3]['source']['template_cluster_id']='tatoeba-owner:'+'b'*64
        with self.assertRaisesRegex(ValueError,'edge_identity'):
            administrative_owner_omissions(graph,{'new1','new2'})

    def test_other_relation_types_remain_included(self):
        for kind in (0,2,3,4,5):
            graph=fixture();graph.kinds[1]=kind
            self.assertEqual(list(administrative_owner_omissions(graph,{'new1','new2'})),[0,0,0])


if __name__=='__main__':unittest.main()
