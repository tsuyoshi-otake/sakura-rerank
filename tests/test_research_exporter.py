from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.contracts import (
    PINNED_DICTIONARY_SHA256,
    PINNED_SAKURA_INPUT_HEAD,
    ContractError,
    _candidate_snapshot_hash,
    candidate_fingerprint,
    canonical_jsonl_bytes,
)
from sakura_rerank.data.research_exporter import (
    validate_export_file,
    validate_export_records,
    validate_exporter_manifest,
)


def _candidate() -> dict[str, object]:
    surface = "かな"
    reading = "かな"
    local_cost = 123
    byte_length = len(surface.encode("utf-8"))
    return {
        "rank": 0,
        "surface": surface,
        "local_cost": local_cost,
        "source_category": "system_dictionary",
        "fingerprint": candidate_fingerprint(surface, local_cost),
        "system_entry_index": 7,
        "segments": [
            {
                "reading_start": 0,
                "reading_end": len(reading.encode("utf-8")),
                "text_start": 0,
                "text_end": byte_length,
                "left_id": 1,
                "right_id": 2,
                "flags": 0,
                "source_category": "system_dictionary",
            }
        ],
    }


def _provenance() -> dict[str, object]:
    return {
        "kind": "sakura_input_converter_export",
        "sakura_input_head": PINNED_SAKURA_INPUT_HEAD,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "feature_contract_version": 1,
    }


def _snapshot_hash(snapshot: dict[str, object], provenance: dict[str, object]) -> str:
    return _candidate_snapshot_hash(snapshot, provenance)


def _record() -> dict[str, object]:
    provenance = _provenance()
    candidates = [_candidate()]
    exporter_run = {
        "contract_version": 1,
        "verification_status": "unverified",
        "exporter_git_sha": "0" * 40,
        "exporter_binary_sha256": "1" * 64,
        "requested_limit": 32,
        "effective_converter_bound": 32,
        "returned_count": 1,
        "result_status": "search_exhausted",
    }
    top32 = {
        "limit": 32,
        "source": "sakura_converter_full_reading_nbest",
        "feature_contract_version": 1,
        "reading": "かな",
        "candidates": copy.deepcopy(candidates),
        "exporter_run": exporter_run,
    }
    top32["content_sha256"] = _snapshot_hash(top32, provenance)
    top6 = {
        "limit": 6,
        "source": "sakura_converter_full_reading_nbest",
        "feature_contract_version": 1,
        "reading": "かな",
        "candidates": copy.deepcopy(candidates),
    }
    top6["content_sha256"] = _snapshot_hash(top6, provenance)
    return {
        "schema_version": 3,
        "record_type": "research_converter_snapshot",
        "stable_id": "case-001",
        "reading": "かな",
        "converter_provenance": provenance,
        "candidate_snapshots": {
            "training_top32": top32,
            "production_top6": top6,
        },
    }


def _manifest(*, status: str = "unverified", sakura_input_head: str = PINNED_SAKURA_INPUT_HEAD) -> dict[str, object]:
    return {
        "schema_version": 1,
        "manifest_kind": "research_top32_exporter",
        "verification_status": status,
        "exporter_git_sha": "0" * 40,
        "exporter_binary_sha256": "1" * 64,
        "sakura_input_head": sakura_input_head,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "instrumentation_patch_sha256": "2" * 64,
        "cargo_lock_sha256": "3" * 64,
        "rustc_version": "rustc 1.96.0",
        "cargo_version": "cargo 1.96.0",
        "target_triple": "x86_64-pc-windows-msvc",
        "profile": "release",
        "requested_limit": 32,
        "effective_converter_bound": 32,
        "user_dictionary_enabled": False,
    }


class ResearchExporterContractTests(unittest.TestCase):
    def test_unverified_export_is_valid_only_in_explicit_measurement_mode(self) -> None:
        record = _record()
        self.assertEqual(validate_export_records([record], require_verified=False)[0]["stable_id"], "case-001")
        with self.assertRaisesRegex(ContractError, "allowlisted identity"):
            validate_export_records([record])

    def test_manifest_requires_exact_pins_and_verified_allowlist(self) -> None:
        manifest = _manifest()
        self.assertEqual(
            validate_exporter_manifest(manifest, require_verified=False)["requested_limit"],
            32,
        )
        with self.assertRaisesRegex(ContractError, "verified identity"):
            validate_exporter_manifest(_manifest(status="verified"))
        with self.assertRaisesRegex(ContractError, "wrong pinned HEAD"):
            validate_exporter_manifest(_manifest(sakura_input_head="f" * 40), require_verified=False)

    def test_manifest_identity_must_match_exporter_run(self) -> None:
        manifest = _manifest()
        record = _record()
        record["candidate_snapshots"]["training_top32"]["exporter_run"]["exporter_git_sha"] = "4" * 40
        record["candidate_snapshots"]["training_top32"]["content_sha256"] = _snapshot_hash(
            record["candidate_snapshots"]["training_top32"], record["converter_provenance"]
        )
        with self.assertRaisesRegex(ContractError, "differs from the manifest"):
            validate_export_records(
                [record], require_verified=False, manifest=manifest
            )

    def test_top6_must_be_an_exact_top32_prefix(self) -> None:
        record = _record()
        replacement = copy.deepcopy(record["candidate_snapshots"]["production_top6"]["candidates"][0])
        replacement["surface"] = "別名"
        replacement["fingerprint"] = candidate_fingerprint("別名", replacement["local_cost"])
        record["candidate_snapshots"]["production_top6"]["candidates"] = [replacement]
        record["candidate_snapshots"]["production_top6"]["content_sha256"] = _snapshot_hash(
            record["candidate_snapshots"]["production_top6"], record["converter_provenance"]
        )
        with self.assertRaisesRegex(ContractError, "not a top-32 prefix"):
            validate_export_records([record], require_verified=False)

    def test_file_validation_uses_canonical_jsonl_hash(self) -> None:
        record = _record()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_path = root / "export.jsonl"
            manifest_path = root / "manifest.json"
            export_path.write_bytes(canonical_jsonl_bytes([record]))
            manifest_path.write_text(json.dumps(_manifest()) + "\n", encoding="utf-8")
            records, content_sha256 = validate_export_file(
                export_path,
                manifest_path=manifest_path,
                require_verified=False,
            )
            self.assertEqual(records, [record])
            self.assertEqual(
                content_sha256,
                hashlib.sha256(export_path.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
