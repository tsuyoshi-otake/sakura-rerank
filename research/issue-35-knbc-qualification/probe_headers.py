"""One bounded official HEAD probe; no corpus body is requested."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

URL = 'https://nlp.ist.i.kyoto-u.ac.jp/kuntt/KNBC_v1.0_090925_utf8.tar.bz2'
ROOT = Path('data/generated/issue-35-knbc-qualification-v1/attempt-01')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    reservation = ROOT/'header-reservation.json'
    if reservation.exists(): raise ValueError('header_reservation_exists')
    request = dict(url=URL, method='HEAD', request_timeout_seconds=30, retries=0,
                   redirects=False, body_requested=False, owner_pid=os.getpid(),
                   requested_at_utc=datetime.now(timezone.utc).isoformat())
    with reservation.open('xb') as stream:
        stream.write(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()+b'\n')
    print(json.dumps(dict(status='running', owner_pid=os.getpid())), flush=True)
    started = time.monotonic(); result = dict(request, status='failed')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        req = urllib.request.Request(URL, method='HEAD', headers={'User-Agent':'Sakura-Rerank-source-qualification/1', 'Accept-Encoding':'identity'})
        with opener.open(req, timeout=30) as response:
            size = response.headers.get('Content-Length')
            if response.status != 200 or response.geturl() != URL or not size or not size.isdecimal() or not 0 < int(size) <= 16*1024*1024:
                raise ValueError('header_response_contract')
            result.update(status='complete', http_status=response.status, bytes=int(size),
                content_type=response.headers.get('Content-Type'), etag=response.headers.get('ETag'),
                last_modified=response.headers.get('Last-Modified'), official_cryptographic_digest=None,
                qualification='official_https_metadata_only_not_dataset_admission')
    except urllib.error.HTTPError as error:
        result.update(error_type='HTTPError', http_status=error.code, retry_after=error.headers.get('Retry-After'))
    except Exception as error:
        result['error_type'] = type(error).__name__
    result['elapsed_seconds'] = round(time.monotonic()-started, 3)
    with (ROOT/'headers.json').open('xb') as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()+b'\n')
    print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
