"""Issue #27 research-only seed-ensemble confidence-gate experiment (aggregate output only).

The model is the mean of the three Issue #21 C2 models' logits. The gate,
threshold, epoch-selection, and counting rules are Issue #25's, imported from
its hash-pinned harness so they cannot drift. No model is trained, the frozen
split JSONL is not read, and the final holdout is never touched.

Stages (each writes its output once and refuses to overwrite it):
  crossfit          cross-fitted per-seed epochs and ensemble score/tau on train OOF
  select            final ensemble score and tau on the full train OOF
  decide-accuracy   criteria 1-3; must run before any dev access
  export            FP32/INT8 ensemble ONNX and the dev decision parity (criterion 5)
  benchmark         repository latency contract for FP32 (criterion 4) and references
  decide            final decision from criteria 1-5; must precede eval-dev
  eval-dev          single dev evaluation of the final gate (reference only)
  publish           tracked aggregate report; refuses unless the independent
                    recomputation agrees
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ISSUE = 27
EXP = Path(__file__).resolve().parent
REPO = EXP.parents[1]
GEN = REPO / "data" / "generated"
SRC21 = GEN / "issue-21-retrain"
OUT = GEN / f"issue-{ISSUE}-ensemble-gate"
REPORT = REPO / "reports" / f"issue-{ISSUE}-ensemble-gate.json"
R2_DIR = GEN / "sakura-rerank-tiny-r2-research"
V1_DIR = GEN / "sakura-rerank-tiny-v1-research"
PLAN_BODY_SHA256 = "531393e6c0082d1f50f24e9779b330427ff6555c9310554fed0d72c39001a8f3"
GATE_PY = REPO / "research" / "issue-25-confidence-gate" / "run.py"
GATE_PY_SHA256 = "4e77fc6ec06c42a4b849e770994bffd4bcbdbab47161a9daa01656416193b7a5"
R2_PY = REPO / "src" / "sakura_rerank" / "research_tiny_r2.py"
R2_PY_SHA256 = "c2ede3575722b0cda97e0da52a04f42c2402db9cf12aec077d63993f09a95f66"
CHECKPOINTS = {
    20260814: "7e27c04632d6118bd26a286efee4e71bc61bfcc1f2317a6f8fbbd636890c2fbd",
    20261103: "61d972bbc642194eac828277af24466db9152b1941714f73c780e7519915d5a0",
    20261104: "b52b5dfc62201ceb3c26d2b2ed10dbcb66f7a01e5c532f62adc187f936f8e2d3",
}
R2_FP32 = ("sakura-rerank-tiny-v1-research-r2-fp32.onnx",
           "96d7694cc3759465a95841aa8d4cd62757f302fc13388ca9c38751c2a9ae5c64")
P95_LIMIT_MS = 2.0
WARMUP_RUNS = 100
MEASURED_RUNS = 10_000
DEV_ACCESS_OUTPUTS = ("export.json", "fp32-benchmark.report.json", "decision.json", "dev-eval.json")


def _load_pinned(path: Path, expected: str, name: str):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"hash mismatch for {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Verify the pinned Issue #25 harness before executing it.
gate = _load_pinned(GATE_PY, GATE_PY_SHA256, "issue25_gate")
HarnessError = gate.HarnessError
SEEDS = gate.SEEDS
FINAL_EPOCHS = gate.FINAL_EPOCHS


def ensemble(scores: dict[int, np.ndarray], epochs: dict[int, int]) -> np.ndarray:
    """Element-wise mean of the seeds' float32 logits in float64."""
    return sum(scores[seed][epochs[seed] - 1].astype(np.float64) for seed in SEEDS) / len(SEEDS)


def stored_dev_ensemble() -> np.ndarray:
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        return sum(np.array(npz[f"dev_C2-s{seed}"]).astype(np.float64) for seed in SEEDS) / len(SEEDS)


