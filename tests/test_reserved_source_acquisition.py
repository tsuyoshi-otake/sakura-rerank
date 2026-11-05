import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("reserved_source_test","research/reserved_source_acquisition.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ReservedSourceAcquisitionTests(unittest.TestCase):
    def plan(self):return dict(source_commit="a"*40,acquisition=dict(concurrency=1,timeout_seconds=1,run_timeout_seconds=10,
        minimum_request_start_interval_seconds=.25,file_bytes_max=1024,total_bytes_max=10000))
    def docs(self):return [dict(document_id=str(i),path=f"knp/a/{i}.knp",bytes=4,git_blob_sha1="b"*40) for i in range(3)]

    def test_failure_stops_and_all_reserved_slots_are_terminal(self):
        with tempfile.TemporaryDirectory(prefix="reserved-source-test-") as temp:
            with patch.object(module,"fetch_one",return_value=dict(index=0,document_id="0",status="failed")) as fetch:
                result=module.acquire(Path(temp),self.docs(),self.plan(),{})
            self.assertEqual(fetch.call_count,1)
            self.assertEqual([r["status"] for r in result["attempts"]],["failed","not_attempted","not_attempted"])
            self.assertEqual(result["status"],"partial")

    def test_receipt_failure_remains_attempted_and_finalization_is_owned(self):
        with tempfile.TemporaryDirectory(prefix="reserved-source-test-") as temp:
            with patch.object(module,"fetch_one",side_effect=OSError("synthetic receipt failure")):
                with self.assertRaises(OSError):module.acquire(Path(temp),self.docs(),self.plan(),{})
            result=json.loads((Path(temp)/"acquisition.json").read_bytes())
            self.assertEqual([r["status"] for r in result["attempts"]],["failed_without_receipt","not_attempted","not_attempted"])

    def test_traversal_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory(prefix="reserved-source-test-") as temp:
            docs=self.docs();docs[0]["path"]="knp/../0.knp"
            with self.assertRaises(ValueError):module.acquire(Path(temp),docs,self.plan(),{})
            self.assertFalse((Path(temp)/"source").exists())


if __name__=="__main__":unittest.main()
