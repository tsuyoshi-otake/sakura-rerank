"""Surface-aware metrics on one immutable, explicit evaluation denominator.

This module scores already supplied observations. It does not open datasets,
run models, select thresholds, certify labels or admit a final Test experiment.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from .data.contracts import canonical_json_bytes
from .evaluation_statistics import (
    MAX_ROWS, clopper_pearson95, holm_adjust, mcnemar_exact,
    paired_component_bootstrap, wilson95,
)

STATUSES = ("applied", "abstained", "timeout", "stale", "malformed", "missing", "error", "unavailable")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}\Z")


class EvaluationError(ValueError):
    """The cohort or observation contract cannot support a valid comparison."""


@dataclass(frozen=True)
class EvaluationCase:
    case_key: str
    component_key: str
    candidates: tuple[str, ...]
    gold: str


@dataclass(frozen=True)
class Observation:
    status: str
    ranking: tuple[int, ...] | None = None
    attempted: bool | None = True


@dataclass(frozen=True)
class EvaluationRun:
    observations: Mapping[str, Observation]
    completed: bool


def _ratio(numerator: int, denominator: int) -> dict[str, object]:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator/denominator if denominator else None,
            "wilson_ci95_row_assumption": wilson95(numerator, denominator)}


def _validate_cases(cases: Sequence[EvaluationCase]) -> list[EvaluationCase]:
    if not isinstance(cases, Sequence) or not 1 <= len(cases) <= MAX_ROWS:
        raise EvaluationError("cohort must be nonempty and bounded")
    keys = set()
    for case in cases:
        if not isinstance(case, EvaluationCase) or any(
            not isinstance(value, str) or _SHA.fullmatch(value) is None
            for value in (case.case_key, case.component_key)
        ):
            raise EvaluationError("case and component keys must be SHA-256 commitments")
        if case.case_key in keys:
            raise EvaluationError("duplicate case key")
        keys.add(case.case_key)
        if (not isinstance(case.candidates, tuple) or not 1 <= len(case.candidates) <= 32
                or any(not isinstance(text, str) or not 1 <= len(text) <= 256
                       for text in (*case.candidates, case.gold))):
            raise EvaluationError("candidate/Gold surfaces outside bound")
    return sorted(cases, key=lambda case: case.case_key)


def _order(observation: Observation, size: int) -> tuple[int, ...]:
    if (not isinstance(observation, Observation) or observation.status not in STATUSES
            or (type(observation.attempted) is not bool
                and not (observation.status == "missing" and observation.attempted is None))):
        raise EvaluationError("unknown or malformed terminal observation")
    if observation.status == "applied":
        if (not observation.attempted or not isinstance(observation.ranking, tuple)
                or any(type(index) is not int for index in observation.ranking)
                or sorted(observation.ranking) != list(range(size))):
            raise EvaluationError("applied ranking must permute the production candidates")
        return observation.ranking
    if observation.ranking is not None:
        raise EvaluationError("fallback/abstention must not provide an applied ranking")
    if observation.status == "abstained" and not observation.attempted:
        raise EvaluationError("gate abstention requires a model attempt")
    if observation.status in {"timeout", "stale", "malformed"} and not observation.attempted:
        raise EvaluationError("response failure requires a model attempt")
    if observation.status == "unavailable" and observation.attempted:
        raise EvaluationError("unavailable model cannot have an inference attempt")
    return tuple(range(size))


def evaluate_runs(
    cases: Sequence[EvaluationCase], runs: Mapping[str, EvaluationRun], *,
    comparisons: Sequence[tuple[str, str]], bootstrap_replicates: int = 10_000,
    bootstrap_seed: int = 20261104,
) -> dict[str, object]:
    """Compare fixed observations; every model shares every supplied case.

    Missing observation keys become explicit missing/local-fallback rows and make
    the run incomplete. Extra keys, malformed contracts and contradictory terminal
    states fail rather than silently changing the evaluation population. Pair
    orientation is left-minus-right; the complete family is required up front.
    """
    ordered = _validate_cases(cases)
    if (not isinstance(runs, Mapping) or not 1 <= len(runs) <= 8
            or any(not isinstance(name, str) or _NAME.fullmatch(name) is None
                   or name == "baseline" for name in runs)):
        raise EvaluationError("one to eight named model runs required")
    names = sorted(runs)
    case_keys = {case.case_key for case in ordered}
    for run in runs.values():
        if (not isinstance(run, EvaluationRun) or type(run.completed) is not bool
                or not isinstance(run.observations, Mapping)
                or set(run.observations) - case_keys):
            raise EvaluationError("run metadata or cohort alignment differs")
    if not isinstance(comparisons, Sequence) or not 1 <= len(comparisons) <= 36:
        raise EvaluationError("a bounded preregistered comparison family is required")
    seen = set()
    family = []
    for pair in comparisons:
        if (not isinstance(pair, tuple) or len(pair) != 2 or pair[0] == pair[1]
                or any(not isinstance(name, str) or name not in {*names, "baseline"} for name in pair)):
            raise EvaluationError("invalid paired comparison")
        identity = frozenset(pair)
        if identity in seen:
            raise EvaluationError("duplicate or reversed comparison")
        seen.add(identity)
        family.append(pair)
    family.sort()
    if any((name, "baseline") not in family for name in names):
        raise EvaluationError("each model requires a model-minus-baseline comparison")
    n = len(ordered)
    baseline = [case.candidates[0] == case.gold for case in ordered]
    c = sum(baseline)
    e = n-c
    cohort_hash = hashlib.sha256()
    for case in ordered:
        cohort_hash.update(canonical_json_bytes({
            "case_key": case.case_key, "component_key": case.component_key,
            "candidates": case.candidates, "gold": case.gold,
        }) + b"\n")
    oracle = {str(k): _ratio(sum(case.gold in case.candidates[:k] for case in ordered), n)
              for k in (1, 5, 6, 10, 32)}
    rows = [[1, int(correct), int(not correct)] for correct in baseline]
    columns = {"baseline": 1}
    correct_by_model = {"baseline": baseline}
    ratios: dict[str, tuple[int, int]] = {}
    reports = {}
    for name in names:
        run = runs[name]
        status = Counter({key: 0 for key in STATUSES})
        correct_values = []
        r = h = w = changed = attempted = missing_entries = unknown_attempts = 0
        reciprocal = []
        ndcg = []
        prediction_hash = hashlib.sha256()
        columns[name] = len(rows[0])
        for i, case in enumerate(ordered):
            if case.case_key not in run.observations:
                missing_entries += 1
            observation = run.observations.get(case.case_key, Observation("missing", None, None))
            order = _order(observation, min(6, len(case.candidates)))
            status[observation.status] += 1
            attempted += int(observation.attempted is True)
            unknown_attempts += int(observation.attempted is None)
            surface = case.candidates[order[0]]
            correct = surface == case.gold
            override = surface != case.candidates[0]
            rescue = not baseline[i] and correct
            harm = baseline[i] and not correct
            wrong_change = not baseline[i] and not correct and override
            r += int(rescue)
            h += int(harm)
            w += int(wrong_change)
            changed += int(override)
            correct_values.append(correct)
            rows[i].extend((int(correct), int(harm)))
            rank = next((j+1 for j, index in enumerate(order) if case.candidates[index] == case.gold), None)
            reciprocal.append(1/rank if rank is not None else 0.0)
            ndcg.append(1/math.log2(rank+1) if rank is not None else 0.0)
            prediction_hash.update(canonical_json_bytes({
                "case_key": case.case_key, "status": observation.status,
                "attempted": observation.attempted, "ranking": observation.ranking,
            }) + b"\n")
        if changed != r+h+w or sum(correct_values) != c-h+r:
            raise EvaluationError("outcome reconciliation failed")
        correct_by_model[name] = correct_values
        ratios[name+"-accuracy"] = (columns[name], 0)
        ratios[name+"-harm"] = (columns[name]+1, 1)
        reports[name] = {
            "record_count": n, "run_completed": run.completed,
            "observation_coverage_complete": missing_entries == 0,
            "complete": run.completed and missing_entries == 0,
            "missing_observation_entries": missing_entries,
            "prediction_sha256": prediction_hash.hexdigest(),
            "terminal_counts": dict(status), "inference_attempts": attempted,
            "attempt_status_unknown": unknown_attempts,
            "gate_applied_count": status["applied"], "effective_changes": changed,
            "correction_success": r, "correction_failure": h+w,
            "baseline_correct_destroyed": h, "wrong_to_different_wrong": w,
            "accuracy": _ratio(c-h+r, n), "harm_rate": _ratio(h, c),
            "harm_clopper_pearson95_row_assumption": clopper_pearson95(h, c),
            "overwrite_coverage": _ratio(changed, n),
            "application_to_error_targets": _ratio(r+w, e),
            "correction_precision": _ratio(r, changed), "correction_recall": _ratio(r, e),
            "baseline_gain": (r-h)/n, "relative_error_reduction": (r-h)/e if e else None,
            "rescue_harm_ratio": {"value": r/h if h else None,
                                  "status": "finite" if h else "positive_infinity" if r else "undefined"},
            "mrr_at_6": math.fsum(reciprocal)/n,
            "ndcg_at_6_first_correct_surface": math.fsum(ndcg)/n,
        }
    paired = {}
    for left, right in family:
        key = left+"__vs__"+right
        l_values, r_values = correct_by_model[left], correct_by_model[right]
        left_only = sum(l and not r for l, r in zip(l_values, r_values))
        right_only = sum(r and not l for l, r in zip(l_values, r_values))
        col = len(rows[0])
        for row, l, r in zip(rows, l_values, r_values):
            row.append(int(l)-int(r))
        ratios[key] = (col, 0)
        paired[key] = {"left": left, "right": right, "record_count": n,
                       "left_only_correct": left_only, "right_only_correct": right_only,
                       "accuracy_difference": (left_only-right_only)/n,
                       "mcnemar_exact_two_sided_p": mcnemar_exact(left_only, right_only)}
    adjusted = holm_adjust({key: result["mcnemar_exact_two_sided_p"] for key, result in paired.items()})
    for key in paired:
        paired[key]["holm_adjusted_p"] = adjusted[key]
    intervals = paired_component_bootstrap(
        [case.component_key for case in ordered], rows, ratios,
        replicates=bootstrap_replicates, seed=bootstrap_seed,
    )
    return {
        "schema_version": 1, "kind": "fixed_cohort_surface_evaluation",
        "cohort_sha256": cohort_hash.hexdigest(), "record_count": n,
        "baseline_correct": c, "baseline_errors": e, "baseline_accuracy": _ratio(c, n),
        "observed_candidate_oracle": oracle, "models": reports,
        "paired_comparisons": paired, "paired_component_intervals": intervals,
        "harm_limit": 0.0025, "gold_quality_certified": False,
        "independence_certified": False, "release_eligible": False,
        "raw_text": False, "raw_case_keys": False,
    }
