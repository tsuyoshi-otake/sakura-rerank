"""Acquire exactly two date/ETag-bound official exports, with no semantic reads."""
import argparse
import datetime as dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from pilot35_common import ROOT,PLAN,authenticate,save,sha


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def run(commit):
    plan=authenticate(commit);spec=plan['acquisition'];output=ROOT/'exports';output.mkdir(exist_ok=False)
    save(ROOT/'acquisition-reservation.json',dict(plan_commit=commit,plan_sha256=sha(PLAN),
        snapshot=plan['snapshot'],requests=len(spec['files']),semantic_content_reads=0))
    start=time.monotonic();opener=urllib.request.build_opener(NoRedirect)
    result=dict(kind='dated_official_export_acquisition',status='failed',plan_commit=commit,
        plan_sha256=sha(PLAN),snapshot=plan['snapshot'],started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        attempts=[],automatic_retries=0,semantic_content_reads=0,official_cryptographic_digest_provided=False,
        artifact_trust='provisional_official_https_export_not_gold_or_calibration_admitted')
    try:
        for index,file in enumerate(spec['files']):
            if index:time.sleep(spec['minimum_request_interval_seconds'])
            item=dict(file=file['name'],status='failed',bytes_received=0)
            target=output/(file['name']+'.part');digest=hashlib.sha256()
            try:
                request=urllib.request.Request(file['url'],headers={'User-Agent':'sakura-rerank-research-source-audit/1.0',
                    'Accept-Encoding':'identity','If-Match':file['etag'],'If-Unmodified-Since':file['last_modified']})
                with opener.open(request,timeout=spec['request_timeout_seconds']) as response:
                    headers={k.lower():v for k,v in response.headers.items()}
                    item.update(http_status=response.status,etag=headers.get('etag'),last_modified=headers.get('last-modified'))
                    if (response.url!=file['url'] or response.status!=200 or headers.get('etag')!=file['etag']
                            or headers.get('last-modified')!=file['last_modified']
                            or int(headers.get('content-length',-1))!=file['bytes']):
                        raise ValueError('pilot35_dated_export_identity_changed')
                    with target.open('xb') as stream:
                        while True:
                            if time.monotonic()-start>spec['total_timeout_seconds']:raise TimeoutError('pilot35_acquisition_deadline')
                            block=response.read(65536)
                            if not block:break
                            item['bytes_received']+=len(block)
                            if item['bytes_received']>file['bytes']:raise ValueError('pilot35_export_byte_bound')
                            digest.update(block);stream.write(block)
                        stream.flush();os.fsync(stream.fileno())
                if item['bytes_received']!=file['bytes']:raise ValueError('pilot35_incomplete_export')
                os.rename(target,output/file['name'])
                item.update(status='complete',sha256=digest.hexdigest())
            except urllib.error.HTTPError as error:
                item.update(error_type=type(error).__name__,http_status=error.code,retry_after=error.headers.get('Retry-After'))
                raise
            except Exception as error:
                item['error_type']=type(error).__name__;raise
            finally:
                result['attempts'].append(item)
                print(json.dumps(dict(stage='dated_source_export',slot=index,status=item['status'],bytes_received=item['bytes_received'])),flush=True)
        authenticate(commit);result['status']='complete'
    except Exception as error:
        result['error_type']=type(error).__name__
    finally:
        result.update(elapsed_seconds=round(time.monotonic()-start,3),not_attempted=2-len(result['attempts']),
            finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
        save(ROOT/'acquisition.json',result)
    return {k:result[k] for k in ('status','elapsed_seconds','not_attempted','artifact_trust')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan-commit',required=True)
    outcome=run(parser.parse_args().plan_commit);print(json.dumps(outcome))
    raise SystemExit(0 if outcome['status']=='complete' else 1)