def require_no_dev_access() -> None:
    for name in DEV_ACCESS_OUTPUTS:
        if (OUT / name).exists():
            raise HarnessError(f"{name} exists; the accuracy decision must precede any dev access")


def r2_module():
    if gate.sha256_file(R2_PY) != R2_PY_SHA256:
        raise HarnessError("hash mismatch for research_tiny_r2.py")
    sys.path.insert(0, str(REPO / "src"))
    from sakura_rerank import research_tiny_r2  # noqa: E402

    return research_tiny_r2


def r2_inputs(r2) -> tuple[Path, Path, Path, Path]:
    return (V1_DIR / "train-dev-cache.npz", V1_DIR / "train-dev-cache.manifest.json",
            R2_DIR / "cost-gap.npz", R2_DIR / "cost-gap.manifest.json")


# -------------------------------------------------------------------- stages

def stage_crossfit(_: argparse.Namespace) -> None:
    gate.verify_inputs()
    fold_of, gold, scores = gate.load_train()
    base_correct = int((gold == 0).sum())
    base_errors = gate.TRAIN_COUNT - base_correct
    result = {"base_correct": base_correct, "base_errors": base_errors, "rules": {}}
    per_rule = {name: {"folds": [], "totals": dict.fromkeys(("correct", "harm", "rescue", "overrides"), 0)}
                for name in gate.RULES}
    for k in range(gate.FOLDS):
        inner = fold_of != k
        outer = ~inner
        epochs = {seed: gate.choose_epoch(scores[seed][:, inner], gold[inner]) for seed in SEEDS}
        logits = ensemble(scores, epochs)
        n_inner = int((gold[inner] == 0).sum())
        for name, (budget_kind, kinds) in gate.RULES.items():
            budget = gate.budget_for(budget_kind, n_inner)
            chosen = gate.choose_gate(logits[inner], gold[inner], budget, kinds)
            held_out = gate.outcome(gate.apply_gate(logits[outer], chosen), gold[outer])
            per_rule[name]["folds"].append({
                "fold": k, "epochs": {str(seed): epochs[seed] for seed in SEEDS},
                "inner_baseline_correct": n_inner, "harm_budget": budget,
                "score": None if chosen is None else chosen["score"],
                "tau": None if chosen is None else chosen["tau"],
                "held_out": held_out,
            })
            for field in held_out:
                per_rule[name]["totals"][field] += held_out[field]
    for name in gate.RULES:
        per_rule[name]["derived"] = gate.derived(per_rule[name]["totals"], base_correct, base_errors)
    result["rules"] = per_rule
    digest = gate.write_once(OUT / "crossfit.json", result)
    print(json.dumps({"crossfit_sha256": digest}))


def stage_select(_: argparse.Namespace) -> None:
    gate.verify_inputs()
    _, gold, scores = gate.load_train()
    base_correct = int((gold == 0).sum())
    logits = ensemble(scores, FINAL_EPOCHS)
    result = {"base_correct": base_correct, "epochs": {str(s): e for s, e in FINAL_EPOCHS.items()}}
    for name in ("main", "reference_issue21"):
        budget_kind, kinds = gate.RULES[name]
        budget = gate.budget_for(budget_kind, base_correct)
        result[name] = {"harm_budget": budget, "gate": gate.choose_gate(logits, gold, budget, kinds)}
    curves = {}
    for kind in gate.SCORES:
        top, margin = gate.margins(logits, kind)
        curves[kind] = [{"tau": tau, **{f: v for f, v in gate.outcome(gate.gated(top, margin, tau), gold).items()
                                          if f in ("harm", "rescue", "overrides")}}
                        for tau in gate.GRIDS[kind]]
    result["oof_curves"] = curves
    digest = gate.write_once(OUT / "selection.json", result)
    print(json.dumps({"selection_sha256": digest}))


