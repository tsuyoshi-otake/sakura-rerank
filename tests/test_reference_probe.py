from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sakura_rerank.data import reference_probe as probe
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_jsonl_bytes, _candidate_snapshot_hash, ContractError
from sakura_rerank.data.research_exporter import validate_export_records
from test_research_exporter import _record


def refresh(row):
    for snapshot in row["candidate_snapshots"].values():
        snapshot["content_sha256"] = _candidate_snapshot_hash(snapshot, row["converter_provenance"])


def probe_row():
    row = _record()
    row["record_type"] = probe.RECORD_TYPE
    row["converter_provenance"]["sakura_input_head"] = probe.SOURCE_COMMIT
    refresh(row)
    return row


IDENTITY = {"exporter_git_sha": "0" * 40, "exporter_binary_sha256": "1" * 64}
REQUEST = [{"stable_id": "case-001", "reading": "kana"}]


class ReferenceProbeTests(unittest.TestCase):
    def test_selection_reads_ids_only_and_excludes_nontrain_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.jsonl"
            raw = b'{"x":0,"split":"train","stable_id":"one",INVALID}\n'
            raw += b'{"x":0,"split":"dev","stable_id":"dev",INVALID}\n'
            raw += b'{"x":0,"split":"final-holdout","stable_id":"test",INVALID}\n'
            path.write_bytes(raw)
            with patch.object(probe.json, "loads", side_effect=AssertionError("JSON must not be parsed")):
                selected = probe.select_train_ids(path, hashlib.sha256(raw).hexdigest(), 1)
            self.assertEqual(selected["selected_ids"], ["one"])
            self.assertEqual(selected["split_counts"], {"train": 1, "dev": 1, "final-holdout": 1})
            self.assertFalse(selected["candidate_contents_parsed"])

    def test_selection_is_hash_ordered_and_source_order_invariant(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.jsonl"
            ids = [f"case-{i:03d}" for i in range(101)]
            expected = sorted(ids, key=lambda stable: hashlib.sha256(
                json.dumps([20261104, stable], separators=(",", ":")).encode()).hexdigest())[:100]
            for order in (ids, list(reversed(ids))):
                raw = b"".join(canonical_json_bytes(dict(split="train", stable_id=i, x=0)) + b"\n" for i in order)
                # Canonical keys put split first; prepend another fixed key for the frozen marker contract.
                raw = raw.replace(b'{"split"', b'{"a":0,"split"')
                path.write_bytes(raw)
                self.assertEqual(probe.select_train_ids(path, hashlib.sha256(raw).hexdigest())["selected_ids"], expected)

    def test_selection_rejects_wrong_hash_duplicates_and_invalid_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.jsonl"
            line = b'{"a":0,"split":"train","stable_id":"one","z":0}\n'
            path.write_bytes(line)
            for digest, count in (("0" * 64, 1), (hashlib.sha256(line).hexdigest(), 101),
                                  (hashlib.sha256(line).hexdigest(), True)):
                with self.assertRaises(ValueError):
                    probe.select_train_ids(path, digest, count)
            path.write_bytes(line * 2)
            with self.assertRaisesRegex(ValueError, "duplicate_train_identity"):
                probe.select_train_ids(path, hashlib.sha256(line * 2).hexdigest(), 1)

    def test_probe_uses_shared_feature_validation_but_is_rejected_by_legacy(self):
        row = probe_row()
        self.assertEqual(probe.validate_probe_records(canonical_jsonl_bytes([row]), REQUEST, IDENTITY), [row])
        with self.assertRaises(ContractError):
            validate_export_records([row], require_verified=False)
        row["record_type"] = "research_converter_snapshot"
        with self.assertRaises(ContractError):
            validate_export_records([row], require_verified=False)

    def test_probe_rejects_substituted_identity_provenance_and_schema(self):
        for field in ("source", "dictionary", "binary", "git", "verified", "record_type", "schema", "reading"):
            row = probe_row()
            run = row["candidate_snapshots"]["training_top32"]["exporter_run"]
            if field == "source": row["converter_provenance"]["sakura_input_head"] = "f" * 40
            if field == "dictionary": row["converter_provenance"]["dictionary_sha256"] = "f" * 64
            if field == "binary": run["exporter_binary_sha256"] = "f" * 64
            if field == "git": run["exporter_git_sha"] = "f" * 40
            if field == "verified": run["verification_status"] = "verified"
            if field == "record_type": row["record_type"] = "research_converter_snapshot"
            if field == "schema": row["schema_version"] = True
            if field == "reading": row["reading"] = "different"
            refresh(row)
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe.validate_probe_records(canonical_jsonl_bytes([row]), REQUEST, IDENTITY)

    def test_probe_rejects_rehashed_malformed_features_and_prefix(self):
        for field in ("fingerprint", "segment", "rank", "returned_count", "prefix", "hash"):
            row = probe_row()
            candidate = row["candidate_snapshots"]["training_top32"]["candidates"][0]
            if field == "fingerprint": candidate["fingerprint"] = "f" * 16
            if field == "segment": candidate["segments"][0]["reading_end"] = 3
            if field == "rank": candidate["rank"] = 1
            if field == "returned_count": row["candidate_snapshots"]["training_top32"]["exporter_run"]["returned_count"] = 2
            if field == "prefix": row["candidate_snapshots"]["production_top6"]["candidates"][0]["system_entry_index"] = 8
            refresh(row)
            if field == "hash": row["candidate_snapshots"]["production_top6"]["content_sha256"] = "f" * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe.validate_probe_records(canonical_jsonl_bytes([row]), REQUEST, IDENTITY)

    def test_missing_duplicate_extra_or_reordered_output_never_changes_denominator(self):
        row = probe_row()
        second = copy.deepcopy(row); second["stable_id"] = "case-002"
        requests = REQUEST + [{"stable_id": "case-002", "reading": "kana"}]
        for records in ([], [row], [row, row], [second, row], [row, second, second]):
            with self.subTest(count=len(records)), self.assertRaises(ValueError):
                raw = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
                probe.validate_probe_records(raw, requests, IDENTITY)

    def test_comparison_reports_full_feature_and_terminal_differences(self):
        before, after = _record(), probe_row()
        self.assertTrue(probe.compare_candidates([before], [after])["passed"])
        after["candidate_snapshots"]["training_top32"]["candidates"][0]["system_entry_index"] += 1
        after["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"] = "truncated"
        result = probe.compare_candidates([before], [after])
        self.assertEqual((result["denominator"], result["matched"], result["mismatched"]), (1, 0, 1))
        self.assertEqual(result["differences"], {"run.result_status": 1, "training_top32.candidates": 1})
        self.assertFalse(result["historical_binary_equivalence_proven"])

    def test_external_binding_and_two_builds_do_not_trust_self_asserted_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); binary = root / "binary"; dictionary = root / "dictionary"; path = root / "identity"
            binary.write_bytes(b"synthetic binary"); dictionary.write_bytes(b"synthetic dictionary")
            binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            dictionary_sha = hashlib.sha256(dictionary.read_bytes()).hexdigest()
            identity = dict(manifest_kind="research_probe_top32_exporter", verification_status="unverified",
                sakura_input_head=probe.SOURCE_COMMIT, dictionary_sha256=dictionary_sha,
                effective_converter_bound=32, requested_limit=32, user_dictionary_enabled=False,
                exporter_git_sha="0" * 40, exporter_binary_sha256=binary_sha)
            binding = dict(kind="reference_probe_identity_binding", schema_version=1, legacy_training_eligible=False,
                runtime_manifest=identity, independent_builds=[dict(build_id=name,status="built",
                    binary_sha256=binary_sha,recipe_git_sha="0"*40) for name in ("a", "b")])
            def publish(value):
                raw = canonical_json_bytes(value);path.write_bytes(raw);return hashlib.sha256(raw).hexdigest()
            with patch.object(probe, "DICTIONARY_SHA", dictionary_sha):
                commitment = publish(binding)
                self.assertEqual(probe.authenticate_identity(path,commitment,binary,dictionary),identity)
                with self.assertRaises(ValueError): probe.authenticate_identity(path,"f"*64,binary,dictionary)
                for change in ("duplicate_build", "failed_build", "self_verified", "wrong_source"):
                    bad=copy.deepcopy(binding)
                    if change=="duplicate_build": bad["independent_builds"][1]["build_id"]="a"
                    if change=="failed_build": bad["independent_builds"][1]["status"]="failed"
                    if change=="self_verified": bad["runtime_manifest"]["verification_status"]="verified"
                    if change=="wrong_source": bad["runtime_manifest"]["sakura_input_head"]="f"*40
                    with self.subTest(change=change),self.assertRaises(ValueError):
                        probe.authenticate_identity(path,publish(bad),binary,dictionary)
                commitment=publish(binding);binary.write_bytes(b"changed")
                with self.assertRaises(ValueError):probe.authenticate_identity(path,commitment,binary,dictionary)


if __name__ == "__main__":
    unittest.main()
