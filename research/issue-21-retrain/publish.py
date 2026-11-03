"""Build the tracked aggregate report for Issue #21 (counts and hashes only).

Usage: python -I publish.py <devin_recompute_output.json> <uv.lock>
Writes reports/issue-21-retrain-experiment.json in canonical JSON.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
REPO = EXP.parents[2]
TARGET = REPO / "reports" / "issue-21-retrain-experiment.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def main() -> None:
    recompute_path, lock_path = Path(sys.argv[1]), Path(sys.argv[2])
    prepare = load("prepare.report.json")
    cache_check = load("cache-check.report.json")
    reproduction = load("reproduction.report.json")
    selection = load("selection.json")
    dev_eval = load("dev-eval.json")
    results = load("results.json")
    recompute = json.loads(recompute_path.read_text(encoding="utf-8"))
    v1_training = json.loads((REPO / "data" / "generated" / "sakura-rerank-tiny-v1-research" /
                              "training.report.json").read_text(encoding="utf-8"))
    v1_best = v1_training["history"][v1_training["best_epoch"] - 1]["dev"]

    # Independent recomputation (logic written separately from run.py) must
    # match every per-model count, every McNemar test, and the decision.
    mismatches = []
    for key, entry in recompute["per_model"].items():
        mine = results["per_model"][key]
        for field in ("oof", "dev", "oof_tau_gated", "dev_tau_gated"):
            theirs = entry.get(field)
            ours = mine.get(field)
            if theirs is None and ours is None:
                continue
            if theirs is None or ours is None or any(theirs[k] != ours[k] for k in ("correct", "harm", "rescue")):
                mismatches.append(f"{key}:{field}")
    for cand, tests in recompute["mcnemar"].items():
        mine = dict(results["candidates"][cand]["mcnemar_oof_vs_B0_gating"])
        mine.update(results["candidates"][cand]["mcnemar_dev_vs_B0_informational"])
        for name, test in tests.items():
            if (test["b"], test["c"]) != (mine[name]["b"], mine[name]["c"]) or abs(test["p"] - mine[name]["p"]) > 1e-12:
                mismatches.append(f"{cand}:{name}")
        for flag in ("oof_condition", "dev_condition", "passes", "oof_seeds_p_below_alpha"):
            if recompute["conditions"][cand][flag] != results["candidates"][cand][flag]:
                mismatches.append(f"{cand}:{flag}")
    if recompute["adopted"] != results["decision"]["adopted"]:
        mismatches.append("decision")
    if mismatches:
        # Fail closed: a disagreement means no trusted report may be published.
        raise SystemExit(json.dumps({"published": False, "mismatches": mismatches}))

    report = {
        "schema_version": 1,
        "report_kind": "sakura_rerank_issue21_retraining_experiment",
        "status": "research_only_gate_a_failed",
        "issue": 21,
        "final_holdout_used": False,
        "production_change_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
        "protocol": {
            "selection": "grouped 5-fold out-of-fold predictions on train only",
            "grouping_keys": prepare["grouping_keys"],
            "dev_evaluations": 1,
            "seeds": results["seeds"],
            "recipes": {
                "B0": "existing research_tiny recipe",
                "C1": "B0 + per-candidate -log1p((cost_i - min cost) / 1000)",
                "C2": "C1 + scorer dropout 0.1 + label smoothing 0.05 over valid candidates",
            },
            "alpha_bonferroni": results["alpha_bonferroni"],
        },
        "environment": {**reproduction["environment"], "uv_lock_sha256": sha(lock_path)},
        "reproduction_of_prototype_without_dev": {
            "all_20_train_losses_equal": reproduction["all_losses_equal"],
            "epoch3_weights_equal": reproduction["epoch3_state_equal_to_prototype"],
        },
        # The v1 prototype's epoch was chosen on dev itself, so its dev numbers
        # are optimistic and are not the comparison the adoption rules use.
        "v1_prototype_reference": {
            "epoch": v1_training["best_epoch"],
            "epoch_selected_on_dev": True,
            "dev_top1_correct": v1_best["top1_correct"],
            "dev_harm_count": v1_best["harm_count"],
            "dev_top1_correct_by_epoch": [entry["dev"]["top1_correct"] for entry in v1_training["history"]],
        },
        "folds": {k: prepare[k] for k in ("train_rows", "groups", "largest_group_rows", "fold_rows",
                                          "fold_baseline_correct", "fold_no_oracle")},
        "cache_check": cache_check["candidate_count_histogram"],
        "selection": {k: {"epoch": v["epoch"], "tau": v["tau"], "harm_limit": v["harm_limit"]}
                      for k, v in selection["recipes"].items()},
        "per_model": results["per_model"],
        "means": results["means"],
        "candidates": results["candidates"],
        "decision": results["decision"],
        "independent_recomputation": {"matches": not mismatches, "mismatches": mismatches,
                                      "script_sha256": sha(EXP / "devin_recompute.py")},
        "artifacts": {
            "run_py_sha256": sha(EXP / "run.py"),
            "selection_sha256": dev_eval["selection_sha256"],
            "predictions_sha256": dev_eval["predictions_sha256"],
            "results_sha256": sha(EXP / "results.json"),
            "dev_eval_sha256": sha(EXP / "dev-eval.json"),
            "oof_files": selection["oof_files"],
            "final_checkpoints": {path.name: sha(path) for path in sorted((EXP / "final").glob("*.pt"))},
        },
    }
    data = (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")
    if TARGET.exists():
        raise SystemExit("refusing to overwrite the tracked report")
    TARGET.write_bytes(data)
    print(json.dumps({"written": TARGET.name, "bytes": len(data), "recompute_matches": not mismatches,
                      "mismatches": mismatches}))


if __name__ == "__main__":
    main()
