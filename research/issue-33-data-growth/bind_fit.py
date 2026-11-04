"""Commit-reviewable hashes of every fitted/evaluated input before fitting."""
import json
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from extend_wiki import ROOT,bound_plan
from prepare_sources import sha
from train import FIT_BINDING,PLAN_COMMIT


def run():
    import numpy as np
    import torch
    plan,plan_sha=bound_plan(PLAN_COMMIT)
    manifest=json.loads((ROOT/"cache/manifest.json").read_bytes())
    if manifest["status"]!="complete" or manifest["training_pool_rows"]!=75000 or manifest["evaluation_rows"]!=4000:
        raise ValueError("fixed_numeric_cohorts_incomplete")
    metadata={name:[json.loads(line) for line in (ROOT/"cache"/(name+"-metadata.jsonl")).read_bytes().splitlines()] for name in ("train","evaluation")}
    for key in ("stable_id","component_id"):
        if {r[key] for r in metadata["train"]}&{r[key] for r in metadata["evaluation"]}:raise ValueError("numeric_population_overlap")
    if len(metadata["train"])!=75000 or len(metadata["evaluation"])!=4000:raise ValueError("metadata_denominator_differs")
    for name in metadata:
        for suffix,key in ((".npz","sha256"),("-metadata.jsonl","metadata_sha256")):
            if sha(ROOT/"cache"/(name+suffix))!=manifest["artifacts"][name][key]:raise ValueError("numeric_cache_changed")
    cohorts=json.loads((ROOT/"cache/cohorts.json").read_bytes())
    expected=dict(wiki_small=list(range(12516)),wiki_large=list(range(50000)),mixed=list(range(25000))+list(range(50000,75000)))
    if cohorts!=expected or sha(ROOT/"cache/cohorts.json")!=manifest["cohorts_sha256"]:raise ValueError("cohort_nesting_differs")
    paths=["research/issue-33-data-growth/plan-v2.json","research/issue-33-data-growth/evaluation-v2.json",
        "research/issue-33-data-growth/train.py","research/issue-33-data-growth/evaluate.py",
        "research/issue-33-data-growth/cache.py","research/issue-33-data-growth/candidates.py",
        "research/issue-33-data-growth/env/pyproject.toml","research/issue-33-data-growth/env/uv.lock",
        "src/sakura_rerank/data/growth_numeric.py","src/sakura_rerank/growth_metrics.py",
        "src/sakura_rerank/evaluation_statistics.py","src/sakura_rerank/research_tiny.py",
        "research/issue-21-retrain/run.py","data/generated/issue-21-retrain/run.py",
        "manifests/reference-probe-identity-v1.json","manifests/data-growth-input-reservations-v2.json",
        plan["training"]["initial_checkpoint"]]
    paths += [(ROOT/name).as_posix() for name in ("candidates/execution.json","input-head-before-candidates.json",
        "cache/manifest.json","cache/cohorts.json","cache/train.npz","cache/evaluation.npz",
        "cache/train-metadata.jsonl","cache/evaluation-metadata.jsonl")]
    if sha(Path(plan["training"]["initial_checkpoint"]))!=plan["training"]["initial_checkpoint_sha256"]:
        raise ValueError("initial_checkpoint_changed")
    binding=dict(kind="growth_fit_binding",schema_version=1,plan_commit=PLAN_COMMIT,plan_sha256=plan_sha,
        environment=dict(torch=torch.__version__,numpy=np.__version__,python=sys.version.split()[0]),
        execution=dict(cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0),torch_threads=4,torch_interop_threads=1,
            cublas_workspace_config=":4096:8",per_fit_timeout_seconds=1800,runner_timeout_seconds=7200),
        artifacts=[dict(path=path,sha256=sha(Path(path))) for path in paths],
        cohort_sizes={key:len(value) for key,value in cohorts.items()},training_pool_rows=75000,
        development_rows=4000,source_components_disjoint=True,models_already_fitted=0,
        development_inference_seen=False,independent_gold=False,new_final_test_used=False)
    write_once(FIT_BINDING,canonical_json_bytes(binding)+b"\n")
    print(json.dumps(dict(binding=FIT_BINDING.as_posix(),sha256=sha(FIT_BINDING),environment=binding["environment"],artifacts=len(paths))))


if __name__=="__main__":run()
