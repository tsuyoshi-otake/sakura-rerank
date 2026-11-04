"""Prove historical inputs and separately bound research inputs remain unchanged."""
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from prepare_sources import ROOT as V1_ROOT,SOURCES,sha
from extend_wiki import ROOT
from train import authenticate_fit

FIT_COMMIT="ad976a7f4515a80ff2602e8153b3decb35e37f6f"


def run():
    binding,plan=authenticate_fit(FIT_COMMIT)
    original=json.loads((V1_ROOT/"source-preparation.json").read_bytes())
    paths={item["path"]:item["sha256"] for item in original["history_sources"]}
    for (manifest,_),item in zip(SOURCES,original["history_sources"]):paths["manifests/"+manifest]=item["checkout_manifest_sha256"]
    base=json.loads(Path("research/issue-33-data-growth/plan-v1.json").read_bytes())
    paths[base["jawiki"]["path"]]=base["jawiki"]["sha256"]
    paths["data/generated/issue15-v5-slot120/frozen-split.jsonl"]="0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"
    paths["data/generated/system-dictionary-index.jsonl"]="4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072"
    paths[plan["training"]["initial_checkpoint"]]=plan["training"]["initial_checkpoint_sha256"]
    checks=[]
    for path,expected in paths.items():
        if sha(Path(path))!=expected:raise ValueError("original_artifact_changed")
        checks.append(dict(path=path,sha256=expected,unchanged=True))
    result=dict(kind="growth_historical_integrity",status="passed",original_artifact_checks=checks,
        bound_fit_artifacts=len(binding["artifacts"]),fit_commit=FIT_COMMIT,
        old_evaluation_labels_decoded=False,new_final_test_used=False)
    raw=canonical_json_bytes(result)+b"\n";destination=ROOT/"original-integrity.json"
    if destination.exists():
        if destination.read_bytes()!=raw:raise ValueError("integrity_report_differs")
    else:write_once(destination,raw)
    print(json.dumps(dict(status="passed",original_artifacts=len(checks),bound_fit_artifacts=len(binding["artifacts"]),report_sha256=sha(destination))))


if __name__=="__main__":run()
