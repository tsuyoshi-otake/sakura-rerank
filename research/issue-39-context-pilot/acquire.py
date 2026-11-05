"""Bounded exact-source acquisition; authenticated metadata is reserved first."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.kwdlc_probe import blob_sha1,write_once

ROOT=Path("data/generated/issue-39-context-pilot-v1")
PLAN=Path("research/issue-39-context-pilot/plan-v1.json")
PLAN_COMMIT="0f8c5af08f730b83a1d6352776b0960be2299eda"


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def authenticate():
    if subprocess.check_output(["git","show",PLAN_COMMIT+":"+PLAN.as_posix()],timeout=30)!=PLAN.read_bytes():
        raise ValueError("registered_plan_changed")
    plan=json.loads(PLAN.read_bytes())
    if sha(ROOT/"selection.json")!=plan["selection_sha256"]:raise ValueError("reserved_source_selection_changed")
    selection=json.loads((ROOT/"selection.json").read_bytes())
    old_root=Path("data/generated/issue-31-kwdlc-probe-v1")
    if sha(old_root/"selection.json")!=selection["old_selection_sha256"]:raise ValueError("old_probe_selection_changed")
    if sha(old_root/"train.id")!=plan["membership_sha256"] or sha(old_root/"source-README.md")!=plan["source_readme_sha256"]:
        raise ValueError("source_membership_or_notice_changed")
    ids=set((old_root/"train.id").read_text(encoding="utf8").splitlines())
    old={r["document_id"] for r in json.loads((old_root/"selection.json").read_bytes())["selected_documents"]}
    wanted=sorted(ids-old,key=lambda x:(canonical_json_hash([20261105,x]),x))[:250]
    docs=selection["documents"]
    if len(ids)!=3915 or len(old)!=50 or [r["document_id"] for r in docs]!=wanted:
        raise ValueError("source_membership_selection_differs")
    if selection["corpus_commit"]!=plan["source_commit"] or selection["corpus_tree"]!=plan["source_tree"]:
        raise ValueError("corpus_identity_changed")
    for row in docs:
        parts=row["path"].split("/")
        if len(parts)!=3 or parts[0]!="knp" or parts[2]!=row["document_id"]+".knp" or any(p in ("",".","..") or ":" in p or "\\" in p for p in parts):
            raise ValueError("source_path_invalid")
        if not 0<row["bytes"]<=1024*1024:raise ValueError("source_size_bound")
    return plan,selection


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("source_redirect_refused")


def run():
    plan,selection=authenticate()
    source=ROOT/"source";source.mkdir(exist_ok=False)
    result=dict(kind="context_pilot_acquisition",status="failed",plan_sha256=sha(PLAN),plan_commit=PLAN_COMMIT,
        selection_sha256=sha(ROOT/"selection.json"),script_sha256=sha(__file__),attempts=[],
        replacements=0,automatic_retries=0,source_readme_sha256=plan["source_readme_sha256"],
        independent_test=False,gold_certified=False,model_training=False)
    start=time.monotonic();total=0;stopped=False
    opener=urllib.request.build_opener(NoRedirect())
    try:
        for index,row in enumerate(selection["documents"]):
            entry=dict(index=index,status="not_attempted",git_blob_sha1=row["git_blob_sha1"])
            if not stopped:
                url="https://raw.githubusercontent.com/ku-nlp/KWDLC/"+plan["source_commit"]+"/"+row["path"]
                try:
                    request=urllib.request.Request(url,headers={"User-Agent":"sakura-rerank-research/issue39","Accept":"application/octet-stream"})
                    with opener.open(request,timeout=30) as response:
                        if response.headers.get("Retry-After") is not None:
                            stopped=True;raise ValueError("source_retry_after_stop")
                        raw=response.read(1024*1024+1)
                        if len(raw)!=row["bytes"] or len(raw)>1024*1024 or blob_sha1(raw)!=row["git_blob_sha1"]:
                            stopped=True;raise ValueError("source_identity_or_size_mismatch")
                    total+=len(raw)
                    if total>plan["acquisition"]["total_bytes_max"]:
                        stopped=True;raise ValueError("source_total_bytes_bound")
                    write_once(source/(row["document_id"]+".knp"),raw)
                    entry.update(status="received",sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
                except urllib.error.HTTPError as error:
                    entry.update(status="failed",error_type="HTTPError",http_status=error.code)
                    if error.code in (403,429) or error.headers.get("Retry-After") is not None:stopped=True
                except (urllib.error.URLError,TimeoutError,ValueError,OSError) as error:
                    entry.update(status="failed",error_type=type(error).__name__)
                    if isinstance(error,ValueError):stopped=True
                time.sleep(.2)
            result["attempts"].append(entry)
            if (index+1)%25==0:print(json.dumps(dict(stage="source_acquisition",terminal_documents=index+1,total=250)),flush=True)
        result.update(status="complete",received=sum(e["status"]=="received" for e in result["attempts"]),
                      requested=sum(e["status"]!="not_attempted" for e in result["attempts"]),source_bytes=total)
        return result
    finally:
        result["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(ROOT/"acquisition.json",canonical_json_bytes(result)+b"\n")


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("status","received","requested","source_bytes","elapsed_seconds")}))