def stage_decide_accuracy(_: argparse.Namespace) -> None:
    require_no_dev_access()
    crossfit, crossfit_sha = gate.read_bound(OUT / "crossfit.json")
    _, selection_sha = gate.read_bound(OUT / "selection.json")
    criteria = crossfit["rules"]["main"]["derived"]["criteria"]
    decision = {"crossfit_sha256": crossfit_sha, "selection_sha256": selection_sha,
                "criteria_1_to_3": criteria, "criteria_1_to_3_pass": all(criteria.values())}
    digest = gate.write_once(OUT / "decision-accuracy.json", decision)
    print(json.dumps({"decision_accuracy_sha256": digest, **decision}))


def stage_export(_: argparse.Namespace) -> None:
    import onnx
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    gate.verify_inputs()
    accuracy, accuracy_sha = gate.read_bound(OUT / "decision-accuracy.json")
    selection, _ = gate.read_bound(OUT / "selection.json", accuracy["selection_sha256"])
    if (OUT / "export.json").exists():
        raise HarnessError("refusing to overwrite export.json")
    r2 = r2_module()
    models = []
    for seed in SEEDS:
        path = SRC21 / "final" / f"C2-s{seed}.pt"
        if gate.sha256_file(path) != CHECKPOINTS[seed]:
            raise HarnessError(f"hash mismatch for {path.name}")
        payload = torch.load(path, map_location="cpu", weights_only=True)
        if (payload["recipe"], int(payload["seed"]), int(payload["epoch"])) != ("C2", seed, FINAL_EPOCHS[seed]):
            raise HarnessError("checkpoint identity differs from the plan")
        model = r2.build_model()
        model.load_state_dict(payload["state_dict"], strict=True)
        model.eval()
        models.append(model)

    class SeedEnsemble(torch.nn.Module):
        def __init__(self, members):
            super().__init__()
            self.members = torch.nn.ModuleList(members)

        def forward(self, *inputs):
            return torch.stack([member(*inputs) for member in self.members]).mean(dim=0)

    ensemble_model = SeedEnsemble(models).eval()
    fp32_path, int8_path = OUT / "ensemble-fp32.onnx", OUT / "ensemble-int8.onnx"
    for path in (fp32_path, int8_path):
        if path.exists():
            raise HarnessError(f"refusing to overwrite {path.name}")
    fixture = r2._example_inputs(1)
    dynamic_axes = {name: {0: "batch"} for name in r2.INPUT_NAMES}
    dynamic_axes["scores"] = {0: "batch"}
    torch.onnx.export(ensemble_model, fixture, fp32_path, input_names=list(r2.INPUT_NAMES),
                      output_names=["scores"], dynamic_axes=dynamic_axes, opset_version=18,
                      do_constant_folding=True, dynamo=False)
    onnx.checker.check_model(onnx.load(fp32_path))
    quantize_dynamic(fp32_path, int8_path, weight_type=QuantType.QInt8, per_channel=True, reduce_range=False)
    onnx.checker.check_model(onnx.load(int8_path))
    values = r2.load_inputs(*r2_inputs(r2))
    batches = [{name: values[f"dev_{name}"][start:start + r2.BATCH_SIZE] for name in r2.INPUT_NAMES}
               for start in range(0, gate.DEV_COUNT, r2.BATCH_SIZE)]
    with torch.inference_mode():
        torch_logits = np.concatenate([ensemble_model(*(torch.from_numpy(b[n]) for n in r2.INPUT_NAMES)).numpy()
                                       for b in batches])
    onnx_logits = {}
    for label, path in (("fp32", fp32_path), ("int8", int8_path)):
        session = r2._cpu_session(path)
        onnx_logits[label] = np.concatenate([session.run(["scores"], b)[0] for b in batches])
        del session
    stored = stored_dev_ensemble()
    final_gate = selection["main"]["gate"]
    decision = {name: gate.apply_gate(array, final_gate) for name, array in
                (("stored", stored), ("torch", torch_logits), ("fp32", onnx_logits["fp32"]),
                 ("int8", onnx_logits["int8"]))}
    result = {
        "decision_accuracy_sha256": accuracy_sha,
        "final_gate": None if final_gate is None else {"score": final_gate["score"], "tau": final_gate["tau"]},
        "onnx": {label: {"file": path.name, "bytes": path.stat().st_size, "sha256": gate.sha256_file(path)}
                 for label, path in (("fp32", fp32_path), ("int8", int8_path))},
        "checkpoint_sha256": {str(seed): CHECKPOINTS[seed] for seed in SEEDS},
        "parity": {
            "record_count": gate.DEV_COUNT,
            "fp32_vs_stored_max_abs_logit_error": float(np.max(np.abs(onnx_logits["fp32"] - stored))),
            "torch_vs_stored_max_abs_logit_error": float(np.max(np.abs(torch_logits - stored))),
            "int8_vs_fp32_max_abs_logit_error": float(np.max(np.abs(onnx_logits["int8"] - onnx_logits["fp32"]))),
            "fp32_vs_stored_decision_mismatch_count": int(np.sum(decision["fp32"] != decision["stored"])),
            "torch_vs_stored_decision_mismatch_count": int(np.sum(decision["torch"] != decision["stored"])),
            "int8_vs_fp32_decision_mismatch_count": int(np.sum(decision["int8"] != decision["fp32"])),
        },
        "software": {"torch": torch.__version__, "onnx": onnx.__version__, "onnxruntime": ort.__version__},
    }
    result["criterion_5_pass"] = result["parity"]["fp32_vs_stored_decision_mismatch_count"] == 0
    digest = gate.write_once(OUT / "export.json", result)
    print(json.dumps({"export_sha256": digest, "parity": result["parity"]}))


