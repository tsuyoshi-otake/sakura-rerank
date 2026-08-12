from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.atomic_io as atomic_io
import sakura_rerank.data.exporter_requests as exporter_requests_module
from sakura_rerank.data.contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sentence_shingle_hashes,
    text_sha256,
)
from sakura_rerank.data.exporter_requests import (
    TierAError,
    ensure_paths_under_root,
    generate_exporter_request_shards,
    generate_exporter_requests,
    publish_exporter_request_shards,
    publish_exporter_requests,
    validate_exporter_requests,
    verify_builder_checkout,
)


BUILDER_SHA = "a" * 40


def source_span(stable_id: str = "case-001", surface: str = "gold") -> dict[str, object]:
    sentence = f"prefix-{surface}"
    return {
        "schema_version": 1,
        "record_type": "jawiki_tier_a_source_span",
        "stable_id": stable_id,
        "source": {
            "corpus": "jawiki",
            "snapshot_date": "2026-08-01",
            "article_id": "article-1",
            "page_id": "page-1",
            "revision_id": "revision-1",
            "paragraph_hash": text_sha256("paragraph"),
            "sentence_hash": text_sha256(sentence),
            "sentence_shingle_hashes": sentence_shingle_hashes(sentence),
            "template_cluster_id": None,
        },
        "committed_prefix": sentence,
        "gold_surface": surface,
    }


def dictionary(readings: list[str] | None = None) -> list[dict[str, object]]:
    return [
        {
            "schema_version": 1,
            "record_type": "system_dictionary_surface_index",
            "surface": "gold",
            "readings": readings or ["reading"],
        }
    ]


def normalized_dictionary_manifest(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "content_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
        "indexer_git_sha": "b" * 40,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
    }


def normalized_source_manifest(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "content_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
        "extractor_git_sha": "c" * 40,
        "jawiki_local_sha256": "d" * 64,
    }


