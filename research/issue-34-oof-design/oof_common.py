"""Bound, write-once metadata evidence; no permission to fit a new model."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes

HERE=Path('research/issue-34-oof-design')
ROOT=Path('data/generated/issue-34-oof-design-v1')
CACHE=Path('data/generated/issue-33-annotation-comparison-v1/attempt-02/numeric-r2/cache')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def committed(path,commit):
    if not isinstance(commit,str) or re.fullmatch('[0-9a-f]{40}',commit) is None:raise ValueError('oof_commit_required')
    raw=subprocess.check_output(['git','show',commit+':'+Path(path).as_posix()],timeout=30)
    if raw!=Path(path).read_bytes():raise ValueError('oof_committed_bytes_changed')
    return raw


def authenticate(commit):
    plan=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():
        if sha(path)!=digest:raise ValueError('oof_bound_artifact_changed')
    for path in plan['code']:committed(path,commit)
    return plan
