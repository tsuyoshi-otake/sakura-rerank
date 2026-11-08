"""Bound inputs for the single loss-weight comparison; prior experiments immutable."""
import json
from pathlib import Path
import sys

sys.path.insert(0,'research/issue-33-annotation-experiment')
try:
    import experiment_common as previous
finally:
    sys.path.pop(0)

ROOT=Path('data/generated/issue-33-loss-balance-v1')
HERE=Path('research/issue-33-loss-balance')
PLAN=HERE/'plan-v1.json'
PAST=previous.ROOT
boundary=previous.boundary
read=previous.read
save=previous.save
sha=previous.sha
rows=previous.rows
write_rows=previous.write_rows


def authenticate(commit):
    plan=json.loads(boundary.committed(PLAN,commit))
    for path,digest in plan['inputs'].items():
        if sha(path)!=digest:raise ValueError('balance_bound_input_changed')
    if sha(plan['evaluation']['selection_path'])!=plan['evaluation']['selection_sha256']:
        raise ValueError('balance_source_reservation_changed')
    return plan
