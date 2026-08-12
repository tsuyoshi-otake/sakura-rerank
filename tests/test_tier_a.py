from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.atomic_io as atomic_io
from sakura_rerank.data.__main__ import main
from sakura_rerank.data.contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    _candidate_snapshot_hash,
    candidate_fingerprint,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sentence_shingle_hashes,
    text_sha256,
)
from sakura_rerank.data.tier_a import (
    TierABlockedError,
    TierAError,
    generate_tier_a_records,
    publish_tier_a_artifacts,
    validate_dictionary_index,
    validate_dictionary_index_manifest,
)


TRUSTED_GIT_SHA = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
TRUSTED_BINARY_SHA = "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"


def _candidate(
    surface: str,
    reading: str,
    rank: int,
    *,
    category: str = "system_dictionary",
) -> dict[str, object]:
    cost = 100 + rank
    return {
        "rank": rank,
        "surface": surface,
        "local_cost": cost,
        "source_category": category,
        "fingerprint": candidate_fingerprint(surface, cost),
        "system_entry_index": rank if category == "system_dictionary" else None,
        "segments": [
            {
                "reading_start": 0,
                "reading_end": len(reading.encode("utf-8")),
                "text_start": 0,
                "text_end": len(surface.encode("utf-8")),
                "left_id": 1,
                "right_id": 2,
                "flags": 0,
                "source_category": category,
            }
        ],
    }


def exporter_record(*, gold_category: str = "system_dictionary") -> dict[str, object]:
    reading = "かなもじ"
    provenance = {
        "kind": "sakura_input_converter_export",
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "feature_contract_version": 1,
    }
    candidates = [
        _candidate("カナ", reading, 0, category=gold_category),
        _candidate("仮名", reading, 1),
    ]
    top32 = {
        "limit": 32,
        "source": "sakura_converter_full_reading_nbest",
        "feature_contract_version": 1,
        "reading": reading,
        "candidates": copy.deepcopy(candidates),
        "exporter_run": {
            "contract_version": 1,
            "verification_status": "verified",
            "exporter_git_sha": TRUSTED_GIT_SHA,
            "exporter_binary_sha256": TRUSTED_BINARY_SHA,
            "requested_limit": 32,
            "effective_converter_bound": 32,
            "returned_count": 2,
            "result_status": "search_exhausted",
        },
    }
    top32["content_sha256"] = _candidate_snapshot_hash(top32, provenance)
    top6 = {
        "limit": 6,
        "source": "sakura_converter_full_reading_nbest",
        "feature_contract_version": 1,
        "reading": reading,
        "candidates": copy.deepcopy(candidates),
    }
    top6["content_sha256"] = _candidate_snapshot_hash(top6, provenance)
    return {
        "schema_version": 3,
        "record_type": "research_converter_snapshot",
        "stable_id": "case-001",
        "reading": reading,
        "converter_provenance": provenance,
        "candidate_snapshots": {"training_top32": top32, "production_top6": top6},
    }


def source_span() -> dict[str, object]:
    sentence = "前の文脈カナ"
    return {
        "schema_version": 1,
        "record_type": "jawiki_tier_a_source_span",
        "stable_id": "case-001",
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
        "gold_surface": "カナ",
    }


def dictionary_index(readings: list[str] | None = None) -> list[dict[str, object]]:
    return [
        {
            "schema_version": 1,
            "record_type": "system_dictionary_surface_index",
            "surface": "カナ",
            "readings": readings or ["かなもじ"],
        }
    ]


def dictionary_manifest(index: list[dict[str, object]]) -> dict[str, object]:
    normalized = validate_dictionary_index(index)
    return {
        "schema_version": 2,
        "manifest_kind": "system_dictionary_surface_index",
        "verification_status": "measured",
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "indexer_git_sha": "1" * 40,
        "normalization": "exact_unicode_v1",
        "user_dictionary_enabled": False,
        "record_count": len(index),
        "content_sha256": hashlib.sha256(canonical_jsonl_bytes(normalized)).hexdigest(),
        "source_audit_sha256": "4" * 64,
        "category_sources_sha256": "5" * 64,
        "category_file_count": 1,
        "source_entry_count": len(index),
    }


