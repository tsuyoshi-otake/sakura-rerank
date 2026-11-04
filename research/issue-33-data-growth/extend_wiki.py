"""Execute the disjoint v2 Wikipedia reservation, preserving every v1 artifact."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from extract import authenticate, wiki

ROOT=Path("data/generated/issue-33-data-growth-v2")
PLAN=Path("research/issue-33-data-growth/plan-v2.json")


def bound_plan(commit):
    if len(commit)!=40 or any(c not in "0123456789abcdef" for c in commit):raise ValueError("full_plan_commit_required")
    raw=subprocess.check_output(["git","show",commit+":"+PLAN.as_posix()],timeout=30)
    if raw!=PLAN.read_bytes():raise ValueError("v2_plan_changed")
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def run(commit):
    _,base=authenticate("d2bff3bcbef7e7104fc081e6ee195c1427cd7f4f")
    plan,plan_sha=bound_plan(commit)
    if plan["wikipedia_extension"]["page_sample_slot"]!=1:raise ValueError("unregistered_extension")
    base["jawiki"]["page_sample_slot"]=1
    directory=ROOT/"wiki-extra"
    directory.mkdir(parents=True,exist_ok=False)
    receipt=dict(kind="growth_source_execution",status="failed",mode="wiki-extra",
        plan_commit=commit,plan_sha256=plan_sha,gold_certified=False)
    start=time.monotonic()
    try:
        wiki(directory,base,receipt)
        receipt["status"]="complete"
        return receipt
    except Exception as error:
        receipt["error_type"]=type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(directory/"execution.json",canonical_json_bytes(receipt)+b"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-commit",required=True)
    print(canonical_json_bytes(run(parser.parse_args().plan_commit)).decode("utf-8"))
