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
    VERIFIED_RESEARCH_EXPORTER_IDENTITIES,
    VERIFIED_RESEARCH_EXPORTER_TRUSTED_METADATA,
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

VERIFIED_EXPORTER_IDENTITY = (
    "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1",
    "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf",
)
COMMIT_C_IDENTITY = (
    "835c5fcf5f02193474353650ea7b5566a7bb5cb4",
    "9b59b08e56446f8462f82cb97dbcf090e7b511e7a39c0a9fa7a07541f7cafbd9",
)
COMMIT_A_IDENTITY = (
    "e6242eecb33e7872954229d7faafef2950a11740",
    "a720f01d763b7129c5a64afdd7e0ac291c7c0efeac63503a0c37ffacddb9a4fd",
)


def _candidate() -> dict[str, object]:
    surface = "kana"
    reading = "kana"
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
        "reading": "kana",
        "candidates": copy.deepcopy(candidates),
        "exporter_run": exporter_run,
    }
    top32["content_sha256"] = _snapshot_hash(top32, provenance)
    top6 = {
        "limit": 6,
        "source": "sakura_converter_full_reading_nbest",
        "feature_contract_version": 1,
        "reading": "kana",
        "candidates": copy.deepcopy(candidates),
    }
    top6["content_sha256"] = _snapshot_hash(top6, provenance)
    return {
        "schema_version": 3,
        "record_type": "research_converter_snapshot",
        "stable_id": "case-001",
        "reading": "kana",
        "converter_provenance": provenance,
        "candidate_snapshots": {
            "training_top32": top32,
            "production_top6": top6,
        },
    }


def _manifest(
    *,
    status: str = "unverified",
    sakura_input_head: str = PINNED_SAKURA_INPUT_HEAD,
    exporter_git_sha: str = "0" * 40,
    exporter_binary_sha256: str = "1" * 64,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "manifest_kind": "research_top32_exporter",
        "verification_status": status,
        "exporter_git_sha": exporter_git_sha,
        "exporter_binary_sha256": exporter_binary_sha256,
        "sakura_input_head": sakura_input_head,
        "dictionary_sha256": PINNED_DICTIONARY_SHA256,
        "instrumentation_patch_sha256": "2" * 64,
        "cargo_lock_sha256": "3" * 64,
        "rustc_version": "rustc 1.96.0",
        "cargo_version": "cargo 1.96.0",
        "target_triple": "x86_64-pc-windows-msvc",
        "profile": "release",
        "build_flags": ["--remap-path-prefix=<WORKSPACE>=/sakura-input", "-C", "link-arg=/Brepro"],
        "build_environment": {
            "CARGO_BUILD_TARGET": "x86_64-pc-windows-msvc",
            "CARGO_INCREMENTAL": "0",
            "CARGO_NET_OFFLINE": "true",
            "RUSTUP_TOOLCHAIN": "1.96.0-x86_64-pc-windows-msvc",
            "SOURCE_DATE_EPOCH": "0",
        },
        "requested_limit": 32,
        "effective_converter_bound": 32,
        "user_dictionary_enabled": False,
    }


