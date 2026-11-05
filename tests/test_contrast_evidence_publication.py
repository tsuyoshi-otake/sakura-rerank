"""Immutable evidence publication must preserve existing and partial files."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def load_recovery():
    directory = Path(__file__).resolve().parents[1] / "research/issue-48-contrast-data"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("test_ruby_recovery_publication", directory / "recover_ruby.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class ContrastEvidencePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recovery = load_recovery()

    def test_identical_replay_preserves_bytes_and_tail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(self.recovery, "ROOT", Path(directory)):
            first = self.recovery.write_supplement([{"stable_id": "synthetic-a"}], "0" * 64)
            path = Path(directory) / "evidence.jsonl"
            before = path.read_bytes()
            second = self.recovery.write_supplement([{"stable_id": "synthetic-a"}], "0" * 64)
            self.assertEqual(first, second)
            self.assertEqual(before, path.read_bytes())
            self.assertFalse((Path(directory) / "evidence.pending").exists())

    def test_correction_requires_a_new_supplement(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(self.recovery, "ROOT", Path(directory)):
            self.recovery.write_supplement([{"stable_id": "synthetic-a"}], "0" * 64)
            path = Path(directory) / "evidence.jsonl"
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "immutable_supplement"):
                self.recovery.write_supplement([{"stable_id": "synthetic-b"}], "0" * 64)
            self.assertEqual(before, path.read_bytes())
            self.assertFalse((Path(directory) / "evidence.pending").exists())

    def test_unowned_pending_file_is_not_deleted_on_open_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(self.recovery, "ROOT", Path(directory)):
            pending = Path(directory) / "evidence.pending"
            pending.write_bytes(b"existing recovery evidence")
            with self.assertRaises(FileExistsError):
                self.recovery.write_supplement([{"stable_id": "synthetic-a"}], "0" * 64)
            self.assertEqual(pending.read_bytes(), b"existing recovery evidence")
            self.assertFalse((Path(directory) / "evidence.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
