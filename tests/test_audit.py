from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.audit import (
    AuditError,
    collect_category_statistics,
    collect_corpus_statistics,
    parse_dictionary_header,
    write_json_atomic,
)


class DictionaryHeaderTests(unittest.TestCase):
    def test_parses_exact_compiled_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "system.dic"
            size = 40
            header = struct.pack(
                "<8sHHHHIIII",
                b"SKRADIC\0",
                1,
                32,
                9,
                12,
                3,
                7,
                size,
                0,
            )
            path.write_bytes(header + b"\0" * (size - len(header)))

            self.assertEqual(
                parse_dictionary_header(path),
                {
                    "format_version": 1,
                    "header_bytes": 32,
                    "table_count": 9,
                    "class_count": 12,
                    "entry_count": 3,
                    "node_count": 7,
                    "image_bytes": size,
                },
            )

    def test_rejects_length_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "system.dic"
            path.write_bytes(
                struct.pack("<8sHHHHIIII", b"SKRADIC\0", 1, 32, 1, 1, 1, 1, 99, 0)
            )
            with self.assertRaisesRegex(AuditError, "length mismatch"):
                parse_dictionary_header(path)


class CategoryStatisticsTests(unittest.TestCase):
    def test_counts_entries_and_unique_identity_across_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = "reading\tsurface\tleft_id\tright_id\tword_cost\tprediction_cost\tflags\tannotation\n"
            (root / "01.tsv").write_text(
                header + "かな\t仮名\t1\t1\t10\t-\t\t\nかな\tかな\t1\t1\t20\t-\t\t\n",
                encoding="utf-8",
            )
            (root / "02.tsv").write_text(
                header + "かな\t仮名\t2\t2\t30\t-\t\t\nさくら\t桜\t2\t2\t40\t-\t\t\n",
                encoding="utf-8",
            )

            result = collect_category_statistics(root)

            self.assertEqual(result["category_count"], 2)
            self.assertEqual(result["entry_count"], 4)
            self.assertEqual(result["unique_reading_count"], 2)
            self.assertEqual(result["unique_surface_count"], 3)
            self.assertEqual(result["unique_reading_surface_pair_count"], 3)
            self.assertEqual([record["entry_count"] for record in result["files"]], [2, 2])


class CorpusStatisticsTests(unittest.TestCase):
    def test_counts_slices_without_exposing_row_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "held-out.tsv"
            path.write_text(
                "# frozen\nid\tslice\treading\texpected\n"
                "a\tgeneral\tかな\t仮名\n"
                "b\tit\tじゅうもじいじょう\t十文字以上\n",
                encoding="utf-8",
            )

            result = collect_corpus_statistics(path)

            self.assertEqual(result["row_count"], 2)
            self.assertEqual(result["slice_counts"], {"general": 1, "it": 1})
            self.assertEqual(result["reading_at_least_10_count"], 0)
            self.assertNotIn("かな", json.dumps(result, ensure_ascii=False))


class AtomicOutputTests(unittest.TestCase):
    def test_replaces_json_and_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("old", encoding="utf-8")

            write_json_atomic(path, {"ok": True})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
