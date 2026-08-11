from __future__ import annotations

import bz2
import hashlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.atomic_io as atomic_io
from sakura_rerank.data.contracts import canonical_jsonl_bytes
from sakura_rerank.data.jawiki_preprocess import (
    ExtractorConfig,
    PreprocessingError,
    SurfaceMatcher,
    clean_wikitext,
    extract_source_spans,
    iter_source_spans,
)
from sakura_rerank.data.tier_a import (
    TierABlockedError,
    TierAError,
    validate_source_span_manifest,
)


EXTRACTOR_SHA = "1" * 40
DUMP_SHA = "2" * 64
INDEX_SHA = "3" * 64


def dictionary_records() -> list[dict[str, object]]:
    return [
        {
            "schema_version": 1,
            "record_type": "system_dictionary_surface_index",
            "surface": "Alpha",
            "readings": ["あるふぁ"],
        },
        {
            "schema_version": 1,
            "record_type": "system_dictionary_surface_index",
            "surface": "Alphabet",
            "readings": ["あるふぁべっと"],
        },
    ]


def dictionary_manifest() -> dict[str, object]:
    return {"content_sha256": INDEX_SHA}


def jawiki_manifest() -> dict[str, object]:
    return {
        "status": "local_artifact_verified",
        "snapshot_date": "2026-08-01",
        "local_sha256": DUMP_SHA,
    }


def xml_fixture() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page><title>A</title><ns>0</ns><id>10</id>
    <revision><id>20</id><text>Before Alpha. Alphabet is longer.</text></revision>
  </page>
  <page><title>Redirect</title><ns>0</ns><id>11</id><redirect title="A" />
    <revision><id>21</id><text>Alpha.</text></revision>
  </page>
  <page><title>Talk</title><ns>1</ns><id>12</id>
    <revision><id>22</id><text>Alpha.</text></revision>
  </page>