def stage_benchmark(_: argparse.Namespace) -> None:
    export, _ = gate.read_bound(OUT / "export.json")
    r2 = r2_module()
    if gate.sha256_file(R2_DIR / R2_FP32[0]) != R2_FP32[1]:
        raise HarnessError("hash mismatch for the r2 FP32 ONNX file")
    targets = (("fp32", OUT / "ensemble-fp32.onnx", export["onnx"]["fp32"]["sha256"]),
               ("int8", OUT / "ensemble-int8.onnx", export["onnx"]["int8"]["sha256"]),
               ("r2-single-fp32", R2_DIR / R2_FP32[0], R2_FP32[1]))
    for label, path, expected in targets:
        report_path = OUT / f"{label}-benchmark.report.json"
        if report_path.exists():
            raise HarnessError(f"refusing to overwrite {report_path.name}")
        if gate.sha256_file(path) != expected:
            raise HarnessError(f"hash mismatch for {path.name}")
        report = r2.benchmark_onnx(path, *r2_inputs(r2), report_path,
                                   warmup_runs=WARMUP_RUNS, measured_runs=MEASURED_RUNS)
        print(json.dumps({label: report["latency_ms"], "failures": report["contract"]["failure_count"]}))


def stage_decide(_: argparse.Namespace) -> None:
    if (OUT / "dev-eval.json").exists():
        raise HarnessError("dev was already evaluated; the decision must precede it")
    accuracy, accuracy_sha = gate.read_bound(OUT / "decision-accuracy.json")
    export, export_sha = gate.read_bound(OUT / "export.json")
    if export["decision_accuracy_sha256"] != accuracy_sha:
        raise HarnessError("export is not bound to the accuracy decision")
    benchmark, benchmark_sha = gate.read_bound(OUT / "fp32-benchmark.report.json")
    if benchmark["model"]["sha256"] != export["onnx"]["fp32"]["sha256"]:
        raise HarnessError("benchmark measured a different FP32 file")
    contract = benchmark["contract"]
    if (contract["measured_runs"], contract["failure_count"], contract["batch_size"],
            contract["ort_intra_op_threads"], contract["ort_inter_op_threads"]) != (MEASURED_RUNS, 0, 1, 1, 1):
        raise HarnessError("benchmark contract differs from the plan")
    criteria = {
        **accuracy["criteria_1_to_3"],
        "fp32_ensemble_p95_at_most_2_ms": benchmark["latency_ms"]["p95"] <= P95_LIMIT_MS,
        "fp32_decisions_equal_stored_on_all_dev_rows": export["criterion_5_pass"],
    }
    decision = {"decision_accuracy_sha256": accuracy_sha, "export_sha256": export_sha,
                "fp32_benchmark_sha256": benchmark_sha, "criteria": criteria,
                "adopted": all(criteria.values())}
    digest = gate.write_once(OUT / "decision.json", decision)
    print(json.dumps({"decision_sha256": digest, "adopted": decision["adopted"], "criteria": criteria}))


