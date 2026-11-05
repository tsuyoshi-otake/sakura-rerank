"""Fixed three-seed mean with shared source draws and explicit harm guard."""
from sakura_rerank.evaluation_statistics import paired_component_bootstrap


def mean_seed_comparison(component_ids,differences,harm_differences,*,inference_complete):
    import numpy as np
    values=np.asarray(differences);harms=np.asarray(harm_differences)
    if (values.shape!=(3,len(component_ids)) or values.dtype.kind not in 'iu'
            or not len(component_ids) or np.any(values < -1) or np.any(values > 1)
            or harms.shape!=(3,) or harms.dtype.kind not in 'iu'):
        raise ValueError('balance_paired_seed_indicator_shape')
    counts=[[int(value),1] for seed in values for value in seed]
    interval=paired_component_bootstrap(list(component_ids)*3,counts,
        {'mean_accuracy_difference':(0,1)},replicates=2000,seed=20261106)
    point=float(values.mean());per_seed=[float(row.mean()) for row in values]
    ci=interval['ratios']['mean_accuracy_difference']['ci95']
    harm_ok=bool(np.all(harms<=0))
    return dict(mean_difference=point,per_seed_differences=per_seed,ci95=ci,
        interval=interval,shared_component_draws=True,averaged_individual_intervals=False,
        per_seed_harm_differences=harms.tolist(),no_seed_harm_increase=harm_ok,
        advances=bool(inference_complete and all(v>=0 for v in per_seed) and ci is not None and ci[0]>0 and harm_ok),
        production_adoption=False,gold_certified=False)
