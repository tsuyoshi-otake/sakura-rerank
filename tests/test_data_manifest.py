from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.manifest import (
    ManifestBlockedError,
    ManifestError,
    load_manifest_document,
    sha256_file,
    validate_manifest,
    validate_manifest_document,
    validate_blocked_report,
)


def manifest_for(root: Path, payload: bytes = b"fixed snapshot fixture") -> dict[str, object]:
    file_name = "jawiki-20260801-pages-articles.xml.bz2"
    local_path = root / "data" / "downloads" / file_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema_version": 1,
        "manifest_kind": "jawiki_snapshot",
        "status": "verified",
        "snapshot_date": "2026-08-01",
        "file_name": file_name,
        "official_url": (
            "https://dumps.wikimedia.org/jawiki/20260801/" + file_name
        ),
        "byte_size": len(payload),
        "official_sha256": digest,
        "local_path": "data/downloads/" + file_name,
        "local_sha256": digest,
        "retrieved_at": "2026-08-11T00:00:00Z",
        "license": "fixture-license-reference",
        "extractor": {"name": "fixture-extractor", "version": "1.0.0"},
        "preprocessing_git_sha": "a" * 40,
    }


class ManifestValidatorTests(unittest.TestCase):
    def test_accepts_complete_manifest_and_checks_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = manifest_for(root)

            validated = validate_manifest(manifest, root)

            self.assertEqual(validated["local_sha256"], sha256_file(root / manifest["local_path"]))

    def test_rejects_latest_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = manifest_for(root)
            manifest["official_url"] = manifest["official_url"].replace(
                "20260801", "latest"
            )

            with self.assertRaisesRegex(ManifestError, "latest"):
                validate_manifest(manifest, root)

    def test_rejects_missing_provenance_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_license = manifest_for(root)
            del missing_license["license"]
            with self.assertRaises(ManifestError):
                validate_manifest(missing_license, root)

            missing_extractor_version = manifest_for(root)
            missing_extractor_version["extractor"] = {"name": "fixture-extractor"}
            with self.assertRaises(ManifestError):
                validate_manifest(missing_extractor_version, root)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = manifest_for(root)
            manifest["local_sha256"] = "b" * 64

            with self.assertRaisesRegex(ManifestError, "local_sha256"):
                validate_manifest(manifest, root)

    def test_rejects_path_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = manifest_for(root)
            manifest["local_path"] = "../jawiki-20260801-pages-articles.xml.bz2"

            with self.assertRaisesRegex(ManifestError, "local_path"):
                validate_manifest(manifest, root)


class BlockedMetadataTests(unittest.TestCase):
    def test_blocked_report_is_structured_but_not_verified(self) -> None:
        path = Path(__file__).parent / "fixtures" / "jawiki-manifest.blocked.json"
        document = load_manifest_document(path)
        self.assertEqual(validate_blocked_report(document)["status"], "blocked")
        with self.assertRaises(ManifestBlockedError) as context:
            validate_manifest_document(document, path.parent)
        self.assertEqual(context.exception.fields, ("official_url",))
