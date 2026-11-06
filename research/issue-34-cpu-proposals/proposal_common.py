"""Fixed-selector proposal bindings, separate from fitting and evaluation."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes

HERE=Path('research/issue-34-cpu-proposals')
ROOT=Path('data/generated/issue-34-cpu-proposals-v1')
CACHE=Path('data/generated/issue-33-annotation-comparison-v1/attempt-02/numeric-r2/cache')
OOF=Path('data/generated/issue-34-oof-design-v1')
LINEAGE=Path('data/generated/issue-34-selector-lineage-v1')
INPUT_NAMES=('context_ids','context_lengths','reading_ids','reading_lengths','candidate_ids','candidate_lengths','features','candidate_mask')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def committed(path,commit):
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('proposal_commit_required')
    raw=subprocess.check_output(['git','show',commit+':'+Path(path).as_posix()],timeout=30)
    if raw!=Path(path).read_bytes():raise ValueError('proposal_committed_bytes_changed')
    return raw


def authenticate(commit):
    plan=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():
        if sha(path)!=digest:raise ValueError('proposal_bound_artifact_changed')
    for path in plan['code']:committed(path,commit)
    if sha(plan['model']['path'])!=plan['model']['sha256']:raise ValueError('proposal_model_changed')
    return plan


def input_arrays(path,expected_sha,*,prepared=False):
    """Read only eight array bodies. Labels in the source archive stay compressed."""
    import numpy as np
    if Path(path).stat().st_size>256*1024*1024:raise ValueError('proposal_archive_byte_bound')
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('proposal_loaded_input_changed')
    expected=set(INPUT_NAMES) if prepared else set(INPUT_NAMES)|{'gold','correct_mask','baseline_equivalent'}
    with np.load(io.BytesIO(raw),allow_pickle=False) as archive:
        if set(archive.files)!=expected:raise ValueError('proposal_archive_schema')
        return {key:archive[key] for key in INPUT_NAMES}


def install_read_guard(allowed):
    # Reuse the already tested Windows-aware training data boundary for inference.
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:from experiment_fit_contract import TrainingReadGuard
    finally:sys.path.pop(0)
    guard=TrainingReadGuard(Path.cwd(),allowed,ROOT);sys.addaudithook(guard)
    return guard


def guard_summary(guard):
    return dict(forbidden_data_reads=guard.blocked,observed_data_paths=sorted(p.relative_to(Path.cwd()).as_posix() for p in guard.observed))
