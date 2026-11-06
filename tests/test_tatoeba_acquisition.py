"""Network-failure contracts using synthetic in-memory responses only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


HERE=Path(__file__).resolve().parents[1]/'research/issue-35-source-pilot'
sys.path.insert(0,str(HERE))
try:
    spec=importlib.util.spec_from_file_location('pilot35_acquisition_contract',HERE/'acquire_dated_exports.py')
    acquire=importlib.util.module_from_spec(spec);spec.loader.exec_module(acquire)
finally:
    sys.path.pop(0)


class Response(io.BytesIO):
    def __init__(self,body=b'abc',*,etag='"fixture"',url='https://example.invalid/a',status=200,size='3'):
        super().__init__(body)
        self.status=status;self.url=url
        self.headers={'ETag':etag,'Last-Modified':'fixture-date','Content-Length':size}


class Opener:
    def __init__(self,responses):self.responses=list(responses);self.calls=[]
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        value=self.responses.pop(0)
        if isinstance(value,Exception):raise value
        return value


class TatoebaAcquisitionTests(unittest.TestCase):
    def execute(self,responses):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        root=Path(folder.name);opener=Opener(responses)
        files=[dict(name=name,url='https://example.invalid/a',bytes=3,etag='"fixture"',last_modified='fixture-date')
               for name in ('a.bz2','b.bz2')]
        plan=dict(snapshot='synthetic',acquisition=dict(files=files,minimum_request_interval_seconds=0,
                  request_timeout_seconds=30,total_timeout_seconds=60))
        with patch.object(acquire,'ROOT',root),patch.object(acquire,'authenticate',return_value=plan),\
             patch.object(acquire,'sha',return_value='0'*64),patch.object(acquire.urllib.request,'build_opener',return_value=opener),\
             contextlib.redirect_stdout(io.StringIO()):
            result=acquire.run('1'*40)
        receipt=json.loads((root/'acquisition.json').read_bytes())
        return root,opener,result,receipt

    def test_complete_is_still_provisional_and_requests_are_conditional(self):
        root,opener,result,receipt=self.execute([Response(),Response()])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(opener.calls),2)
        self.assertEqual(opener.calls[0][0].get_header('If-match'),'"fixture"')
        self.assertEqual(opener.calls[0][0].get_header('If-unmodified-since'),'fixture-date')
        self.assertFalse(receipt['official_cryptographic_digest_provided'])
        self.assertEqual((root/'exports/a.bz2').read_bytes(),b'abc')

    def test_rate_limit_retains_failed_slot_and_does_not_retry(self):
        error=urllib.error.HTTPError('https://example.invalid/a',429,'synthetic',{'Retry-After':'120'},None)
        root,opener,result,receipt=self.execute([error,Response()])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(len(opener.calls),1)
        self.assertEqual(receipt['attempts'][0]['retry_after'],'120')
        self.assertEqual(receipt['not_attempted'],1)
        self.assertFalse((root/'exports/a.bz2').exists())

    def test_refusal_does_not_attempt_second_file(self):
        error=urllib.error.HTTPError('https://example.invalid/a',403,'synthetic',{},None)
        _,opener,_,receipt=self.execute([error])
        self.assertEqual(len(opener.calls),1)
        self.assertEqual(receipt['attempts'][0]['http_status'],403)

    def test_changed_source_identity_fails_before_body_read(self):
        for response in (Response(etag='"different"'),Response(url='https://example.invalid/b'),
                         Response(size='4'),Response(status=206)):
            with self.subTest():
                root,opener,result,receipt=self.execute([response])
                self.assertEqual(result['status'],'failed')
                self.assertEqual(receipt['attempts'][0]['bytes_received'],0)
                self.assertFalse((root/'exports/a.bz2').exists())
                self.assertEqual(len(opener.calls),1)

    def test_truncated_or_oversize_body_is_not_published(self):
        for body in (b'ab',b'abcd'):
            with self.subTest():
                root,_,result,receipt=self.execute([Response(body)])
                self.assertEqual(result['status'],'failed')
                self.assertEqual(receipt['not_attempted'],1)
                self.assertFalse((root/'exports/a.bz2').exists())
                self.assertTrue((root/'exports/a.bz2.part').exists())

    def test_second_file_failure_keeps_first_provisional_and_terminal(self):
        root,_,result,receipt=self.execute([Response(),TimeoutError('synthetic')])
        self.assertEqual(result['status'],'failed')
        self.assertEqual([r['status'] for r in receipt['attempts']],['complete','failed'])
        self.assertTrue((root/'exports/a.bz2').exists())
        self.assertFalse((root/'exports/b.bz2').exists())


if __name__=='__main__':unittest.main()
