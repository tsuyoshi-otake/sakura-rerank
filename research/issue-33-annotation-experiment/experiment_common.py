"""Bound paired experiment inputs; no protected evaluation access during fitting."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, 'research/issue-33-annotation-comparison')
try:
    import comparison_common as preparation
finally:
    sys.path.pop(0)

ROOT = Path('data/generated/issue-33-annotation-experiment-v1')
HERE = Path('research/issue-33-annotation-experiment')
EXECUTION_PLAN = HERE/'execution-plan-v1.json'
PREPARATION_ROOT = preparation.ROOT
TRAIN_CACHE = PREPARATION_ROOT/'numeric-r2/cache'
boundary = preparation.prior.boundary
read = preparation.read
sha = preparation.sha
save = preparation.save
rows = preparation.rows
write_rows = preparation.write_rows


def authenticate(commit):
    spec = json.loads(boundary.committed(EXECUTION_PLAN, commit))
    plan = preparation.authenticate()
    for path, digest in spec['inputs'].items():
        if sha(path) != digest:
            raise ValueError('experiment_preparation_binding_changed')
    return plan, spec


def implementation(paths):
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=15).strip()
    for path in paths:
        boundary.committed(path, head)
    return head, {str(path).replace('\\', '/'): sha(path) for path in paths}


def jsonl(values):
    return boundary.jsonl(values)
