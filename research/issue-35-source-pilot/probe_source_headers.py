"""Inspect official export headers only; never read a sentence/transcription body."""
import datetime as dt
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT=Path('data/generated/issue-35-source-pilot-v1')
BASE='https://downloads.tatoeba.org/exports/per_language/jpn/'
FILES={'jpn_sentences_detailed.tsv.bz2':4462456,'jpn_transcriptions.tsv.bz2':4281664}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def run():
    opener=urllib.request.build_opener(NoRedirect)
    report=dict(kind='official_source_header_probe',method='HEAD',body_bytes_read=0,
        snapshot_date='2026-10-31',started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        retries=0,status='failed',requests=[])
    start=time.monotonic()
    try:
        for index,(name,size) in enumerate(FILES.items()):
            if index:time.sleep(1)
            request=urllib.request.Request(BASE+name,method='HEAD',headers={
                'User-Agent':'sakura-rerank-research-source-audit/1.0','Accept-Encoding':'identity'})
            item=dict(file=name,status='failed')
            try:
                with opener.open(request,timeout=30) as response:
                    headers={key.lower():value for key,value in response.headers.items()}
                    item.update(status='complete',http_status=response.status,final_url=response.url,
                        headers={key:headers[key] for key in ('content-length','last-modified','etag','content-type',
                            'content-md5','digest','content-digest','retry-after') if key in headers})
                    if response.url!=BASE+name or response.status!=200 or int(headers.get('content-length',-1))!=size:
                        raise ValueError('official_export_header_contract_changed')
                    if not headers.get('last-modified','').startswith('Sat, 31 Oct 2026 '):
                        raise ValueError('official_export_snapshot_date_changed')
            except urllib.error.HTTPError as error:
                item.update(http_status=error.code,retry_after=error.headers.get('Retry-After'),
                    error_type=type(error).__name__)
                raise
            except Exception as error:
                item.update(status='failed',error_type=type(error).__name__);raise
            finally:
                report['requests'].append(item)
        report['status']='complete'
    except Exception as error:
        report['error_type']=type(error).__name__
    finally:
        report.update(elapsed_seconds=round(time.monotonic()-start,3),not_attempted=2-len(report['requests']),
            finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
        with (ROOT/'header-probe.json').open('xb') as stream:
            stream.write((json.dumps(report,sort_keys=True)+'\n').encode())
    print(json.dumps(report))
    return report['status']=='complete'


if __name__=='__main__':raise SystemExit(0 if run() else 1)
