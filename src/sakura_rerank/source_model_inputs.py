"""Label-free model feeds for authenticated continuous-source research snapshots.

Preserve the existing prefix truncation and expose its consequences. This does
not admit source labels, synthesize session context or change a model contract.
"""
from __future__ import annotations

import math

from . import research_tiny as v1
from . import research_tiny_r2 as r2

INPUT_NAMES = ('context_ids','context_lengths','reading_ids','reading_lengths',
               'candidate_ids','candidate_lengths','features','candidate_mask')


def encode_snapshot(snapshot):
    """Caller authenticates full native bytes; only reading/candidates enter feeds."""
    import numpy as np
    reading=snapshot['reading']
    candidates=snapshot['candidate_snapshots']['production_top6']['candidates']
    training=snapshot['candidate_snapshots']['training_top32']['candidates']
    if (not isinstance(reading,str) or not 1<=len(reading)<=128 or not 1<=len(candidates)<=6
            or candidates!=training[:6]):
        raise ValueError('source_model_candidate_or_reading_contract')
    if any(not isinstance(c['surface'],str) or not 1<=len(c['surface'])<=256
           or not math.isfinite(c['local_cost']) or not 1<=len(c['segments'])<=18 for c in candidates):
        raise ValueError('source_model_candidate_bounds')
    values=dict(context_ids=np.zeros((1,64),dtype=np.int64),context_lengths=np.zeros(1,dtype=np.int64),
        reading_ids=np.zeros((1,32),dtype=np.int64),reading_lengths=np.zeros(1,dtype=np.int64),
        candidate_ids=np.zeros((1,6,32),dtype=np.int64),candidate_lengths=np.zeros((1,6),dtype=np.int64),
        features=np.zeros((1,6,7),dtype=np.float32),candidate_mask=np.zeros((1,6),dtype=np.bool_))
    count=len(candidates);values['candidate_mask'][0,:count]=True
    ids,length=v1.character_ids(reading,32)
    values['reading_ids'][0]=ids;values['reading_lengths'][0]=length
    for index,candidate in enumerate(candidates):
        ids,length=v1.character_ids(candidate['surface'],32)
        values['candidate_ids'][0,index]=ids;values['candidate_lengths'][0,index]=length
    values['features'][0,:count]=r2.candidate_features(reading,candidates)
    if not np.array_equal(values['features'][0,:count,:6],np.asarray(v1.candidate_features(reading,candidates),dtype=np.float32)):
        raise ValueError('source_model_shared_features_differ')
    if not np.isfinite(values['features']).all():raise ValueError('source_model_nonfinite_features')
    pairs=prefix_pairs=hash_pairs=0
    for left in range(count):
        for right in range(left+1,count):
            a,b=candidates[left]['surface'],candidates[right]['surface']
            if a!=b and values['candidate_lengths'][0,left]==values['candidate_lengths'][0,right] and np.array_equal(values['candidate_ids'][0,left],values['candidate_ids'][0,right]):
                pairs+=1
                if a[:32]==b[:32]:prefix_pairs+=1
                else:hash_pairs+=1
    surface_truncations=sum(len(c['surface'])>32 for c in candidates)
    profile=dict(candidate_count=count,reading_characters=len(reading),reading_truncated=len(reading)>32,
        surface_truncations=surface_truncations,any_truncation=len(reading)>32 or bool(surface_truncations),
        encoded_surface_collision_pairs=pairs,same_prefix_collision_pairs=prefix_pairs,hash_collision_pairs=hash_pairs,
        empty_observed_session_context=True)
    return values,profile


def model_feed(arrays,index,feature_dim):
    """One row, exactly eight inputs and one of the two frozen feature widths."""
    import numpy as np
    if feature_dim not in (6,7) or type(index) is not int or not 0<=index<len(arrays['reading_lengths']):
        raise ValueError('source_model_feed_contract')
    result={name:np.ascontiguousarray(arrays[name][index:index+1]) for name in INPUT_NAMES}
    result['features']=np.ascontiguousarray(result['features'][:,:,:feature_dim])
    return result
