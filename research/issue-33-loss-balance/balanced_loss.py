"""The single intervention: train-derived source/class weights on unchanged C2 CE."""
import numpy as np


def source_class_weights(baseline_correct, cohorts, group_rows=25000):
    if set(cohorts)!={'dictionary','annotation'} or baseline_correct.ndim!=1 or baseline_correct.dtype!=np.bool_:
        raise ValueError('balance_weight_inputs')
    sets={k:set(map(int,v)) for k,v in cohorts.items()}
    if any(len(v)!=2*group_rows or len(cohorts[k])!=len(v) for k,v in sets.items()):
        raise ValueError('balance_weight_arm_size')
    common=sets['dictionary']&sets['annotation']
    d=np.array(sorted(sets['dictionary']-common),dtype=np.int64)
    a=np.array(sorted(sets['annotation']-common),dtype=np.int64)
    if (len(common)!=group_rows or len(d)!=group_rows or len(a)!=group_rows
            or sets['dictionary']|sets['annotation']!=set(range(len(baseline_correct)))):
        raise ValueError('balance_weight_cohort_partition')
    d_correct=int(baseline_correct[d].sum());a_correct=int(baseline_correct[a].sum())
    if not 0<d_correct<group_rows or not 0<a_correct<group_rows:
        raise ValueError('balance_weight_both_classes_required')
    correct_ratio=d_correct/a_correct
    error_ratio=(group_rows-d_correct)/(group_rows-a_correct)
    weights=np.ones(len(baseline_correct),dtype=np.float32)
    weights[a]=np.where(baseline_correct[a],correct_ratio,error_ratio).astype(np.float32)
    if not np.isfinite(weights).all() or not (weights>0).all():
        raise ValueError('balance_weight_positive_finite')
    result=dict(rows_per_source=group_rows,dictionary_aozora_correct=d_correct,annotation_aozora_correct=a_correct,
        dictionary_aozora_error=group_rows-d_correct,annotation_aozora_error=group_rows-a_correct,
        correct_weight=correct_ratio,error_weight=error_ratio,
        annotation_correct_weight_mass=float(weights[a[baseline_correct[a]]].sum(dtype=np.float64)),
        annotation_error_weight_mass=float(weights[a[~baseline_correct[a]]].sum(dtype=np.float64)),
        annotation_total_weight_mass=float(weights[cohorts['annotation']].sum(dtype=np.float64)),
        common_wikipedia_weights_unchanged=bool((weights[list(common)]==1).all()),
        normalization='Arithmetic batch mean of weighted per-example losses; no per-batch weight-sum normalization.')
    return weights,result


def weighted_c2_loss(scores,gold,mask,weights):
    import torch
    from torch.nn import functional
    if (scores.ndim!=2 or scores.shape[1]!=6 or mask.shape!=scores.shape or mask.dtype!=torch.bool
            or gold.shape!=(len(scores),) or weights.shape!=(len(scores),) or not len(scores)):
        raise ValueError('balance_loss_shapes')
    if (not bool(mask.any(dim=1).all()) or not bool(mask.gather(1,gold[:,None]).all())
            or not bool(torch.isfinite(weights).all()) or not bool((weights>0).all())):
        raise ValueError('balance_loss_label_or_weight')
    log_probs=torch.log_softmax(scores,dim=1)
    valid=mask.to(log_probs.dtype)
    target=valid*(0.05/valid.sum(dim=1,keepdim=True))
    target=target+0.95*functional.one_hot(gold,6).to(log_probs.dtype)
    return (-(target*log_probs).sum(dim=1)*weights).mean()