class ResearchExporterContractTests(unittest.TestCase):
    def test_commit_f_pins_only_the_measured_commit_e_identity(self) -> None:
        manifest_path = (
            Path(__file__).parents[1] / "manifests" / "research-exporter-verified.json"
        )
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        normalized = validate_exporter_manifest(manifest)
        self.assertEqual(normalized, manifest)
        self.assertEqual(
            VERIFIED_RESEARCH_EXPORTER_IDENTITIES,
            frozenset({VERIFIED_EXPORTER_IDENTITY}),
        )
        self.assertEqual(
            set(VERIFIED_RESEARCH_EXPORTER_TRUSTED_METADATA), {VERIFIED_EXPORTER_IDENTITY}
        )
        trusted_metadata = {
            key: value
            for key, value in normalized.items()
            if key not in {"exporter_git_sha", "exporter_binary_sha256", "verification_status"}
        }
        self.assertEqual(
            VERIFIED_RESEARCH_EXPORTER_TRUSTED_METADATA[VERIFIED_EXPORTER_IDENTITY],
            trusted_metadata,
        )
        self.assertNotIn(COMMIT_C_IDENTITY, VERIFIED_RESEARCH_EXPORTER_IDENTITIES)
        self.assertNotIn(COMMIT_A_IDENTITY, VERIFIED_RESEARCH_EXPORTER_IDENTITIES)

    def test_old_and_fake_identities_are_rejected(self) -> None:
        for identity in (COMMIT_C_IDENTITY, COMMIT_A_IDENTITY, ("f" * 40, "e" * 64)):
            with self.subTest(identity=identity):
                manifest = _manifest(
                    status="verified",
                    exporter_git_sha=identity[0],
                    exporter_binary_sha256=identity[1],
                )
                with self.assertRaisesRegex(ContractError, "outside the allowlist"):
                    validate_exporter_manifest(manifest)

    def test_every_trusted_metadata_field_is_fail_closed(self) -> None:
        manifest_path = (
            Path(__file__).parents[1] / "manifests" / "research-exporter-verified.json"
        )
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata_fields = set(
            VERIFIED_RESEARCH_EXPORTER_TRUSTED_METADATA[VERIFIED_EXPORTER_IDENTITY]
        )
        self.assertEqual(
            metadata_fields,
            set(original) - {"exporter_git_sha", "exporter_binary_sha256", "verification_status"},
        )
        for field in sorted(metadata_fields):
            with self.subTest(field=field):
                tampered = copy.deepcopy(original)
                value = tampered[field]
                if isinstance(value, bool):
                    tampered[field] = not value
                elif isinstance(value, int):
                    tampered[field] = value + 1
                elif isinstance(value, list):
                    tampered[field] = [*value, "tampered"]
                elif isinstance(value, dict):
                    tampered[field] = {**value, "TAMPERED": "1"}
                else:
                    tampered[field] = "tampered"
                with self.assertRaises(ContractError):
                    validate_exporter_manifest(tampered)

    def test_unverified_export_is_valid_only_in_explicit_measurement_mode(self) -> None:
        record = _record()
        self.assertEqual(
            validate_export_records([record], require_verified=False)[0]["stable_id"],
            "case-001",
        )
        with self.assertRaisesRegex(ContractError, "allowlisted identity"):
            validate_export_records([record])

    def test_manifest_schema_and_pins_are_fail_closed(self) -> None:
        manifest = _manifest()
        self.assertEqual(
            validate_exporter_manifest(manifest, require_verified=False)["requested_limit"],
            32,
        )
        with self.assertRaisesRegex(ContractError, "verified identity"):
            validate_exporter_manifest(_manifest(status="verified"))
        with self.assertRaisesRegex(ContractError, "wrong pinned HEAD"):
            validate_exporter_manifest(
                _manifest(sakura_input_head="f" * 40), require_verified=False
            )
        old_schema = _manifest()
        old_schema["schema_version"] = 1
        with self.assertRaisesRegex(ContractError, "unsupported schema"):
            validate_exporter_manifest(old_schema, require_verified=False)

    def test_manifest_identity_must_match_exporter_run(self) -> None:
        manifest = _manifest()
        record = _record()
        record["candidate_snapshots"]["training_top32"]["exporter_run"][
            "exporter_git_sha"
        ] = "4" * 40
        record["candidate_snapshots"]["training_top32"]["content_sha256"] = _snapshot_hash(
            record["candidate_snapshots"]["training_top32"], record["converter_provenance"]
        )
        with self.assertRaisesRegex(ContractError, "differs from the manifest"):
            validate_export_records([record], require_verified=False, manifest=manifest)

    def test_top6_must_be_an_exact_top32_prefix(self) -> None:
        record = _record()
        replacement = copy.deepcopy(
            record["candidate_snapshots"]["production_top6"]["candidates"][0]
        )
        replacement["surface"] = "other"
        replacement["fingerprint"] = candidate_fingerprint(
            "other", replacement["local_cost"]
        )
        replacement["segments"][0]["text_end"] = len("other".encode("utf-8"))
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
            manifest_path.write_text(
                json.dumps(_manifest()) + "\n", encoding="utf-8"
            )
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
