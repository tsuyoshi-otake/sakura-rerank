from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.__main__ import main
from sakura_rerank.data.contracts import canonical_json_bytes

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
