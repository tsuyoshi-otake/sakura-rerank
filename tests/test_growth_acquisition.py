"""Synthetic source failures must remain observable without replacement requests."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
import zipfile

DIRECTORY = Path(__file__).resolve().parents[1] / "research/issue-33-data-growth"
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location("growth_acquisition", DIRECTORY / "extract.py")
acquisition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acquisition)
sys.path.remove(str(DIRECTORY))


class AcquisitionTests(unittest.TestCase):
    def execute(self, responses, budget=1024*1024):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        works = [dict(work_id=str(i), url=f"https://www.aozora.gr.jp/cards/1/files/{i}.zip") for i in range(2)]
        opener = MagicMock()
        opener.open.side_effect = responses
        receipt = {}
        plan = {"aozora":dict(max_zip_bytes_per_work=10000,max_total_download_bytes=budget,max_uncompressed_bytes_per_work=10000)}
        with patch.object(acquisition,"read",return_value=works), patch.object(acquisition.urllib.request,"build_opener",return_value=opener), patch.object(acquisition.time,"sleep"):
            try:
                acquisition.download_aozora(directory,plan,receipt)
                error = None
            except ValueError as caught:
                error = caught
        return directory,receipt,opener,error

    def response(self, index, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = f"https://www.aozora.gr.jp/cards/1/files/{index}.zip"
        response.headers = {}
        response.read.side_effect = lambda size: payload[:size]
        return response

    def test_rate_limit_reserves_attempt_and_stops_without_second_work(self):
        error=urllib.error.HTTPError("synthetic",429,"limited",{"Retry-After":"60"},None)
        directory,receipt,opener,caught=self.execute([error])
        self.assertIsNotNone(caught)
        self.assertEqual(opener.open.call_count,1)
        self.assertTrue((directory/"0.attempt.json").exists())
        self.assertFalse((directory/"1.attempt.json").exists())
        self.assertEqual(json.loads((directory/"0.json").read_bytes())["retry_after"],"60")
        self.assertEqual(receipt["counts"]["failed"],1)

    def test_total_byte_budget_stops_acquisition(self):
        directory,receipt,opener,caught=self.execute([self.response(0,b"x"*200)],budget=100)
        self.assertIsInstance(caught,acquisition.DownloadBudgetExceeded)
        self.assertEqual(opener.open.call_count,1)
        self.assertEqual(receipt["downloaded_bytes"],100)
        self.assertEqual(json.loads((directory/"0.json").read_bytes())["status"],"failed")

    def test_invalid_archive_is_counted_and_not_replaced_or_retried(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w") as archive: archive.writestr("body.txt",b"body")
        directory,receipt,opener,caught=self.execute([self.response(0,b"invalid"),self.response(1,buffer.getvalue())])
        self.assertIsNone(caught)
        self.assertEqual(opener.open.call_count,2)
        self.assertEqual(receipt["counts"],{"failed":1,"downloaded":1})
        self.assertTrue((directory/"1.zip").exists())
        self.assertFalse((directory/"0.zip").exists())

    def test_redirects_are_not_followed(self):
        self.assertIsNone(acquisition.NoRedirect().redirect_request(None,None,302,"",{},"https://other.example/"))


if __name__ == "__main__": unittest.main()
