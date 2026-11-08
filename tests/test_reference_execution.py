import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location("shared_reference_execution_test","research/reference_execution.py")
execution=importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)


class ReferenceExecutionTests(unittest.TestCase):
    def test_known_rejection_has_receipt_but_never_a_candidate_record(self):
        with tempfile.TemporaryDirectory(prefix="reference-execution-test-") as directory:
            def reject(*args,**kwargs):
                kwargs["stderr"].write(execution.REJECTION)
                return SimpleNamespace(returncode=2)
            with mock.patch.object(execution.subprocess,"run",side_effect=reject):
                outcome,record=execution.execute_request(Path(directory)/"one",0,dict(stable_id="one",reading="あ。"),{},Path("converter"),Path("dictionary"),mock.Mock(),30)
            self.assertEqual(outcome["status"],"candidate_count_rejected")
            self.assertIsNone(record)
            self.assertTrue((Path(directory)/"one/execution.json").is_file())

    def test_failed_finalization_stops_and_is_not_reported_as_unattempted(self):
        with tempfile.TemporaryDirectory(prefix="reference-execution-test-") as directory:
            requests=[dict(stable_id=str(i),reading="あ") for i in range(5)]
            with mock.patch.object(execution,"execute_request",side_effect=OSError("synthetic receipt failure")) as worker:
                result,records=execution.execute_requests(requests,Path(directory)/"output",{},Path("converter"),Path("dictionary"),mock.Mock())
            self.assertEqual(worker.call_count,2)
            self.assertEqual(len(result["attempts"]),2)
            self.assertTrue(all(r["status"]=="failed_without_receipt" for r in result["attempts"]))
            self.assertEqual(result["not_attempted"],3)
            self.assertEqual(result["stop_reason"],"UnexpectedRequestFailure")
            self.assertEqual(records,{})

    def test_known_rejections_continue_once_per_input_under_fixed_waves(self):
        with tempfile.TemporaryDirectory(prefix="reference-execution-test-") as directory:
            requests=[dict(stable_id=str(i),reading="あ") for i in range(5)]
            def reject(directory,index,*args):return dict(index=index,status="candidate_count_rejected"),None
            with mock.patch.object(execution,"execute_request",side_effect=reject) as worker:
                result,records=execution.execute_requests(requests,Path(directory)/"output",{},Path("converter"),Path("dictionary"),mock.Mock())
            self.assertEqual(worker.call_count,5)
            self.assertEqual([r["index"] for r in result["attempts"]],list(range(5)))
            self.assertEqual(result["not_attempted"],0)
            self.assertIsNone(result["stop_reason"])

    def test_duplicate_or_excessive_concurrency_is_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory(prefix="reference-execution-test-") as directory:
            output=Path(directory)/"output"
            args=({},Path("converter"),Path("dictionary"),mock.Mock())
            with self.assertRaises(ValueError):execution.execute_requests([dict(stable_id="same")]*2,output,*args)
            with self.assertRaises(ValueError):execution.execute_requests([],output,*args,concurrency=3)
            self.assertFalse(output.exists())


if __name__=="__main__":unittest.main()