def jawiki_manifest() -> dict[str, object]:
    return {
        "status": "preprocessing_verified",
        "snapshot_date": "2026-08-01",
        "local_sha256": "2" * 64,
        "preprocessing_git_sha": "3" * 40,
    }


def source_span_manifest() -> dict[str, object]:
    return {"verification_status": "verified"}


def generate(
    spans: list[dict[str, object]],
    index: list[dict[str, object]],
    exports: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    manifest = dictionary_manifest(index)
    normalized_manifest = validate_dictionary_index_manifest(
        manifest, validate_dictionary_index(index), require_verified=False
    )
    with (
        patch(
            "sakura_rerank.data.tier_a.validate_dictionary_index_manifest",
            return_value=normalized_manifest,
        ),
        patch(
            "sakura_rerank.data.tier_a.validate_source_span_manifest",
            return_value={
                "extractor_git_sha": "3" * 40,
                "manifest_kind": "jawiki_tier_a_source_spans",
            },
        ),
    ):
        return generate_tier_a_records(
            spans,
            index,
            exports,
            jawiki_manifest=jawiki_manifest(),
            dictionary_manifest=manifest,
            source_span_manifest=source_span_manifest(),
        )


class TierAGeneratorTests(unittest.TestCase):
    def test_generates_contract_v3_tier_a_deterministically(self) -> None:
        first, first_report = generate(
            [source_span()], dictionary_index(), [exporter_record()]
        )
        second, second_report = generate(
            [source_span()], dictionary_index(), [exporter_record()]
        )

        self.assertEqual(canonical_jsonl_bytes(first), canonical_jsonl_bytes(second))
        self.assertEqual(canonical_json_bytes(first_report), canonical_json_bytes(second_report))
        self.assertEqual(first[0]["tier"], "A")
        self.assertTrue(first[0]["training_eligible"])
        self.assertEqual(first[0]["session"]["left_context"], "前の文脈")
        self.assertEqual(first_report["rejection_counts"], {})

    def test_ambiguous_dictionary_reading_blocks_empty_output(self) -> None:
        with self.assertRaisesRegex(TierABlockedError, "no source span") as raised:
            generate(
                [source_span()], dictionary_index(["かな", "カナ"]), [exporter_record()]
            )
        self.assertEqual(
            raised.exception.report["details"]["rejection_counts"],
            {"dictionary_reading_ambiguous": 1},
        )

    def test_short_dictionary_reading_blocks_empty_output(self) -> None:
        with self.assertRaisesRegex(TierABlockedError, "no source span") as raised:
            generate([source_span()], dictionary_index(["かな"]), [exporter_record()])
        self.assertEqual(
            raised.exception.report["details"]["rejection_counts"],
            {"reading_outside_target_bounds": 1},
        )

    def test_fallback_gold_path_blocks_empty_output(self) -> None:
        record = exporter_record(gold_category="reading_fallback")
        with self.assertRaisesRegex(TierABlockedError, "no source span"):
            generate([source_span()], dictionary_index(), [record])

    def test_unverified_exporter_is_rejected(self) -> None:
        record = exporter_record()
        record["candidate_snapshots"]["training_top32"]["exporter_run"][
            "verification_status"
        ] = "unverified"
        provenance = record["converter_provenance"]
        top32 = record["candidate_snapshots"]["training_top32"]
        top32["content_sha256"] = _candidate_snapshot_hash(top32, provenance)
        with self.assertRaisesRegex(TierAError, "allowlisted identity"):
            generate([source_span()], dictionary_index(), [record])

    def test_dictionary_manifest_binds_exact_content(self) -> None:
        index = dictionary_index()
        manifest = dictionary_manifest(index)
        validate_dictionary_index_manifest(
            manifest, validate_dictionary_index(index), require_verified=False
        )
        manifest["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(TierAError, "does not match index"):
            validate_dictionary_index_manifest(
                manifest, validate_dictionary_index(index), require_verified=False
            )

    def test_measured_dictionary_manifest_is_blocked_by_default(self) -> None:
        index = dictionary_index()
        with self.assertRaisesRegex(TierABlockedError, "allowlisted verified"):
            validate_dictionary_index_manifest(
                dictionary_manifest(index), validate_dictionary_index(index)
            )

    def test_fake_verified_dictionary_identity_is_rejected(self) -> None:
        index = dictionary_index()
        manifest = dictionary_manifest(index)
        manifest["verification_status"] = "verified"
        with self.assertRaisesRegex(TierAError, "outside the allowlist"):
            validate_dictionary_index_manifest(
                manifest, validate_dictionary_index(index), require_verified=False
            )

    def test_verified_dictionary_identity_rejects_changed_metadata(self) -> None:
        index = dictionary_index()
        manifest = dictionary_manifest(index)
        manifest["verification_status"] = "verified"
        identity = (manifest["indexer_git_sha"], manifest["content_sha256"])
        trusted_metadata = {
            "source_audit_sha256": manifest["source_audit_sha256"],
            "category_sources_sha256": "6" * 64,
            "category_file_count": manifest["category_file_count"],
            "source_entry_count": manifest["source_entry_count"],
            "record_count": manifest["record_count"],
        }
        with (
            patch(
                "sakura_rerank.data.tier_a.VERIFIED_DICTIONARY_INDEX_IDENTITIES",
                frozenset({identity}),
            ),
            patch(
                "sakura_rerank.data.tier_a.VERIFIED_DICTIONARY_INDEX_METADATA",
                {identity: trusted_metadata},
            ),
            self.assertRaisesRegex(TierAError, "metadata does not match identity"),
        ):
            validate_dictionary_index_manifest(
                manifest, validate_dictionary_index(index), require_verified=False
            )

    def test_pair_publication_is_byte_identical(self) -> None:
        records, report = generate(
            [source_span()], dictionary_index(), [exporter_record()]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_output = root / "first.jsonl"
            first_report = root / "first-report.json"
            second_output = root / "second.jsonl"
            second_report = root / "second-report.json"
            publish_tier_a_artifacts(first_output, first_report, records, report)
            publish_tier_a_artifacts(second_output, second_report, records, report)
            self.assertEqual(first_output.read_bytes(), second_output.read_bytes())
            self.assertEqual(first_report.read_bytes(), second_report.read_bytes())

    def test_second_replace_failure_restores_existing_pair(self) -> None:
        records, generated_report = generate(
            [source_span()], dictionary_index(), [exporter_record()]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output.jsonl"
            report = root / "report.json"
            output.write_bytes(b"existing output")
            report.write_bytes(b"existing report")
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
                    publish_tier_a_artifacts(output, report, records, generated_report)
            self.assertEqual(output.read_bytes(), b"existing output")
            self.assertEqual(report.read_bytes(), b"existing report")
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith((".tmp", ".bak"))],
                [],
            )

    def test_cli_official_only_manifest_returns_structured_blocker_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output.jsonl"
            report = root / "report.json"
            output.write_bytes(b"output sentinel")
            report.write_bytes(b"report sentinel")
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                status = main(
                    [
                        "tier-a",
                        str(root / "source.jsonl"),
                        str(root / "export.jsonl"),
                        str(output),
                        "--dictionary-index",
                        str(root / "dictionary.jsonl"),
                        "--dictionary-manifest",
                        str(root / "dictionary-manifest.json"),
                        "--exporter-manifest",
                        str(root / "exporter-manifest.json"),
                        "--jawiki-manifest",
                        "manifests/jawiki-20260801-pages-articles-multistream.json",
                        "--source-span-manifest",
                        str(root / "source-manifest.json"),
                        "--allowed-root",
                        str(root),
                        "--report",
                        str(report),
                    ]
                )
            blocker = json.loads(stdout.getvalue())
            self.assertEqual(status, 3)
            self.assertEqual(blocker["status"], "blocked")
            self.assertEqual(output.read_bytes(), b"output sentinel")
            self.assertEqual(report.read_bytes(), b"report sentinel")


if __name__ == "__main__":
    unittest.main()
