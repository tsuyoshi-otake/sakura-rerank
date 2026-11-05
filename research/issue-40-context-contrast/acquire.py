"""Reserve-first, bounded public-source acquisition with explicit terminal slots."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.kwdlc_probe import blob_sha1, write_once
from feasibility import boundary

ROOT=Path("data/generated/issue-40-context-contrast-v1")
PLAN=Path("research/issue-40-context-contrast/plan-v1.json")
PLAN_COMMIT="864a37588abaae12b07db5d21e8924865fde5c5d"
sha=boundary.sha


def authenticate():
    plan=json.loads(boundary.committed(PLAN,PLAN_COMMIT))
    boundary.authenticate_population()
    if sha(ROOT/"selection.json")!=plan["selection_sha256"]:raise ValueError("reserved_selection_changed")
    selection=json.loads((ROOT/"selection.json").read_bytes())
    old_root=Path("data/generated/issue-31-kwdlc-probe-v1")
    if sha(old_root/"train.id")!=plan["membership_sha256"] or sha(old_root/"source-README.md")!=plan["source_readme_sha256"]:
        raise ValueError("source_membership_or_notice_changed")
    ids=set((old_root/"train.id").read_text(encoding="utf8").splitlines())
    seen={r["document_id"] for r in json.loads((old_root/"selection.json").read_bytes())["selected_documents"]}
    seen.update(r["document_id"] for r in json.loads((boundary.pilot.ROOT/"selection.json").read_bytes())["documents"])
    wanted=sorted(ids-seen,key=lambda d:(canonical_json_hash([20261105,"issue-40-context-contrast-v1",d]),d))[:1000]
    docs=selection["documents"]
    if len(ids)!=3915 or len(seen)!=300 or [d["document_id"] for d in docs]!=wanted:
        raise ValueError("source_reservation_rule_differs")
    if selection["corpus_commit"]!=plan["source_commit"] or selection["corpus_tree"]!=plan["source_tree"]:
        raise ValueError("source_revision_changed")
    for doc in docs:
        parts=doc["path"].split("/")
        if (len(parts)!=3 or parts[0]!="knp" or parts[2]!=doc["document_id"]+".knp"
                or any(p in ("",".","..") or ":" in p or "\\" in p for p in parts)
                or not re.fullmatch(r"[0-9a-f]{40}",doc["git_blob_sha1"])
                or not 0<doc["bytes"]<=plan["acquisition"]["file_bytes_max"]):
            raise ValueError("source_file_contract_differs")
    if sum(d["bytes"] for d in docs)!=plan["expected_source_bytes"]:
        raise ValueError("source_population_size_differs")
    return plan,selection


def fetch_one(index,doc,plan):
    result=dict(index=index,document_id=doc["document_id"],status="failed",downloaded_bytes=0)
    try:
        url="https://raw.githubusercontent.com/ku-nlp/KWDLC/"+plan["source_commit"]+"/"+doc["path"]
        opener=urllib.request.build_opener(boundary.pilot.NoRedirect())
        request=urllib.request.Request(url,headers={"User-Agent":"sakura-rerank-research/issue-40"})
        with opener.open(request,timeout=plan["acquisition"]["timeout_seconds"]) as response:
            if response.status!=200 or response.headers.get("Retry-After") is not None:
                raise ValueError("source_status_or_rate_limit")
            raw=response.read(plan["acquisition"]["file_bytes_max"]+1)
        result["downloaded_bytes"]=len(raw)
        if len(raw)!=doc["bytes"] or blob_sha1(raw)!=doc["git_blob_sha1"]:
            raise ValueError("source_blob_mismatch")
        write_once(ROOT/"source"/(doc["document_id"]+".knp"),raw)
        result.update(status="received",sha256=hashlib.sha256(raw).hexdigest(),git_blob_sha1=doc["git_blob_sha1"])
    except urllib.error.HTTPError as error:
        result.update(error_type="HTTPError",http_status=error.code,retry_after_present=error.headers.get("Retry-After") is not None)
        error.close()
    except (OSError,ValueError) as error:
        result["error_type"]=type(error).__name__
    write_once(ROOT/"receipts"/f"document-{index:04d}.json",canonical_json_bytes(result)+b"\n")
    return result


def run():
    plan,selection=authenticate()
    (ROOT/"source").mkdir(exist_ok=False)
    (ROOT/"receipts").mkdir(exist_ok=False)
    start=time.monotonic();last_start=None;attempts=[]
    receipt=dict(kind="unused_context_source_acquisition",status="failed",plan_commit=PLAN_COMMIT,
        plan_sha256=sha(PLAN),selection_sha256=sha(ROOT/"selection.json"),script_sha256=sha(__file__),
        started_at=datetime.now(timezone.utc).isoformat(),attempts=attempts,retries=0,replacements=0)
    try:
        with ThreadPoolExecutor(max_workers=plan["acquisition"]["concurrency"]) as executor:
            for offset in range(0,len(selection["documents"]),plan["acquisition"]["concurrency"]):
                if time.monotonic()-start>=plan["acquisition"]["run_timeout_seconds"]:
                    receipt["stop_reason"]="RunTimeLimit";break
                futures=[]
                for i,doc in enumerate(selection["documents"][offset:offset+plan["acquisition"]["concurrency"]]):
                    if last_start is not None:
                        delay=plan["acquisition"]["minimum_request_start_interval_seconds"]-(time.monotonic()-last_start)
                        if delay>0:time.sleep(delay)
                    last_start=time.monotonic()
                    futures.append(executor.submit(fetch_one,offset+i,doc,plan))
                wave=[future.result() for future in futures]
                attempts.extend(wave)
                if offset%100==0:print(json.dumps(dict(stage="context_source_acquisition",processed=len(attempts),planned=1000)),flush=True)
                if any(r["status"]!="received" for r in wave):
                    receipt["stop_reason"]="SourceFailure";break
        receipt["status"]="complete" if len(attempts)==1000 and all(r["status"]=="received" for r in attempts) else "partial"
    except Exception as error:
        receipt["error_type"]=type(error).__name__
        raise
    finally:
        attempted={a["index"] for a in attempts}
        for i,doc in enumerate(selection["documents"]):
            if i not in attempted:attempts.append(dict(index=i,document_id=doc["document_id"],status="not_attempted"))
        attempts.sort(key=lambda a:a["index"])
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        receipt["finished_at"]=datetime.now(timezone.utc).isoformat()
        write_once(ROOT/"acquisition.json",canonical_json_bytes(receipt)+b"\n")
    return dict(status=receipt["status"],received=sum(r["status"]=="received" for r in attempts),elapsed_seconds=receipt["elapsed_seconds"])


if __name__=="__main__":print(json.dumps(run()))
