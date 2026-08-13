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
from sakura_rerank.data.__main__ import main
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.corpus_v4 import (
    GATE_A_REVIEWER_ID,
    V4_SCHEMA_VERSION,
    V4_VERDICT_RECORD_TYPE,
    build_gate_a_teacher_batches,
    publish_teacher_queue_directory,
    read_teacher_queue_directory,
    stage3_human_audit_items,
)
from sakura_rerank.data.human_audit import (
    build_queue_manifest,
    publish_audit_queue,
    read_audit_responses,
)
from sakura_rerank.data.splitter import split_jsonl

from tests.test_data_contracts import _rehash_snapshots, fixture_record, production_record


def _write_unassigned_input(path: Path) -> bytes:
    record = fixture_record()
    record["split"] = None
    payload = canonical_json_bytes(record) + b"\n"
    path.write_bytes(payload)
    return payload


class DataCliPathTests(unittest.TestCase):
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


class GateADataCliTests(unittest.TestCase):
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
        self, teacher_queue_directory: Path, verdict_directory: Path
    ) -> None:
        batches, _ = read_teacher_queue_directory(teacher_queue_directory)
        verdict_directory.mkdir()
        for batch in batches:
            payload = {
                "schema_version": V4_SCHEMA_VERSION,
                "record_type": V4_VERDICT_RECORD_TYPE,
                "batch_index": batch["batch_index"],
                "reviewer_kind": "ai_teacher",
                "reviewer_id": GATE_A_REVIEWER_ID,
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
