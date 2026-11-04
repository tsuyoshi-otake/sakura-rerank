"""Bounded statistical calculations for fixed-cohort reranker evaluation.

Intervals describe their supplied sampling units; none certifies independence,
Gold labels, preregistration or a release gate. NumPy is loaded only for bootstrap.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Mapping, Sequence

MAX_ROWS = 100_000


def _counts(successes: int, total: int) -> None:
    if type(total) is not int or type(successes) is not int or not 0 <= successes <= total <= MAX_ROWS:
        raise ValueError("counts outside the evaluation bound")


def wilson95(successes: int, total: int) -> list[float] | None:
    _counts(successes, total)
    if not total:
        return None
    z = NormalDist().inv_cdf(0.975)
    p = successes / total
    scale = 1 + z*z/total
    center = (p + z*z/(2*total)) / scale
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / scale
    return [max(0.0, center-half), min(1.0, center+half)]


def _binomial_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n or p == 0:
        return 1.0
    if p == 1:
        return 0.0
    mode = min(k, int((n+1)*p))
    log_peak = (math.lgamma(n+1)-math.lgamma(mode+1)-math.lgamma(n-mode+1)
                + mode*math.log(p)+(n-mode)*math.log1p(-p))
    terms = [1.0]
    term = 1.0
    for i in range(mode, 0, -1):
        term *= i/(n-i+1) * (1-p)/p
        if term == 0:
            break
        terms.append(term)
    term = 1.0
    for i in range(mode, k):
        term *= (n-i)/(i+1) * p/(1-p)
        if term == 0:
            break
        terms.append(term)
    return min(1.0, math.exp(log_peak + math.log(math.fsum(terms))))


def clopper_pearson95(successes: int, total: int) -> dict[str, object]:
    _counts(successes, total)
    if not total:
        return {"two_sided": None, "upper_one_sided": None}

    def upper(k: int, alpha: float) -> float:
        if k == total:
            return 1.0
        if k == 0:
            return -math.expm1(math.log(alpha)/total)
        low, high = 0.0, 1.0
        for _ in range(64):
            mid = (low+high)/2
            if _binomial_cdf(k, total, mid) > alpha:
                low = mid
            else:
                high = mid
        return (low+high)/2

    return {"two_sided": [1-upper(total-successes, 0.025), upper(successes, 0.025)],
            "upper_one_sided": upper(successes, 0.05)}


def mcnemar_exact(left_only_correct: int, right_only_correct: int) -> float:
    _counts(left_only_correct, left_only_correct + right_only_correct)
    _counts(right_only_correct, left_only_correct + right_only_correct)
    n = left_only_correct + right_only_correct
    if not n:
        return 1.0
    return min(1.0, 2*_binomial_cdf(min(left_only_correct, right_only_correct), n, 0.5))


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    if not p_values or len(p_values) > 64 or any(
        type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
        for p in p_values.values()
    ):
        raise ValueError("invalid confirmatory p-value family")
    adjusted = {}
    previous = 0.0
    for rank, (key, value) in enumerate(sorted(p_values.items(), key=lambda item: (item[1], item[0]))):
        previous = max(previous, min(1.0, (len(p_values)-rank)*value))
        adjusted[key] = previous
    return {key: adjusted[key] for key in sorted(adjusted)}


def paired_component_bootstrap(
    component_ids: Sequence[str], counts: Sequence[Sequence[int]],
    ratios: Mapping[str, tuple[int, int]], *, replicates: int = 10_000, seed: int = 20261104,
) -> dict[str, object]:
    """Resample whole components, sharing each draw across all ratio contrasts.

    counts is an N-by-D integer sufficient-statistics matrix. Ratios index signed
    numerator and nonnegative denominator columns. Undefined draws are counted;
    if any occur the interval is null rather than conditioning on favorable draws.
    Draws are batched at 32: O(32*components + N*D + replicates*ratios) memory.
    """
    import numpy as np

    if (not 1 <= len(component_ids) <= MAX_ROWS or len(counts) != len(component_ids)
            or type(replicates) is not int or not 100 <= replicates <= 10_000
            or type(seed) is not int or not 0 <= seed < 2**32 or not ratios or len(ratios) > 64):
        raise ValueError("bootstrap dimensions or options outside bound")
    width = len(counts[0])
    if not 1 <= width <= 64 or any(
        len(row) != width or any(type(v) is not int or not -1 <= v <= 1 for v in row)
        for row in counts
    ):
        raise ValueError("bootstrap requires bounded integer row indicators")
    if any(not isinstance(key, str) or not key for key in component_ids):
        raise ValueError("component IDs must be nonempty strings")
    for numerator, denominator in ratios.values():
        if (type(numerator) is not int or type(denominator) is not int
                or not 0 <= numerator < width or not 0 <= denominator < width
                or any(row[denominator] < 0 for row in counts)):
            raise ValueError("invalid bootstrap ratio columns")
    keys = sorted(set(component_ids))
    indexes = {key: i for i, key in enumerate(keys)}
    # Products are integer-valued and <= MAX_ROWS**2, exactly representable in
    # float64; use BLAS rather than a serial integer matrix multiply.
    aggregated = np.zeros((len(keys), width), dtype=np.float64)
    for key, row in zip(component_ids, counts):
        aggregated[indexes[key]] += row
    rng = np.random.Generator(np.random.PCG64(seed))
    samples = {name: [] for name in ratios}
    invalid = {name: 0 for name in ratios}
    probabilities = np.full(len(keys), 1/len(keys))
    for offset in range(0, replicates, 32):
        draws = rng.multinomial(len(keys), probabilities, size=min(32, replicates-offset))
        totals = draws @ aggregated
        for name, (numerator, denominator) in ratios.items():
            valid = totals[:, denominator] > 0
            invalid[name] += int((~valid).sum())
            samples[name].extend((totals[valid, numerator]/totals[valid, denominator]).tolist())
    result = {}
    for name, values in samples.items():
        result[name] = {
            "ci95": None if invalid[name] else np.quantile(values, [0.025, 0.975], method="linear").tolist(),
            "invalid_replicates": invalid[name],
            "degenerate": bool(values) and min(values) == max(values),
        }
    return {"method": "paired_component_percentile_linear_v1", "replicates": replicates,
            "seed": seed, "component_count": len(keys), "numpy_version": np.__version__,
            "independence_certified": False, "ratios": result}
