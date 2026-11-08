"""Reproduce planning arithmetic from public aggregates, without opening datasets.

The Decimal calculations independently check the existing float interval helpers.
All results assume independent Bernoulli units; this script cannot establish that
assumption, label truth, statistical power for paired gains, or release eligibility.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import platform

from sakura_rerank.evaluation_statistics import clopper_pearson95, wilson95

REPO = Path(__file__).resolve().parents[2]
PILOT = "reports/issue-35-knbc-format-pilot-v1.json"
PILOT_SHA = "596909b6289469f29835ecb4ea47b23caa86875c46b55a69590c9b150da6b16c"
LIMIT = Decimal("0.0025")
ALPHA = Decimal("0.05")
Z = Decimal("1.95996398454005423552")


def cdf(k: int, n: int, p: Decimal) -> Decimal:
    """Direct probability recurrence, distinct from the production log-mode sum."""
    with localcontext() as context:
        context.prec = 70
        q = 1 - p
        term = q ** n
        total = term
        for i in range(k):
            term *= Decimal(n - i) * p / (Decimal(i + 1) * q)
            total += term
        return +total


def upper(k: int, n: int) -> float:
    with localcontext() as context:
        context.prec = 70
        low, high = Decimal(0), Decimal(1)
        for _ in range(150):
            mid = (low + high) / 2
            if cdf(k, n, mid) > ALPHA:
                low = mid
            else:
                high = mid
        value = float((low + high) / 2)
    actual = clopper_pearson95(k, n)["upper_one_sided"]
    assert abs(actual - value) < 1e-11, "independent harm interval disagreement"
    return actual


def minimum_correct(k: int) -> dict[str, object]:
    low, high = k + 1, 100_000
    assert cdf(k, high, LIMIT) <= ALPHA
    while low < high:
        mid = (low + high) // 2
        if cdf(k, mid, LIMIT) <= ALPHA:
            high = mid
        else:
            low = mid + 1
    assert cdf(k, low - 1, LIMIT) > ALPHA
    assert upper(k, low) <= float(LIMIT) < upper(k, low - 1)
    return {"harms": k, "minimum_baseline_correct": low,
            "upper95_at_minimum": upper(k, low),
            "upper95_at_one_fewer": upper(k, low - 1)}


def harm_scenario(n: int) -> dict[str, object]:
    budget = -1
    for k in range(101):
        if cdf(k, n, LIMIT) > ALPHA:
            break
        budget = k
    assert budget < 100, "scenario scan bound reached"
    if budget >= 0:
        assert upper(budget, n) <= float(LIMIT)
    assert upper(budget + 1, n) > float(LIMIT)
    return {"baseline_correct": n, "max_harms_for_one_sided95": max(budget, 0) if budget >= 0 else None,
            "zero_harm_upper95": upper(0, n),
            "max_harm_upper95": upper(budget, n) if budget >= 0 else None,
            "one_more_harm_upper95": upper(budget + 1, n),
            "safety_component_only_power": {
                str(p): float(cdf(budget, n, p)) if budget >= 0 else 0.0
                for p in (Decimal("0.001"), Decimal("0.0015"))}}


def quality_scenario(n: int) -> dict[str, object]:
    max_errors = -1
    for errors in range(n // 200 + 2):
        valid = n - errors
        interval = wilson95(valid, n)
        with localcontext() as context:
            context.prec = 70
            rate = Decimal(valid) / n
            # Invert the score test at p0=.99 rather than copying Wilson's formula.
            score_pass = (rate >= Decimal(".995") and
                          (rate - Decimal(".99")) ** 2 * n >= Z ** 2 * Decimal(".0099"))
        float_pass = valid / n >= .995 and interval[0] >= .99
        assert score_pass == float_pass, "independent quality threshold disagreement"
        if float_pass:
            max_errors = errors
        else:
            break
    assert max_errors >= 0
    return {"audited": n, "max_errors_meeting_both_numeric_conditions": max_errors,
            "precision_at_boundary": (n - max_errors) / n,
            "wilson95_at_boundary": wilson95(n - max_errors, n),
            "wilson95_one_more_error": wilson95(n - max_errors - 1, n),
            "point_only_error_allowance": n // 200,
            "point_only_boundary_wilson95": wilson95(n - n // 200, n)}


def build() -> dict[str, object]:
    raw = (REPO / PILOT).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PILOT_SHA, "old pilot evidence changed"
    pilot = json.loads(raw)
    capacity = pilot["capacity_diagnostic"]
    assert capacity["remaining_after_conservative_family_exclusion"] == 2786
    assert pilot["selection"]["census"]["prefix_families"] == 81
    assert pilot["selection"]["census"]["selected_prefix_families"] == 19
    paths = [PILOT, "research/independent-evaluation-protocol-v1.md",
             "research/evaluation-admission-v1.md", "src/sakura_rerank/evaluation_metrics.py",
             "src/sakura_rerank/evaluation_statistics.py", "src/sakura_rerank/evaluation_admission.py",
             Path(__file__).relative_to(REPO).as_posix()]
    return {
        "kind": "evaluation_unit_and_sample_feasibility", "version": 1,
        "issue": 35, "parent_issue": 1, "related_issues": [31, 32, 33, 34],
        "status": "planning_arithmetic_verified_not_gold_or_experiment_registration",
        "inputs": {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in paths},
        "python": platform.python_version(),
        "method": {"independent_check": "70-digit Decimal probability recurrence/inversion and score-test inversion",
                   "harm_upper": "one-sided95 Clopper-Pearson; unchanged limit0.0025",
                   "quality": "point>=0.995 and two-sided95 Wilson lower>=0.99",
                   "assumption": "Independent Bernoulli units. Neither clustering nor labels are certified here.",
                   "reference": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html"},
        "unit_contract": {
            "evaluation_case": "One frozen full-reading conversion request with bounded observed-session left context, actual candidate snapshot and independently supported unique Gold surface.",
            "metric_rows": "All valid-label cases N, including oracle misses and runtime fallbacks; acquisition failures reported separately.",
            "harm_denominator": "C: baseline-correct cases, not all cases N or changed cases A.",
            "independence": "Unfixed sampling/power design. Source/input components cannot cross splits; component IDs alone do not prove statistical independence.",
            "source_sentence_to_cases": "Not specified as one-to-one. Multiple derived inputs retain parent exposure and dependence; no multiplication of independent observations."},
        "requirements": {"valid_test_minimum": 3000, "audit_completed_minimum": 1000,
                         "initial_planning_test_rows": 12000, "initial_planning_calibration_rows": 3000,
                         "final_fixed_sample_registered": False, "oracle6_minimum": .97,
                         "safety_limit": .0025},
        "knbc_conditional_capacity": {"unconsumed_sentence_candidates_ceiling": 2786,
            "unreserved_prefix_families": 62, "verified_author_mapping": False,
            "one_sentence_one_case_shortfall_to_test_minimum": 214,
            "one_sentence_one_case_shortfall_to_initial_total_plan": 12214,
            "interpretation": "Before quality, documentation and historical exclusions. Not a verified case, independent-unit or Gold count. Prefix families are not proven authors or independent trials."},
        "harm_minimum_correct_scenarios": [minimum_correct(k) for k in (0, 1, 2, 3)],
        "harm_fixed_C_scenarios": [harm_scenario(n) for n in (62, 1000, 1197, 2786, 3000, 10000)],
        "quality_audit_scenarios": [quality_scenario(n) for n in (1000, 3000, 12000)],
        "claims_excluded": ["Source-format parsing certifies intended Japanese output",
            "Pilot agreement measures final population truth", "Additional correlated rows prove safety",
            "Safety-only power is whole Gate-B power", "Collect until the observed bound passes",
            "A source change improves adopted accuracy", "A self-added certificate is independent evidence"],
        "additional_source_decodes": 0, "dataset_or_test_payloads_opened": 0,
        "model_inferences": 0, "new_fits": 0, "original_labels_changed": 0,
        "gold_admission": False, "calibration": False, "final_test": False,
        "safety_limit_relaxed": False, "release_eligible": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args()
    payload = (json.dumps(build(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if args.check:
        assert args.check.read_bytes() == payload, "aggregate report reproduction mismatch"
        print(json.dumps({"status": "verified", "sha256": hashlib.sha256(payload).hexdigest()}))
    else:
        with args.output.open("xb") as stream:
            stream.write(payload)
        print(json.dumps({"status": "written", "sha256": hashlib.sha256(payload).hexdigest()}))
