"""Reproduce aggregate source evidence without publishing source texts or IDs."""
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from prepare_sources import ROOT,sha


def run():
    paths={"reservation":"source-preparation.json","wikipedia":"wiki/execution.json",
        "aozora_acquisition":"aozora-download/execution.json","aozora_extraction":"aozora-extract/execution.json",
        "isolation":"isolation/execution.json","relation_diagnostic":"isolation-diagnostic.json",
        "context8_counterfactual":"isolation-diagnostic-context8.json"}
    results={key:json.loads((ROOT/path).read_bytes()) for key,path in paths.items()}
    isolation=results["isolation"]
    if isolation["status"]!="insufficient_fixed_cohort_yield" or isolation["models_trained"]!=0:
        raise ValueError("v1_outcome_changed")
    n=sum(results[key]["target_count"] for key in ("wikipedia","aozora_extraction"))
    if sum(isolation["audit"]["counts"].values())!=n:raise ValueError("source_denominator_differs")
    result=dict(kind="growth_source_reassessment",issue=33,parent_issue=1,
        status="v1_stopped_before_fitting_v2_separately_registered",source_targets=n,
        evidence=results,artifacts={key:dict(path=(ROOT/path).as_posix(),sha256=sha(ROOT/path)) for key,path in paths.items()},
        source_script_sha256=sha(Path(__file__)),gold_certified=False,new_final_test_used=False,
        accuracy_improvement_measured=False,safety_threshold=0.0025,
        v2_plan_commit="1ca3fb4ff9670d1cd12f21e4d87f6bb975248415")
    raw=canonical_json_bytes(result)+b"\n"
    destination=Path("reports/issue-33-data-growth-source-v1.json")
    if destination.exists():
        if destination.read_bytes()!=raw:raise ValueError("published_source_report_differs")
    else:write_once(destination,raw)
    print(json.dumps(dict(report=destination.as_posix(),sha256=sha(destination),matches=True,source_targets=n)))


if __name__=="__main__":run()
