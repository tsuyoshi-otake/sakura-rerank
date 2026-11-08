"""Diagnostic propagation and invalid-certificate contracts, never admission."""
from array import array
import importlib.util
from pathlib import Path
import sys
import unittest

from sakura_rerank.data.relation_witnesses import WitnessGraph, component_labels, trace_paths

HERE = Path(__file__).resolve().parents[1]/'research/issue-33-knbc-screening'
sys.path.insert(0, str(HERE))
try:
    spec = importlib.util.spec_from_file_location('knbc_trace_contract', HERE/'trace.py')
    trace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace)
finally:
    sys.path.pop(0)


def fixture():
    def row(index, family, paragraph):
        return dict(stable_id=str(index), population='evaluation', input_hash=str(index),
            source=dict(article_id='knbc:'+str(index), template_cluster_id=family,
                        paragraph_hash=paragraph, sentence_shingle_hashes=[str(index)]))
    # 0 -> 1 by prefix grouping; 1 -> 2 by repeated paragraph; 3 is isolated.
    return WitnessGraph([row(0, 'a', 'x'), row(1, 'a', 'y'), row(2, 'b', 'y'), row(3, 'c', 'z')],
                        array('I', [0, 1]), array('I', [1, 2]), array('B', [1, 3]))


class KnbcTraceTests(unittest.TestCase):
    def test_views_distinguish_direct_group_and_content_propagation(self):
        graph = fixture()
        seeds = dict(known_input_alias=[0], historical_input=[], consumed_source=[])
        for view, expected in [('input_only', 1), ('identity_only', 2), ('full', 3)]:
            result = trace.census(component_labels(graph, trace.VIEWS[view]), range(4), seeds)
            self.assertEqual(result['any_seed_connected'], expected)
            self.assertEqual(result['unconnected_inputs'], 4-expected)
        self.assertEqual(trace.verify_edges(graph), 2)

    def test_paths_certify_connected_and_unreachable_terminals(self):
        graph = fixture()
        identity = component_labels(graph, trace.VIEWS['identity_only'])
        full = component_labels(graph)
        forest = trace_paths(graph, identity, [0])
        self.assertEqual(trace.verify_forest(graph, identity, full, [0], forest), 3)
        self.assertEqual([forest['distance'][i] for i in identity], [0, 0, 1, -1])

    def test_mutated_seed_parent_distance_and_unreachable_are_rejected(self):
        graph = fixture()
        identity = component_labels(graph, trace.VIEWS['identity_only'])
        full = component_labels(graph)
        for field, target, value in [('seed', 2, 3), ('parent', 2, 2), ('distance', 2, 7),
                                     ('edge', 2, 0), ('parent', 3, 3)]:
            with self.subTest(field=field, target=target):
                forest = trace_paths(graph, identity, [0])
                forest[field][identity[target]] = value
                with self.assertRaises(ValueError):
                    trace.verify_forest(graph, identity, full, [0], forest)

    def test_empty_seeds_remain_unreachable(self):
        graph = fixture()
        identity = component_labels(graph, trace.VIEWS['identity_only'])
        forest = trace_paths(graph, identity, [])
        self.assertEqual(trace.verify_forest(graph, identity, component_labels(graph), [], forest), 3)

    def test_relation_names_do_not_certify_authors(self):
        graph = fixture()
        self.assertEqual(trace.source_kind(graph.records[0]), 'knbc')
        graph.records[0]['source']['template_cluster_id'] = 'different'
        with self.assertRaisesRegex(ValueError, 'trace_edge_without_metadata_evidence'):
            trace.verify_edges(graph)


if __name__ == '__main__':
    unittest.main()
