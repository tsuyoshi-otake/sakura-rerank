from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.manifest import (
    ManifestBlockedError,
    ManifestError,
    _verify_local_artifact,
    hash_file_many,
    load_manifest_document,
    validate_blocked_report,
    validate_manifest,
    validate_manifest_document,
)


REPOSITORY_ROOT = Path(__file__).parents[1]
CONFIRMED_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "manifests"
    / "jawiki-20260801-pages-articles-multistream.json"
)


def confirmed_manifest() -> dict[str, object]:
    return load_manifest_document(CONFIRMED_MANIFEST_PATH)


def local_stage_for(
    root: Path,
    payload: bytes = b"local digest verifier fixture",
) -> tuple[dict[str, object], Path]:
    manifest = confirmed_manifest()
    file_name = "jawiki-20260801-pages-articles-multistream.xml.bz2"
    local_path = root / "data" / "downloads" / file_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(payload)
    manifest.update(
        {
            "status": "local_artifact_verified",
            "local_path": "data/downloads/" + file_name,
            "local_sha256": hashlib.sha256(payload).hexdigest(),
            "retrieved_at": "2026-08-11T05:30:00Z",
        }
    )
    return manifest, local_path


class ManifestValidatorTests(unittest.TestCase):
    def test_multi_digest_hashes_one_payload_consistently(self) -> None:
        payload = b"one pass digest fixture"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(payload)
            measured = hash_file_many(path, ("md5", "sha1", "sha256"), chunk_size=3)
        self.assertEqual(measured["md5"], hashlib.md5(payload).hexdigest())
        self.assertEqual(measured["sha1"], hashlib.sha1(payload).hexdigest())
        self.assertEqual(measured["sha256"], hashlib.sha256(payload).hexdigest())

    def test_committed_20260801_metadata_is_verified_without_downloading_dump(self) -> None:
        validated = validate_manifest_document(
            load_manifest_document(CONFIRMED_MANIFEST_PATH), REPOSITORY_ROOT
        )

        self.assertEqual(validated["status"], "official_metadata_verified")
        self.assertEqual(validated["byte_size"], 4_827_732_824)
        self.assertEqual(validated["official_md5"], "b51bab6d1cc23efddc4363e78b5526c6")
        self.assertEqual(
            validated["official_sha1"], "6c917b51d6f6b53a34eaebcb2a675c0769054343"
        )
        self.assertIsNone(validated["local_path"])
        self.assertIsNone(validated["local_sha256"])

    def test_schema_pins_match_the_committed_official_metadata(self) -> None:
        manifest = confirmed_manifest()
        schema = load_manifest_document(
            REPOSITORY_ROOT / "manifests" / "jawiki-snapshot.schema.json"
        )
        for field in (
            "snapshot_date",
            "file_name",
            "official_url",
            "byte_size",
            "official_md5",
            "official_sha1",
        ):
            with self.subTest(field=field):
                self.assertEqual(schema["properties"][field]["const"], manifest[field])
        for field in ("dump_status_url", "md5_url", "sha1_url"):
            with self.subTest(field=f"metadata_sources.{field}"):
                self.assertEqual(
                    schema["properties"]["metadata_sources"]["properties"][field][
                        "const"
                    ],
                    manifest["metadata_sources"][field],
                )

    def test_local_digest_verifier_checks_all_three_distinct_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"local digest verifier fixture"
            path = root / "artifact.bin"
            path.write_bytes(payload)
            digests = {
                "official_md5": hashlib.md5(payload).hexdigest(),
                "official_sha1": hashlib.sha1(payload).hexdigest(),
                "local_sha256": hashlib.sha256(payload).hexdigest(),
            }

            _verify_local_artifact(path, byte_size=len(payload), **digests)
            for field in digests:
                with self.subTest(field=field):
                    mutated = dict(digests)
                    mutated[field] = "b" * len(mutated[field])
                    with self.assertRaisesRegex(ManifestError, field):
                        _verify_local_artifact(
                            path,
                            byte_size=len(payload),
                            **mutated,
                        )

    def test_small_fixture_cannot_claim_the_pinned_local_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = local_stage_for(root)

            with self.assertRaisesRegex(ManifestError, "byte_size"):
                validate_manifest(manifest, root)

    def test_rejects_unconfirmed_official_checksums(self) -> None:
        for field, value in (
            ("official_md5", "b" * 32),
            ("official_sha1", "b" * 40),
        ):
            with self.subTest(field=field):
                manifest = confirmed_manifest()
                manifest[field] = value
                with self.assertRaisesRegex(ManifestError, field):
                    validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_unconfirmed_official_size(self) -> None:
        manifest = confirmed_manifest()
        manifest["byte_size"] += 1
        with self.assertRaisesRegex(ManifestError, "byte_size"):
            validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_noncanonical_official_metadata_source_urls(self) -> None:
        for field in ("dump_status_url", "md5_url", "sha1_url"):
            with self.subTest(field=field):
                manifest = confirmed_manifest()
                metadata_sources = manifest["metadata_sources"]
                self.assertIsInstance(metadata_sources, dict)
                metadata_sources[field] = metadata_sources[field].replace(
                    "dumps.wikimedia.org", "DUMPS.WIKIMEDIA.ORG"
                )
                with self.assertRaisesRegex(
                    ManifestError, f"metadata_sources.{field}"
                ):
                    validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_unconfirmed_snapshot_date(self) -> None:
        manifest = confirmed_manifest()
        manifest["snapshot_date"] = "2026-07-01"
        manifest["file_name"] = (
            "jawiki-20260701-pages-articles-multistream.xml.bz2"
        )
        manifest["official_url"] = (
            "https://dumps.wikimedia.org/jawiki/20260701/"
            "jawiki-20260701-pages-articles-multistream.xml.bz2"
        )
        with self.assertRaisesRegex(ManifestError, "snapshot_date"):
            validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_latest_as_substring_and_after_url_decode(self) -> None:
        deeply_encoded_latest = "".join(f"%{ord(character):02x}" for character in "latest")
        for _ in range(12):
            deeply_encoded_latest = deeply_encoded_latest.replace("%", "%25")
        mutations = {
            "file substring": lambda manifest: manifest.__setitem__(
                "file_name",
                "jawiki-20260801-pages-articles-multistream-latest.xml.bz2",
            ),
            "url substring": lambda manifest: manifest.__setitem__(
                "official_url", manifest["official_url"].replace("/20260801/", "/prelatest20260801/")
            ),
            "url encoded": lambda manifest: manifest.__setitem__(
                "official_url",
                manifest["official_url"].replace(
                    "/20260801/", "/20260801/%6c%61%74%65%73%74/"
                ),
            ),
            "double encoded": lambda manifest: manifest.__setitem__(
                "official_url",
                manifest["official_url"].replace(
                    "/20260801/", "/20260801/%256c%2561%2574%2565%2573%2574/"
                ),
            ),
            "deeply encoded": lambda manifest: manifest.__setitem__(
                "official_url",
                manifest["official_url"].replace(
                    "/20260801/", f"/20260801/{deeply_encoded_latest}/"
                ),
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                manifest = confirmed_manifest()
                mutate(manifest)
                with self.assertRaisesRegex(ManifestError, "latest"):
                    validate_manifest(manifest, REPOSITORY_ROOT)

    def test_requires_snapshot_url_filename_and_artifact_to_agree(self) -> None:
        mutations = {
            "snapshot/file date": lambda manifest: manifest.__setitem__(
                "snapshot_date", "2026-07-01"
            ),
            "url directory date": lambda manifest: manifest.__setitem__(
                "official_url", manifest["official_url"].replace("/20260801/", "/20260701/")
            ),
            "multistream index": lambda manifest: manifest.__setitem__(
                "file_name",
                "jawiki-20260801-pages-articles-multistream-index.txt.bz2",
            ),
            "artifact kind": lambda manifest: manifest.__setitem__(
                "artifact_kind",
                "pages_articles_xml_bz2",
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                manifest = confirmed_manifest()
                mutate(manifest)
                with self.assertRaises(ManifestError):
                    validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_missing_provenance(self) -> None:
        manifest = confirmed_manifest()
        del manifest["metadata_sources"]
        with self.assertRaises(ManifestError):
            validate_manifest(manifest, REPOSITORY_ROOT)

    def test_rejects_path_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = local_stage_for(root)
            manifest["local_path"] = (
                "../jawiki-20260801-pages-articles-multistream.xml.bz2"
            )

            with self.assertRaisesRegex(ManifestError, "local_path"):
                validate_manifest(manifest, root)

    def test_official_metadata_state_rejects_claimed_local_values(self) -> None:
        manifest = confirmed_manifest()
        manifest["local_path"] = (
            "data/downloads/jawiki-20260801-pages-articles-multistream.xml.bz2"
        )
        with self.assertRaisesRegex(ManifestError, "local stages"):
            validate_manifest(manifest, REPOSITORY_ROOT)


class BlockedMetadataTests(unittest.TestCase):
    def test_blocked_report_is_structured_but_not_verified(self) -> None:
        path = Path(__file__).parent / "fixtures" / "jawiki-manifest.blocked.json"
        document = load_manifest_document(path)
        self.assertEqual(validate_blocked_report(document)["status"], "blocked")
        with self.assertRaises(ManifestBlockedError) as context:
            validate_manifest_document(document, path.parent)
        self.assertEqual(context.exception.fields, ("official_url",))
