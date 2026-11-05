import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("boundary_test_common", "research/issue-31-input-boundary/common.py")
with mock.patch.dict(sys.modules, {"common": common}):
    forward = load("boundary_test_forward", "research/issue-31-input-boundary/forward.py")
    isolated = load("boundary_test_isolated", "research/issue-31-input-boundary/isolated_forward.py")
    publication = load("boundary_test_publication", "research/issue-31-input-boundary/publish.py")


class InputBoundaryExecutionTests(unittest.TestCase):
    def test_composed_top1_counts_exact_output_even_if_segment_boundaries_shift(self):
        view = dict(status="ready", parts=[dict(kind="convert", request_id="one", target="橋"),
                                          dict(kind="convert", request_id="two", target="の道")])
        candidates = {"one": [dict(surface="橋の")], "two": [dict(surface="道")]}
        self.assertTrue(publication.composed_top1(view, candidates))
        self.assertIsNone(publication.composed_top1(view, {"one": candidates["one"]}))
        self.assertFalse(publication.composed_top1(view, {"one": candidates["one"], "two": []}))

    def failure_case(self, result, validation_failure=False):
        with tempfile.TemporaryDirectory(prefix="boundary-execution-test-") as directory:
            root = Path(directory)
            (root/"new-requests.jsonl").write_bytes(common.jsonl([dict(stable_id=str(i), reading="あ") for i in range(205)]))
            (root/"targets.jsonl").write_bytes(b"")
            plan = dict(bounds=dict(batch=100, batch_timeout_seconds=120, run_timeout_seconds=600))
            with (mock.patch.object(forward, "ROOT", root),
                  mock.patch.object(forward, "authenticate_population", return_value=(plan, [], {})),
                  mock.patch.object(forward, "authenticate_input", return_value=dict(reused_requests=0)),
                  mock.patch.object(forward, "identity", return_value={}),
                  mock.patch.object(forward, "load_old_snapshots", return_value={}),
                  mock.patch.object(forward, "aggregate", return_value=dict(slots=205)),
                  mock.patch.object(forward.subprocess, "run", side_effect=result if isinstance(result, Exception) else None,
                                    return_value=result) as process,
                  mock.patch.object(forward.native, "validate_result", side_effect=ValueError("invalid_snapshot")) as validate,
                  mock.patch("builtins.print")):
                summary = forward.run("fixed-input-commit")
            receipt = json.loads((root/"execution.json").read_bytes())
            self.assertEqual(summary["status"], "partial")
            self.assertEqual(process.call_count, 1)
            self.assertEqual(validate.call_count, int(validation_failure))
            self.assertEqual(receipt["failed_requests"], 100)
            self.assertEqual(receipt["not_attempted_requests"], 105)
            self.assertEqual(receipt["measured_new_requests"], 0)
            self.assertEqual(len(receipt["batches"]), 1)
            self.assertEqual(receipt["batches"][0]["status"], "failed")
            self.assertTrue((root/"candidates/batch-000/execution.json").is_file())
            self.assertFalse((root/"candidates/batch-001").exists())

    def test_timeout_stops_without_retry_and_accounts_for_unattempted_inputs(self):
        self.failure_case(subprocess.TimeoutExpired("synthetic", 120))

    def test_nonzero_exit_is_a_terminal_failed_batch(self):
        self.failure_case(SimpleNamespace(returncode=1))

    def test_invalid_snapshot_stops_even_when_native_exit_was_zero(self):
        self.failure_case(SimpleNamespace(returncode=0), validation_failure=True)

    def test_isolated_known_rejection_keeps_no_candidate_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="boundary-isolated-test-") as directory:
            root = Path(directory)
            (root/"candidates").mkdir()
            def rejected(*args, **kwargs):
                kwargs["stderr"].write(isolated.EXPECTED_ERROR)
                return SimpleNamespace(returncode=2)
            with (mock.patch.object(isolated, "R2", root),
                  mock.patch.object(isolated.subprocess, "run", side_effect=rejected)):
                receipt, record = isolated.execute_one(0, dict(stable_id="synthetic", reading="あ。"), {}, 30)
            self.assertEqual(receipt["status"], "candidate_count_rejected")
            self.assertIsNone(record)
            self.assertFalse((root/"candidates/request-0000/output.jsonl").exists())

    def test_isolated_unknown_error_does_not_use_known_rejection_path(self):
        with tempfile.TemporaryDirectory(prefix="boundary-isolated-test-") as directory:
            root = Path(directory)
            (root/"candidates").mkdir()
            with (mock.patch.object(isolated, "R2", root),
                  mock.patch.object(isolated.subprocess, "run", return_value=SimpleNamespace(returncode=2))):
                receipt, record = isolated.execute_one(0, dict(stable_id="synthetic", reading="あ"), {}, 30)
            self.assertEqual(receipt["status"], "failed")
            self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
