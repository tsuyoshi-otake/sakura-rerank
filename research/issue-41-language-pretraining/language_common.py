"""Pinned prior contracts and a separate write-once language experiment root."""
import json
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once

sys.path.insert(0,"research/issue-40-context-contrast")
try:
    import model_common as context_model
    import history as context_history
    import forward as context_forward
    from feasibility import boundary
    from evaluate_models import cluster_ids,uncertainty,context_arrays
finally:sys.path.pop(0)

ROOT=Path("data/generated/issue-41-language-pretraining-v1")
PLAN=Path("research/issue-41-language-pretraining/plan-v1.json")
PRIOR_ROOT=Path("data/generated/issue-40-context-contrast-v1")
TRAIN_ROOT=context_model.TRAIN_ROOT
sha=boundary.sha
jsonl=boundary.jsonl


def read_json(path):return json.loads(Path(path).read_bytes())
def rows(path):
    with Path(path).open("rb") as stream:
        for line in stream:yield json.loads(line)


def save(path,value):
    path=Path(path);raw=canonical_json_bytes(value)+b"\n"
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError("immutable_artifact_differs")
    else:write_once(path,raw)


def authenticate_prior():
    context_model.authenticate("2f3c86640d5509aeb9c619485f8607c59eb8e373")
    bound=read_json("manifests/context-contrast-cohort-v1.json")
    prep=read_json(PRIOR_ROOT/"preparation.json")
    for name,expected in prep["artifacts"].items():
        if sha(PRIOR_ROOT/(name+".jsonl"))!=expected:raise ValueError("prior_context_preparation_changed")
    for name,extension in (("selected",".jsonl"),("main-terminal",".jsonl"),("source-relations",".json")):
        if sha(PRIOR_ROOT/(name+extension))!=bound["artifacts"][name]:raise ValueError("prior_context_cohort_changed")
    return bound


def bound_plan(commit):
    plan=json.loads(boundary.committed(PLAN,commit))
    if sha(ROOT/"selection.json")!=plan["selection_sha256"]:raise ValueError("language_selection_changed")
    authenticate_prior()
    return plan
