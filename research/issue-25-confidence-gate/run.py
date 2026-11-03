"""Issue #25 research-only confidence-gate experiment (aggregate output only).

Reads the hash-pinned Issue #21 out-of-fold (OOF) and dev logits. It never
trains, never reads the frozen split JSONL, and never touches the final
holdout. The pre-registered plan is the Issue #25 body.

Stages (each writes its output once and refuses to overwrite it):
  crossfit   cross-fitted epoch/score/tau selection on train OOF
  select     final score and tau per seed on the full train OOF
  decide     apply the adoption rule; must run before any dev access
  eval-dev   single dev evaluation bound to the decision hash
  int8       FP32/INT8 ONNX gated decisions on dev (reference only)
  publish    tracked aggregate report; refuses unless the independent
             recomputation agrees

Nothing here prints or stores readings, surfaces, contexts, or stable IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

ISSUE = 25
EXP = Path(__file__).resolve().parent
REPO = EXP.parents[1]
GEN = REPO / "data" / "generated"
SRC21 = GEN / "issue-21-retrain"
OUT = GEN / f"issue-{ISSUE}-confidence-gate"
REPORT = REPO / "reports" / f"issue-{ISSUE}-confidence-gate.json"
R2_DIR = GEN / "sakura-rerank-tiny-r2-research"
V1_DIR = GEN / "sakura-rerank-tiny-v1-research"

PLAN_BODY_SHA256 = "461190b3be9069601f8916b703bdfc0c6d410c1d55956459be19d40312b23b99"
INPUTS = {
    "folds.npz": "0fb609ad40b4aaf18051b2886ca76cf71a635b970f2becba22aab0569b3502cc",
    "oof/C2-s20260814.npz": "d9f1bda4dd659ebb9ac621285ef3e48eec6ffb95c4b8648de2ff522055f1b3d5",
    "oof/C2-s20261103.npz": "a3a6f8e87432557db36bdb904ef02910dae6ed559475b435a1d900c17125ca55",
    "oof/C2-s20261104.npz": "f4e0761a4a2949af5914c15fbc300115c513f2f7649744a2645eb9c97ed6a740",
    "predictions.npz": "3be6ad904fd669b088ebfe9553bdc1f83c83f3ca29b077480167c30eb7392e52",
    "selection.json": "c47996ba0aa3d4f8435524fef3ccaea6d8c2e965b7753149f02647e6c4e430a6",
}
ONNX = {
    "fp32": ("sakura-rerank-tiny-v1-research-r2-fp32.onnx",
             "96d7694cc3759465a95841aa8d4cd62757f302fc13388ca9c38751c2a9ae5c64"),
    "int8": ("sakura-rerank-tiny-v1-research-r2-int8.onnx",
             "0e9abdb1fc79efd1cf9fe8587d2d04ace9fd5f3c92fd8a1be7efb85905ed6f90"),
}
R2_MODULE_SHA256 = "c2ede3575722b0cda97e0da52a04f42c2402db9cf12aec077d63993f09a95f66"
SEEDS = (20260814, 20261103, 20261104)
ARTIFACT_SEED = 20260814
FINAL_EPOCHS = {20260814: 9, 20261103: 8, 20261104: 10}
FOLDS = 5
EPOCHS = 20
TRAIN_COUNT = 12_516
DEV_COUNT = 1_788
HARM_RATE = Fraction(1, 400)
ALPHA = Fraction(1, 20)
SCORES = ("L", "P")  # tie order: L wins a full tie
GRIDS = {
    "L": tuple(round(0.1 * i, 1) for i in range(81)),
    "P": tuple(round(0.01 * i, 2) for i in range(101)),
}
RULES = {
    # name: (budget kind, scores considered); only "main" decides adoption
    "main": ("exact_binomial", ("L", "P")),
    "reference_issue21": ("floor", ("L",)),
    "fixed_L": ("exact_binomial", ("L",)),
    "fixed_P": ("exact_binomial", ("P",)),
}


class HarnessError(RuntimeError):
    pass


# ----------------------------------------------------------------- utilities

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_once(path: Path, value: object) -> str:
    if path.exists():
        raise HarnessError(f"refusing to overwrite {path.name}")
    data = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return sha256_bytes(data)


def read_bound(path: Path, expected_sha: str | None = None) -> tuple[dict, str]:
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if expected_sha is not None and digest != expected_sha:
        raise HarnessError(f"{path.name} changed after it was bound")
    return json.loads(raw), digest


def verify_inputs() -> None:
    for name, expected in INPUTS.items():
        if sha256_file(SRC21 / name) != expected:
            raise HarnessError(f"hash mismatch for {name}")
    selection = json.loads((SRC21 / "selection.json").read_text(encoding="utf-8"))
    for seed, epoch in FINAL_EPOCHS.items():
        if selection["recipes"][f"C2-s{seed}"]["epoch"] != epoch:
            raise HarnessError("Issue #21 epoch differs from the plan")


def load_train() -> tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]:
    with np.load(SRC21 / "folds.npz", allow_pickle=False) as npz:
        fold_of = np.array(npz["fold"])
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        gold = np.array(npz["train_gold"])
    scores = {}
    for seed in SEEDS:
        with np.load(SRC21 / "oof" / f"C2-s{seed}.npz", allow_pickle=False) as npz:
            scores[seed] = np.array(npz["scores"])
        if scores[seed].shape[:2] != (EPOCHS, TRAIN_COUNT) or not np.isfinite(scores[seed]).all():
            raise HarnessError("OOF scores violate the fixed shape")
    if fold_of.shape != (TRAIN_COUNT,) or gold.shape != (TRAIN_COUNT,):
        raise HarnessError("train arrays violate the fixed shape")
    if set(np.unique(fold_of).tolist()) != set(range(FOLDS)):
        raise HarnessError("fold ids violate the fixed contract")
    return fold_of, gold, scores


# ---------------------------------------------------------------- statistics

def k_max(n: int) -> int:
    """Largest k with P(Binomial(n, 1/400) <= k) <= 1/20, in exact integers (-1 if none)."""
    total = 400 ** n
    cumulative = 0
    best = -1
    for k in range(n + 1):
        cumulative += math.comb(n, k) * 399 ** (n - k)
        if ALPHA.denominator * cumulative <= ALPHA.numerator * total:
            best = k
        else:
            return best
    return best


def floor_budget(n: int) -> int:
    return (n * HARM_RATE.numerator) // HARM_RATE.denominator


def binom_cdf_exact(k: int, n: int, p: Fraction) -> Fraction:
    q = 1 - p
    return sum(Fraction(math.comb(n, i)) * p ** i * q ** (n - i) for i in range(k + 1))


def _log_cdf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 0.0 if k >= n else -math.inf
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
             + i * math.log(p) + (n - i) * math.log1p(-p) for i in range(k + 1)]
    top = max(terms)
    return top + math.log(sum(math.exp(t - top) for t in terms))


def clopper_pearson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    tail = (1.0 - level) / 2.0

    def solve(target_k: int, target: float) -> float:
        low, high = 0.0, 1.0
        for _ in range(200):
            mid = (low + high) / 2.0
            if math.exp(_log_cdf(target_k, n, mid)) > target:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0

    lower = 0.0 if k == 0 else solve(k - 1, 1.0 - tail)
    upper = 1.0 if k == n else solve(k, tail)
    return round(lower, 10), round(upper, 10)


# ---------------------------------------------------------------------- gate

def margins(scores: np.ndarray, kind: str) -> tuple[np.ndarray, np.ndarray]:
    z = scores.astype(np.float64)
    index = np.arange(len(z))
    top = z.argmax(axis=1)
    if kind == "L":
        return top, z[index, top] - z[:, 0]
    if kind == "P":
        exp = np.exp(z - z.max(axis=1, keepdims=True))
        prob = exp / exp.sum(axis=1, keepdims=True)
        return top, prob[index, top] - prob[:, 0]
    raise HarnessError("unknown score")


def gated(top: np.ndarray, margin: np.ndarray, tau: float) -> np.ndarray:
    return np.where((top != 0) & (margin > tau), top, 0)


def outcome(pred: np.ndarray, gold: np.ndarray) -> dict[str, int]:
    correct = (gold >= 0) & (pred == gold)
    base = gold == 0
    return {
        "correct": int(correct.sum()),
        "harm": int((base & ~correct).sum()),
        "rescue": int((~base & correct).sum()),
        "overrides": int((pred != 0).sum()),
    }


def choose_epoch(scores: np.ndarray, gold: np.ndarray) -> int:
    per_epoch = [outcome(scores[e].argmax(axis=1), gold) for e in range(EPOCHS)]
    return min(range(EPOCHS), key=lambda e: (-per_epoch[e]["correct"], per_epoch[e]["harm"], e)) + 1


def budget_for(kind: str, n: int) -> int:
    return k_max(n) if kind == "exact_binomial" else floor_budget(n)


def choose_gate(scores: np.ndarray, gold: np.ndarray, budget: int, kinds: tuple[str, ...]) -> dict | None:
    options = []
    for kind in kinds:
        top, margin = margins(scores, kind)
        for tau in GRIDS[kind]:
            result = outcome(gated(top, margin, tau), gold)
            if result["harm"] <= budget:
                options.append((kind, tau, result))
                break
    if not options:
        return None
    kind, tau, result = min(options, key=lambda o: (-o[2]["rescue"], o[2]["harm"], SCORES.index(o[0])))
    return {"score": kind, "tau": tau, "selection_outcome": result}


def apply_gate(scores: np.ndarray, gate: dict | None) -> np.ndarray:
    if gate is None:
        return np.zeros(len(scores), dtype=np.int64)
    top, margin = margins(scores, gate["score"])
    return gated(top, margin, gate["tau"])


def derived(totals: dict[str, int], base_correct: int, base_errors: int) -> dict:
    harm, rescue = totals["harm"], totals["rescue"]
    lower, upper = clopper_pearson(harm, base_correct)
    return {
        "harm_rate": round(harm / base_correct, 10),
        "harm_rate_ci95": [lower, upper],
        "rer": round((rescue - harm) / base_errors, 10),
        "rescue_per_harm": None if harm == 0 else round(rescue / harm, 10),
        "criteria": {
            "harm_rate_at_most_0_25_percent": HARM_RATE.denominator * harm <= HARM_RATE.numerator * base_correct,
            "rescue_at_least_3x_harm": rescue >= 3 * harm,
            "rer_at_least_10_percent": 10 * (rescue - harm) >= base_errors,
        },
    }


# -------------------------------------------------------------------- stages

def stage_crossfit(_: argparse.Namespace) -> None:
    verify_inputs()
    fold_of, gold, scores = load_train()
    base_correct = int((gold == 0).sum())
    base_errors = TRAIN_COUNT - base_correct
    result = {"base_correct": base_correct, "base_errors": base_errors, "seeds": {}}
    for seed in SEEDS:
        per_rule = {name: {"folds": [], "totals": dict.fromkeys(("correct", "harm", "rescue", "overrides"), 0)}
                    for name in RULES}
        for k in range(FOLDS):
            inner = fold_of != k
            outer = ~inner
            epoch = choose_epoch(scores[seed][:, inner], gold[inner])
            n_inner = int((gold[inner] == 0).sum())
            for name, (budget_kind, kinds) in RULES.items():
                budget = budget_for(budget_kind, n_inner)
                gate = choose_gate(scores[seed][epoch - 1][inner], gold[inner], budget, kinds)
                held_out = outcome(apply_gate(scores[seed][epoch - 1][outer], gate), gold[outer])
                per_rule[name]["folds"].append({
                    "fold": k, "epoch": epoch, "inner_baseline_correct": n_inner, "harm_budget": budget,
                    "score": None if gate is None else gate["score"],
                    "tau": None if gate is None else gate["tau"],
                    "held_out": held_out,
                })
                for field in held_out:
                    per_rule[name]["totals"][field] += held_out[field]
        for name in RULES:
            per_rule[name]["derived"] = derived(per_rule[name]["totals"], base_correct, base_errors)
        result["seeds"][str(seed)] = per_rule
    digest = write_once(OUT / "crossfit.json", result)
    print(json.dumps({"crossfit_sha256": digest}))


def stage_select(_: argparse.Namespace) -> None:
    verify_inputs()
    _, gold, scores = load_train()
    base_correct = int((gold == 0).sum())
    result = {"base_correct": base_correct, "seeds": {}}
    for seed in SEEDS:
        epoch_scores = scores[seed][FINAL_EPOCHS[seed] - 1]
        entry = {"epoch": FINAL_EPOCHS[seed]}
        for name in ("main", "reference_issue21"):
            budget_kind, kinds = RULES[name]
            budget = budget_for(budget_kind, base_correct)
            gate = choose_gate(epoch_scores, gold, budget, kinds)
            entry[name] = {"harm_budget": budget, "gate": gate}
        curves = {}
        for kind in SCORES:
            top, margin = margins(epoch_scores, kind)
            curves[kind] = [{"tau": tau, **{f: v for f, v in outcome(gated(top, margin, tau), gold).items()
                                              if f in ("harm", "rescue", "overrides")}}
                            for tau in GRIDS[kind]]
        entry["oof_curves"] = curves
        result["seeds"][str(seed)] = entry
    digest = write_once(OUT / "selection.json", result)
    print(json.dumps({"selection_sha256": digest}))


def stage_decide(_: argparse.Namespace) -> None:
    if (OUT / "dev-eval.json").exists():
        raise HarnessError("dev was already evaluated; the decision must precede it")
    crossfit, crossfit_sha = read_bound(OUT / "crossfit.json")
    _, selection_sha = read_bound(OUT / "selection.json")
    per_seed = {seed: all(crossfit["seeds"][seed]["main"]["derived"]["criteria"].values())
                for seed in crossfit["seeds"]}
    decision = {
        "crossfit_sha256": crossfit_sha,
        "selection_sha256": selection_sha,
        "rule": "adopt iff every seed meets all three criteria under the main rule (cross-fitted train OOF)",
        "per_seed_pass": per_seed,
        "adopted": all(per_seed.values()) and len(per_seed) == len(SEEDS),
    }
    digest = write_once(OUT / "decision.json", decision)
    print(json.dumps({"decision_sha256": digest, "adopted": decision["adopted"], "per_seed_pass": per_seed}))


def stage_eval_dev(_: argparse.Namespace) -> None:
    verify_inputs()
    target = OUT / "dev-eval.json"
    if target.exists():
        raise HarnessError("dev has already been evaluated once")
    decision, decision_sha = read_bound(OUT / "decision.json")
    selection, selection_sha = read_bound(OUT / "selection.json", decision["selection_sha256"])
    read_bound(OUT / "crossfit.json", decision["crossfit_sha256"])
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        dev_gold = np.array(npz["dev_gold"])
        dev_scores = {seed: np.array(npz[f"dev_C2-s{seed}"]) for seed in SEEDS}
    base_correct = int((dev_gold == 0).sum())
    base_errors = DEV_COUNT - base_correct
    seeds = {}
    for seed in SEEDS:
        gate = selection["seeds"][str(seed)]["main"]["gate"]
        gated_outcome = outcome(apply_gate(dev_scores[seed], gate), dev_gold)
        seeds[str(seed)] = {
            "gate": None if gate is None else {"score": gate["score"], "tau": gate["tau"]},
            "ungated": outcome(dev_scores[seed].argmax(axis=1), dev_gold),
            "gated": gated_outcome,
            "gated_derived": derived(gated_outcome, base_correct, base_errors),
            "harm_below_limit_one_sided_p": float(binom_cdf_exact(gated_outcome["harm"], base_correct, HARM_RATE)),
        }
    result = {"decision_sha256": decision_sha, "selection_sha256": selection_sha,
              "base_correct": base_correct, "base_errors": base_errors, "seeds": seeds}
    digest = write_once(target, result)
    print(json.dumps({"dev_eval_sha256": digest}))


def stage_int8(_: argparse.Namespace) -> None:
    import onnxruntime as ort

    verify_inputs()
    dev_eval, dev_eval_sha = read_bound(OUT / "dev-eval.json")
    if sha256_file(REPO / "src" / "sakura_rerank" / "research_tiny_r2.py") != R2_MODULE_SHA256:
        raise HarnessError("hash mismatch for research_tiny_r2.py")
    sys.path.insert(0, str(REPO / "src"))
    from sakura_rerank import research_tiny_r2 as r2  # noqa: E402

    for label, (name, expected) in ONNX.items():
        if sha256_file(R2_DIR / name) != expected:
            raise HarnessError(f"hash mismatch for the {label} ONNX file")
    values = r2.load_inputs(V1_DIR / "train-dev-cache.npz", V1_DIR / "train-dev-cache.manifest.json",
                            R2_DIR / "cost-gap.npz", R2_DIR / "cost-gap.manifest.json")
    batches = [{name: values[f"dev_{name}"][start:start + r2.BATCH_SIZE] for name in r2.INPUT_NAMES}
               for start in range(0, DEV_COUNT, r2.BATCH_SIZE)]
    logits = {}
    for label, (name, _) in ONNX.items():
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        session = ort.InferenceSession(str(R2_DIR / name), options, providers=["CPUExecutionProvider"])
        logits[label] = np.concatenate([session.run(["scores"], batch)[0] for batch in batches])
        del session
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        dev_gold = np.array(npz["dev_gold"])
        stored = np.array(npz[f"dev_C2-s{ARTIFACT_SEED}"])
    if not np.array_equal(values["dev_gold"], dev_gold):
        raise HarnessError("dev gold differs between the cache and predictions.npz")
    gate = dev_eval["seeds"][str(ARTIFACT_SEED)]["gate"]
    decisions = {"stored": apply_gate(stored, gate), "fp32": apply_gate(logits["fp32"], gate),
                 "int8": apply_gate(logits["int8"], gate)}
    base_correct = int((dev_gold == 0).sum())
    result = {
        "dev_eval_sha256": dev_eval_sha,
        "gate": gate,
        "onnx_sha256": {label: expected for label, (_, expected) in ONNX.items()},
        "fp32_vs_stored_decision_mismatch_count": int(np.sum(decisions["fp32"] != decisions["stored"])),
        "int8_vs_fp32_decision_mismatch_count": int(np.sum(decisions["int8"] != decisions["fp32"])),
        "fp32_gated": outcome(decisions["fp32"], dev_gold),
        "int8_gated": outcome(decisions["int8"], dev_gold),
        "int8_gated_derived": derived(outcome(decisions["int8"], dev_gold), base_correct, DEV_COUNT - base_correct),
        "onnxruntime": ort.__version__,
    }
    digest = write_once(OUT / "int8.json", result)
    print(json.dumps({"int8_sha256": digest}))


def _comparable(crossfit: dict, selection: dict, decision: dict, dev_eval: dict) -> dict:
    """The fields the independent recomputation must reproduce exactly."""
    return {
        "crossfit": {seed: {rule: {"totals": body["totals"],
                                   "folds": [{f: fold[f] for f in ("fold", "epoch", "harm_budget", "score", "tau")}
                                             for fold in body["folds"]]}
                            for rule, body in rules.items()}
                     for seed, rules in crossfit["seeds"].items()},
        "final_gates": {seed: None if entry["main"]["gate"] is None
                        else {f: entry["main"]["gate"][f] for f in ("score", "tau")}
                        for seed, entry in selection["seeds"].items()},
        "adopted": decision["adopted"],
        "dev_gated": {seed: entry["gated"] for seed, entry in dev_eval["seeds"].items()},
    }


def stage_publish(args: argparse.Namespace) -> None:
    if REPORT.exists():
        raise HarnessError("refusing to overwrite the tracked report")
    crossfit, crossfit_sha = read_bound(OUT / "crossfit.json")
    selection, selection_sha = read_bound(OUT / "selection.json")
    decision, decision_sha = read_bound(OUT / "decision.json")
    dev_eval, dev_eval_sha = read_bound(OUT / "dev-eval.json")
    int8, int8_sha = read_bound(OUT / "int8.json")
    if (decision["crossfit_sha256"], decision["selection_sha256"]) != (crossfit_sha, selection_sha):
        raise HarnessError("decision is not bound to the current crossfit/selection")
    if dev_eval["decision_sha256"] != decision_sha or int8["dev_eval_sha256"] != dev_eval_sha:
        raise HarnessError("dev or INT8 evaluation is not bound to the decision")
    recompute_script = EXP / "recompute.py"
    recompute, recompute_sha = read_bound(OUT / "recompute.json")
    expected = _comparable(crossfit, selection, decision, dev_eval)
    if canonical(recompute["comparable"]) != canonical(expected):
        raise HarnessError("independent recomputation disagrees")
    report = {
        "schema_version": 1,
        "report_kind": f"sakura_rerank_issue{ISSUE}_confidence_gate",
        "issue": ISSUE,
        "status": "research_only_gate_a_failed",
        "final_holdout_used": False,
        "production_change_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
        "plan_body_sha256": PLAN_BODY_SHA256,
        "inputs": {**INPUTS, **{f"onnx_{label}": sha for label, (_, sha) in ONNX.items()}},
        "protocol": {
            "seeds": list(SEEDS), "folds": FOLDS, "epochs_searched": EPOCHS,
            "score_grids": {kind: [grid[0], grid[-1], len(grid)] for kind, grid in GRIDS.items()},
            "harm_rate_limit": "1/400", "one_sided_alpha": "1/20",
            "decision_rule": decision["rule"], "decision_written_before_dev": True, "dev_evaluations": 1,
        },
        "train": {"row_count": TRAIN_COUNT, "baseline_correct": crossfit["base_correct"],
                  "baseline_errors": crossfit["base_errors"]},
        "dev": {"row_count": DEV_COUNT, "baseline_correct": dev_eval["base_correct"],
                "baseline_errors": dev_eval["base_errors"]},
        "crossfit": crossfit["seeds"],
        "final_selection": selection["seeds"],
        "decision": {"adopted": decision["adopted"], "per_seed_pass": decision["per_seed_pass"]},
        "dev_reference": dev_eval["seeds"],
        "int8_reference": {k: v for k, v in int8.items() if k != "dev_eval_sha256"},
        "independent_recomputation": {"matches": True, "script_sha256": sha256_file(recompute_script),
                                      "output_sha256": recompute_sha},
        "artifacts": {"run_py_sha256": sha256_file(Path(__file__)), "crossfit_sha256": crossfit_sha,
                      "selection_sha256": selection_sha, "decision_sha256": decision_sha,
                      "dev_eval_sha256": dev_eval_sha, "int8_sha256": int8_sha},
    }
    write_once(REPORT, report)
    print(json.dumps({"report": REPORT.name, "adopted": decision["adopted"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("crossfit", "select", "decide", "eval-dev", "int8", "publish"):
        sub.add_parser(name)
    args = parser.parse_args()
    {"crossfit": stage_crossfit, "select": stage_select, "decide": stage_decide,
     "eval-dev": stage_eval_dev, "int8": stage_int8, "publish": stage_publish}[args.stage](args)


if __name__ == "__main__":
    main()
