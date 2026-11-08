"""Descriptive census arithmetic; never estimates independent model accuracy."""
import numpy as np


def partitions(indices, rows, group_size=25000):
    if set(indices) != {'dictionary', 'annotation'}:
        raise ValueError('audit_cohort_names')
    sets = {k: set(map(int, v)) for k, v in indices.items()}
    if any(len(v) != 2 * group_size or len(indices[k]) != len(v) for k, v in sets.items()):
        raise ValueError('audit_arm_size_or_duplicates')
    result = dict(common_wikipedia=sets['dictionary'] & sets['annotation'],
                  dictionary_aozora=sets['dictionary'] - sets['annotation'],
                  annotation_aozora=sets['annotation'] - sets['dictionary'])
    if any(len(v) != group_size for v in result.values()) or set.union(*result.values()) != set(range(rows)):
        raise ValueError('audit_disjoint_cohort_coverage')
    return {k: np.array(sorted(v), dtype=np.int64) for k, v in result.items()}


def observations(scores, arrays, gated=False):
    scores = np.asarray(scores)
    mask = arrays['candidate_mask']
    if scores.shape != mask.shape or scores.ndim != 2 or scores.shape[1] != 6:
        raise ValueError('audit_score_shape')
    invalid = ~np.isfinite(scores).all(axis=1) | ~mask.any(axis=1)
    effective = np.where(mask & np.isfinite(scores), scores, -np.inf)
    winner = effective.argmax(axis=1)
    row = np.arange(len(scores))
    margin = scores[row, winner] - scores[:, 0]
    if gated:
        winner = np.where(margin > np.float32(1.7), winner, 0)
    winner = np.where(invalid, 0, winner)
    before = arrays['correct_mask'][:, 0]
    after = arrays['correct_mask'][row, winner]
    changed = ~arrays['baseline_equivalent'][row, winner]
    alternatives = mask & ~arrays['baseline_equivalent']
    proposal = np.where(alternatives, effective, -np.inf).max(axis=1) - scores[:, 0]
    proposal = np.where(invalid | ~alternatives.any(axis=1), np.nan, proposal)
    return dict(winner=winner, correct=after, baseline_correct=before,
                rescue=~before & after, harm=before & ~after,
                wrong_to_wrong=~before & ~after & changed, changed=changed,
                failed_inference=invalid, proposed_change_margin=proposal)


def summary(observed, indexes):
    n = len(indexes)
    counts = {key: int(observed[key][indexes].sum()) for key in
              ('correct', 'baseline_correct', 'rescue', 'harm', 'wrong_to_wrong', 'changed', 'failed_inference')}
    if counts['correct'] != counts['baseline_correct'] + counts['rescue'] - counts['harm']:
        raise ValueError('audit_correct_identity')
    if counts['changed'] != counts['rescue'] + counts['harm'] + counts['wrong_to_wrong']:
        raise ValueError('audit_change_identity')
    errors = n - counts['baseline_correct']
    def rate(a, b):
        return None if b == 0 else a / b
    values = observed['proposed_change_margin'][indexes]
    finite = values[np.isfinite(values)]
    return dict(rows=n, **counts, correction_failure=counts['harm'] + counts['wrong_to_wrong'],
                source_correct_rate=rate(counts['correct'], n),
                precision=rate(counts['rescue'], counts['changed']), recall=rate(counts['rescue'], errors),
                coverage=rate(counts['changed'], n), harm_rate=rate(counts['harm'], counts['baseline_correct']),
                error_application=rate(counts['rescue'] + counts['wrong_to_wrong'], errors),
                winner_rank_counts=np.bincount(observed['winner'][indexes], minlength=6).tolist(),
                proposed_change_margin_rows=len(finite),
                proposed_change_margin_quantiles=None if not len(finite) else np.quantile(finite, [.1, .5, .9]).tolist())


def slices(groups, lengths):
    result = dict(groups)
    for name, indexes in groups.items():
        for label, low, high in [('2', 2, 2), ('3-4', 3, 4), ('5-8', 5, 8), ('9-32', 9, 32)]:
            result[name + '/reading-' + label] = indexes[(lengths[indexes] >= low) & (lengths[indexes] <= high)]
    return result


def paired(first, second, indexes):
    # second minus first on the exact same rows; no outcome-defined membership.
    result = {key + '_difference': int(second[key][indexes].sum()) - int(first[key][indexes].sum())
              for key in ('correct', 'rescue', 'harm', 'wrong_to_wrong', 'changed')}
    result.update(rows=len(indexes), winner_changes=int((first['winner'][indexes] != second['winner'][indexes]).sum()))
    delta = second['proposed_change_margin'][indexes] - first['proposed_change_margin'][indexes]
    delta = delta[np.isfinite(delta)]
    result.update(margin_delta_rows=len(delta), margin_delta_positive=int((delta > 0).sum()),
                  margin_delta_quantiles=None if not len(delta) else np.quantile(delta, [.1, .5, .9]).tolist())
    return result
