"""Write-once source-consumption artifacts and exact committed evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes

ROOT = Path('data/generated/issue-35-source-consumption-v1')
HERE = Path('research/issue-35-source-consumption')
PAST = Path('data/generated/issue-35-source-pilot-v1')
UNITS = Path('data/generated/issue-35-source-units-v1')
PLAN = HERE/'plan-v1.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n')


def committed(path, commit):
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('consumption_commit_required')
    raw = subprocess.check_output(['git', 'show', commit+':'+Path(path).as_posix()], timeout=30)
    if raw != Path(path).read_bytes():
        raise ValueError('consumption_committed_bytes_changed')
    return raw


def authenticate(commit):
    plan = json.loads(committed(PLAN, commit))
    for path, digest in {**plan['inputs'], **plan['code']}.items():
        if sha(path) != digest:
            raise ValueError('consumption_bound_artifact_changed')
    return plan


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
