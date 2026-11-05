"""Separate training-byte authentication from protected evaluation inputs."""
import json
from pathlib import Path

from language_common import ROOT,PLAN,boundary,sha,read_json

BINDING=Path("manifests/language-fit-v1.json")


def authenticate(commit,*,evaluation=False):
    bound=json.loads(boundary.committed(BINDING,commit))
    if bound!=read_json(ROOT/"fit-binding.json"):raise ValueError("language_fit_binding_changed")
    plan=json.loads(boundary.committed(PLAN,bound["plan_commit"]))
    if sha(PLAN)!=bound["plan_sha256"]:raise ValueError("language_plan_changed")
    paths=dict(bound["training_artifacts"]);paths.update(bound["code"])
    if evaluation:paths.update(bound["evaluation_artifacts"])
    for path,expected in paths.items():
        if sha(path)!=expected:raise ValueError("bound_language_artifact_changed:"+str(path))
    return plan,bound
