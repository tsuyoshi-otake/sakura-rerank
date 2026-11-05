"""Immutable experiment identities and fixed reference architecture access."""
import json
from pathlib import Path
import sys

from sakura_rerank.context_conditioned import build_context_conditioned
from acquire import ROOT,sha
from feasibility import boundary

PLAN=Path("research/issue-40-context-contrast/model_plan.json")
BINDING=Path("manifests/context-model-fit-v1.json")
H21=Path("data/generated/issue-21-retrain/run.py")
H21_SHA="d0e24a57ccf9d5a1aa5fc3c9de0b3ff4ef8124bd15c126fc47c9c3bfbf55216d"
TRAIN_ROOT=Path("data/generated/issue-33-data-growth-v2")


def reference():
    if sha(H21)!=H21_SHA or sha("research/issue-21-retrain/run.py")!=H21_SHA:raise ValueError("reference_model_code_changed")
    return boundary.load_script("context_fixed_c2",H21)


def growth_training():
    sys.path.insert(0,"research/issue-33-data-growth")
    try:return boundary.load_script("context_fixed_training_recipe","research/issue-33-data-growth/train.py")
    finally:sys.path.pop(0)


def build(harness,architecture):
    if architecture=="c2":return harness.build_model("C2")
    if architecture=="context_initialized":return build_context_conditioned(lambda:harness.build_model("C2"))
    raise ValueError("unknown_registered_architecture")


def authenticate(commit):
    plan=json.loads(boundary.committed(PLAN,commit))
    raw=boundary.committed(BINDING,commit)
    if raw!=(ROOT/"model-fit-binding.json").read_bytes():raise ValueError("local_model_binding_differs")
    bound=json.loads(raw)
    if sha(PLAN)!=bound["plan_sha256"]:raise ValueError("model_plan_binding_differs")
    for path,expected in bound["artifacts"].items():
        if sha(path)!=expected:raise ValueError("model_bound_artifact_changed")
    return plan,bound
