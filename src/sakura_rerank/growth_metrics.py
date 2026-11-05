"""Source-exact research metrics with one acquisition-inclusive denominator."""
from .evaluation_statistics import clopper_pearson95,wilson95


def observe(arrays,scores,mode):
    import numpy as np
    mask=arrays["candidate_mask"]
    if mode not in ("ungated","gated") or scores.shape!=mask.shape or mask.shape[1]!=6:
        raise ValueError("research_score_shape_or_mode_differs")
    available=mask.any(axis=1)
    finite=np.isfinite(scores).all(axis=1)
    safe=np.where(mask & np.isfinite(scores),scores,-np.inf)
    predicted=safe.argmax(axis=1)
    if mode=="gated":
        margin=np.zeros(len(scores))
        usable=available & finite
        margin[usable]=safe[np.arange(len(scores))[usable],predicted[usable]]-safe[usable,0]
        predicted=np.where(margin>1.7,predicted,0)
    predicted=np.where(available & finite,predicted,0)
    positions=np.arange(len(scores))
    baseline=arrays["correct_mask"][:,0]
    correct=arrays["correct_mask"][positions,predicted]
    changed=available & ~arrays["baseline_equivalent"][positions,predicted]
    return dict(correct=correct,baseline=baseline,changed=changed,available=available,
        inference_failed=available & ~finite,predicted=predicted)


def summarize(observation,indexes=None):
    import numpy as np
    data={key:np.asarray(value) if indexes is None else np.asarray(value)[indexes] for key,value in observation.items()}
    correct,base,changed=data["correct"],data["baseline"],data["changed"]
    n=len(correct)
    if not n:raise ValueError("empty_research_metric_population")
    rescue=int((~base & correct).sum());harm=int((base & ~correct).sum())
    wrong=int((~base & ~correct & changed).sum());applied=int(changed.sum())
    base_correct=int(base.sum());count=int(correct.sum());errors=n-base_correct
    if count!=base_correct+rescue-harm or applied!=rescue+harm+wrong:
        raise ValueError("surface_metric_reconciliation_failed")
    def rate(value,total):return dict(numerator=value,denominator=total,value=value/total if total else None,
        wilson95_row_assumption=wilson95(value,total))
    return dict(rows=n,baseline_correct=base_correct,baseline_errors=errors,correct=count,
        rescue=rescue,harm=harm,wrong_to_wrong=wrong,correction_failure=harm+wrong,changed=applied,
        candidate_acquisition_failure=int((~data["available"]).sum()),model_inference_failure=int(data["inference_failed"].sum()),
        accuracy=rate(count,n),baseline_accuracy=rate(base_correct,n),precision=rate(rescue,applied),recall=rate(rescue,errors),
        application=rate(applied,n),application_to_error=rate(int((changed & ~base).sum()),errors),
        harm_rate=rate(harm,base_correct),harm_exact95_row_assumption=clopper_pearson95(harm,base_correct),
        baseline_gain=(rescue-harm)/n,gold_certified=False)
