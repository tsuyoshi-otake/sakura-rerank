from collections import defaultdict
import random
import unittest

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.relation_witnesses import (
    IDENTITY_KINDS, KINDS, build_witness_graph, component_labels,
    exact_group_omissions, trace_paths)


def row(index, population="train", *, article=None, author=None, paragraph=None, shingles=None, input_key=None):
    result = dict(stable_id=f"node-{index:04d}", population=population, source=dict(
        article_id=article or f"a-{index}", template_cluster_id=author,
        paragraph_hash=text_sha256(paragraph or f"p-{index}"), sentence_hash=text_sha256(f"s-{index}"),
        sentence_shingle_hashes=sorted(text_sha256(v) for v in set(shingles or [f"g-{index}"]))))
    if population != "source_coverage":
        result["input_hash"] = text_sha256(input_key or f"i-{index}")
    return result


def hashes(graph, labels):
    groups = defaultdict(list)
    for index, label in enumerate(labels):
        groups[label].append(graph.records[index]["stable_id"])
    values = {label: canonical_json_hash(sorted(ids)) for label, ids in groups.items()}
    return {r["stable_id"]: values[label] for r, label in zip(graph.records, labels) if r["population"] == "train"}


class RelationWitnessTests(unittest.TestCase):
    def test_full_closure_equals_frozen_adapter_and_is_order_invariant(self):
        generator = random.Random(32049)
        for size in (1, 12, 100):
            records = [row(i, "historical" if i % 7 == 0 else "source_coverage" if i % 5 == 0 else "train",
                article=f"a-{generator.randrange(size)}", author=f"author-{generator.randrange(size)}",
                paragraph=f"p-{generator.randrange(size)}", shingles=[f"s-{generator.randrange(20)}" for _ in range(5)],
                input_key=f"i-{generator.randrange(size)}") for i in range(size)]
            _, expected, _ = isolate_annotations(records)
            graph = build_witness_graph(records)
            reverse = build_witness_graph(records[::-1])
            self.assertEqual(hashes(graph, component_labels(graph)), expected)
            self.assertEqual((graph.left, graph.right, graph.kinds), (reverse.left, reverse.right, reverse.kinds))

    def test_text_bridge_reaches_whole_author_without_source_only_input(self):
        records = [row(0, "historical", paragraph="shared"),
            row(1, "source_coverage", article="work-a", author="author", paragraph="shared"),
            row(2, article="work-a", author="author"), row(3, article="work-b", author="author")]
        graph = build_witness_graph(records)
        identity = component_labels(graph, IDENTITY_KINDS)
        paths = trace_paths(graph, identity, [0])
        self.assertEqual(paths["distance"][identity[3]], 1)
        self.assertEqual(paths["seed"][identity[3]], 0)
        self.assertEqual(KINDS[graph.kinds[paths["edge"][identity[3]]]], "paragraph")
        self.assertEqual(graph.audit["duplicate_key_groups"]["input"], 0)

    def test_unknown_history_remains_a_bridge_in_evaluation_only_paths(self):
        records = [row(0, "historical", paragraph="p"), row(1, "historical", paragraph="p", input_key="bridge"),
            row(2, input_key="bridge"), row(3)]
        graph = build_witness_graph(records)
        identity = component_labels(graph, IDENTITY_KINDS)
        paths = trace_paths(graph, identity, [0])
        self.assertEqual(paths["distance"][identity[2]], 1)
        self.assertEqual(paths["distance"][identity[3]], -1)
        self.assertEqual(paths["parent"][identity[3]], -1)

    def test_omitting_exact_groups_preserves_near_and_input_relations(self):
        records = [row(0, "historical", paragraph="same", shingles=list("abcd")),
            row(1, paragraph="same", shingles=list("abcd")), row(2, shingles=list("abcde")),
            row(3, input_key="shared"), row(4, input_key="shared")]
        graph = build_witness_graph(records)
        signature = tuple(records[0]["source"]["sentence_shingle_hashes"])
        omit = exact_group_omissions(graph, {text_sha256("same")}, {signature})
        self.assertTrue(any(omit))
        self.assertTrue(all(graph.kinds[i] in (3, 4) for i, value in enumerate(omit) if value))
        labels = component_labels(graph, omitted=omit)
        self.assertEqual(labels[0], labels[2])
        self.assertEqual(labels[1], labels[2])  # Each equal-signature member also has the near edge.
        self.assertEqual(labels[3], labels[4])

    def test_signature_match_boundary_and_all_pair_oracle(self):
        records = [row(i, shingles=s) for i, s in enumerate((list("abcd"), list("abcde"), list("abcdef"), ["isolated"]))]
        graph = build_witness_graph(records)
        labels = component_labels(graph, ["sentence_exact", "sentence_near"])
        self.assertEqual(labels[0], labels[2])  # .8 then 5/6, transitive
        self.assertNotEqual(labels[0], labels[3])
        self.assertEqual(graph.audit["conceptual_near_record_pairs"], 2)

    def test_bounds_duplicates_and_source_only_input_are_rejected(self):
        with self.assertRaises(ValueError):
            build_witness_graph([])
        with self.assertRaises(ValueError):
            build_witness_graph([row(0), row(0)])
        invalid = row(0, "source_coverage")
        invalid["input_hash"] = text_sha256("fake")
        with self.assertRaises(ValueError):
            build_witness_graph([invalid])
        with self.assertRaises(ValueError):
            build_witness_graph([row(i, article="same", author="same") for i in range(3)], max_edges=1)

    def test_near_edges_match_independent_exhaustive_pair_closure(self):
        generator = random.Random(32)
        for _ in range(25):
            records = [row(i, shingles=generator.sample(list("abcdefghijk"), generator.randrange(3, 10))) for i in range(24)]
            graph = build_witness_graph(records)
            labels = component_labels(graph, ["sentence_exact", "sentence_near"])
            reachable = [{i} for i in range(len(records))]
            pair_count = 0
            for left in range(len(records)):
                a = set(records[left]["source"]["sentence_shingle_hashes"])
                for right in range(left):
                    b = set(records[right]["source"]["sentence_shingle_hashes"])
                    if len(a & b) / len(a | b) >= .8:
                        group = reachable[left] | reachable[right]
                        for index in group:
                            reachable[index] = group
                        pair_count += 1
            self.assertEqual(graph.audit["conceptual_near_record_pairs"], pair_count)
            for left in range(len(records)):
                for right in range(len(records)):
                    self.assertEqual(labels[left] == labels[right], right in reachable[left])

    def test_no_history_and_no_edges_are_explicit_unreachable(self):
        graph = build_witness_graph([row(0)])
        paths = trace_paths(graph, component_labels(graph, IDENTITY_KINDS), [])
        self.assertEqual(list(paths["distance"]), [-1])
        self.assertEqual(list(paths["edge"]), [-1])
        with self.assertRaises(ValueError):
            component_labels(graph, ["invented"])

    def test_near_only_view_preserves_full_bipartite_connectivity_without_exact_stars(self):
        records = [row(i, shingles=list("abcd" if i < 5 else "abcde")) for i in range(9)]
        graph = build_witness_graph(records)
        labels = component_labels(graph, ["sentence_near"])
        self.assertEqual(len(set(labels)), 1)
        self.assertEqual(graph.audit["distinct_near_signature_pairs"], 1)
        self.assertEqual(graph.audit["edge_kinds"]["sentence_near"], 8)
        self.assertEqual(graph.audit["conceptual_near_record_pairs"], 36)


if __name__ == "__main__":
    unittest.main()
