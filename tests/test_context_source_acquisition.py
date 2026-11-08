import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from sakura_rerank.data.kwdlc_probe import blob_sha1

sys.path.insert(0,"research/issue-40-context-contrast")
try:
    spec=importlib.util.spec_from_file_location("context_source_acquisition_test","research/issue-40-context-contrast/acquire.py")
    acquisition=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acquisition)
finally:
    sys.path.pop(0)


class Response:
    status=200
    def __init__(self,raw,headers=None):self.raw=raw;self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return self.raw[:limit]


class ContextSourceAcquisitionTests(unittest.TestCase):
    def check_fetch(self,raw,headers=None,expected="received"):
        with tempfile.TemporaryDirectory(prefix="context-source-test-") as directory:
            root=Path(directory);(root/"source").mkdir();(root/"receipts").mkdir()
            doc=dict(document_id="synthetic",path="knp/synthetic/synthetic.knp",bytes=4,git_blob_sha1=blob_sha1(b"body"))
            plan=dict(source_commit="fixed",acquisition=dict(timeout_seconds=30,file_bytes_max=1024))
            opener=SimpleNamespace(open=mock.Mock(return_value=Response(raw,headers)))
            with mock.patch.object(acquisition,"ROOT",root),mock.patch.object(acquisition.urllib.request,"build_opener",return_value=opener):
                result=acquisition.fetch_one(0,doc,plan)
            self.assertEqual(result["status"],expected)
            self.assertEqual(opener.open.call_count,1)
            self.assertEqual((root/"source/synthetic.knp").exists(),expected=="received")
            self.assertEqual(json.loads((root/"receipts/document-0000.json").read_bytes()),result)

    def test_exact_blob_is_received_with_terminal_receipt(self):self.check_fetch(b"body")
    def test_blob_mismatch_is_not_saved_or_retried(self):self.check_fetch(b"evil",expected="failed")
    def test_retry_after_even_on_success_status_stops_without_body_save(self):self.check_fetch(b"body",{"Retry-After":"30"},"failed")


if __name__=="__main__":unittest.main()
