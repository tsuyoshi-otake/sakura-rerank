import importlib.util
from pathlib import Path
import sys
import unittest

from sakura_rerank.data.contracts import sentence_shingle_hashes, text_sha256

DIRECTORY = Path("research/issue-49-annotation-first")
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location("annotation_relation_audit_test", DIRECTORY / "audit_relations.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
finally:
    sys.path.pop(0)


def record(identifier, paragraph, sentence):
    return dict(stable_id=identifier, source=dict(article_id=identifier,
        paragraph_hash=text_sha256(paragraph), sentence_hash=text_sha256(sentence),
        sentence_shingle_hashes=sentence_shingle_hashes(sentence)))


class AnnotationRelationAuditTests(unittest.TestCase):
    def test_same_normalized_signature_is_distinct_from_literal_paragraph(self):
        history = [record("h1", "paragraph-one", "ＡＢＣ"), record("h2", "paragraph-two", "abc")]
        coverage = [record("s1", "paragraph-three", "abc"), record("s2", "paragraph-one", "separate")]
        result = audit.shared_groups(history, iter(coverage))
        paragraph = next(g for g in result if g["kind"] == "paragraph")
        signature = next(g for g in result if g["kind"] == "sentence_signature")
        self.assertEqual(paragraph["historical_ids"], ["h1"])
        self.assertEqual(paragraph["coverage_ids"], ["s2"])
        self.assertEqual(signature["historical_ids"], ["h1", "h2"])
        self.assertEqual(signature["coverage_ids"], ["s1"])
        self.assertEqual(result, audit.shared_groups(history[::-1], coverage[::-1]))

    def test_empty_signatures_do_not_create_edges_and_no_cartesian_pairs(self):
        historical = [record(f"h{i}", "p", "shared") for i in range(50)]
        coverage = [record(f"s{i}", "q", "shared") for i in range(60)]
        groups = audit.shared_groups(historical, coverage)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["historical_ids"]), 50)
        self.assertEqual(len(groups[0]["coverage_ids"]), 60)
        self.assertEqual(audit.shared_groups([record("h", "p", " ")], [record("s", "q", " ")]), [])

    def test_descriptive_bins_never_change_membership_or_expose_text(self):
        for length, bucket in ((4, "0..4"), (5, "5..9"), (9, "5..9"), (10, "10..19"), (19, "10..19"), (20, "20+")):
            self.assertEqual(audit.describe("文" * length)["length_bin"], bucket)
        punctuation = audit.describe("……！？ ")
        self.assertTrue(punctuation["punctuation_symbols_whitespace_only"])
        mixed = audit.describe("文あアA1!")
        self.assertFalse(mixed["punctuation_symbols_whitespace_only"])
        self.assertEqual(sum(mixed["characters"].values()), mixed["length"])
        self.assertNotIn("text", mixed)


if __name__ == "__main__":
    unittest.main()
