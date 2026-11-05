"""Separate fit permission and train-only reads from evaluation authentication."""
import hashlib
import io
import json
import os
from pathlib import Path

from sakura_rerank.data.consumed_numeric import LABEL_FIELDS,MODEL_FIELDS,tensor_hash,validate_arrays,verify_chain
from sakura_rerank.data.contracts import canonical_json_hash
from experiment_common import ROOT,HERE,TRAIN_CACHE,boundary,read,sha

BINDING=HERE/'fit-binding-v1.json'
MODEL_CODE=Path('data/generated/issue-21-retrain/run.py')


def authenticated_bytes(path,digest,maximum=512*1024*1024):
    path=Path(path)
    if path.stat().st_size>maximum:raise ValueError('fit_artifact_byte_bound')
    with path.open('rb') as stream:raw=stream.read(maximum+1)
    if len(raw)>maximum or hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError('fit_authenticated_bytes_changed')
    return raw


def authenticate_fit(commit,*,evaluation=False):
    bound=json.loads(boundary.committed(BINDING,commit))
    if bound!=read(ROOT/'fit-binding.json') or bound['purpose']!='paired_source_reconstruction_fit':
        raise ValueError('fit_binding_or_purpose_changed')
    plan=json.loads(boundary.committed(bound['plan_path'],bound['plan_commit']))
    if sha(bound['plan_path'])!=bound['plan_sha256']:
        raise ValueError('fit_frozen_plan_changed')
    paths=dict(bound['training_artifacts']);paths.update(bound['code'])
    if evaluation:paths.update(bound['evaluation_artifacts'])
    for path,digest in paths.items():
        if sha(path)!=digest:raise ValueError('fit_bound_artifact_changed')
    return plan,bound


class TrainingReadGuard:
    """Refuse data reads outside bound train files and this run's model output."""
    def __init__(self,workspace,allowed,output):
        self.workspace=Path(workspace).resolve()
        self.data_roots=tuple((self.workspace/p).resolve() for p in ('data/generated','data/downloads'))
        self.allowed={Path(p).resolve() for p in allowed}
        self.output=Path(output).resolve()
        self.observed=set();self.blocked=0

    def check(self,path,mode,flags=0):
        if not isinstance(path,(str,bytes,os.PathLike)):return
        access_mask=os.O_WRONLY|os.O_RDWR
        reading=('r' in mode or '+' in mode) if isinstance(mode,str) else (flags&access_mask)!=os.O_WRONLY
        if not reading:return
        resolved=Path(os.fsdecode(path)).resolve()
        if not any(resolved.is_relative_to(root) for root in self.data_roots):return
        if resolved in self.allowed or resolved.is_relative_to(self.output):
            self.observed.add(resolved);return
        self.blocked+=1
        raise ValueError('evaluation_or_unbound_data_read_forbidden_during_fit')

    def __call__(self,event,args):
        if event=='open':self.check(*args)


def reference(bound):
    # Preserve the original generated-file location used by the frozen harness.
    raw=authenticated_bytes(MODEL_CODE,bound['code'][MODEL_CODE.as_posix()],4*1024*1024)
    namespace={'__name__':'annotation_fixed_c2','__file__':str(MODEL_CODE.resolve())}
    exec(compile(raw,str(MODEL_CODE),'exec'),namespace)
    from types import SimpleNamespace
    return SimpleNamespace(**namespace)


def load_training(bound):
    import numpy as np
    files=bound['training_artifacts']
    cache=json.loads(authenticated_bytes(TRAIN_CACHE/'manifest.json',files[(TRAIN_CACHE/'manifest.json').as_posix()]))
    if (cache['rows']!=75000 or cache['status']!='prepared_unverified'
            or cache['training_eligible'] is not False or cache['independent_gold_eligible'] is not False
            or cache['consumer']!='numeric_verification_only_until_separate_committed_fit_binding'):
        raise ValueError('fit_source_reconstruction_cache_contract')
    raw=authenticated_bytes(TRAIN_CACHE/'arrays.npz',files[(TRAIN_CACHE/'arrays.npz').as_posix()])
    with np.load(io.BytesIO(raw),allow_pickle=False) as saved:
        arrays={name:np.array(saved[name]) for name in saved.files}
    validate_arrays(arrays,75000)
    ledger=verify_chain(authenticated_bytes(TRAIN_CACHE/'row-receipts.jsonl',files[(TRAIN_CACHE/'row-receipts.jsonl').as_posix()]),
                        75000,cache['row_chain_head'])
    if canonical_json_hash([r['origin']['stable_id'] for r in ledger])!=cache['source_order_sha256']:
        raise ValueError('fit_training_order_changed')
    for i,row in enumerate(ledger):
        if (row['origin']['training_eligible'] is not False or row['origin']['independent_gold_eligible'] is not False
                or row['input_tensor_sha256']!=tensor_hash(arrays,i,MODEL_FIELDS)
                or row['label_tensor_sha256']!=tensor_hash(arrays,i,LABEL_FIELDS)):
            raise ValueError('fit_training_row_provenance_changed')
    indices=json.loads(authenticated_bytes(TRAIN_CACHE/'cohort-indices.json',files[(TRAIN_CACHE/'cohort-indices.json').as_posix()]))
    if (set(indices)!={'dictionary','annotation'} or any(len(v)!=50000 or len(set(v))!=50000 for v in indices.values())
            or indices['dictionary'][:25000]!=indices['annotation'][:25000]
            or set().union(*(set(v) for v in indices.values()))!=set(range(75000))
            or any(profile['source_counts']!={'jawiki':25000,'aozora':25000} for profile in cache['profiles'].values())):
        raise ValueError('fit_fixed_cohort_contract')
    return arrays,{key:np.asarray(value,dtype=np.int64) for key,value in indices.items()},cache
