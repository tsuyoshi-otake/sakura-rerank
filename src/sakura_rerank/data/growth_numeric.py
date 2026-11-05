"""Explicit weak-supervision adapter for the fixed C2 feature contract."""
from .. import research_tiny as tiny


def eligible_target(target, candidates):
    matches=[i for i,c in enumerate(candidates[:6]) if c["surface"]==target]
    if len(candidates)<2:return False,"fewer_than_two_candidates"
    if len(matches)!=1:return False,"source_target_missing_or_nonunique_top6"
    if any(s["source_category"]!="system_dictionary" for s in candidates[matches[0]]["segments"]):
        return False,"source_target_non_dictionary_path"
    return True,"eligible"


def encode(targets, snapshots):
    """No legacy validation bypass: these arrays remain separately bound research."""
    import numpy as np
    arrays=tiny._empty_split_arrays(len(targets))
    arrays["features"]=np.zeros((len(targets),6,7),dtype=np.float32)
    arrays["correct_mask"]=np.zeros((len(targets),6),dtype=np.bool_)
    arrays["baseline_equivalent"]=np.zeros((len(targets),6),dtype=np.bool_)
    metadata=[]
    for i,row in enumerate(targets):
        snapshot=snapshots.get(row["candidate_request_id"])
        candidates=[] if snapshot is None else snapshot["candidate_snapshots"]["training_top32"]["candidates"]
        top=candidates[:6]
        arrays["context_ids"][i],arrays["context_lengths"][i]=tiny.character_ids(row["left_context"],64)
        arrays["reading_ids"][i],arrays["reading_lengths"][i]=tiny.character_ids(row["reading"],32)
        if top:
            arrays["features"][i,:len(top),:6]=tiny.candidate_features(row["reading"],top)
            costs=np.asarray([float(c["local_cost"]) for c in top],dtype=np.float64)
            arrays["features"][i,:len(top),6]=-np.log1p(np.maximum(costs-costs.min(),0.0)/1000.0).astype(np.float32)
            arrays["candidate_mask"][i,:len(top)]=True
        matches=[]
        for j,candidate in enumerate(top):
            arrays["candidate_ids"][i,j],arrays["candidate_lengths"][i,j]=tiny.character_ids(candidate["surface"],32)
            arrays["correct_mask"][i,j]=candidate["surface"]==row["target"]
            arrays["baseline_equivalent"][i,j]=candidate["surface"]==top[0]["surface"]
            if candidate["surface"]==row["target"]:matches.append(j)
        arrays["gold"][i]=matches[0] if matches else -1
        metadata.append(dict(stable_id=row["stable_id"],component_id=row["component_id"],corpus=row["corpus"],
            reading_chars=len(row["reading"]),context_chars=len(row["left_context"]),candidate_count=len(top),
            acquisition_status="complete" if snapshot is not None else "failed",
            source_exact_presence={str(k):any(c["surface"]==row["target"] for c in candidates[:k]) for k in (1,5,6,10,32)},
            candidate_surfaces_truncated=sum(len(c["surface"])>32 for c in top)))
    return arrays,metadata
