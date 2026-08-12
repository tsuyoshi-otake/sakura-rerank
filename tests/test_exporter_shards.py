from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_jsonl_bytes
from sakura_rerank.data.exporter_requests import publish_exporter_request_shards
from sakura_rerank.data.exporter_shards import (
    read_exporter_output_shards,
    read_request_shard_directory,
)
from sakura_rerank.data.tier_a import TierAError
from tests.test_research_exporter import _record, _snapshot_hash


def _request_manifest(shards: list[list[dict[str, str]]]) -> dict[str, object]:
    records = [record for shard in shards for record in shard]
    return {
        "schema_version": 1,
        "manifest_kind": "research_top32_request_shards",
        "verification_status": "verified_inputs",
        "builder_git_sha": "1" * 40,
        "source_span_content_sha256": "2" * 64,
        "source_span_extractor_git_sha": "3" * 40,
        "dictionary_index_content_sha256": "4" * 64,
        "dictionary_indexer_git_sha": "5" * 40,
        "dictionary_sha256": "6" * 64,
        "sakura_input_head": "7" * 40,
        "jawiki_local_sha256": "8" * 64,
        "record_count": len(records),
        "shard_size": 1,
        "shard_count": len(shards),
        "content_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
        "shards": [
            {
                "file_name": f"requests-{index:05d}.jsonl",
                "record_count": len(shard),
                "content_sha256": hashlib.sha256(canonical_jsonl_bytes(shard)).hexdigest(),
            }
            for index, shard in enumerate(shards)
        ],
        "raw_text_in_manifest": False,
    }


def _verified_record(stable_id: str) -> dict[str, object]:
    record = _record()
    record["stable_id"] = stable_id
    top32 = record["candidate_snapshots"]["training_top32"]
    top32["exporter_run"]["verification_status"] = "verified"
    top32["exporter_run"]["exporter_git_sha"] = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
    top32["exporter_run"]["exporter_binary_sha256"] = (
        "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
    )
    top32["content_sha256"] = _snapshot_hash(top32, record["converter_provenance"])
    return record


def _export_report(requests: list[dict[str, str]], records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "exported",
        "verification_status": "verified",
        "exporter_git_sha": "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1",
        "exporter_binary_sha256": "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf",
        "dictionary_sha256": "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad",
        "requested_limit": 32,
        "effective_converter_bound": 32,
        "record_count": len(records),
        "total_candidate_count": sum(
            len(record["candidate_snapshots"]["training_top32"]["candidates"])
            for record in records
        ),
        "search_exhausted_record_count": len(records),
        "truncated_record_count": 0,
        "input_sha256": hashlib.sha256(canonical_jsonl_bytes(requests)).hexdigest(),
        "output_sha256": hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest(),
    }


class ExporterShardTests(unittest.TestCase):
    def _create_bundle(self, root: Path) -> tuple[Path, Path, list[list[dict[str, str]]]]:
        requests = [
            [{"stable_id": "case-001", "reading": "kana"}],
            [{"stable_id": "case-002", "reading": "kana"}],
        ]
        request_directory = root / "requests"
        publish_exporter_request_shards(request_directory, requests, _request_manifest(requests))
        output_directory = root / "outputs"
        output_directory.mkdir()
        for index, shard in enumerate(requests):
            records = [_verified_record(request["stable_id"]) for request in shard]
            (output_directory / f"output-{index:05d}.jsonl").write_bytes(
                canonical_jsonl_bytes(records)
            )
            report = _export_report(shard, records)
            (output_directory / f"report-{index:05d}.json").write_bytes(
                canonical_json_bytes(report) + b"\n"
            )
        return request_directory, output_directory, requests

    def test_reads_complete_request_and_output_shards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_directory, output_directory, requests = self._create_bundle(root)
            loaded_requests, request_manifest = read_request_shard_directory(request_directory)
            self.assertEqual(loaded_requests, requests)
            outputs, aggregate = read_exporter_output_shards(
                output_directory,
                loaded_requests,
                exporter_manifest_path=Path(__file__).parents[1]
                / "manifests"
                / "research-exporter-verified.json",
            )
            self.assertEqual(aggregate["record_count"], 2)
            self.assertEqual(aggregate["shard_count"], 2)
            self.assertEqual(request_manifest["record_count"], 2)
            self.assertEqual([record["stable_id"] for shard in outputs for record in shard], ["case-001", "case-002"])

    def test_rejects_tampered_report_and_unexpected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_directory, output_directory, _ = self._create_bundle(root)
            loaded_requests, _ = read_request_shard_directory(request_directory)
            report_path = output_directory / "report-00000.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["record_count"] = 99
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "evidence mismatch"):
                read_exporter_output_shards(
                    output_directory,
                    loaded_requests,
                    exporter_manifest_path=Path(__file__).parents[1]
                    / "manifests"
                    / "research-exporter-verified.json",
                )
            (request_directory / "unexpected.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "unexpected"):
                read_request_shard_directory(request_directory)


if __name__ == "__main__":
    unittest.main()
