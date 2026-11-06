"""Frozen v1/r2 mathematics applied to observed native pre-fusion path edges."""
from __future__ import annotations

from . import native_paths


def legacy_feature_candidates(candidates):
    """Semantic projection, not a legacy exporter/dataset provenance certificate."""
    values=[]
    for candidate in candidates:
        categories={s['source_category'] for s in candidate['path']['segments']}
        values.append(dict(rank=candidate['rank'],surface=candidate['surface'],local_cost=candidate['local_cost'],
                           source_category=next(iter(categories)) if len(categories)==1 else 'mixed',
                           segments=candidate['path']['segments']))
    return values


def encode_request(request,feature_width):
    import numpy as np
    from . import research_tiny as v1, research_tiny_r2 as r2
    candidates=native_paths.validate_input(request)
    if type(feature_width) is not int or feature_width not in (6,7) or len(candidates)>6:
        raise ValueError('native path model shape differs')
    values=dict(context_ids=np.zeros((1,64),dtype=np.int64),context_lengths=np.zeros(1,dtype=np.int64),
                reading_ids=np.zeros((1,32),dtype=np.int64),reading_lengths=np.zeros(1,dtype=np.int64),
                candidate_ids=np.zeros((1,6,32),dtype=np.int64),candidate_lengths=np.zeros((1,6),dtype=np.int64),
                features=np.zeros((1,6,feature_width),dtype=np.float32),candidate_mask=np.zeros((1,6),dtype=np.bool_))
    ids,length=v1.character_ids(request['reading'],32)
    values['reading_ids'][0]=ids;values['reading_lengths'][0]=length
    for index,candidate in enumerate(candidates):
        ids,length=v1.character_ids(candidate['surface'],32)
        values['candidate_ids'][0,index]=ids;values['candidate_lengths'][0,index]=length
    features=(v1.candidate_features if feature_width==6 else r2.candidate_features)(request['reading'],legacy_feature_candidates(candidates))
    values['features'][0,:len(candidates)]=features
    values['candidate_mask'][0,:len(candidates)]=True
    if not np.isfinite(values['features']).all():raise ValueError('native path features are not finite')
    return values


def native_gru_factory(artifacts,feature_width):
    from .evaluation_worker import validate_gru,cpu_session,cpu_scores
    validate_gru(artifacts,feature_width)
    session=cpu_session(artifacts['weights'],feature_width)
    class Scorer:
        def score(self,request):return cpu_scores(session,encode_request(request,feature_width))
        def close(self):pass
    return Scorer()
