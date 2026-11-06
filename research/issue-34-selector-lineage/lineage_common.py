"""Immutable ancestry evidence; historical metadata is not a training input."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes

HERE=Path('research/issue-34-selector-lineage')
ROOT=Path('data/generated/issue-34-selector-lineage-v1')
OLD=Path('data/generated/issue-29-distill-gate')
SOURCE=Path('data/generated/issue-33-annotation-comparison-v1/attempt-02')
CACHE=SOURCE/'numeric-r2/cache'
OOF=Path('data/generated/issue-34-oof-design-v1')
FROZEN=Path('data/generated/issue15-v5-slot120/frozen-split.jsonl')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def rows(path):
    with gzip.open(path,'rb') as stream:
        for line in stream:
            if len(line)>256*1024:raise ValueError('lineage_metadata_line_bound')
            yield json.loads(line)


def write_rows(path,values):
    with Path(path).open('xb') as raw,gzip.GzipFile(fileobj=raw,filename='',mode='wb',mtime=0) as stream:
        for value in values:stream.write(canonical_json_bytes(value)+b'\n')


def committed(path,commit):
    raw=subprocess.check_output(['git','show',commit+':'+Path(path).as_posix()],timeout=30)
    if raw!=Path(path).read_bytes():raise ValueError('lineage_committed_bytes_changed')
    return raw


def legacy():
    path=Path('research/issue-29-distill-gate/run.py')
    if sha(path)!='3533c0c1197868e59003648402d4c13dfa3ec7ef078e25016b95af8879b13c01':
        raise ValueError('lineage_legacy_entry_changed')
    spec=importlib.util.spec_from_file_location('lineage_legacy29',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def source_inventory():
    sys.path.insert(0,'research/issue-32-consumed-source')
    try:import consumption_common
    finally:sys.path.pop(0)
    return consumption_common


def authenticate(commit):
    spec=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**spec['inputs'],**spec['code']}.items():
        if sha(path)!=digest:raise ValueError('lineage_bound_input_changed')
    for path in spec['code']:committed(path,commit)
    return spec