def stage_eval_dev(_: argparse.Namespace) -> None:
    gate.verify_inputs()
    target = OUT / "dev-eval.json"
    if target.exists():
        raise HarnessError("dev has already been evaluated once")
    decision, decision_sha = gate.read_bound(OUT / "decision.json")
    accuracy, _ = gate.read_bound(OUT / "decision-accuracy.json", decision["decision_accuracy_sha256"])
    selection, selection_sha = gate.read_bound(OUT / "selection.json", accuracy["selection_sha256"])
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        dev_gold = np.array(npz["dev_gold"])
    logits = stored_dev_ensemble()
    base_correct = int((dev_gold == 0).sum())
    base_errors = gate.DEV_COUNT - base_correct
    final_gate = selection["main"]["gate"]
    gated_outcome = gate.outcome(gate.apply_gate(logits, final_gate), dev_gold)
    result = {
        "decision_sha256": decision_sha, "selection_sha256": selection_sha,
        "base_correct": base_correct, "base_errors": base_errors,
        "gate": None if final_gate is None else {"score": final_gate["score"], "tau": final_gate["tau"]},
        "ungated": gate.outcome(logits.argmax(axis=1), dev_gold),
        "gated": gated_outcome,
        "gated_derived": gate.derived(gated_outcome, base_correct, base_errors),
        "harm_below_limit_one_sided_p": float(gate.binom_cdf_exact(gated_outcome["harm"], base_correct, gate.HARM_RATE)),
    }
    digest = gate.write_once(target, result)
    print(json.dumps({"dev_eval_sha256": digest}))


def _comparable(crossfit: dict, selection: dict, decision_accuracy: dict, dev_eval: dict) -> dict:
    """The fields the independent recomputation must reproduce exactly."""
    return {
        "crossfit": {rule: {"totals": body["totals"],
                            "folds": [{f: fold[f] for f in ("fold", "epochs", "harm_budget", "score", "tau")}
                                      for fold in body["folds"]]}
                     for rule, body in crossfit["rules"].items()},
        "final_gate": None if selection["main"]["gate"] is None
        else {f: selection["main"]["gate"][f] for f in ("score", "tau")},
        "criteria_1_to_3_pass": decision_accuracy["criteria_1_to_3_pass"],
        "dev_gated": dev_eval["gated"],
    }


