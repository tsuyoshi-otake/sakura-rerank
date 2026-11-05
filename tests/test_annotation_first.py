import hashlib
import unittest

from sakura_rerank.data.annotation_first import extract_work


def raw_source(body):
    return ("合成資料\n" + "-" * 20 + "\n記号\n" + "-" * 20 + "\n" + body + "\n底本：合成\n").encode("cp932")


def extract(body):
    raw = raw_source(body)
    return extract_work(raw, "900000", "900001", hashlib.sha256(raw).hexdigest())


class AnnotationFirstTests(unittest.TestCase):
    def test_full_original_base_without_dictionary_preselection(self):
        targets, terminals, _, report = extract("これは合成の前文です。｜架空試験語《かくうしけんご》を使います。")
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["target"], "架空試験語")
        self.assertEqual(targets[0]["reading"], "かくうしけんご")
        self.assertFalse(targets[0]["training_eligible"])
        self.assertFalse(targets[0]["independent_gold_eligible"])
        self.assertEqual(terminals[0]["status"], "provisional")
        self.assertEqual(report["annotation_slots"], 1)

    def test_context_is_only_bounded_preceding_text(self):
        first = extract("前" * 90 + "。公園《こうえん》右側の続き。")
        second = extract("前" * 90 + "。公園《こうえん》別の未来。")
        self.assertEqual(first[0][0]["left_context"], second[0][0]["left_context"])
        self.assertEqual(len(first[0][0]["left_context"]), 64)
        self.assertNotIn("公園", first[0][0]["left_context"])

    def test_annotation_script_is_preserved_with_explicit_mapping(self):
        targets, _, _, _ = extract("これは合成の前文です。公園《コウエン》。")
        self.assertEqual(targets[0]["raw_annotation_reading"], "コウエン")
        self.assertEqual(targets[0]["reading"], "こうえん")
        self.assertEqual(targets[0]["reading_mapping"], "fullwidth_katakana_to_hiragana_only")

    def test_historical_kana_is_not_rewritten(self):
        targets, _, _, _ = extract("これは合成の前文です。公園《こうゑん》。")
        self.assertEqual(targets[0]["reading"], "こうゑん")

    def test_no_partial_reading_allocation_or_base_expansion(self):
        targets, _, _, _ = extract("これは合成の前文です。｜都市公園《としこうえん》へ。")
        self.assertEqual([r["target"] for r in targets], ["都市公園"])
        self.assertEqual([r["reading"] for r in targets], ["としこうえん"])

    def test_unsupported_editorial_and_short_context_keep_all_slots(self):
        targets, terminals, _, report = extract("公園《こうえん》。\nこれは合成の前文です。ABC《えーびーしー》。公園《ママ》。")
        self.assertEqual(targets, [])
        self.assertEqual(len(terminals), 3)
        self.assertEqual(report["annotation_slots"], sum(report["terminal_counts"].values()))
        self.assertEqual({r["status"] for r in terminals}, {"insufficient_left_context", "ruby_base_unresolved", "editorial_or_nonphonetic"})

    def test_cross_sentence_base_is_not_an_input_unit(self):
        targets, terminals, _, _ = extract("これは合成の前文です。｜試験。公園《しけんこうえん》。")
        self.assertEqual(targets, [])
        self.assertIn("source_sentence_boundary", terminals[0]["flags"])

    def test_long_sentences_have_coverage_but_no_targets(self):
        targets, terminals, coverage, report = extract("長" * 520 + "公園《こうえん》。")
        self.assertEqual(targets, [])
        self.assertIn("source_sentence_too_long", terminals[0]["flags"])
        self.assertGreater(len(coverage), 1)
        self.assertEqual(report["coverage_counts"]["long_sentences_windowed"], 1)

    def test_unselected_sentences_remain_in_source_coverage_without_fake_inputs(self):
        _, _, coverage, _ = extract("ここには注釈がありません。\nこれは合成の前文です。公園《こうえん》。")
        self.assertEqual(len(coverage), 3)
        self.assertTrue(all(set(r) == {"stable_id", "population", "source"} for r in coverage))
        self.assertTrue(all(r["population"] == "source_coverage" for r in coverage))

    def test_repeated_source_slots_are_not_removed(self):
        targets, terminals, coverage, _ = extract("これは合成の前文です。公園《こうえん》。\nこれは合成の前文です。公園《こうえん》。")
        self.assertEqual(len(targets), 2)
        self.assertNotEqual(targets[0]["stable_id"], targets[1]["stable_id"])
        self.assertEqual(len(terminals), 2)
        self.assertEqual(len(coverage), 2)

    def test_original_source_identity_is_required(self):
        raw = raw_source("公園《こうえん》。")
        with self.assertRaisesRegex(ValueError, "identity_differs"):
            extract_work(raw, "900000", "900001", "0" * 64)


if __name__ == "__main__":
    unittest.main()