class ExporterRequestTests(unittest.TestCase):
    def test_builder_checkout_requires_matching_clean_head(self) -> None:
        completed_head = type("Result", (), {"stdout": "1" * 40 + "\n"})()
        completed_clean = type("Result", (), {"stdout": ""})()
        with patch.object(
            exporter_requests_module.subprocess,
            "run",
            side_effect=[completed_head, completed_clean],
        ):
            verify_builder_checkout("1" * 40, Path("."))
        completed_dirty = type("Result", (), {"stdout": " M README.md\n"})()
        with patch.object(
            exporter_requests_module.subprocess,
            "run",
            side_effect=[completed_head, completed_dirty],
        ):
            with self.assertRaisesRegex(TierAError, "clean"):
                verify_builder_checkout("1" * 40, Path("."))
        with patch.object(
            exporter_requests_module.subprocess,
            "run",
            side_effect=[completed_head, completed_clean],
        ):
            with self.assertRaisesRegex(TierAError, "checkout HEAD"):
                verify_builder_checkout("2" * 40, Path("."))

    def generate(
        self,
        spans: list[dict[str, object]],
        index: list[dict[str, object]],
    ) -> tuple[list[dict[str, str]], dict[str, object]]:
        with (
            patch(
                "sakura_rerank.data.exporter_requests.validate_dictionary_index_manifest",
                return_value=normalized_dictionary_manifest(index),
            ),
            patch(
                "sakura_rerank.data.exporter_requests.validate_source_span_manifest",
                return_value=normalized_source_manifest(spans),
            ),
        ):
            return generate_exporter_requests(
                spans,
                index,
                jawiki_manifest={},
                dictionary_manifest={},
                source_span_manifest={},
                builder_git_sha=BUILDER_SHA,
            )

    def generate_shards(
        self,
        spans: list[dict[str, object]],
        index: list[dict[str, object]],
        *,
        shard_size: int,
    ) -> tuple[list[list[dict[str, str]]], dict[str, object]]:
        with (
            patch(
                "sakura_rerank.data.exporter_requests.validate_dictionary_index_manifest",
                return_value=normalized_dictionary_manifest(index),
            ),
            patch(
                "sakura_rerank.data.exporter_requests.validate_source_span_manifest",
                return_value=normalized_source_manifest(spans),
            ),
        ):
            return generate_exporter_request_shards(
                spans,
                index,
                jawiki_manifest={},
                dictionary_manifest={},
                source_span_manifest={},
                builder_git_sha=BUILDER_SHA,
                shard_size=shard_size,
            )

    def test_generates_exact_bounded_request_and_text_free_report(self) -> None:
        spans = [source_span()]
        index = dictionary()

        requests, report = self.generate(spans, index)

        self.assertEqual(requests, [{"stable_id": "case-001", "reading": "reading"}])
        self.assertEqual(
            report["content_sha256"], hashlib.sha256(canonical_jsonl_bytes(requests)).hexdigest()
        )
        self.assertEqual(report["record_count"], 1)
        self.assertFalse(report["raw_text_in_report"])
        report_text = canonical_json_bytes(report).decode("utf-8")
        self.assertNotIn("reading", report_text)
        self.assertNotIn("gold", report_text)
        self.assertNotIn("case-001", report_text)

    def test_generation_is_byte_deterministic(self) -> None:
        spans = [source_span()]
        index = dictionary()
        first = self.generate(copy.deepcopy(spans), copy.deepcopy(index))
        second = self.generate(copy.deepcopy(spans), copy.deepcopy(index))

        self.assertEqual(canonical_jsonl_bytes(first[0]), canonical_jsonl_bytes(second[0]))
        self.assertEqual(canonical_json_bytes(first[1]), canonical_json_bytes(second[1]))

    def test_missing_or_ambiguous_reading_fails_closed(self) -> None:
        with self.assertRaisesRegex(TierAError, "absent"):
            self.generate([source_span(surface="missing")], dictionary())
        with self.assertRaisesRegex(TierAError, "exactly one"):
            self.generate([source_span()], dictionary(["one", "two"]))
        with self.assertRaisesRegex(TierAError, "outside target bounds"):
            self.generate([source_span()], dictionary(["かな"]))

    def test_request_schema_rejects_short_readings(self) -> None:
        for reading in ("か", "かな"):
            with self.subTest(reading=reading), self.assertRaisesRegex(
                TierAError, "outside bounded contract"
            ):
                validate_exporter_requests(
                    [{"stable_id": "case-001", "reading": reading}]
                )

    def test_invalid_builder_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(TierAError, "Git SHA"):
            generate_exporter_requests(
                [source_span()],
                dictionary(),
                jawiki_manifest={},
                dictionary_manifest={},
                source_span_manifest={},
                builder_git_sha="latest",
            )

    def test_publication_rejects_schema_extension_and_malformed_request(self) -> None:
        requests, report = self.generate([source_span()], dictionary())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extended_report = dict(report)
            extended_report["raw_surface"] = "gold"
            with self.assertRaisesRegex(TierAError, "aggregate-only"):
                publish_exporter_requests(
                    root / "requests.jsonl", root / "report.json", requests, extended_report
                )
            malformed = [{"stable_id": "case-001", "reading": "reading\nleak"}]
            with self.assertRaisesRegex(TierAError, "bounded contract"):
                publish_exporter_requests(
                    root / "requests.jsonl", root / "report.json", malformed, report
                )
            self.assertFalse((root / "requests.jsonl").exists())
            self.assertFalse((root / "report.json").exists())

    def test_paths_must_remain_below_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_paths_under_root({"inside": root / "new.jsonl"}, root)
            with self.assertRaisesRegex(TierAError, "below allowed_root"):
                ensure_paths_under_root({"outside": root.parent / "outside.jsonl"}, root)

    def test_second_replace_failure_restores_existing_pair(self) -> None:
        requests, report = self.generate([source_span()], dictionary())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "requests.jsonl"
            report_path = root / "report.json"
            output.write_bytes(b"old-output\n")
            report_path.write_bytes(b"old-report\n")
            real_replace = atomic_io.os.replace
            calls = 0

            def fail_second(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected")
                real_replace(source, destination)

            with patch("sakura_rerank.atomic_io.os.replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_exporter_requests(output, report_path, requests, report)

            self.assertEqual(output.read_bytes(), b"old-output\n")
            self.assertEqual(report_path.read_bytes(), b"old-report\n")
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith((".tmp", ".bak"))], []
            )

    def test_request_shards_are_globally_sorted_bounded_and_deterministic(self) -> None:
        spans = [
            source_span("case-001", "gold"),
            source_span("case-002", "silver"),
            source_span("case-003", "bronze"),
        ]
        index = [
            {
                "schema_version": 1,
                "record_type": "system_dictionary_surface_index",
                "surface": surface,
                "readings": [f"reading-{surface}"],
            }
            for surface in ("bronze", "gold", "silver")
        ]
        shards, manifest = self.generate_shards(spans, index, shard_size=2)

        self.assertEqual([len(shard) for shard in shards], [2, 1])
        self.assertEqual(manifest["record_count"], 3)
        self.assertEqual(manifest["shard_count"], 2)
        self.assertFalse(manifest["raw_text_in_manifest"])
        self.assertNotIn("reading-gold", canonical_json_bytes(manifest).decode("utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first_hashes = publish_exporter_request_shards(first, shards, manifest)
            second_hashes = publish_exporter_request_shards(second, shards, manifest)
            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(
                sorted(path.name for path in first.iterdir()),
                ["manifest.json", "requests-00000.jsonl", "requests-00001.jsonl"],
            )
            for name in ("manifest.json", "requests-00000.jsonl", "requests-00001.jsonl"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_request_shard_publication_rejects_existing_destination(self) -> None:
        shards, manifest = self.generate_shards([source_span()], dictionary(), shard_size=1)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing"
            destination.mkdir()
            marker = destination / "marker"
            marker.write_bytes(b"keep")
            with self.assertRaisesRegex(TierAError, "already exists"):
                publish_exporter_request_shards(destination, shards, manifest)
            self.assertEqual(marker.read_bytes(), b"keep")

    def test_request_shard_manifest_rejects_unknown_fields(self) -> None:
        shards, manifest = self.generate_shards([source_span()], dictionary(), shard_size=1)
        manifest["raw_reading"] = "must not enter aggregate metadata"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TierAError, "aggregate-only"):
                publish_exporter_request_shards(Path(directory) / "output", shards, manifest)

    def test_request_shard_replace_failure_removes_staging_directory(self) -> None:
        shards, manifest = self.generate_shards([source_span()], dictionary(), shard_size=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "output"
            with patch.object(exporter_requests_module.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_exporter_request_shards(destination, shards, manifest)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
