"""Strict label-free projections for fixed-selector research proposals.

The input is an authenticated source-reconstruction cache. Empty context is an
explicit ablation, not fabricated observed session text. Projected equality
must be added to the source components before a gate experiment can use folds.
"""
import numpy as np

from .data.consumed_numeric import MODEL_FIELDS,schema
from .gate_oof import component_folds


def validate_source_inputs(arrays):
    """Reject labels, malformed masks, nonfinite features and noncanonical padding."""
    if not isinstance(arrays,dict) or set(arrays)!=set(MODEL_FIELDS):
        raise ValueError('proposal_exact_input_fields')
    if not isinstance(arrays['reading_lengths'],np.ndarray) or arrays['reading_lengths'].ndim!=1:
        raise ValueError('proposal_row_shape')
    count=len(arrays['reading_lengths']);expected=schema(count)
    for name in MODEL_FIELDS:
        value=arrays[name];spec=expected[name]
        if (not isinstance(value,np.ndarray) or list(value.shape)!=spec['shape']
            or value.dtype.str!=spec['dtype'] or not value.flags.c_contiguous):
            raise ValueError('proposal_input_schema')
    mask=arrays['candidate_mask'];counts=mask.sum(axis=1)
    if np.any(counts<2) or np.any(counts>6) or not np.array_equal(mask,np.arange(6)[None,:]<counts[:,None]):
        raise ValueError('proposal_candidate_mask')
    if not np.isfinite(arrays['features']).all() or np.any(arrays['features'][~mask]!=0):
        raise ValueError('proposal_features')
    for prefix,minimum,maximum in (('context',8,64),('reading',2,32),('candidate',1,32)):
        ids=arrays[prefix+'_ids'];lengths=arrays[prefix+'_lengths'];active=mask if prefix=='candidate' else np.ones(count,dtype=np.bool_)
        if np.any(lengths[active]<minimum) or np.any(lengths[active]>maximum) or np.any(lengths[~active]!=0):
            raise ValueError('proposal_length')
        positions=np.arange(maximum)<lengths[...,None]
        if np.any(ids[positions]<1) or np.any(ids[positions]>=13312) or np.any(ids[~positions]!=0):
            raise ValueError('proposal_token_or_padding')
    return count


def project_inputs(arrays,condition):
    """Read-only views, with only context IDs and lengths replaced for empty."""
    if condition not in ('source','empty'):raise ValueError('proposal_context_condition')
    validate_source_inputs(arrays)
    result={name:value.view() for name,value in arrays.items()}
    if condition=='empty':
        for name in ('context_ids','context_lengths'):result[name]=np.zeros_like(arrays[name])
    for value in result.values():value.flags.writeable=False
    return result


def projected_folds(records,base_components,numeric_hashes,fold_count=5):
    """Retain complete original components, then join projected-input equality."""
    if len(records)!=len(numeric_hashes) or set(base_components)!={r['row_key'] for r in records}:
        raise ValueError('proposal_projection_denominator')
    projected=[dict(r,component_key=base_components[r['row_key']],numeric_input_key=digest)
        for r,digest in zip(records,numeric_hashes)]
    return component_folds(projected,fold_count)
