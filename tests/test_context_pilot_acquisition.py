"""Acquisition contracts exercise stop/failure accounting without network access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

SPEC=importlib.util.spec_from_file_location("pilot_acquisition_contract",Path(__file__).resolve().parents[1]/"research/issue-39-context-pilot/acquire.py")
acquire=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(acquire)


class FakeResponse:
    def __init__(self,raw=b"wrong",headers=None):self.raw=raw;self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return self.raw[:limit]


class ContextPilotAcquisitionTests(unittest.TestCase):
    def exercise(self,opener):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            docs=[dict(document_id=f"w201106-{i:010d}",path=f"knp/a/w201106-{i:010d}.knp",git_blob_sha1="a"*40,bytes=5) for i in range(250)]
            plan=dict(source_commit="b"*40,source_readme_sha256="c"*64,acquisition=dict(total_bytes_max=262144000))
            with patch.object(acquire,"ROOT",root),patch.object(acquire,"authenticate",return_value=(plan,dict(documents=docs))),patch.object(acquire,"sha",return_value="d"*64),patch.object(acquire.urllib.request,"build_opener",return_value=opener),patch.object(acquire.time,"sleep"),patch("builtins.print"):
                result=acquire.run()
            saved=json.loads((root/"acquisition.json").read_bytes())
            self.assertEqual(saved,result)
            self.assertEqual(len(result["attempts"]),250)
            self.assertEqual(result["requested"],1)
            self.assertEqual(result["received"],0)
            self.assertEqual(sum(x["status"]=="not_attempted" for x in result["attempts"]),249)
            self.assertEqual(list((root/"source").iterdir()),[])
            return result

    def test_rate_limit_has_no_retry_and_all_remaining_documents_terminal(self):
        class Opener:
            def open(self,*args,**kwargs):raise urllib.error.HTTPError("https://example.invalid",429,"limited",{"Retry-After":"30"},None)
        result=self.exercise(Opener())
        self.assertEqual(result["attempts"][0]["http_status"],429)
        self.assertEqual(result["automatic_retries"],0)

    def test_hash_mismatch_stops_without_publishing_source(self):
        class Opener:
            def open(self,*args,**kwargs):return FakeResponse()
        result=self.exercise(Opener())
        self.assertEqual(result["attempts"][0]["error_type"],"ValueError")

    def test_retry_after_on_success_stops_before_body_is_accepted(self):
        class Opener:
            def open(self,*args,**kwargs):return FakeResponse(headers={"Retry-After":"30"})
        self.exercise(Opener())


if __name__=="__main__":unittest.main()