def stage_publish(_: argparse.Namespace) -> None:
    if REPORT.exists():
        raise HarnessError("refusing to overwrite the tracked report")
    crossfit, crossfit_sha = gate.read_bound(OUT / "crossfit.json")
    selection, selection_sha = gate.read_bound(OUT / "selection.json")
    accuracy, accuracy_sha = gate.read_bound(OUT / "decision-accuracy.json")
    export, export_sha = gate.read_bound(OUT / "export.json")
    decision, decision_sha = gate.read_bound(OUT / "decision.json")
    dev_eval, dev_eval_sha = gate.read_bound(OUT / "dev-eval.json")
    if (accuracy["crossfit_sha256"], accuracy["selection_sha256"]) != (crossfit_sha, selection_sha):
        raise HarnessError("accuracy decision is not bound to the current crossfit/selection")
    if (decision["decision_accuracy_sha256"], decision["export_sha256"]) != (accuracy_sha, export_sha):
        raise HarnessError("decision is not bound to the accuracy decision and export")
    if dev_eval["decision_sha256"] != decision_sha:
        raise HarnessError("dev evaluation is not bound to the decision")
    benchmarks = {}
    for label in ("fp32", "int8", "r2-single-fp32"):
        bench, bench_sha = gate.read_bound(OUT / f"{label}-benchmark.report.json")
        benchmarks[label] = {"latency_ms": bench["latency_ms"], "model_sha256": bench["model"]["sha256"],
                             "contract": bench["contract"], "report_sha256": bench_sha}
    if benchmarks["fp32"]["report_sha256"] != decision["fp32_benchmark_sha256"]:
        raise HarnessError("decision is not bound to the FP32 benchmark")
    recompute, recompute_sha = gate.read_bound(OUT / "recompute.json")
    if gate.canonical(recompute["comparable"]) != gate.canonical(_comparable(crossfit, selection, accuracy, dev_eval)):
        raise HarnessError("independent recomputation disagrees")
    report = {
        "schema_version": 1,
        "report_kind": f"sakura_rerank_issue{ISSUE}_ensemble_gate",
        "issue": ISSUE,
        "status": "research_only_gate_a_failed",
        "final_holdout_used": False,
        "production_change_authorized": False,
        "artifact_distribution_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
        "plan_body_sha256": PLAN_BODY_SHA256,
        "inputs": {**gate.INPUTS, **{f"final/C2-s{s}.pt": h for s, h in CHECKPOINTS.items()},
                   "issue25_run_py": GATE_PY_SHA256, "research_tiny_r2_py": R2_PY_SHA256,
                   "r2_fp32_onnx": R2_FP32[1]},
        "protocol": {
            "seeds": list(SEEDS), "ensemble": "mean of float64-converted logits of the three C2 models",
            "gate_rules": "Issue #25 run.py, imported by hash", "p95_limit_ms": P95_LIMIT_MS,
            "warmup_runs": WARMUP_RUNS, "measured_runs": MEASURED_RUNS,
            "accuracy_decision_written_before_dev": True, "dev_evaluations": 1,
        },
        "train": {"row_count": gate.TRAIN_COUNT, "baseline_correct": crossfit["base_correct"],
                  "baseline_errors": crossfit["base_errors"]},
        "dev": {"row_count": gate.DEV_COUNT, "baseline_correct": dev_eval["base_correct"],
                "baseline_errors": dev_eval["base_errors"]},
        "crossfit": crossfit["rules"],
        "final_selection": {k: v for k, v in selection.items() if k != "base_correct"},
        "export": {k: v for k, v in export.items() if k != "decision_accuracy_sha256"},
        "benchmarks": benchmarks,
        "decision": {"criteria": decision["criteria"], "adopted": decision["adopted"]},
        "dev_reference": {k: v for k, v in dev_eval.items() if k not in ("decision_sha256", "selection_sha256")},
        "independent_recomputation": {"matches": True, "script_sha256": gate.sha256_file(EXP / "recompute.py"),
                                      "output_sha256": recompute_sha},
        "artifacts": {"run_py_sha256": gate.sha256_file(Path(__file__)), "crossfit_sha256": crossfit_sha,
                      "selection_sha256": selection_sha, "decision_accuracy_sha256": accuracy_sha,
                      "export_sha256": export_sha, "decision_sha256": decision_sha,
                      "dev_eval_sha256": dev_eval_sha},
    }
    gate.write_once(REPORT, report)
    print(json.dumps({"report": REPORT.name, "adopted": decision["adopted"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    stages = {"crossfit": stage_crossfit, "select": stage_select, "decide-accuracy": stage_decide_accuracy,
              "export": stage_export, "benchmark": stage_benchmark, "decide": stage_decide,
              "eval-dev": stage_eval_dev, "publish": stage_publish}
    for name in stages:
        sub.add_parser(name)
    args = parser.parse_args()
    stages[args.stage](args)


if __name__ == "__main__":
    main()
