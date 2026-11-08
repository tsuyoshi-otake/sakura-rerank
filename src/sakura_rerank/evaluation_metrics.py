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
from .current_tiny import MAX_NATIVE_CANDIDATES, MAX_NATIVE_TEXT_BYTES
from .evaluation_statistics import (
    MAX_ROWS, clopper_pearson95, holm_adjust, mcnemar_exact,
    paired_component_bootstrap, wilson95,
)

STATUSES = ("applied", "abstained", "timeout", "stale", "malformed", "missing", "error", "unavailable", "not_eligible")
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
    baseline_index: int = 0
    production_count: int | None = None


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


def _validate_cases(cases: Sequence[EvaluationCase], *, full_population=False) -> list[EvaluationCase]:
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
        if (not isinstance(case.candidates, tuple)
                or not 1 <= len(case.candidates) <= (MAX_NATIVE_CANDIDATES if full_population else 32)
                or any(not isinstance(text, str) or not 1 <= len(text) <= (MAX_NATIVE_TEXT_BYTES if full_population else 256)
                       for text in (*case.candidates, case.gold))):
            raise EvaluationError("candidate/Gold surfaces outside bound")
        if full_population:
            try:
                if any(len(text.encode('utf-8',errors='strict'))>MAX_NATIVE_TEXT_BYTES
                       for text in (*case.candidates,case.gold)):
                    raise EvaluationError("native surface byte bound exceeded")
            except UnicodeError:
                raise EvaluationError("invalid native surface encoding") from None
        if (type(case.baseline_index) is not int or not 0 <= case.baseline_index < len(case.candidates)
                or (case.production_count is not None and (type(case.production_count) is not int
                    or not 1 <= case.production_count <= min(6, len(case.candidates))))):
            raise EvaluationError("local baseline or production count outside candidates")
    return sorted(cases, key=lambda case: case.case_key)


def _order(observation: Observation, size: int, baseline_index: int = 0) -> tuple[int, ...]:
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
    if observation.status in {"unavailable", "not_eligible"} and observation.attempted:
        raise EvaluationError("unavailable or ineligible model cannot have an inference attempt")
    return tuple(([baseline_index] + [i for i in range(size) if i != baseline_index])[:size])


def evaluate_runs(
    cases: Sequence[EvaluationCase], runs: Mapping[str, EvaluationRun], *,
    comparisons: Sequence[tuple[str, str]], bootstrap_replicates: int = 10_000,
    bootstrap_seed: int = 20261104, reference_baseline: str = "local_selection",
    candidate_contract: str = "legacy32",
) -> dict[str, object]:
    """Compare fixed observations; every model shares every supplied case.

    Missing observation keys become explicit missing/local-fallback rows and make
    the run incomplete. Extra keys, malformed contracts and contradictory terminal
    states fail rather than silently changing the evaluation population. Pair
    orientation is left-minus-right; the complete family is required up front.
    """
    if candidate_contract not in ("legacy32", "native_full_population_v1"):
        raise EvaluationError("unknown candidate population contract")
    full_population = candidate_contract == "native_full_population_v1"
    ordered = _validate_cases(cases, full_population=full_population)
    if not isinstance(reference_baseline, str) or reference_baseline not in {"local_selection", "converter_top1"}:
        raise EvaluationError("unknown comparison baseline")
    if (not isinstance(runs, Mapping) or not 1 <= len(runs) <= 16
            or any(not isinstance(name, str) or _NAME.fullmatch(name) is None
                   or name == "baseline" for name in runs)):
        raise EvaluationError("one to sixteen named model runs required")
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
    if 3 + 2 * len(names) + len(family) > 64:
        raise EvaluationError("comparison family exceeds the fixed bootstrap column budget")
    n = len(ordered)
    reference_indices = [case.baseline_index if reference_baseline == "local_selection" else 0 for case in ordered]
    baseline = [case.candidates[index] == case.gold for case, index in zip(ordered, reference_indices)]
    c = sum(baseline)
    e = n-c
    cohort_hash = hashlib.sha256()
    for case in ordered:
        local = ({} if case.baseline_index == 0 and case.production_count is None else
                 {"baseline_index": case.baseline_index, "production_count": case.production_count})
        if full_population:
            local["candidate_contract"] = candidate_contract
        cohort_hash.update(canonical_json_bytes({
            "case_key": case.case_key, "component_key": case.component_key,
            "candidates": case.candidates, "gold": case.gold, **local,
        }) + b"\n")
    oracle = {str(k): _ratio(sum(case.gold in case.candidates[:k] for case in ordered), n)
              for k in (1, 5, 6, 10, 32)}
    # Oracle@6 as certified: Gold inside the prefix a model may rank, never a
    # positional first six that can include a product row's non-direct tail.
    model_present = sum(case.gold in case.candidates[:case.production_count or min(6, len(case.candidates))]
                        for case in ordered)
    population = {}
    if full_population:
        present = sum(case.gold in case.candidates for case in ordered)
        oracle["all"] = _ratio(present,n)
        population = {"candidate_contract":candidate_contract,
                      "candidate_population":{"total":sum(len(case.candidates) for case in ordered),
                          "minimum":min(len(case.candidates) for case in ordered),
                          "maximum":max(len(case.candidates) for case in ordered),
                          "full_oracle_misses":n-present, "present_outside_model_prefix":present-model_present,
                          "model_prefix_oracle":_ratio(model_present,n)}}
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
            order = _order(observation, case.production_count or min(6, len(case.candidates)), case.baseline_index)
            status[observation.status] += 1
            attempted += int(observation.attempted is True)
            unknown_attempts += int(observation.attempted is None)
            surface = case.candidates[order[0]]
            correct = surface == case.gold
            override = surface != case.candidates[reference_indices[i]]
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
        "schema_version": 2 if full_population else 1, "kind": "fixed_cohort_surface_evaluation", **population,
        "cohort_sha256": cohort_hash.hexdigest(), "record_count": n,
        "reference_baseline": reference_baseline,
        "baseline_correct": c, "baseline_errors": e, "baseline_accuracy": _ratio(c, n),
        "observed_candidate_oracle": oracle, "scored_prefix_oracle6": _ratio(model_present, n), "models": reports,
        "paired_comparisons": paired, "paired_component_intervals": intervals,
        "harm_limit": 0.0025, "gold_quality_certified": False,
        "independence_certified": False, "release_eligible": False,
        "raw_text": False, "raw_case_keys": False,
    }
