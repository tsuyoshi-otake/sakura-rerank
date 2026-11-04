from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
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


def revision_fixture(root):
    docs, rows = [], []
    (root / "source").mkdir()
    for index in range(50):
        doc = f"w201106-{index:010d}"
        raw = document([token("漢字", "かんじ")]).replace(DOC.encode(), doc.encode())
        if index == 0:
            raw = raw.replace((doc + "-1").encode(), (doc + "-1-01").encode())
        (root / "source" / (doc + ".knp")).write_bytes(raw)
        docs.append(dict(document_id=doc, git_blob_sha1=probe.blob_sha1(raw), bytes=len(raw)))
        row = probe.extract_target(doc, raw)
        if index == 0:
            row = dict(kind=row["kind"], document_id=doc, source_sha256=row["source_sha256"],
                       status="parse_failure", failure_code="foreign_or_reordered_sentence")
        rows.append(row)
    manifest = dict(plan_sha256=probe.PLAN_SHA256, corpus_commit=probe.COMMIT, index_base=0,
                    selected_documents=docs, selection_sha256=probe.canonical_json_hash(docs))
    selection = probe.canonical_json_bytes(manifest) + b"\n"
    targets = b"".join(probe.canonical_json_bytes(row) + b"\n" for row in rows)
    requests = [dict(stable_id=row["stable_id"], reading=row["reading"]) for row in rows[1:]]
    request_bytes = b"".join(probe.canonical_json_bytes(row) + b"\n"
                             for row in sorted(requests, key=lambda row: row["stable_id"]))
    initial = probe.canonical_json_bytes(dict(targets_sha256=hashlib.sha256(targets).hexdigest(),
        requests_sha256=hashlib.sha256(request_bytes).hexdigest(), selected_documents=50)) + b"\n"
    for name, raw in (("selection.json", selection), ("targets.jsonl", targets),
                      ("requests.jsonl", request_bytes), ("extraction.json", initial)):
        (root / name).write_bytes(raw)
    return dict(expected_selection_sha256=hashlib.sha256(selection).hexdigest(),
                expected_initial_extraction_sha256=hashlib.sha256(initial).hexdigest())


class KwdlcProbeTests(unittest.TestCase):
    def test_revision_preserves_successes_and_initial_artifacts_and_is_reproducible(self):
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                pins = revision_fixture(root)
                old = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
                result = probe.reextract_split_units(root, **pins)
                self.assertEqual(result["counts"], {"ready_for_forward_check": 50})
                self.assertEqual(result["previous_successes_preserved"], 49)
                self.assertFalse(result["forward_executed"])
                self.assertEqual(result["additional_source_requests"], 0)
                self.assertEqual({name: (root / name).read_bytes() for name in old}, old)
                outputs.append([(root / name).read_bytes() for name in
                                ("targets-r2.jsonl", "requests-r2.jsonl", "extraction-r2.json")])
                with self.assertRaises(FileExistsError):
                    probe.reextract_split_units(root, **pins)
        self.assertEqual(outputs[0], outputs[1])

    def test_revision_rejects_modified_provenance_or_prior_artifacts(self):
        for name in ("selection.json", "extraction.json", "targets.jsonl", "requests.jsonl",
                     "source/w201106-0000000000.knp"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                pins = revision_fixture(root)
                with (root / name).open("ab") as stream:
                    stream.write(b" ")
                with self.assertRaises(probe.ProbeError):
                    probe.reextract_split_units(root, **pins)
                self.assertFalse((root / "extraction-r2.json").exists())

    def test_revision_refuses_changed_success_even_when_prior_hashes_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pins = revision_fixture(root)
            rows = [json.loads(line) for line in (root / "targets.jsonl").read_bytes().splitlines()]
            rows[1]["left_context"] = "changed"
            targets = b"".join(probe.canonical_json_bytes(row) + b"\n" for row in rows)
            (root / "targets.jsonl").write_bytes(targets)
            report = json.loads((root / "extraction.json").read_bytes())
            report["targets_sha256"] = hashlib.sha256(targets).hexdigest()
            initial = probe.canonical_json_bytes(report) + b"\n"
            (root / "extraction.json").write_bytes(initial)
            pins["expected_initial_extraction_sha256"] = hashlib.sha256(initial).hexdigest()
            with self.assertRaisesRegex(probe.ProbeError, "previously extracted target changed"):
                probe.reextract_split_units(root, **pins)
            self.assertFalse((root / "extraction-r2.json").exists())

    def test_split_sentence_units_keep_indices_and_reset_context(self):
        raw = document([token("まえ", "まえ")], [token("漢字", "かんじ")])
        raw = raw.replace((DOC + "-1").encode(), (DOC + "-1-01").encode())
        part = f"# S-ID:{DOC}-1-02\n{token('かな', 'かな')}\nEOS\n".encode()
        raw = raw.replace((f"# S-ID:{DOC}-2").encode(), part + (f"# S-ID:{DOC}-2").encode())
        row = probe.extract_target(DOC, raw)
        self.assertEqual(row["sentence_index"], 2)
        self.assertEqual(row["left_context"], "")
        self.assertEqual(row["surface"], "漢字")
        # A target at the start of part 02 must not inherit part 01 context.
        raw = raw.replace(token('かな', 'かな').encode(), token('漢字', 'かんじ').encode(), 1)
        raw = raw.replace((f"# S-ID:{DOC}-2\n* -1D\n+ -1D\n" + token('漢字', 'かんじ')).encode(),
                          (f"# S-ID:{DOC}-2\n" + token('かな', 'かな')).encode())
        row = probe.extract_target(DOC, raw)
        self.assertEqual(row["sentence_index"], 1)
        self.assertEqual(row["left_context"], "")

    def test_split_ids_cannot_skip_duplicate_mix_or_reorder(self):
        for suffixes in (("1-02", "2", "3"), ("1-01", "1-01", "2", "3"),
                         ("1", "1-01", "2", "3"), ("1-01", "1-03", "2", "3"),
                         ("2", "1", "3"), ("1", "3"), ("1-1", "2", "3"),
                         ("1-00", "2", "3"), ("1-100", "2", "3")):
            raw = "".join(f"# S-ID:{DOC}-{suffix}\n{token('漢字', 'かんじ')}\nEOS\n"
                          for suffix in suffixes).encode()
            with self.subTest(suffixes=suffixes), self.assertRaises(probe.ProbeError):
                probe.extract_target(DOC, raw)

    def test_append_only_artifact_write_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            probe.write_once(path, b"initial\n")
            with self.assertRaises(FileExistsError):
                probe.write_once(path, b"replacement\n")
            self.assertEqual(path.read_bytes(), b"initial\n")

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
