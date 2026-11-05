"""Acquire the #41 reservation; no replacement or automatic retry."""
import argparse
import json
from language_common import ROOT,PLAN,bound_plan,read_json,sha,boundary

PLAN_COMMIT="057b2cee79c2b8ada5e9c584e60ba7625fee7637"


def run(implementation_commit):
    plan=bound_plan(PLAN_COMMIT);selection=read_json(ROOT/"selection.json")
    for path in ("research/issue-41-language-pretraining/acquire_sources.py","research/reserved_source_acquisition.py"):
        boundary.committed(path,implementation_commit)
    executor=boundary.load_script("language_reserved_sources","research/reserved_source_acquisition.py")
    result=executor.acquire(ROOT,selection["documents"],plan,dict(plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),
        selection_sha256=sha(ROOT/"selection.json"),implementation_commit=implementation_commit,
        executor_sha256=sha("research/reserved_source_acquisition.py"),script_sha256=sha(__file__)))
    return dict(status=result["status"],received=sum(r["status"]=="received" for r in result["attempts"]),elapsed_seconds=result["elapsed_seconds"])


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--implementation-commit",required=True)
    print(json.dumps(run(parser.parse_args().implementation_commit)))
