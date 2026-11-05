import random
import unittest

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import text_sha256


def metadata(index, population, article, paragraph, shingles, input_key=None, author=None):
    row = dict(stable_id=f"test-{index}", population=population, source=dict(article_id=article,
        paragraph_hash=text_sha256(paragraph), sentence_hash=text_sha256(str(shingles)),
        sentence_shingle_hashes=sorted(text_sha256(s) for s in set(shingles)), template_cluster_id=author))
    if input_key is not None:
        row["input_hash"] = text_sha256(input_key)
    return row


class AnnotationIsolationTests(unittest.TestCase):
    def test_source_without_targets_can_bridge_a_train_work_to_history(self):
        records = [metadata(0, "historical", "old", "shared", ["old"]),
            metadata(1, "source_coverage", "new-work", "shared", ["coverage"]),
            metadata(2, "train", "new-work", "target-only", ["target"], "input")]
        excluded, _, result = isolate_annotations(records)
        self.assertEqual(excluded, {"test-2": "historical_relation"})
        self.assertEqual(result["historical_coverage_shared_paragraph_groups"], 1)

    def test_actual_input_bridge_and_author_closure_are_transitive(self):
        records = [metadata(0, "historical", "old", "old-p", ["a"], "same-input"),
            metadata(1, "train", "work-1", "p-1", ["b"], "same-input", "author"),
            metadata(2, "train", "work-2", "p-2", ["c"], "other-input", "author")]
        excluded, components, _ = isolate_annotations(records)
        self.assertEqual(set(excluded), {"test-1", "test-2"})
        self.assertEqual(components["test-1"], components["test-2"])

    def test_exact_equality_with_frozen_adapter_on_bounded_random_graphs(self):
        rng = random.Random(49)
        for size in (1, 10, 70, 200):
            records = []
            for i in range(size):
                population = rng.choice(["historical", "train", "evaluation", "source_coverage"])
                records.append(metadata(i, population, str(rng.randrange(100)), str(rng.randrange(100)),
                    [str(rng.randrange(50)), "common"], None if population == "source_coverage" else str(rng.randrange(150)),
                    "author-" + str(rng.randrange(100))))
            old = isolate_with_source_coverage(records)
            new = isolate_annotations(records)
            self.assertEqual(new[:2], old[:2])
            self.assertEqual({k: new[2][k] for k in old[2]}, old[2])
            reverse = isolate_annotations(records[::-1])
            self.assertEqual(new, reverse)

    def test_source_only_nodes_cannot_invent_input_edges(self):
        row = metadata(0, "source_coverage", "a", "p", ["x"], "fake")
        with self.assertRaisesRegex(ValueError, "source_only_has_input"):
            isolate_annotations([row])

    def test_duplicate_identity_and_empty_population_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "record_bound"):
            isolate_annotations([])
        row = metadata(0, "historical", "a", "p", ["x"])
        with self.assertRaisesRegex(ValueError, "duplicate_id"):
            isolate_annotations([row, row])


if __name__ == "__main__":
    unittest.main()
