"""Immutable inputs and write-once private artifacts for the source-only pilot."""
import hashlib
import json
from pathlib import Path
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes

ROOT=Path('data/generated/issue-35-source-pilot-v1')
HERE=Path('research/issue-35-source-pilot')
PLAN=HERE/'plan-v1.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def committed(path,commit):
    if not isinstance(commit,str) or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('pilot35_commit_required')
    key=Path(path).as_posix()
    raw=subprocess.check_output(['git','show',commit+':'+key],timeout=30)
    if raw!=Path(path).read_bytes():raise ValueError('pilot35_committed_bytes_changed')
    return raw


def authenticate(commit):
    plan=json.loads(committed(PLAN,commit))
    for path,digest in plan['code'].items():
        if sha(path)!=digest:raise ValueError('pilot35_code_changed')
    if sha(ROOT/'header-probe.json')!=plan['header_probe_sha256']:
        raise ValueError('pilot35_header_evidence_changed')
    return plan
