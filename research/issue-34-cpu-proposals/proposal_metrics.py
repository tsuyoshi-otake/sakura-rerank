"""Empirical information limits of fixed numeric inputs, not Gold accuracy."""
from collections import defaultdict
import numpy as np


def input_ceiling(hashes,correct,positions):
    if correct.ndim!=2 or correct.shape!=(len(hashes),6) or correct.dtype!=np.bool_:
        raise ValueError('proposal_ceiling_label_shape')
    if len(set(map(int,positions)))!=len(positions) or any(not 0<=int(i)<len(hashes) for i in positions):
        raise ValueError('proposal_ceiling_population')
    buckets=defaultdict(list)
    for i in positions:buckets[hashes[int(i)]].append(int(i))
    irreducible=conflicting=conflict_rows=variations=duplicates=0
    for members in buckets.values():
        values=correct[members];count=len(members);best=int(values.sum(axis=0).max())
        lost=count-best;irreducible+=lost;conflicting+=lost>0;conflict_rows+=count if lost else 0;duplicates+=count>1
        variations+=len({r.tobytes() for r in values})>1
    count=len(positions)
    return dict(rows=count,unique_inputs=len(buckets),duplicate_groups=duplicates,duplicate_excess=count-len(buckets),
        label_variation_groups=variations,incompatible_label_groups=conflicting,rows_in_incompatible_groups=conflict_rows,
        unavoidable_source_mismatches=irreducible,maximum_source_matches=count-irreducible,
        empirical_source_match_ceiling=None if not count else (count-irreducible)/count,
        scope='Oracle bound for a deterministic selector of these exact numeric inputs and fixed source labels; not an independently estimated IME accuracy ceiling.')
