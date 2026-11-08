"""Own immutable unit/ownership diagnostics while preserving the source pilot."""
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0,'research/issue-35-source-pilot')
try:
    from pilot35_common import committed,read,save,sha
    from isolate_pilot import historical_records
finally:
    sys.path.pop(0)

ROOT=Path('data/generated/issue-35-source-units-v1')
HERE=Path('research/issue-35-source-units')
PAST=Path('data/generated/issue-35-source-pilot-v1')
PLAN=HERE/'plan-v1.json'


def authenticate(commit):
    plan=json.loads(committed(PLAN,commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():
        if sha(path)!=digest:raise ValueError('unit35_bound_artifact_changed')
    return plan


def load_script(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
