"""Own the new fit permission; reuse the immutable training-reader contract."""
import io
import json

from balance_common import ROOT,HERE,PLAN,previous,boundary,read,sha

PLAN_COMMIT='8ea14eed349b375a63b09c744d3bf40c15ee196b'
BINDING=HERE/'fit-binding-v1.json'
TRAIN_CACHE=previous.TRAIN_CACHE
legacy=boundary.load_script('loss_balance_legacy_fit_contract',
    'research/issue-33-annotation-experiment/experiment_fit_contract.py')
MODEL_CODE=legacy.MODEL_CODE
authenticated_bytes=legacy.authenticated_bytes
load_training=legacy.load_training
reference=legacy.reference
TrainingReadGuard=legacy.TrainingReadGuard


def authenticate_fit(commit,*,evaluation=False):
    bound=json.loads(boundary.committed(BINDING,commit))
    if bound!=read(ROOT/'fit-binding.json') or bound['purpose']!='fixed_loss_contribution_fit':
        raise ValueError('balance_fit_binding_or_purpose_changed')
    plan=json.loads(boundary.committed(PLAN,PLAN_COMMIT))
    if sha(PLAN)!=bound['plan_sha256'] or bound['plan_commit']!=PLAN_COMMIT:
        raise ValueError('balance_fit_plan_changed')
    paths=dict(bound['training_artifacts']);paths.update(bound['code'])
    if evaluation:paths.update(bound['evaluation_artifacts'])
    for path,digest in paths.items():
        if sha(path)!=digest:raise ValueError('balance_fit_artifact_changed')
    return plan,bound


def load_weights(bound,arrays,cohorts):
    import numpy as np
    from balanced_loss import source_class_weights
    path=ROOT/'training-weights.npy'
    raw=authenticated_bytes(path,bound['training_artifacts'][path.as_posix()])
    weights=np.load(io.BytesIO(raw),allow_pickle=False)
    expected,statistics=source_class_weights(arrays['correct_mask'][:,0],cohorts)
    if (weights.dtype!=np.float32 or not np.array_equal(weights,expected)
            or statistics!=bound['weight_derivation']):
        raise ValueError('balance_training_weights_changed')
    return weights
