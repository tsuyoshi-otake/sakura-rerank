#!/usr/bin/env python3
"""Independent recomputation of candidate-vs-B0 metrics and the pre-registered
adoption decision.

Usage:
    python recompute.py <predictions.npz> <selection.json> <output.json>

Standard library + numpy only.
"""

import json
import math
import sys
from fractions import Fraction

import numpy as np

RECIPES = ("B0", "C1", "C2")
CANDIDATES = ("C1", "C2")
SEEDS = (20260814, 20261103, 20261104)
SPLITS = ("oof", "dev")
ALPHA = 0.025


def model_key(recipe, seed):
    return f"{recipe}-s{seed}"


def argmax_pred(scores):
    # np.argmax returns the index of the FIRST maximum, as specified.
    return scores.argmax(axis=1)


def tau_gated_pred(scores, tau):
    p = argmax_pred(scores)
    top = np.take_along_axis(scores, p[:, None], axis=1)[:, 0]
    margin = top - scores[:, 0]
    return np.where(margin > tau, p, 0)


def correctness(pred, gold):
    return (gold >= 0) & (pred == gold)


def summarize(correct, gold):
    base = gold == 0
    return {
        "correct": int(np.count_nonzero(correct)),
        "harm": int(np.count_nonzero(base & ~correct)),
        "rescue": int(np.count_nonzero(~base & correct)),
    }


def mcnemar(correct_c, correct_b):
    b = int(np.count_nonzero(correct_c & ~correct_b))
    c = int(np.count_nonzero(~correct_c & correct_b))
    n = b + c
    if n == 0:
        p = 1.0
    else:
        num = sum(math.comb(n, i) for i in range(min(b, c) + 1))
        p = min(1.0, float(Fraction(2 * num, 1 << n)))
    return {"b": b, "c": c, "p": p}


def main():
    npz_path, sel_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(sel_path, encoding="utf-8") as f:
        selection = json.load(f)
    sel_recipes = selection.get("recipes", {})

    with np.load(npz_path, allow_pickle=False) as data:
        gold = {
            "oof": np.asarray(data["train_gold"], dtype=np.int64),
            "dev": np.asarray(data["dev_gold"], dtype=np.int64),
        }

        per_model = {}
        correct_map = {}  # (model_key, split) -> boolean array

        for r in RECIPES:
            for s in SEEDS:
                k = model_key(r, s)
                entry = {}
                for split in SPLITS:
                    scores = data[f"{split}_{k}"]
                    corr = correctness(argmax_pred(scores), gold[split])
                    correct_map[(k, split)] = corr
                    entry[split] = summarize(corr, gold[split])
                tau = sel_recipes.get(k, {}).get("tau")
                if tau is None:
                    entry["oof_tau_gated"] = None
                    entry["dev_tau_gated"] = None
                else:
                    tau = float(tau)
                    for split in SPLITS:
                        scores = data[f"{split}_{k}"]
                        corr = correctness(
                            tau_gated_pred(scores, tau), gold[split]
                        )
                        entry[f"{split}_tau_gated"] = summarize(
                            corr, gold[split]
                        )
                per_model[k] = entry

    mcnemar_out = {}
    for cnd in CANDIDATES:
        per = {}
        for s in SEEDS:
            for split in SPLITS:
                per[f"{split}-s{s}"] = mcnemar(
                    correct_map[(model_key(cnd, s), split)],
                    correct_map[(model_key("B0", s), split)],
                )
        mcnemar_out[cnd] = per

    conditions = {}
    oof_correct_sum = {}
    for cnd in CANDIDATES:
        all_seeds_better = all(
            per_model[model_key(cnd, s)]["oof"]["correct"]
            > per_model[model_key("B0", s)]["oof"]["correct"]
            for s in SEEDS
        )
        n_below = sum(
            1 for s in SEEDS if mcnemar_out[cnd][f"oof-s{s}"]["p"] < ALPHA
        )
        oof_harm_c = sum(
            per_model[model_key(cnd, s)]["oof"]["harm"] for s in SEEDS
        )
        oof_harm_b = sum(
            per_model[model_key("B0", s)]["oof"]["harm"] for s in SEEDS
        )
        dev_corr_c = sum(
            per_model[model_key(cnd, s)]["dev"]["correct"] for s in SEEDS
        )
        dev_corr_b = sum(
            per_model[model_key("B0", s)]["dev"]["correct"] for s in SEEDS
        )
        dev_harm_c = sum(
            per_model[model_key(cnd, s)]["dev"]["harm"] for s in SEEDS
        )
        dev_harm_b = sum(
            per_model[model_key("B0", s)]["dev"]["harm"] for s in SEEDS
        )

        # Means over the same 3 seeds compare identically to sums; integer sums
        # avoid floating-point error entirely.
        oof_condition = (
            all_seeds_better and n_below >= 2 and oof_harm_c <= oof_harm_b
        )
        dev_condition = dev_corr_c >= dev_corr_b and dev_harm_c <= dev_harm_b
        conditions[cnd] = {
            "oof_condition": bool(oof_condition),
            "dev_condition": bool(dev_condition),
            "passes": bool(oof_condition and dev_condition),
            "oof_seeds_p_below_alpha": int(n_below),
        }
        oof_correct_sum[cnd] = sum(
            per_model[model_key(cnd, s)]["oof"]["correct"] for s in SEEDS
        )

    adopted = None
    best = None
    for cnd in CANDIDATES:  # C1 first; strict ">" keeps C1 on a tie.
        if conditions[cnd]["passes"] and (
            best is None or oof_correct_sum[cnd] > best
        ):
            adopted = cnd
            best = oof_correct_sum[cnd]

    out = {
        "per_model": per_model,
        "mcnemar": mcnemar_out,
        "conditions": conditions,
        "adopted": adopted,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