</mediawiki>"""


def config() -> ExtractorConfig:
    return ExtractorConfig(
        sample_modulus=1,
        sample_slots=1,
        max_records=100,
        max_records_per_page=10,
    )


class CleanerAndMatcherTests(unittest.TestCase):
    def test_cleaner_removes_supported_markup_and_rejects_ambiguous_markup(self) -> None:
        paragraphs, counts = clean_wikitext(
            "Before {{drop}} [[Target|Alpha]]<ref>citation</ref>。\n\n"
            "[https://example.test label] remains。"
        )
        self.assertEqual(paragraphs, ["Before Alpha。", "label remains。"])
        self.assertEqual(counts, {})
        self.assertEqual(clean_wikitext("Before {{unclosed"), ([], Counter({"unbalanced_template": 1})))

    def test_matcher_uses_longest_non_overlapping_exact_surface(self) -> None:
        matcher = SurfaceMatcher(dictionary_records(), config())
        self.assertEqual(
            list(matcher.matches("Alphabet Alpha")),
            [(0, 8, "Alphabet"), (9, 14, "Alpha")],
        )


class StreamingExtractionTests(unittest.TestCase):
    def test_iterparse_is_deterministic_and_filters_namespace_and_redirect(self) -> None:
        first_counts: Counter[str] = Counter()
        second_counts: Counter[str] = Counter()
        matcher = SurfaceMatcher(dictionary_records(), config())
        first = list(iter_source_spans(io.BytesIO(xml_fixture()), matcher, config(), first_counts))
        second = list(iter_source_spans(io.BytesIO(xml_fixture()), matcher, config(), second_counts))
        self.assertEqual(canonical_jsonl_bytes(first), canonical_jsonl_bytes(second))
        self.assertEqual([record["gold_surface"] for record in first], ["Alpha", "Alphabet"])
        self.assertEqual(first_counts, second_counts)
        self.assertEqual(first_counts["pages_total"], 3)
        self.assertEqual(first_counts["pages_redirect"], 1)
        self.assertEqual(first_counts["pages_non_main"], 1)

    def test_publication_is_byte_identical_and_report_contains_no_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "fixture.xml.bz2"
            dump.write_bytes(bz2.compress(xml_fixture()))
            normalized_dictionary_manifest = {"content_sha256": INDEX_SHA}
            with patch(
                "sakura_rerank.data.jawiki_preprocess.validate_dictionary_index_manifest",
                return_value=normalized_dictionary_manifest,
            ):
                results = []
                for prefix in ("first", "second"):
                    output = root / f"{prefix}.jsonl"
                    report = root / f"{prefix}-report.json"
                    results.append(
                        extract_source_spans(
                            dump,
                            output,
                            report,
                            jawiki_manifest=jawiki_manifest(),
                            dictionary_records=dictionary_records(),
                            dictionary_manifest=dictionary_manifest(),
                            extractor_git_sha=EXTRACTOR_SHA,
                            config=config(),
                        )
                    )
            self.assertEqual(results[0], results[1])
            self.assertEqual((root / "first.jsonl").read_bytes(), (root / "second.jsonl").read_bytes())
            first_report = json.loads((root / "first-report.json").read_text(encoding="utf-8"))
            self.assertIs(first_report["raw_text_in_report"], False)
            self.assertNotIn("Before", (root / "first-report.json").read_text(encoding="utf-8"))

    def test_second_replace_failure_restores_existing_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "fixture.xml.bz2"
            dump.write_bytes(bz2.compress(xml_fixture()))
            output = root / "output.jsonl"
            report = root / "report.json"
            output.write_bytes(b"old output")
            report.write_bytes(b"old report")
            real_replace = atomic_io.os.replace
            calls = 0

            def fail_second(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected")
                real_replace(source, destination)

            with (
                patch(
                    "sakura_rerank.data.jawiki_preprocess.validate_dictionary_index_manifest",
                    return_value={"content_sha256": INDEX_SHA},
                ),
                patch.object(atomic_io.os, "replace", side_effect=fail_second),
                self.assertRaisesRegex(OSError, "injected"),
            ):
                extract_source_spans(
                    dump,
                    output,
                    report,
                    jawiki_manifest=jawiki_manifest(),
                    dictionary_records=dictionary_records(),
                    dictionary_manifest=dictionary_manifest(),
                    extractor_git_sha=EXTRACTOR_SHA,
                    config=config(),
                )
            self.assertEqual(output.read_bytes(), b"old output")
            self.assertEqual(report.read_bytes(), b"old report")
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith((".tmp", ".bak"))],
                [],
            )


class SourceSpanManifestTests(unittest.TestCase):
    def measured_manifest(self, records: list[dict[str, object]]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "manifest_kind": "jawiki_tier_a_source_spans",
            "verification_status": "measured",
            "snapshot_date": "2026-08-01",
            "jawiki_local_sha256": DUMP_SHA,
            "dictionary_index_sha256": INDEX_SHA,
            "extractor_git_sha": EXTRACTOR_SHA,
            "cleaner_version": "conservative_wikitext_v1",
            "config": {
                "sample_modulus": 1,
                "sample_slots": 1,
                "max_records": 100,
                "max_records_per_page": 10,
                "max_output_bytes": 251658240,
                "min_sentence_chars": 4,
                "max_sentence_chars": 512,
                "min_surface_chars": 1,
                "max_surface_chars": 64,
            },
            "eligible_dictionary_surface_count": 2,
            "record_count": len(records),
            "content_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
            "counts": {"pages_total": 1},
            "raw_text_in_report": False,
        }

    def records(self) -> list[dict[str, object]]:
        counts: Counter[str] = Counter()
        return list(
            iter_source_spans(
                io.BytesIO(xml_fixture()),
                SurfaceMatcher(dictionary_records(), config()),
                config(),
                counts,
            )
        )

    def test_measured_manifest_validates_but_is_blocked_by_default(self) -> None:
        records = self.records()
        manifest = self.measured_manifest(records)
        validate_source_span_manifest(
            manifest,
            records,
            jawiki_manifest=jawiki_manifest(),
            dictionary_manifest=dictionary_manifest(),
            require_verified=False,
        )
        with self.assertRaisesRegex(TierABlockedError, "allowlisted verified"):
            validate_source_span_manifest(
                manifest,
                records,
                jawiki_manifest=jawiki_manifest(),
                dictionary_manifest=dictionary_manifest(),
            )

    def test_content_or_metadata_tampering_is_rejected(self) -> None:
        records = self.records()
        manifest = self.measured_manifest(records)
        manifest["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(TierAError, "does not match source spans"):
            validate_source_span_manifest(
                manifest,
                records,
                jawiki_manifest=jawiki_manifest(),
                dictionary_manifest=dictionary_manifest(),
                require_verified=False,
            )

    def test_verified_identity_pins_every_non_identity_field(self) -> None:
        records = self.records()
        manifest = self.measured_manifest(records)
        normalized = validate_source_span_manifest(
            manifest,
            records,
            jawiki_manifest=jawiki_manifest(),
            dictionary_manifest=dictionary_manifest(),
            require_verified=False,
        )
        identity = (normalized["extractor_git_sha"], normalized["content_sha256"])
        trusted_metadata = {
            field: value
            for field, value in normalized.items()
            if field not in {"verification_status", "extractor_git_sha", "content_sha256"}
        }
        manifest["verification_status"] = "verified"
        with (
            patch(
                "sakura_rerank.data.tier_a.VERIFIED_SOURCE_SPAN_IDENTITIES",
                frozenset({identity}),
            ),
            patch(
                "sakura_rerank.data.tier_a.VERIFIED_SOURCE_SPAN_METADATA",
                {identity: trusted_metadata},
            ),
        ):
            validate_source_span_manifest(
                manifest,
                records,
                jawiki_manifest=jawiki_manifest(),
                dictionary_manifest=dictionary_manifest(),
            )
            manifest["counts"]["pages_total"] = 2
            with self.assertRaisesRegex(TierAError, "metadata does not match identity"):
                validate_source_span_manifest(
                    manifest,
                    records,
                    jawiki_manifest=jawiki_manifest(),
                    dictionary_manifest=dictionary_manifest(),
                )


if __name__ == "__main__":
    unittest.main()
