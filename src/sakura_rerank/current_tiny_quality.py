"""Reduce raw current-Tiny evaluator output to a text-free quality summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from sakura_rerank.audit import AuditError, file_record, write_json_atomic


SCHEMA_VERSION = "sakura-rerank.current-tiny-quality-summary.v1"
SAFE_ELIGIBILITY = {
    "eligible",
    "not-enough-candidates",
    "not-long-enough",
}
SAFE_NEURAL_STATUS = {
    "applied",
    "worker-fallback",
    "not-enough-candidates",
    "not-long-enough",
}
SAFE_COMPARISON = {"win", "loss", "tie"}


class QualitySummaryError(RuntimeError):
    """Raw evaluator output is malformed or internally inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QualitySummaryError(f"unable to read evaluator report: {path.name}") from error
    if not isinstance(value, dict):
        raise QualitySummaryError("evaluator report root must be an object")
    return value


def _integer_mapping(value: Any, name: str, required: Iterable[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise QualitySummaryError(f"{name} must be an object")
    result: dict[str, int] = {}
    for field in required:
        item = value.get(field)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise QualitySummaryError(f"{name}.{field} must be a non-negative integer")
        result[field] = item
    return result


def _safe_category(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise QualitySummaryError(f"unexpected {name} category")
    return value


def _normalized_worker_error(value: Any) -> str:
    if value is None:
        return "none"
    if not isinstance(value, str):
        raise QualitySummaryError("worker_error must be a string or null")
    prefix = "worker reported failure status "
    if value.startswith(prefix) and value[len(prefix) :].isdigit():
        return f"worker-status-{value[len(prefix):]}"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"redacted-error-sha256:{digest}"


def _slice_record(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "cases": len(rows),
        "baseline_correct": sum(bool(row["baseline_correct"]) for row in rows),
        "neural_correct": sum(bool(row["neural_correct"]) for row in rows),
        "eligible": sum(bool(row["eligible"]) for row in rows),
        "applied": sum(row["neural_status"] == "applied" for row in rows),
        "fallback": sum(row["neural_status"] == "worker-fallback" for row in rows),
        "wins": sum(row["comparison"] == "win" for row in rows),
        "losses": sum(row["comparison"] == "loss" for row in rows),
        "ties": sum(row["comparison"] == "tie" for row in rows),
    }


def summarize_raw_report(path: Path) -> dict[str, Any]:
    report = _read_json(path)
    rows_value = report.get("rows")
    if not isinstance(rows_value, list) or not all(
        isinstance(row, dict) for row in rows_value
    ):
        raise QualitySummaryError("evaluator rows must be an array of objects")
    rows: list[dict[str, Any]] = rows_value
    cases = report.get("cases")
    if not isinstance(cases, int) or isinstance(cases, bool) or cases != len(rows):
        raise QualitySummaryError("evaluator case count does not match rows")

    slice_rows: dict[str, list[dict[str, Any]]] = {}
    eligibility = Counter[str]()
    statuses = Counter[str]()
    comparisons = Counter[str]()
    errors = Counter[str]()
    for row in rows:
        slice_name = row.get("slice")
        if not isinstance(slice_name, str) or not slice_name:
            raise QualitySummaryError("row slice must be a non-empty string")
        for flag in ("baseline_correct", "neural_correct", "eligible"):
            if not isinstance(row.get(flag), bool):
                raise QualitySummaryError(f"row {flag} must be a boolean")
        row_eligibility = _safe_category(
            row.get("eligibility"), SAFE_ELIGIBILITY, "eligibility"
        )
        row_status = _safe_category(
            row.get("neural_status"), SAFE_NEURAL_STATUS, "neural status"
        )
        row_comparison = _safe_category(
            row.get("comparison"), SAFE_COMPARISON, "comparison"
        )
        slice_rows.setdefault(slice_name, []).append(row)
        eligibility[row_eligibility] += 1
        statuses[row_status] += 1
        comparisons[row_comparison] += 1
        errors[_normalized_worker_error(row.get("worker_error"))] += 1

    expected_slice_counts = {
        name: len(items) for name, items in sorted(slice_rows.items())
    }
    if report.get("slice_counts") != expected_slice_counts:
        raise QualitySummaryError("slice counts do not match evaluator rows")

    baseline = _integer_mapping(
        report.get("baseline"), "baseline", ("evaluated", "correct")
    )
    neural = _integer_mapping(
        report.get("neural"),
        "neural",
        ("eligible", "attempted", "applied", "fallback", "correct"),
    )
    comparison_totals = _integer_mapping(
        report.get("comparisons"), "comparisons", ("wins", "losses", "ties")
    )
    recomputed = {
        "baseline": {
            "evaluated": cases,
            "correct": sum(bool(row["baseline_correct"]) for row in rows),
        },
        "neural": {
            "eligible": sum(bool(row["eligible"]) for row in rows),
            "attempted": statuses["applied"] + statuses["worker-fallback"],
            "applied": statuses["applied"],
            "fallback": statuses["worker-fallback"],
            "correct": sum(
                bool(row["neural_correct"]) for row in rows if row["eligible"]
            ),
        },
        "comparisons": {
            "wins": comparisons["win"],
            "losses": comparisons["loss"],
            "ties": comparisons["tie"],
        },
    }
    if baseline != recomputed["baseline"]:
        raise QualitySummaryError("baseline aggregate does not match evaluator rows")
    if neural != recomputed["neural"]:
        raise QualitySummaryError("neural aggregate does not match evaluator rows")
    if comparison_totals != recomputed["comparisons"]:
        raise QualitySummaryError("comparison aggregate does not match evaluator rows")

    mode = report.get("mode")
    if mode not in ("long", "all-normal"):
        raise QualitySummaryError("evaluator mode is invalid")
    structural_eligible = report.get("acceptance_eligible")
    exploratory = report.get("exploratory")
    if not isinstance(structural_eligible, bool) or not isinstance(exploratory, bool):
        raise QualitySummaryError("evaluator eligibility flags must be boolean")

    return {
        "mode": mode,
        "cases": cases,
        "evaluator_structural_acceptance_eligible": structural_eligible,
        "exploratory": exploratory,
        "slice_counts": expected_slice_counts,
        "baseline": baseline,
        "neural": neural,
        "comparisons": comparison_totals,
        "eligibility_counts": dict(sorted(eligibility.items())),
        "neural_status_counts": dict(sorted(statuses.items())),
        "worker_error_counts": dict(sorted(errors.items())),
        "slices": {
            name: _slice_record(items) for name, items in sorted(slice_rows.items())
        },
        "raw_report": file_record(path, display_path=path.name),
        "raw_row_text_recorded_in_summary": False,
    }


def build_summary(
    *,
    raw_reports: Iterable[Path],
    corpus: Path,
    evaluator_source: Path,
    evaluator_executable: Path,
    audit_report: Path,
) -> dict[str, Any]:
    audit = _read_json(audit_report)
    sakura_input = audit.get("sakura_input")
    if not isinstance(sakura_input, dict):
        raise QualitySummaryError("current-state audit lacks Sakura Input identity")
    runs = [summarize_raw_report(path.resolve(strict=True)) for path in raw_reports]
    modes = [run["mode"] for run in runs]
    if sorted(modes) != ["all-normal", "long"]:
        raise QualitySummaryError("exactly one long and one all-normal report are required")
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_status": {
            "gate_a_b_eligible": False,
            "reason": (
                "The 600-row authored regression corpus is a draft and is not the "
                "independently reviewed, provenance-complete frozen holdout."
            ),
            "production_change_authorized": False,
        },
        "sakura_input": {
            "head": sakura_input.get("head"),
            "dirty": sakura_input.get("dirty"),
            "dirty_path_count": sakura_input.get("dirty_path_count"),
        },
        "inputs": {
            "corpus": file_record(corpus.resolve(strict=True), display_path=corpus.name),
            "corpus_review_status": "authored-regression-draft-not-independent-holdout",
            "evaluator_source": file_record(
                evaluator_source.resolve(strict=True), display_path=evaluator_source.name
            ),
            "evaluator_executable": file_record(
                evaluator_executable.resolve(strict=True),
                display_path=evaluator_executable.name,
            ),
            "current_state_audit": file_record(
                audit_report.resolve(strict=True), display_path=audit_report.name
            ),
        },
        "runs": sorted(runs, key=lambda run: run["mode"]),
        "limitations": [
            "The corpus is authored and templated, not independently reviewed or provenance-complete.",
            "The evaluator exists only in the inspected dirty Sakura Input working tree, not at the pinned HEAD.",
            "A worker failure preserves local Top-1, so fallback rows are not evidence of neural quality.",
            (
                "The evaluator reports Top-1 only; it does not establish oracle "
                "recall, MRR, NDCG, calibration, confidence intervals, or leakage "
                "safety."
            ),
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize current Tiny quality reports without raw row text"
    )
    parser.add_argument("--raw-report", type=Path, action="append", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--evaluator-source", type=Path, required=True)
    parser.add_argument("--evaluator-executable", type=Path, required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = build_summary(
            raw_reports=arguments.raw_report,
            corpus=arguments.corpus,
            evaluator_source=arguments.evaluator_source,
            evaluator_executable=arguments.evaluator_executable,
            audit_report=arguments.audit_report,
        )
        write_json_atomic(arguments.output, summary)
    except (AuditError, QualitySummaryError, OSError) as error:
        print(f"current Tiny quality summary failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
