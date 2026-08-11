from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.atomic_io as atomic_io
from sakura_rerank.data.contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    canonical_json_bytes,
)
from sakura_rerank.data.dictionary_index import (
    DictionaryIndexError,
    build_dictionary_index,
    publish_dictionary_index,
)


def _write_inputs(root: Path) -> tuple[Path, Path, str]:
    categories = root / "categories"
    categories.mkdir()
    first = categories / "01.tsv"
    second = categories / "02.tsv"
    first.write_text("reading\tsurface\nかな\t仮名\nかめい\t仮名\n", encoding="utf-8")
    second.write_text("reading\tsurface\nかな\t仮名\nさくら\t桜\n", encoding="utf-8")
    files = []
    for path, count in ((first, 2), (second, 2)):
        payload = path.read_bytes()
        files.append(
            {
                "path": path.name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "entry_count": count,
            }
        )
    audit = {
        "schema_version": "sakura-rerank.current-state-audit.v1",
        "sakura_input": {"head": PINNED_SAKURA_INPUT_HEAD},
        "dictionary": {
            "compiled": {"sha256": PINNED_DICTIONARY_SHA256},
            "categories": {"files": files, "entry_count": 4},
        },
        "checks": {
            "category_entry_count_matches_compiled_header": True,
            "category_files_match_checked_report": True,
            "dictionary_matches_checked_report": True,
        },
        "all_artifact_checks_passed": True,
    }
    audit_path = root / "audit.json"
    audit_payload = canonical_json_bytes(audit) + b"\n"
    audit_path.write_bytes(audit_payload)
    return categories, audit_path, hashlib.sha256(audit_payload).hexdigest()


class DictionaryIndexBuilderTests(unittest.TestCase):
    def test_builds_complete_sorted_index_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            categories, audit, audit_sha = _write_inputs(Path(directory))
            first, first_manifest = build_dictionary_index(
                categories,
                audit,
                indexer_git_sha="1" * 40,
                expected_audit_sha256=audit_sha,
            )
            second, second_manifest = build_dictionary_index(
                categories,
                audit,
                indexer_git_sha="1" * 40,
                expected_audit_sha256=audit_sha,
            )
            self.assertEqual(first, second)
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(
                [(record["surface"], record["readings"]) for record in first],
                [("仮名", ["かな", "かめい"]), ("桜", ["さくら"])],
            )
            self.assertEqual(first_manifest["source_entry_count"], 4)
            self.assertEqual(first_manifest["verification_status"], "measured")

    def test_changed_category_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories, audit, audit_sha = _write_inputs(root)
            (categories / "01.tsv").write_text(
                "reading\tsurface\nかな\t改変\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(DictionaryIndexError, "byte size mismatch|SHA-256 mismatch"):
                build_dictionary_index(
                    categories,
                    audit,
                    indexer_git_sha="1" * 40,
                    expected_audit_sha256=audit_sha,
                )

    def test_changed_audit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories, audit, audit_sha = _write_inputs(root)
            audit.write_bytes(audit.read_bytes() + b" ")
            with self.assertRaisesRegex(DictionaryIndexError, "pinned SHA-256"):
                build_dictionary_index(
                    categories,
                    audit,
                    indexer_git_sha="1" * 40,
                    expected_audit_sha256=audit_sha,
                )

    def test_publication_binds_manifest_to_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories, audit, audit_sha = _write_inputs(root)
            records, manifest = build_dictionary_index(
                categories,
                audit,
                indexer_git_sha="1" * 40,
                expected_audit_sha256=audit_sha,
            )
            output = root / "index.jsonl"
            report = root / "index-manifest.json"
            output_hash, _ = publish_dictionary_index(
                output, report, records, manifest
            )
            self.assertEqual(output_hash, manifest["content_sha256"])
            self.assertEqual(json.loads(report.read_text()), manifest)

    def test_failed_second_replace_restores_existing_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories, audit, audit_sha = _write_inputs(root)
            records, manifest = build_dictionary_index(
                categories,
                audit,
                indexer_git_sha="1" * 40,
                expected_audit_sha256=audit_sha,
            )
            output = root / "index.jsonl"
            report = root / "index-manifest.json"
            output.write_bytes(b"existing index")
            report.write_bytes(b"existing manifest")
            real_replace = atomic_io.os.replace
            calls = 0

            def fail_second(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected second replace failure")
                real_replace(source, destination)

            with patch.object(atomic_io.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_dictionary_index(output, report, records, manifest)
            self.assertEqual(output.read_bytes(), b"existing index")
            self.assertEqual(report.read_bytes(), b"existing manifest")
            self.assertEqual(
                [path for path in root.iterdir() if path.suffix in {".tmp", ".bak"}],
                [],
            )


if __name__ == "__main__":
    unittest.main()
