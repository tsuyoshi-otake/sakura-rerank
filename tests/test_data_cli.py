from __future__ import annotations

import copy
import io
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sakura_rerank.atomic_io as atomic_io
from sakura_rerank.data.__main__ import _parser, main
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_jsonl_bytes
from sakura_rerank.data.corpus_v4 import (
    GATE_A_REVIEWER_ID,
    V4_SCHEMA_VERSION,
    V4_VERDICT_RECORD_TYPE,
    build_gate_a_teacher_batches,
    publish_teacher_queue_directory,
    read_teacher_queue_directory,
    stage3_human_audit_items,
)
from sakura_rerank.data.corpus_v5 import (
    CONFIRMATION_PASS,
    FIRST_PASS,
    V5_GATE_A_AUDIT_SEED,
    V5_GATE_A_QUEUE_MANIFEST_KIND,
    V5_SCHEMA_VERSION,
    V5_SPLIT_RATIOS,
    V5_SPLIT_SEED,
    V5_VERDICT_RECORD_TYPE,
    build_blind_queue_manifest,
    build_blind_teacher_batches,
    partition_blind_teacher_passes,
    read_blind_teacher_queue_directory,
)
from sakura_rerank.data.human_audit import (
    build_queue_manifest,
    publish_audit_queue,
    read_audit_responses,
    select_audit_records,
)
from sakura_rerank.data.splitter import assign_splits, split_jsonl

from tests.test_data_contracts import (
    _rehash_snapshots,
    fixture_record,
    production_record,
)


def _write_unassigned_input(path: Path) -> bytes:
    record = fixture_record()
    record["split"] = None
    payload = canonical_json_bytes(record) + b"\n"
    path.write_bytes(payload)
    return payload


