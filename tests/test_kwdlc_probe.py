from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from sakura_rerank.data import kwdlc_probe as probe

DOC = "w201106-0000000001"


def token(surface, reading):
    return f"{surface} {reading} {surface} 名詞 6 普通名詞 1 * 0 * 0"


def document(first, second=None, third=None):
    parts = [first, second or [token("かな", "かな")], third or [token("かな", "かな")]]
    return "\n".join(
        f"# S-ID:{DOC}-{i+1}\n* -1D\n+ -1D\n" + "\n".join(lines) + "\nEOS"
        for i, lines in enumerate(parts)
    ).encode("utf-8") + b"\n"


class KwdlcProbeTests(unittest.TestCase):
    def test_source_identity_covers_utf8_and_every_byte(self):
        raw = "独立した読み\n".encode()
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.assertEqual(probe.authenticate_blob(raw.decode(), expected, len(raw)), raw)
        for value in (raw.decode().rstrip(), raw.decode() + " "):
            with self.assertRaises(probe.ProbeError):
                probe.authenticate_blob(value, expected)

    def test_context_is_prior_only_bounded_and_resets_at_sentence(self):
        raw = document([token("あ" * 80, "あ"), token("漢字", "かんじ"), token("あと", "あと")])
        selected = probe.extract_target(DOC, raw)
        self.assertEqual(selected["left_context"], "あ" * 64)
        self.assertEqual(selected["surface"], "漢字")
        self.assertEqual(selected["reading"], "かんじ")
        self.assertEqual(selected["status"], "ready_for_forward_check")
        raw = document([token("まえ", "まえ")], [token("漢字", "かんじ")])
        self.assertEqual(probe.extract_target(DOC, raw)["left_context"], "")

    def test_source_spelling_is_not_normalized(self):
        row = probe.extract_target(DOC, document([token("Ａ漢字", "かんじ")]))
        self.assertEqual(row["surface"], "Ａ漢字")

    def test_one_character_reading_is_exporter_eligible_but_not_tier_a_certified(self):
        row = probe.extract_target(DOC, document([token("蚊", "か")]))
        self.assertEqual(row["status"], "ready_for_forward_check")
        self.assertEqual(row["kind"], "kwdlc_development_target_not_gold")

    def test_special_reading_and_alternative_are_retained_without_guessing(self):
        row = probe.extract_target(DOC, document([token("漢字", "かんじ/かんぢ")]))
        self.assertEqual(row["status"], "special_reading_annotation")
        row = probe.extract_target(DOC, document([token("漢字", "かんじ"), "@ " + token("漢字", "かんぢ")]))
        self.assertEqual(row["status"], "alternative_annotation")
        self.assertEqual(row["reading"], "かんじ")

    def test_no_target_is_explicit(self):
        row = probe.extract_target(DOC, document([token("かな", "かな")]))
        self.assertEqual(row["status"], "no_target")
        self.assertEqual(row["eligible_ideograph_targets"], 0)

    def test_choice_does_not_filter_by_reading_or_length(self):
        initial = probe.extract_target(DOC, document([token("漢字", "かんじ"), token("日本", "にほん")]))
        selected_index = initial["morpheme_index"]
        parts = [token("漢字", "かんじ"), token("日本", "にほん")]
        parts[selected_index] = token(initial["surface"], "あ" * 129)
        changed = probe.extract_target(DOC, document(parts))
        self.assertEqual(changed["stable_id"], initial["stable_id"])
        self.assertEqual(changed["status"], "length_outside_contract")

    def test_malformed_or_foreign_sentence_is_not_partially_accepted(self):
        original = document([token("漢字", "かんじ")])
        for raw in (original[:-4], original.replace((DOC + "-2").encode(), (DOC + "-9").encode()),
                    original.replace(b"EOS", b"", 1), original.replace(b" 6 ", b" wrong ", 1),
                    original + b"unexpected\n"):
            with self.subTest(raw=hashlib.sha256(raw).hexdigest()), self.assertRaises(probe.ProbeError):
                probe.extract_target(DOC, raw)

    def test_orphan_alternative_and_resource_bounds_fail_closed(self):
        with self.assertRaises(probe.ProbeError):
            probe.extract_target(DOC, document(["@ " + token("漢字", "かんじ")]))
        with self.assertRaises(probe.ProbeError):
            probe.extract_target(DOC, b"x" * (probe.MAX_FILE_BYTES + 1))

    def test_document_selection_uses_train_membership_and_is_order_invariant(self):
        ids = [f"w201106-{i:010d}" for i in range(3915)]
        raw = ("\n".join(ids) + "\n").encode()
        tree = {"commit": probe.COMMIT, "tree": probe.TREE, "files": [
            {"path": f"knp/w201106-00000/{doc}.knp", "mode": "100644", "size": 100, "sha": "a" * 40}
            for doc in ids
        ]}
        with patch.object(probe, "TRAIN_BLOB", probe.blob_sha1(raw)):
            selected = probe.select_documents(raw, tree)
            self.assertEqual(len(selected), 50)
            self.assertEqual(probe.select_documents(raw, dict(tree, files=list(reversed(tree["files"])))), selected)
            expected = sorted(ids, key=lambda doc: hashlib.sha256(
                json.dumps([20261104, doc], separators=(",", ":")).encode()).hexdigest())[:50]
            self.assertEqual([r["document_id"] for r in selected], expected)
            selected_path = selected[0]["path"]
            broken = [row for row in tree["files"] if row["path"] != selected_path]
            with self.assertRaises(probe.ProbeError):
                probe.select_documents(raw, dict(tree, files=broken))
        with self.assertRaises(probe.ProbeError):
            probe.select_documents(raw, tree)


if __name__ == "__main__":
    unittest.main()
