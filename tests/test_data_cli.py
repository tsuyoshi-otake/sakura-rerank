from __future__ import annotations

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
from sakura_rerank.data.splitter import split_jsonl

from tests.test_data_contracts import fixture_record


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