def _write_v5_dataset(
    path: Path,
    *,
    count: int = 2,
    stable_id_prefix: str = "data-cli-v5",
    independent_sources: bool = False,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(count):
        record = production_record()
        record["stable_id"] = f"{stable_id_prefix}-{index:04d}"
        record["split"] = None
        if independent_sources:
            source = record["source"]
            source["article_id"] = f"{stable_id_prefix}-article-{index:04d}"
            source["page_id"] = f"{stable_id_prefix}-page-{index:04d}"
            source["revision_id"] = f"{stable_id_prefix}-revision-{index:04d}"
            source["paragraph_hash"] = hashlib.sha256(
                f"{stable_id_prefix}-paragraph-{index:04d}".encode("utf-8")
            ).hexdigest()
            source["sentence_hash"] = hashlib.sha256(
                f"{stable_id_prefix}-sentence-{index:04d}".encode("utf-8")
            ).hexdigest()
            source["sentence_shingle_hashes"] = [
                hashlib.sha256(
                    f"{stable_id_prefix}-shingle-{index:04d}".encode("utf-8")
                ).hexdigest()
            ]
            source["template_cluster_id"] = None
        exporter = record["candidate_snapshots"]["training_top32"]["exporter_run"]
        exporter["verification_status"] = "verified"
        exporter["exporter_git_sha"] = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
        exporter["exporter_binary_sha256"] = (
            "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
        )
        _rehash_snapshots(record)
        records.append(record)
    path.write_bytes(
        b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    )
    return records


def _write_v5_verdicts(
    queue_directory: Path, verdict_directory: Path, reviewer_id: str
) -> None:
    batches, _ = read_blind_teacher_queue_directory(queue_directory)
    verdict_directory.mkdir()
    for batch in batches:
        payload = {
            "schema_version": V5_SCHEMA_VERSION,
            "record_type": V5_VERDICT_RECORD_TYPE,
            "batch_index": batch["batch_index"],
            "reviewer_kind": "ai_teacher",
            "reviewer_id": reviewer_id,
            "verdicts": [
                {"stable_id": item["stable_id"], "verdict": "valid", "note": ""}
                for item in batch["items"]
            ],
        }
        (verdict_directory / f"verdicts-{batch['batch_index']:03d}.json").write_bytes(
            canonical_json_bytes(payload) + b"\n"
        )


class DataCliPathTests(unittest.TestCase):
    def test_jawiki_preprocess_cli_accepts_sample_slot_start(self) -> None:
        arguments = _parser().parse_args(
            [
                "jawiki-preprocess",
                "dump.xml.bz2",
                "source-spans.jsonl",
                "--jawiki-manifest",
                "jawiki-manifest.json",
                "--allowed-root",
                ".",
                "--dictionary-index",
                "dictionary.jsonl",
                "--dictionary-manifest",
                "dictionary-manifest.json",
                "--report",
                "report.json",
                "--extractor-git-sha",
                "0" * 40,
                "--sample-slot-start",
                "120",
            ]
        )
        self.assertEqual(arguments.sample_slot_start, 120)

    def _run_split(self, input_path: Path, output_path: Path, report_path: Path) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(
                [
                    "split",
                    os.fspath(input_path),
                    os.fspath(output_path),
                    "--seed",
                    "17",
                    "--report",
                    os.fspath(report_path),
                ]
            )

    def test_split_cli_records_explicit_ratio_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            _write_unassigned_input(input_path)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = main(
                    [
                        "split",
                        os.fspath(input_path),
                        os.fspath(output_path),
                        "--seed",
                        "17",
                        "--report",
                        os.fspath(report_path),
                        "--train-ratio",
                        "0.75",
                        "--dev-ratio",
                        "0.10",
                        "--final-holdout-ratio",
                        "0.15",
                    ]
                )
            self.assertEqual(status, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(
                report["split_ratios"],
                {"train": 0.75, "dev": 0.10, "final-holdout": 0.15},
            )

    def _assert_no_transaction_residue(self, root: Path) -> None:
        residue = [
            path
            for path in root.rglob(".*")
            if path.name.endswith((".tmp", ".bak"))
        ]
        self.assertEqual(residue, [])

    def test_rejects_input_output_alias_before_mutating_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            report_path = root / "report.json"
            original = _write_unassigned_input(input_path)

            status = self._run_split(input_path, root / "." / "input.jsonl", report_path)

            self.assertEqual(status, 2)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertFalse(report_path.exists())

    def test_rejects_output_report_collision_before_writing_either(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            collision = root / "result.jsonl"
            original = _write_unassigned_input(input_path)

            status = self._run_split(input_path, collision, collision)

            self.assertEqual(status, 2)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertFalse(collision.exists())

    def test_rejects_input_report_collision_before_mutating_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            original = _write_unassigned_input(input_path)

            status = self._run_split(input_path, output_path, input_path)

            self.assertEqual(status, 2)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertFalse(output_path.exists())

    def test_rejects_existing_hardlink_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            hardlink_path = root / "input-hardlink.jsonl"
            report_path = root / "report.json"
            original = _write_unassigned_input(input_path)
            os.link(input_path, hardlink_path)

            status = self._run_split(input_path, hardlink_path, report_path)

            self.assertEqual(status, 2)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertEqual(hardlink_path.read_bytes(), original)
            self.assertFalse(report_path.exists())

    def test_fails_closed_when_existing_path_identity_cannot_be_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            original = _write_unassigned_input(input_path)
            original_output = b"existing output sentinel"
            output_path.write_bytes(original_output)

            with patch.object(Path, "samefile", side_effect=OSError("identity unavailable")):
                status = self._run_split(input_path, output_path, report_path)

            self.assertEqual(status, 2)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertEqual(output_path.read_bytes(), original_output)
            self.assertFalse(report_path.exists())

    def test_distinct_paths_write_report_with_all_split_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            _write_unassigned_input(input_path)

            status = self._run_split(input_path, output_path, report_path)

            self.assertEqual(status, 0)
            self.assertTrue(output_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(report["split_content_sha256"]),
                {"train", "dev", "final-holdout"},
            )

    def test_missing_report_parent_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "missing" / "report.json"
            _write_unassigned_input(input_path)
            original_output = b"existing output sentinel"
            output_path.write_bytes(original_output)

            status = self._run_split(input_path, output_path, report_path)

            self.assertEqual(status, 2)
            self.assertEqual(output_path.read_bytes(), original_output)
            self.assertFalse(report_path.exists())
            self._assert_no_transaction_residue(root)


    def test_report_temporary_write_failure_preserves_existing_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            _write_unassigned_input(input_path)
            original_output = b"existing output sentinel"
            original_report = b"existing report sentinel"
            output_path.write_bytes(original_output)
            report_path.write_bytes(original_report)
            real_write = atomic_io._write_temporary_bytes
            call_count = 0

            def fail_second_write(*args: object, **kwargs: object) -> Path:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("injected report write failure")
                return real_write(*args, **kwargs)

            with patch.object(
                atomic_io,
                "_write_temporary_bytes",
                side_effect=fail_second_write,
            ):
                status = self._run_split(input_path, output_path, report_path)

            self.assertEqual(status, 2)
            self.assertEqual(output_path.read_bytes(), original_output)
            self.assertEqual(report_path.read_bytes(), original_report)
            self._assert_no_transaction_residue(root)


    def test_first_replace_failure_preserves_existing_pair(self) -> None:
        self._assert_replace_failure_preserves_pair(failure_call=1)

    def test_second_replace_failure_rolls_back_existing_pair(self) -> None:
        self._assert_replace_failure_preserves_pair(failure_call=2)

    def _assert_replace_failure_preserves_pair(self, *, failure_call: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            _write_unassigned_input(input_path)
            original_output = b"existing output sentinel"
            original_report = b"existing report sentinel"
            output_path.write_bytes(original_output)
            report_path.write_bytes(original_report)
            real_replace = atomic_io.os.replace
            call_count = 0

            def fail_selected_replace(source: object, destination: object) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == failure_call:
                    raise OSError(f"injected replace failure {failure_call}")
                real_replace(source, destination)

            with patch.object(
                atomic_io.os,
                "replace",
                side_effect=fail_selected_replace,
            ):
                status = self._run_split(input_path, output_path, report_path)

            self.assertEqual(status, 2)
            self.assertEqual(output_path.read_bytes(), original_output)
            self.assertEqual(report_path.read_bytes(), original_report)
            self._assert_no_transaction_residue(root)

    def test_split_jsonl_success_publishes_matching_pair_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            report_path = root / "report.json"
            _write_unassigned_input(input_path)

            output_hash, report_hash = split_jsonl(
                os.fspath(input_path),
                os.fspath(output_path),
                os.fspath(report_path),
                seed=17,
            )

            self.assertEqual(
                output_hash, hashlib.sha256(output_path.read_bytes()).hexdigest()
            )
            self.assertEqual(
                report_hash, hashlib.sha256(report_path.read_bytes()).hexdigest()
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["content_sha256"], output_hash)
            self._assert_no_transaction_residue(root)


class CorpusV5DataCliTests(unittest.TestCase):
    def _run(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(arguments)
        return status, stdout.getvalue(), stderr.getvalue()

    def _queue_arguments(
        self,
        dataset: Path,
        output_directory: Path,
        *,
        pass_name: str,
        reviewer_id: str,
    ) -> list[str]:
        return [
            "corpus-v5",
            "queue",
            os.fspath(dataset),
            os.fspath(output_directory),
            "--pass-name",
            pass_name,
            "--reviewer-id",
            reviewer_id,
            "--batch-size",
            "1",
        ]

    def _partition_arguments(
        self,
        dataset: Path,
        first_queue: Path,
        first_verdicts: Path,
        confirmation_queue: Path,
        confirmation_verdicts: Path,
        output_directory: Path,
    ) -> list[str]:
        return [
            "corpus-v5",
            "partition",
            os.fspath(dataset),
            os.fspath(first_queue),
            os.fspath(first_verdicts),
            os.fspath(confirmation_queue),
            os.fspath(confirmation_verdicts),
            os.fspath(output_directory),
        ]

    def test_two_pass_cli_publishes_aggregate_only_status_and_immutable_partition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "tier-a.jsonl"
            records = _write_v5_dataset(dataset)
            first_queue = root / "first-queue"
            confirmation_queue = root / "confirmation-queue"
            first_reviewer = "teacher-first"
            confirmation_reviewer = "teacher-confirm"

            status, stdout, stderr = self._run(
                self._queue_arguments(
                    dataset,
                    first_queue,
                    pass_name=FIRST_PASS,
                    reviewer_id=first_reviewer,
                )
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(
                set(json.loads(stdout)),
                {
                    "status",
                    "record_count",
                    "batch_count",
                    "content_sha256",
                    "source_dataset_content_sha256",
                },
            )
            self.assertNotIn(records[0]["stable_id"], stdout)
            self.assertNotIn(records[0]["reading"], stdout)
            self.assertNotIn(first_reviewer, stdout)

            status, _, stderr = self._run(
                self._queue_arguments(
                    dataset,
                    confirmation_queue,
                    pass_name=CONFIRMATION_PASS,
                    reviewer_id=confirmation_reviewer,
                )
            )
            self.assertEqual((status, stderr), (0, ""))

            first_verdicts = root / "first-verdicts"
            status, stdout, stderr = self._run(
                [
                    "corpus-v5",
                    "verdict-status",
                    os.fspath(first_queue),
                    os.fspath(first_verdicts),
                ]
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(
                json.loads(stdout),
                {
                    "completed_batch_count": 0,
                    "completed_record_count": 0,
                    "pending_batch_count": 2,
                    "status": "resumable",
                    "verdict_counts": {},
                },
            )

            _write_v5_verdicts(first_queue, first_verdicts, first_reviewer)
            status, stdout, stderr = self._run(
                [
                    "corpus-v5",
                    "verdict-status",
                    os.fspath(first_queue),
                    os.fspath(first_verdicts),
                ]
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(
                json.loads(stdout),
                {
                    "completed_batch_count": 2,
                    "completed_record_count": 2,
                    "pending_batch_count": 0,
                    "status": "complete",
                    "verdict_counts": {"valid": 2},
                },
            )
            self.assertNotIn(records[0]["stable_id"], stdout)
            self.assertNotIn(records[0]["reading"], stdout)
            self.assertNotIn(first_reviewer, stdout)

            confirmation_verdicts = root / "confirmation-verdicts"
            output_directory = root / "partition"
            status, _, stderr = self._run(
                self._partition_arguments(
                    dataset,
                    first_queue,
                    first_verdicts,
                    confirmation_queue,
                    confirmation_verdicts,
                    output_directory,
                )
            )
            self.assertEqual(status, 2)
            self.assertIn("incomplete", stderr)
            self.assertFalse(output_directory.exists())

            _write_v5_verdicts(
                confirmation_queue, confirmation_verdicts, confirmation_reviewer
            )
            status, stdout, stderr = self._run(
                self._partition_arguments(
                    dataset,
                    first_queue,
                    first_verdicts,
                    confirmation_queue,
                    confirmation_verdicts,
                    output_directory,
                )
            )
            self.assertEqual((status, stderr), (0, ""))
            partition_status = json.loads(stdout)
            self.assertEqual(partition_status["status"], "generated")
            self.assertEqual(partition_status["input_record_count"], len(records))
            self.assertEqual(
                partition_status["bucket_record_counts"],
                {
                    "eligible_unanimous_valid": 2,
                    "extraction_noise": 0,
                    "intrinsic_surface_ambiguity": 0,
                    "repairable_label_error": 0,
                    "unresolved_disagreement": 0,
                },
            )
            self.assertNotIn(records[0]["stable_id"], stdout)
            self.assertNotIn(records[0]["reading"], stdout)
            self.assertNotIn(first_reviewer, stdout)
            self.assertNotIn(confirmation_reviewer, stdout)
            self.assertTrue((output_directory / "report.json").is_file())

            status, _, stderr = self._run(
                self._partition_arguments(
                    dataset,
                    first_queue,
                    first_verdicts,
                    confirmation_queue,
                    confirmation_verdicts,
                    output_directory,
                )
            )
            self.assertEqual(status, 2)
            self.assertIn("immutable", stderr)

    def test_historical_exclude_requires_explicit_commitments_and_reports_aggregates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical_path = root / "historical.jsonl"
            candidate_path = root / "candidate.jsonl"
            historical = _write_v5_dataset(
                historical_path, count=1, stable_id_prefix="historical-cli"
            )
            candidates = _write_v5_dataset(
                candidate_path, count=2, stable_id_prefix="candidate-cli"
            )
            output_directory = root / "historical-exclusion"
            arguments = [
                "corpus-v5",
                "historical-exclude",
                os.fspath(historical_path),
                os.fspath(candidate_path),
                os.fspath(output_directory),
                "--expected-historical-record-count",
                "1",
                "--expected-historical-content-sha256",
                hashlib.sha256(canonical_jsonl_bytes(historical)).hexdigest(),
                "--expected-candidate-record-count",
                "2",
                "--expected-candidate-content-sha256",
                hashlib.sha256(canonical_jsonl_bytes(candidates)).hexdigest(),
            ]
            wrong_arguments = list(arguments)
            wrong_arguments[4] = os.fspath(root / "wrong-commitment")
            hash_index = wrong_arguments.index("--expected-candidate-content-sha256") + 1
            wrong_arguments[hash_index] = "0" * 64
            status, _, stderr = self._run(wrong_arguments)
            self.assertEqual(status, 2)
            self.assertIn("expected commitment", stderr)
            self.assertFalse((root / "wrong-commitment").exists())

            status, stdout, stderr = self._run(arguments)
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(
                json.loads(stdout),
                {
                    "status": "generated",
                    "historical_record_count": 1,
                    "candidate_record_count": 2,
                    "eligible_record_count": 0,
                    "excluded_record_count": 2,
                    "report_content_sha256": hashlib.sha256(
                        (output_directory / "report.json").read_bytes()
                    ).hexdigest(),
                },
            )
            self.assertNotIn(historical[0]["stable_id"], stdout)
            self.assertNotIn(candidates[0]["stable_id"], stdout)
            self.assertNotIn(historical[0]["reading"], stdout)
            self.assertTrue((output_directory / "eligible.jsonl").is_file())
            self.assertTrue((output_directory / "excluded.jsonl").is_file())

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as missing:
                    _parser().parse_args(
                        [
                            "corpus-v5",
                            "historical-exclude",
                            os.fspath(historical_path),
                            os.fspath(candidate_path),
                            os.fspath(root / "missing-commitment"),
                        ]
                    )
            self.assertEqual(missing.exception.code, 2)


class GateADataCliTests(unittest.TestCase):
    FRESH_V5_REVIEWER_ID = "fresh-v5-gate-a-cli"

    def _write_v5_gate_a_inputs(
        self,
        root: Path,
        *,
        count: int = 10,
        suffix: str = "",
        minimum_sample_size: int = 2,
    ) -> tuple[Path, Path, Path, Path, Path, Path, list[dict[str, object]]]:
        eligible_path = root / f"v5-eligible{suffix}.jsonl"
        source = _write_v5_dataset(
            eligible_path,
            count=count,
            stable_id_prefix=f"gate-a-cli{suffix}",
            independent_sources=True,
        )
        batches = build_blind_teacher_batches(source)
        first_reviewer = f"v5-first{suffix}"
        confirmation_reviewer = f"v5-confirmation{suffix}"
        first_manifest = build_blind_queue_manifest(
            source,
            batches,
            pass_name=FIRST_PASS,
            reviewer_id=first_reviewer,
        )
        confirmation_manifest = build_blind_queue_manifest(
            source,
            batches,
            pass_name=CONFIRMATION_PASS,
            reviewer_id=confirmation_reviewer,
        )

        def verdicts(reviewer_id: str) -> dict[int, dict[str, object]]:
            return {
                batch["batch_index"]: {
                    "schema_version": V5_SCHEMA_VERSION,
                    "record_type": V5_VERDICT_RECORD_TYPE,
                    "batch_index": batch["batch_index"],
                    "reviewer_kind": "ai_teacher",
                    "reviewer_id": reviewer_id,
                    "verdicts": [
                        {
                            "stable_id": item["stable_id"],
                            "verdict": "valid",
                            "note": "",
                        }
                        for item in batch["items"]
                    ],
                }
                for batch in batches
            }

        _, report = partition_blind_teacher_passes(
            source,
            batches,
            first_manifest,
            verdicts(first_reviewer),
            batches,
            confirmation_manifest,
            verdicts(confirmation_reviewer),
        )
        report_path = root / f"v5-partition-report{suffix}.json"
        report_path.write_bytes(canonical_json_bytes(report) + b"\n")

        split_dataset, split_report = assign_splits(
            source,
            seed=V5_SPLIT_SEED,
            split_ratios=V5_SPLIT_RATIOS,
        )
        split_dataset_path = root / f"v5-split{suffix}.jsonl"
        split_dataset_path.write_bytes(canonical_jsonl_bytes(split_dataset))
        split_report_path = root / f"v5-split-report{suffix}.json"
        split_report_path.write_bytes(canonical_json_bytes(split_report) + b"\n")

        queue = select_audit_records(
            split_dataset,
            seed=V5_GATE_A_AUDIT_SEED,
            minimum_sample_size=minimum_sample_size,
        )
        queue_manifest = build_queue_manifest(
            split_dataset,
            queue,
            seed=V5_GATE_A_AUDIT_SEED,
            minimum_sample_size=minimum_sample_size,
        )
        queue_path = root / f"v5-audit-queue{suffix}.jsonl"
        queue_manifest_path = root / f"v5-audit-manifest{suffix}.json"
        publish_audit_queue(queue_path, queue_manifest_path, queue, queue_manifest)
        return (
            queue_path,
            queue_manifest_path,
            report_path,
            eligible_path,
            split_dataset_path,
            split_report_path,
            queue,
        )

    def _write_audit_inputs(
        self, root: Path, *, count: int = 2
    ) -> tuple[Path, Path, list[dict[str, object]]]:
        records: list[dict[str, object]] = []
        for index in range(count):
            record = production_record()
            record["stable_id"] = f"gate-a-cli-{index:03d}"
            record["split"] = "final-holdout"
            exporter = record["candidate_snapshots"]["training_top32"]["exporter_run"]
            exporter["verification_status"] = "verified"
            exporter["exporter_git_sha"] = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
            exporter["exporter_binary_sha256"] = (
                "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
            )
            _rehash_snapshots(record)
            records.append(record)
        queue = stage3_human_audit_items(
            records, [record["stable_id"] for record in records]
        )
        manifest = build_queue_manifest(
            records, queue, seed=17, minimum_sample_size=count
        )
        queue_path = root / "audit-queue.jsonl"
        manifest_path = root / "audit-manifest.json"
        publish_audit_queue(queue_path, manifest_path, queue, manifest)
        return queue_path, manifest_path, queue

    def _publish_teacher_queue(
        self,
        output_directory: Path,
        queue: list[dict[str, object]],
        *,
        stage: str = "gate_a",
        batch_size: int = 1,
    ) -> None:
        publish_teacher_queue_directory(
            output_directory,
            build_gate_a_teacher_batches(queue, batch_size=batch_size),
            stage=stage,
            reviewer_kind="ai_teacher",
            reviewer_id=GATE_A_REVIEWER_ID,
        )

    def _write_complete_verdicts(
        self,
        teacher_queue_directory: Path,
        verdict_directory: Path,
        *,
        reviewer_id: str = GATE_A_REVIEWER_ID,
        v5: bool = False,
    ) -> None:
        read_options = (
            {
                "expected_manifest_kind": V5_GATE_A_QUEUE_MANIFEST_KIND,
                "require_source_provenance": True,
                "require_canonical_bytes": True,
            }
            if v5
            else {}
        )
        batches, _ = read_teacher_queue_directory(
            teacher_queue_directory, **read_options
        )
        verdict_directory.mkdir()
        for batch in batches:
            payload = {
                "schema_version": V5_SCHEMA_VERSION if v5 else V4_SCHEMA_VERSION,
                "record_type": V5_VERDICT_RECORD_TYPE if v5 else V4_VERDICT_RECORD_TYPE,
                "batch_index": batch["batch_index"],
                "reviewer_kind": "ai_teacher",
                "reviewer_id": reviewer_id,
                "verdicts": [
                    {
                        "stable_id": item["stable_id"],
                        "verdict": "valid",
                        "note": "",
                    }
                    for item in batch["items"]
                ],
            }
            (verdict_directory / f"verdicts-{batch['batch_index']:03d}.json").write_bytes(
                canonical_json_bytes(payload) + b"\n"
            )

    def _v5_finalize_arguments(
        self,
        queue_path: Path,
        manifest_path: Path,
        partition_report_path: Path,
        partition_eligible_path: Path,
        split_dataset_path: Path,
        split_report_path: Path,
        teacher_queue_directory: Path,
        verdict_directory: Path,
        responses_path: Path,
        report_path: Path,
        *,
        authorize: bool = True,
    ) -> list[str]:
        arguments = [
            "corpus-v5",
            "gate-a-finalize",
            os.fspath(queue_path),
            os.fspath(teacher_queue_directory),
            os.fspath(verdict_directory),
            os.fspath(responses_path),
            os.fspath(report_path),
            "--partition-report",
            os.fspath(partition_report_path),
            "--partition-eligible",
            os.fspath(partition_eligible_path),
            "--split-dataset",
            os.fspath(split_dataset_path),
            "--split-report",
            os.fspath(split_report_path),
            "--queue-manifest",
            os.fspath(manifest_path),
            "--reviewed-at",
            "2026-08-13T12:34:56+09:00",
        ]
        if authorize:
            arguments.append("--allow-ai-teacher")
        return arguments

    def test_v5_gate_a_cli_is_fresh_bound_complete_and_aggregate_only(self) -> None:
        with patch(
            "sakura_rerank.data.corpus_v5.V5_GATE_A_MINIMUM_SAMPLE_SIZE", 2
        ), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                queue_path,
                manifest_path,
                partition_report_path,
                partition_eligible_path,
                split_dataset_path,
                split_report_path,
                queue,
            ) = self._write_v5_gate_a_inputs(root)
            teacher_queue_directory = root / "v5-teacher-queue"
            queue_stdout = io.StringIO()
            queue_stderr = io.StringIO()
            with redirect_stdout(queue_stdout), redirect_stderr(queue_stderr):
                queue_status = main(
                    [
                        "corpus-v5",
                        "gate-a-queue",
                        os.fspath(queue_path),
                        os.fspath(teacher_queue_directory),
                        "--partition-report",
                        os.fspath(partition_report_path),
                        "--partition-eligible",
                        os.fspath(partition_eligible_path),
                        "--split-dataset",
                        os.fspath(split_dataset_path),
                        "--split-report",
                        os.fspath(split_report_path),
                        "--queue-manifest",
                        os.fspath(manifest_path),
                        "--reviewer-id",
                        self.FRESH_V5_REVIEWER_ID,
                        "--batch-size",
                        "40",
                    ]
                )
            self.assertEqual((queue_status, queue_stderr.getvalue()), (0, ""))
            queue_summary = json.loads(queue_stdout.getvalue())
            self.assertEqual(queue_summary["reviewer_id"], self.FRESH_V5_REVIEWER_ID)
            self.assertEqual(queue_summary["batch_count"], 1)
            self.assertNotIn("left_context", queue_summary)
            self.assertNotIn(queue[0]["stable_id"], queue_stdout.getvalue())
            batches, teacher_manifest = read_teacher_queue_directory(
                teacher_queue_directory,
                expected_manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
                require_source_provenance=True,
                require_canonical_bytes=True,
            )
            self.assertEqual(teacher_manifest["reviewer_id"], self.FRESH_V5_REVIEWER_ID)
            self.assertLessEqual(max(len(batch["items"]) for batch in batches), 40)
            self.assertFalse(
                teacher_manifest["source_provenance"]["raw_text_in_provenance"]
            )

            verdict_directory = root / "v5-verdicts"
            responses_path = root / "v5-responses.jsonl"
            quality_report_path = root / "v5-quality.json"
            incomplete_stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(incomplete_stderr):
                incomplete_status = main(
                    self._v5_finalize_arguments(
                        queue_path,
                        manifest_path,
                        partition_report_path,
                        partition_eligible_path,
                        split_dataset_path,
                        split_report_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        quality_report_path,
                    )
                )
            self.assertEqual(incomplete_status, 2)
            self.assertIn("incomplete", incomplete_stderr.getvalue())
            self.assertFalse(responses_path.exists())

            self._write_complete_verdicts(
                teacher_queue_directory,
                verdict_directory,
                reviewer_id=self.FRESH_V5_REVIEWER_ID,
                v5=True,
            )
            unauthorized_stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(unauthorized_stderr):
                unauthorized_status = main(
                    self._v5_finalize_arguments(
                        queue_path,
                        manifest_path,
                        partition_report_path,
                        partition_eligible_path,
                        split_dataset_path,
                        split_report_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        quality_report_path,
                        authorize=False,
                    )
                )
            self.assertEqual(unauthorized_status, 2)
            self.assertIn("explicit owner authorization", unauthorized_stderr.getvalue())

            swapped_partition = self._write_v5_gate_a_inputs(
                root, suffix="-swapped"
            )[2]
            swapped_stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(swapped_stderr):
                swapped_status = main(
                    self._v5_finalize_arguments(
                        queue_path,
                        manifest_path,
                        swapped_partition,
                        partition_eligible_path,
                        split_dataset_path,
                        split_report_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        quality_report_path,
                    )
                )
            self.assertEqual(swapped_status, 2)
            self.assertIn("partition eligible artifact", swapped_stderr.getvalue())

            finalize_stdout = io.StringIO()
            finalize_stderr = io.StringIO()
            with redirect_stdout(finalize_stdout), redirect_stderr(finalize_stderr):
                finalize_status = main(
                    self._v5_finalize_arguments(
                        queue_path,
                        manifest_path,
                        partition_report_path,
                        partition_eligible_path,
                        split_dataset_path,
                        split_report_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        quality_report_path,
                    )
                )
            self.assertEqual((finalize_status, finalize_stderr.getvalue()), (0, ""))
            summary = json.loads(finalize_stdout.getvalue())
            self.assertEqual(summary["reviewer_id"], self.FRESH_V5_REVIEWER_ID)
            self.assertEqual(summary["completed_record_count"], len(queue))
            self.assertEqual(summary["pending_record_count"], 0)
            self.assertFalse(summary["gate_a_human_audit_pass"])
            self.assertNotIn("left_context", summary)
            self.assertNotIn(queue[0]["stable_id"], finalize_stdout.getvalue())
            responses = read_audit_responses(responses_path)
            self.assertTrue(
                all(
                    response["reviewer_id"] == self.FRESH_V5_REVIEWER_ID
                    for response in responses
                )
            )
            quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
            self.assertTrue(quality["ai_teacher_authorized_by_owner"])
            self.assertFalse(quality["gate_a_human_audit_pass"])

    def _finalize_arguments(
        self,
        queue_path: Path,
        manifest_path: Path,
        teacher_queue_directory: Path,
        verdict_directory: Path,
        responses_path: Path,
        report_path: Path,
        *,
        authorize: bool = True,
    ) -> list[str]:
        arguments = [
            "corpus-v4",
            "gate-a-finalize",
            os.fspath(queue_path),
            os.fspath(teacher_queue_directory),
            os.fspath(verdict_directory),
            os.fspath(responses_path),
            os.fspath(report_path),
            "--queue-manifest",
            os.fspath(manifest_path),
            "--reviewed-at",
            "2026-08-13T12:34:56+09:00",
        ]
        if authorize:
            arguments.append("--allow-ai-teacher")
        return arguments

    def test_gate_a_queue_and_finalize_publish_complete_aggregate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path, manifest_path, _ = self._write_audit_inputs(root)
            teacher_queue_directory = root / "teacher-queue"
            queue_stdout = io.StringIO()
            with redirect_stdout(queue_stdout), redirect_stderr(io.StringIO()):
                queue_status = main(
                    [
                        "corpus-v4",
                        "gate-a-queue",
                        os.fspath(queue_path),
                        os.fspath(teacher_queue_directory),
                        "--queue-manifest",
                        os.fspath(manifest_path),
                        "--batch-size",
                        "1",
                    ]
                )
            self.assertEqual(queue_status, 0)
            self.assertEqual(json.loads(queue_stdout.getvalue())["batch_count"], 2)

            verdict_directory = root / "verdicts"
            self._write_complete_verdicts(teacher_queue_directory, verdict_directory)
            responses_path = root / "responses.jsonl"
            report_path = root / "report.json"
            finalize_stdout = io.StringIO()
            with redirect_stdout(finalize_stdout), redirect_stderr(io.StringIO()):
                finalize_status = main(
                    self._finalize_arguments(
                        queue_path,
                        manifest_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        report_path,
                    )
                )

            self.assertEqual(finalize_status, 0)
            summary = json.loads(finalize_stdout.getvalue())
            self.assertEqual(summary["completed_record_count"], 2)
            self.assertEqual(summary["pending_record_count"], 0)
            self.assertEqual(summary["point_precision"], 1.0)
            self.assertGreater(summary["wilson_95_lower_bound"], 0.0)
            self.assertFalse(summary["gate_a_human_audit_pass"])
            self.assertFalse(summary["gate_a_owner_authorized_audit_pass"])
            self.assertNotIn("left_context", summary)
            responses = read_audit_responses(responses_path)
            self.assertEqual(len(responses), 2)
            self.assertTrue(
                all(response["reviewer_id"] == GATE_A_REVIEWER_ID for response in responses)
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["ai_teacher_authorized_by_owner"])
            self.assertFalse(report["gate_a_human_audit_pass"])
            self.assertEqual(report["pending_record_count"], 0)

    def test_gate_a_finalize_requires_explicit_ai_teacher_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path, manifest_path, queue = self._write_audit_inputs(root)
            teacher_queue_directory = root / "teacher-queue"
            self._publish_teacher_queue(teacher_queue_directory, queue)
            verdict_directory = root / "verdicts"
            self._write_complete_verdicts(teacher_queue_directory, verdict_directory)
            responses_path = root / "responses.jsonl"
            report_path = root / "report.json"
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                status = main(
                    self._finalize_arguments(
                        queue_path,
                        manifest_path,
                        teacher_queue_directory,
                        verdict_directory,
                        responses_path,
                        report_path,
                        authorize=False,
                    )
                )
            self.assertEqual(status, 2)
            self.assertIn("explicit owner authorization", stderr.getvalue())
            self.assertFalse(responses_path.exists())
            self.assertFalse(report_path.exists())

    def test_gate_a_finalize_rejects_incomplete_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path, manifest_path, queue = self._write_audit_inputs(root)
            teacher_queue_directory = root / "teacher-queue"
            self._publish_teacher_queue(teacher_queue_directory, queue)
            responses_path = root / "responses.jsonl"
            report_path = root / "report.json"
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                status = main(
                    self._finalize_arguments(
                        queue_path,
                        manifest_path,
                        teacher_queue_directory,
                        root / "missing-verdicts",
                        responses_path,
                        report_path,
                    )
                )
            self.assertEqual(status, 2)
            self.assertIn("verdicts are incomplete", stderr.getvalue())
            self.assertFalse(responses_path.exists())
            self.assertFalse(report_path.exists())

    def test_gate_a_finalize_rejects_wrong_provenance_and_binding(self) -> None:
        for case in ("provenance", "binding"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                queue_path, manifest_path, queue = self._write_audit_inputs(root)
                teacher_queue_directory = root / "teacher-queue"
                if case == "provenance":
                    self._publish_teacher_queue(
                        teacher_queue_directory, queue, stage="stage1"
                    )
                else:
                    foreign_queue = copy.deepcopy(queue)
                    foreign_queue[0]["left_context"] += " altered"
                    self._publish_teacher_queue(teacher_queue_directory, foreign_queue)
                responses_path = root / "responses.jsonl"
                report_path = root / "report.json"
                stderr = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    status = main(
                        self._finalize_arguments(
                            queue_path,
                            manifest_path,
                            teacher_queue_directory,
                            root / "missing-verdicts",
                            responses_path,
                            report_path,
                        )
                    )
                self.assertEqual(status, 2)
                self.assertIn(
                    "provenance" if case == "provenance" else "bind",
                    stderr.getvalue(),
                )
                self.assertFalse(responses_path.exists())
                self.assertFalse(report_path.exists())
