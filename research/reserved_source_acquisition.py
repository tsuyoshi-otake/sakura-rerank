"""Bounded acquisition of a committed Git-blob reservation, with terminal slots."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import blob_sha1,write_once


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError("source_redirect_rejected")


def fetch_one(root,index,doc,plan):
    result=dict(index=index,document_id=doc["document_id"],status="failed",downloaded_bytes=0)
    try:
        url="https://raw.githubusercontent.com/ku-nlp/KWDLC/"+plan["source_commit"]+"/"+doc["path"]
        request=urllib.request.Request(url,headers={"User-Agent":"sakura-rerank-reserved-research"})
        opener=urllib.request.build_opener(NoRedirect())
        with opener.open(request,timeout=plan["acquisition"]["timeout_seconds"]) as response:
            if response.status!=200 or response.headers.get("Retry-After") is not None:raise ValueError("source_status_or_rate_limit")
            raw=response.read(plan["acquisition"]["file_bytes_max"]+1)
        result["downloaded_bytes"]=len(raw)
        if len(raw)!=doc["bytes"] or blob_sha1(raw)!=doc["git_blob_sha1"]:raise ValueError("source_blob_mismatch")
        write_once(root/"source"/(doc["document_id"]+".knp"),raw)
        result.update(status="received",sha256=hashlib.sha256(raw).hexdigest(),git_blob_sha1=doc["git_blob_sha1"])
    except urllib.error.HTTPError as error:
        result.update(error_type="HTTPError",http_status=error.code,retry_after_present=error.headers.get("Retry-After") is not None)
        error.close()
    except (OSError,ValueError) as error:result["error_type"]=type(error).__name__
    write_once(root/"receipts"/f"document-{index:04d}.json",canonical_json_bytes(result)+b"\n")
    return result


def acquire(root,documents,plan,identity):
    root=Path(root);settings=plan["acquisition"];concurrency=settings["concurrency"]
    if (concurrency not in (1,2) or not 1<=len(documents)<=2000 or not 0<settings["timeout_seconds"]<=30
            or not 0<settings["run_timeout_seconds"]<=900 or settings["minimum_request_start_interval_seconds"]<.25
            or not re.fullmatch(r"[0-9a-f]{40}",plan["source_commit"])):raise ValueError("source_execution_bounds")
    seen=set()
    for doc in documents:
        parts=doc["path"].split("/");name=doc["document_id"]
        if (name in seen or not re.fullmatch(r"[A-Za-z0-9_-]+",name) or len(parts)!=3 or parts[0]!="knp" or parts[2]!=name+".knp"
                or any(p in ("",".","..") or ":" in p or "\\" in p for p in parts)
                or not re.fullmatch(r"[0-9a-f]{40}",doc["git_blob_sha1"]) or not 0<doc["bytes"]<=settings["file_bytes_max"]):
            raise ValueError("reserved_source_path_or_size")
        seen.add(name)
    if sum(d["bytes"] for d in documents)+concurrency*(settings["file_bytes_max"]+1)>settings["total_bytes_max"]:
        raise ValueError("reserved_source_total_size")
    (root/"source").mkdir(exist_ok=False);(root/"receipts").mkdir(exist_ok=False)
    attempts=[];scheduled=set();start=time.monotonic();last=None
    receipt=dict(kind="reserved_source_acquisition",status="failed",identity=identity,attempts=attempts,retries=0,replacements=0,
        started_at=datetime.now(timezone.utc).isoformat())
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for offset in range(0,len(documents),concurrency):
                if time.monotonic()-start>=settings["run_timeout_seconds"]:receipt["stop_reason"]="RunTimeLimit";break
                pending=[]
                for i,doc in enumerate(documents[offset:offset+concurrency],offset):
                    if last is not None:
                        delay=settings["minimum_request_start_interval_seconds"]-(time.monotonic()-last)
                        if delay>0:time.sleep(delay)
                    last=time.monotonic();scheduled.add(i)
                    pending.append(pool.submit(fetch_one,root,i,doc,plan))
                wave=[future.result() for future in pending];attempts.extend(wave)
                if offset%100==0:print(json.dumps(dict(stage="reserved_source_acquisition",processed=len(attempts),planned=len(documents))),flush=True)
                if any(r["status"]!="received" for r in wave):receipt["stop_reason"]="SourceFailure";break
        receipt["status"]="complete" if len(attempts)==len(documents) and all(a["status"]=="received" for a in attempts) else "partial"
    except Exception as error:receipt["error_type"]=type(error).__name__;raise
    finally:
        attempted={a["index"] for a in attempts}
        for i,doc in enumerate(documents):
            if i in attempted:continue
            path=root/"receipts"/f"document-{i:04d}.json"
            if i in scheduled and path.is_file():attempts.append(json.loads(path.read_bytes()))
            else:attempts.append(dict(index=i,document_id=doc["document_id"],status="failed_without_receipt" if i in scheduled else "not_attempted"))
        attempts.sort(key=lambda a:a["index"])
        receipt.update(elapsed_seconds=round(time.monotonic()-start,3),finished_at=datetime.now(timezone.utc).isoformat())
        write_once(root/"acquisition.json",canonical_json_bytes(receipt)+b"\n")
    return receipt
