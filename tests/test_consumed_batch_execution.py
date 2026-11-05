import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, "research/issue-49-consumed-contrast")
try:
    import batch_execution as batch
finally:
    sys.path.pop(0)


class ConsumedBatchExecutionTests(unittest.TestCase):
    def requests(self, count):
        return [dict(stable_id=f"request-{i}", reading="よみ") for i in range(count)]

    def execute(self, root, requests, validator=None, **kwargs):
        return batch.execute_batches(requests, root/"candidates", {}, root/"native.exe", root/"dictionary",
            validator or (lambda directory, raw, identity: [json.loads(line) for line in raw.splitlines()]), **kwargs)

    def success(self, command, **kwargs):
        output = Path(command[command.index("--output")+1])
        output.write_bytes(b"synthetic")
        return SimpleNamespace(returncode=0)

    def test_batch_bound_and_every_request_are_accounted(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.subprocess, "run", side_effect=self.success) as run:
            result, records = self.execute(Path(directory), self.requests(101))
            self.assertEqual(run.call_count, 2)
            self.assertEqual([a["request_count"] for a in result["attempts"]], [100, 1])
            self.assertEqual(result["request_outcomes"], {"complete": 101})
            self.assertEqual(len(records), 101)
            self.assertEqual(result["not_attempted"], 0)

    def test_known_rejection_keeps_whole_batch_unmeasured_without_retry(self):
        calls = 0
        def run(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                kwargs["stderr"].write(batch.REJECTION); kwargs["stderr"].flush()
                return SimpleNamespace(returncode=2)
            return self.success(command, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.subprocess, "run", side_effect=run):
            result, records = self.execute(Path(directory), self.requests(101))
            self.assertEqual(result["request_outcomes"], {"candidate_count_rejected": 100, "complete": 1})
            self.assertEqual(len(records), 1)
            self.assertEqual(calls, 2)

    def test_timeout_stops_and_preserves_unattempted_tail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.subprocess, "run", side_effect=subprocess.TimeoutExpired("native", 30)):
            result, records = self.execute(Path(directory), self.requests(101))
            self.assertEqual(result["request_outcomes"], {"failed": 100})
            self.assertEqual(result["not_attempted"], 1)
            self.assertEqual(result["stop_reason"], "UnexpectedBatchFailure")
            self.assertEqual(records, {})

    def test_invalid_validation_publishes_no_partial_records(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.subprocess, "run", side_effect=self.success):
            result, records = self.execute(Path(directory), self.requests(2), validator=lambda *args: [])
            self.assertEqual(result["request_outcomes"], {"failed": 2})
            self.assertEqual(records, {})

    def test_duplicate_requests_are_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                self.execute(root, self.requests(1)*2)
            self.assertFalse((root/"candidates").exists())

    def test_receipt_failure_has_an_observable_attempted_terminal(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(batch, "execute_batch", side_effect=OSError("synthetic")):
            result, records = self.execute(Path(directory), self.requests(101))
            self.assertEqual(result["request_outcomes"], {"failed_without_receipt": 100})
            self.assertEqual(result["not_attempted"], 1)
            self.assertEqual(records, {})


if __name__ == "__main__":
    unittest.main()
