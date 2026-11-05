import copy
import hashlib
import unittest

from sakura_rerank.data.annotation_first import extract_work
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.consumed_source import (PERMITTED, quarantine_units, target_terminal, unit_key, verify_consumption)
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.relation_witnesses import build_witness_graph, component_labels
from sakura_rerank.data.annotation_isolation import isolate_annotations
from test_annotation_first import raw_source


def metadata(index, population, article, paragraph, sentence, author=None, input_key=None):
    row = dict(stable_id=f"unit-test-{index}", population=population, source=dict(article_id=article,
        template_cluster_id=author, paragraph_hash=text_sha256(paragraph), sentence_hash=text_sha256(sentence),
        sentence_shingle_hashes=[text_sha256(sentence)]))
    if population != "source_coverage":
        row["input_hash"] = text_sha256(input_key or str(index))
    return row


class ConsumedSourceTests(unittest.TestCase):
    def classify(self, rows):
        graph = build_witness_graph(rows)
        decisions, counts = quarantine_units(graph.records,
            component_labels(graph, ("article", "author", "input")),
            component_labels(graph, ("paragraph", "sentence_exact", "sentence_near", "input")))
        return decisions, counts

    def test_shared_sentence_quarantines_whole_paragraph_not_unrelated_author_paragraph(self):
        rows = [metadata(0, "historical", "history", "old", "shared"),
            metadata(1, "source_coverage", "work", "mixed", "shared", "author"),
            metadata(2, "source_coverage", "work", "mixed", "other", "author"),
            metadata(3, "source_coverage", "work", "clean", "clean-s", "author")]
        decisions, counts = self.classify(rows)
        self.assertEqual(decisions[unit_key(rows[1]["source"])]["status"], "quarantined_content_or_input")
        self.assertEqual(decisions[unit_key(rows[3]["source"])]["status"], PERMITTED)
        self.assertEqual(sum(counts.values()), 2)

    def test_same_author_with_history_quarantines_even_clean_text(self):
        rows = [metadata(0, "historical", "old", "old", "old", "author"),
                metadata(1, "source_coverage", "new", "clean", "clean", "author")]
        decisions, _ = self.classify(rows)
        self.assertEqual(decisions[unit_key(rows[1]["source"])]["status"], "quarantined_identity")

    def test_old_unused_input_bridge_taints_all_of_its_paragraph(self):
        rows = [metadata(0, "historical", "old", "old", "old", input_key="same"),
            metadata(1, "train", "work", "whole", "first", input_key="same"),
            metadata(2, "source_coverage", "work", "whole", "second")]
        decisions, _ = self.classify(rows)
        self.assertEqual(decisions[unit_key(rows[2]["source"])]["status"], "quarantined_identity")
        self.assertTrue(decisions[unit_key(rows[2]["source"])]["content_or_input_relation"])

    def test_missing_coverage_and_invalid_labels_fail_closed(self):
        row = metadata(0, "train", "a", "p", "s")
        self.assertEqual(target_terminal(row, {}), "missing_full_source_coverage")
        with self.assertRaises(ValueError):
            quarantine_units([row], [1], [0])

    def fixture(self):
        raw = raw_source("これは入力範囲を確認するための原文です。｜学校《がっこう》へ行きます。")
        revision = hashlib.sha256(raw).hexdigest()
        targets, _, _, _ = extract_work(raw, "1", "2", revision)
        paragraph = paragraphs_with_ruby(raw)[0][0]
        row = targets[0]
        decision = dict(unit_id=unit_key(row["source"]), article_id=row["source"]["article_id"],
                        paragraph_hash=row["source"]["paragraph_hash"], status=PERMITTED)
        arguments = dict(work_id="1", author_id="2", revision=revision, paragraph_index=0, consumer="source_verification")
        return row, decision, paragraph, arguments

    def test_original_exact_input_is_verified_but_never_admitted(self):
        row, decision, paragraph, args = self.fixture()
        evidence = verify_consumption(row, decision, paragraph, **args)
        self.assertEqual(evidence["input_and_label_sha256"], canonical_json_hash([row["left_context"], row["reading"], row["target"]]))
        self.assertFalse(evidence["training_eligible"])
        self.assertFalse(evidence["independent_gold_eligible"])

    def test_training_body_cache_model_and_checkpoint_consumers_are_rejected(self):
        row, decision, paragraph, args = self.fixture()
        for consumer in ("training", "body_pretraining", "numeric_cache", "model_inference", "checkpoint"):
            with self.subTest(consumer=consumer), self.assertRaises(ValueError):
                verify_consumption(row, decision, paragraph, **dict(args, consumer=consumer))

    def test_changed_context_reading_target_revision_or_admission_is_rejected(self):
        row, decision, paragraph, args = self.fixture()
        for key, value in (("left_context", row["left_context"] + "外"), ("reading", "べつ"),
            ("target", "別"), ("source_revision", "0" * 64), ("training_eligible", True),
            ("paragraph_start", row["paragraph_start"] - 1)):
            changed = copy.deepcopy(row); changed[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                verify_consumption(changed, decision, paragraph, **args)
        with self.assertRaises(ValueError):
            verify_consumption(row, dict(decision, status="quarantined_content_or_input"), paragraph, **args)

    def test_fresh_rebuild_preserves_remaining_relation_after_representative_deletion(self):
        rows = [metadata(0, "source_coverage", "unused", "same", "same"),
                metadata(1, "historical", "history", "same", "same"),
                metadata(2, "train", "new", "same", "same")]
        excluded, _, _ = isolate_annotations(rows[1:])
        self.assertIn(rows[2]["stable_id"], excluded)


if __name__ == "__main__":
    unittest.main()
