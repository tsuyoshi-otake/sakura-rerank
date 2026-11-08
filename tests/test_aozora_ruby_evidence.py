"""Synthetic original annotations exercise evidence scope, not Gold quality."""
from collections import Counter
import hashlib
import unittest

from sakura_rerank.data.aozora_ruby_evidence import parse_line, paragraphs_with_ruby, recover_rows, ruby_state
from sakura_rerank.data.growth_corpus import GrowthExtractor, aozora_paragraphs


def source(body):
    return ("合成題名\n" + "-" * 20 + "\n記号説明\n" + "-" * 20 + "\n" + body + "\n底本：合成資料\n").encode("cp932")


def extracted(body, surface="公園", reading="こうえん"):
    raw = source(body)
    paragraphs, _ = aozora_paragraphs(raw)
    extractor = GrowthExtractor([dict(surface=surface, readings=[reading])])
    rows = extractor.document(paragraphs, "aozora", "900000", hashlib.sha256(raw).hexdigest(), "train", 128, Counter())
    if not rows:
        raise AssertionError("synthetic target was not extracted")
    return raw, rows


class AozoraRubyEvidenceTests(unittest.TestCase):
    def test_explicit_mixed_base_retains_exact_scope(self):
        text, spans, _ = parse_line("ここで｜試験Ａ《しけんえー》を扱う。")
        self.assertEqual(text, "ここで試験Ａを扱う。")
        self.assertEqual((spans[0]["start"], spans[0]["end"], spans[0]["kind"]), (3, 6, "explicit"))

    def test_adjacent_ruby_does_not_absorb_previous_base(self):
        text, spans, _ = parse_line("公園《こうえん》管理《かんり》")
        self.assertEqual(text, "公園管理")
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(0, 2), (2, 4)])

    def test_documented_special_character_is_within_implicit_base(self):
        _, spans, _ = parse_line("試々《しし》")
        self.assertEqual((spans[0]["start"], spans[0]["end"]), (0, 2))

    def test_unsupported_implicit_base_stays_unresolved(self):
        text, spans, flags = parse_line("ABC《えーびーしー》")
        self.assertEqual(text, "ABC")
        self.assertEqual(spans[0]["kind"], "unresolved_base")
        self.assertEqual(ruby_state(dict(spans=spans, flags=flags), 0, 3, "えーびーしー")[0], "ruby_parse_unresolved")

    def test_katakana_comparison_preserves_annotation(self):
        text, spans, flags = parse_line("公園《コウエン》")
        self.assertEqual(ruby_state(dict(spans=spans, flags=flags), 0, len(text), "こうえん")[0], "exact_ruby_reading_match")
        self.assertEqual(spans[0]["reading"], "コウエン")

    def test_old_kana_and_vowel_differences_are_not_repaired(self):
        for observed in ("こうゑん", "こーえん"):
            text, spans, flags = parse_line("公園《" + observed + "》")
            self.assertEqual(ruby_state(dict(spans=spans, flags=flags), 0, len(text), "こうえん")[0], "exact_ruby_reading_disagreement")

    def test_nonphonetic_and_editorial_ruby_are_not_reading_proof(self):
        for observed in ("park", "ママ", "", "あ" * 33):
            text, spans, flags = parse_line("公園《" + observed + "》")
            self.assertEqual(ruby_state(dict(spans=spans, flags=flags), 0, len(text), "こうえん")[0], "exact_ruby_nonphonetic_or_out_of_bounds")

    def test_partial_base_cannot_supply_a_partial_reading(self):
        _, spans, flags = parse_line("都市公園《としこうえん》")
        self.assertEqual(ruby_state(dict(spans=spans, flags=flags), 2, 4, "こうえん")[0], "ruby_scope_differs")

    def test_unbalanced_and_nested_notation_fails_closed(self):
        for line in ("公園《こうえん", "公園《こう《えん》》", "公園》《"):
            with self.assertRaisesRegex(ValueError, "not_supported"):
                parse_line(line)

    def test_frozen_cleaner_parity_and_annotation_line_exclusion(self):
        raw = source("公園《こうえん》。\n※［＃外字］の行。\n普通の文。")
        paragraphs, report = paragraphs_with_ruby(raw)
        self.assertEqual([p["text"] for p in paragraphs], aozora_paragraphs(raw)[0])
        self.assertEqual(report["paragraphs"], 2)

    def test_original_extractor_ids_context_and_positions_recover(self):
        raw, rows = extracted("ここには合成の前文がある。公園《こうえん》へ行く。公園《こうえん》は広い。")
        proof, _ = recover_rows(raw, rows)
        self.assertEqual(len(proof), 2)
        self.assertEqual({p["state"] for p in proof}, {"exact_ruby_reading_match"})
        self.assertEqual(proof, recover_rows(raw, rows[::-1])[0])
        self.assertEqual({p["stable_id"] for p in proof}, {r["stable_id"] for r in rows})

    def test_no_ruby_is_missing_evidence_not_a_match(self):
        raw, rows = extracted("ここには合成の前文がある。公園へ行く。")
        proof, _ = recover_rows(raw, rows)
        self.assertEqual(proof[0]["state"], "no_ruby_overlap")

    def test_context_reading_conflict_does_not_relabel_source(self):
        raw, rows = extracted("ここには合成の前文がある。公園《こうえん》へ行く。", reading="おおやけその")
        proof, _ = recover_rows(raw, rows)
        self.assertEqual(proof[0]["state"], "exact_ruby_reading_disagreement")
        self.assertEqual(rows[0]["reading"], "おおやけその")

    def test_changed_source_revision_and_evaluation_rows_rejected(self):
        raw, rows = extracted("ここには合成の前文がある。公園《こうえん》へ行く。")
        with self.assertRaisesRegex(ValueError, "provenance_differs"):
            recover_rows(raw + b"\n", rows)
        rows[0]["population"] = "evaluation"
        with self.assertRaisesRegex(ValueError, "provenance_differs"):
            recover_rows(raw, rows)

    def test_missing_span_is_an_observable_terminal(self):
        raw, rows = extracted("ここには合成の前文がある。公園《こうえん》へ行く。")
        rows[0]["stable_id"] = "growth-" + "0" * 64
        self.assertEqual(recover_rows(raw, rows)[0][0]["state"], "span_not_recovered")


if __name__ == "__main__":
    unittest.main()
