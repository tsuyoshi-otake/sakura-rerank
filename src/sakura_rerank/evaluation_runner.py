"""One-use evaluator orchestration; no Gold bypass, tuning or release approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from .data.contracts import canonical_json_bytes
from .evaluation_admission import access_test
from .evaluation_metrics import EvaluationCase, EvaluationRun, Observation, evaluate_runs
from .evaluation_payload import RunnerError, prepare, read_cohort, require
from .evaluation_worker import default_adapters, execute_metrics, execute_model, runtime_identity


def _observations(scores, state, count, threshold):
    if state != "complete":
        require(state in {"timeout", "error", "stale", "malformed", "unavailable"}, "unexpected score terminal")
        item = {"status": state, "ranking": None, "attempted": state != "unavailable"}
        return item, dict(item)
    order = sorted(range(count), key=lambda i: (-scores[i], i))
    ungated = {"status": "applied", "ranking": order, "attempted": True}
    gated = (dict(ungated) if order[0] != 0 and scores[order[0]] - scores[0] > threshold
             else {"status": "abstained", "ranking": None, "attempted": True})
    return ungated, gated


def score_sealed_outputs(payload):
    """Metrics process receives sealed observations, never model execution APIs."""
    records, sealed, experiment = payload["cases"], payload["sealed"], payload["experiment"]
    cases = [EvaluationCase(row["case_key"], row["component_key"], tuple(row["candidates"]), row["gold"]) for row in records]
    runs = {name: EvaluationRun({key: Observation(item["status"], tuple(item["ranking"]) if item["ranking"] is not None else None,
                                                          item["attempted"])
                                for key, item in spec["observations"].items()}, spec["completed"])
            for name, spec in sealed["runs"].items()}
    comparisons = [tuple(pair) for pair in experiment["comparisons"]]
    report = evaluate_runs(cases, runs, comparisons=comparisons)
    slices = {}
    for tag in experiment["slices"]:
        selected = [case for case, record in zip(cases, records) if tag in record["tags"]]
        if not selected:
            slices[tag] = {"record_count": 0, "metrics": None}
            continue
        selected_keys = {case.case_key for case in selected}
        selected_runs = {name: EvaluationRun({key: value for key, value in run.observations.items() if key in selected_keys}, run.completed)
                         for name, run in runs.items()}
        slices[tag] = {"record_count": len(selected), "metrics": evaluate_runs(selected, selected_runs, comparisons=comparisons)}
    return {"overall": report, "slices": slices}


def _seal(path: Path, payload: dict) -> str:
    raw = canonical_json_bytes(payload)
    require(len(raw) <= 512 * 1024 * 1024, "sealed observations exceed byte bound")
    with path.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("incomplete observation write")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def run_evaluation(*, artifact_root: Path, plan_path: Path, expected_plan_sha256: str,
                   registry: Path, anchor: Path, adapters=None) -> dict:
    """Execute one admitted fixed cohort. Missing Gold still refuses all real runs.

    Custom adapters are trusted importable code explicitly registered by the caller,
    not dynamically imported from a dataset. They must match their frozen identities
    and implement validate(artifacts,width), factory(artifacts,width), score(input)
    and close(). Their own tokenization/fusion parity remains an evidence obligation.
    """
    adapters = dict(default_adapters() if adapters is None else adapters)
    registry = registry.resolve(strict=True)
    prepared = None

    def preflight(snapshot, raw_plan):
        nonlocal prepared
        try:
            prepared = prepare(snapshot, raw_plan, adapters)
        except Exception:
            raise RunnerError("evaluation preflight rejected before Test") from None

    with access_test(artifact_root=artifact_root, plan_path=plan_path, expected_plan_sha256=expected_plan_sha256,
                     registry=registry, anchor=anchor, preflight=preflight) as access:
        require(prepared is not None and hashlib.sha256(access.plan_bytes).hexdigest() == expected_plan_sha256,
                "authenticated execution plan missing")
        experiment = prepared["experiment"]
        limits = experiment["limits"]
        started = time.monotonic()
        deadline = started + limits["job_seconds"]
        cases = read_cohort(access.artifacts[prepared["plan"]["data"]["test"]], prepared)
        # Slice/source identities and Gold are intentionally excluded from this payload.
        requests = [{**row["input"], "candidates": row["input"]["candidates"][:6]} for row in cases]
        runs, proposals, model_reports = {}, {}, []
        for model in prepared["models"]:
            spec = model["spec"]
            require(runtime_identity() == experiment["runtime"], "runtime changed after preflight")
            if time.monotonic() >= deadline:
                output = {"states": ["unavailable"]*len(cases), "scores": [None]*len(cases), "complete": False,
                          "terminal": "job_budget_exhausted", "process": None, "request_count": len(cases), "attempted": 0}
            else:
                output = execute_model(requests, model["artifacts"], model["adapter"], spec["feature_width"], limits,
                                       deadline=deadline, expected_identity=spec["adapter_identity"], expected_runtime=experiment["runtime"])
            ungated, gated = {}, {}
            for row, scores, state in zip(cases, output["scores"], output["states"], strict=True):
                a, b = _observations(scores, state, min(6, len(row["input"]["candidates"])), model["threshold"])
                ungated[row["case_key"]], gated[row["case_key"]] = a, b
            for variant, observations in (("ungated", ungated), ("gated", gated)):
                runs[spec["runs"][variant]] = {"observations": observations, "completed": output["complete"]}
            proposals[spec["model"]] = {"scores": output["scores"], "states": output["states"]}
            model_reports.append({"model": spec["model"], "adapter": spec["adapter"], "complete": output["complete"],
                                  "terminal": output["terminal"], "request_count": output["request_count"],
                                  "attempted": output["attempted"], "process": output["process"]})
        sealed = {"kind": "sealed_evaluation_observations", "version": 1,
                  "plan_sha256": expected_plan_sha256, "reservation_sha256": access.reservation_sha256,
                  "case_order": [row["case_key"] for row in cases],
                  "candidate_counts": [min(6, len(row["input"]["candidates"])) for row in cases],
                  "model_proposals": proposals, "runs": runs, "models": model_reports}
        seal_hash = _seal(registry / ("observations-" + access.reservation_sha256 + ".json"), sealed)
        metric_rows = [{"case_key": row["case_key"], "component_key": row["component_key"],
                        "candidates": [c["surface"] for c in row["input"]["candidates"]], "gold": row["gold"], "tags": row["tags"]}
                       for row in cases]
        metrics, metric_process = execute_metrics({"cases": metric_rows, "sealed": {"runs": runs}, "experiment": experiment},
                                                 min(limits["metrics_seconds"], deadline-time.monotonic()), limits["shutdown_seconds"])
        result = {"kind": "authenticated_evaluation_execution", "version": 1,
                  "status": "complete" if all(m["complete"] for m in model_reports) else "incomplete",
                  "plan_sha256": expected_plan_sha256, "reservation_sha256": access.reservation_sha256,
                  "sealed_observations_sha256": seal_hash, "models": model_reports, "metric_process": metric_process,
                  "metrics": metrics, "primary": experiment["primary"], "safety_limit": .0025,
                  "all_outputs_sealed_before_scoring": True, "model_retries": 0,
                  "threshold_selection": False, "release_eligible": False, "gold_certified_by_runner": False,
                  "raw_text": False, "raw_case_keys": False, "production_benchmark": False}
        access.complete(canonical_json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute a separately admitted one-use evaluation")
    for name in ("artifact-root", "plan-path", "registry", "anchor"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    try:
        report = run_evaluation(**vars(args))
    except Exception:
        # Inner exception contexts may contain third-party diagnostics; don't print them.
        print(json.dumps({"status": "failed", "release_eligible": False, "automatic_retry": False}))
        return 1
    print(json.dumps({"status": report["status"], "release_eligible": False}))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
