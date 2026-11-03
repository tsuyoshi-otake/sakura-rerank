"""Independent recomputation of Issue #29 counts from saved numeric arrays."""
import json
import os
import sys
from fractions import Fraction
from math import comb

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
G21 = os.path.join(ROOT, "data", "generated", "issue-21-retrain")
G29 = os.path.join(ROOT, "data", "generated", "issue-29-distill-gate")
SEEDS = ["20260814", "20261103", "20261104"]
L_GRID = [i / 10 for i in range(0, 81)]
P_GRID = [i / 100 for i in range(0, 101)]


def kmax(n):
    p = Fraction(1, 400)
    cdf = Fraction(0)
    best = -1
    for k in range(n + 1):
        cdf += comb(n, k) * p**k * (1 - p) ** (n - k)
        if cdf <= Fraction(1, 20):
            best = k
        else:
            break
    return best


def prep(z, gold):
    """z (n,6) float -> top t, scores L and P, in float64."""
    z = z.astype(np.float64)
    n = z.shape[0]
    t = np.argmax(z, axis=1)
    idx = np.arange(n)
    valid = z > -5000.0
    L = z[idx, t] - z[:, 0]
    m = np.where(valid, z, -np.inf).max(axis=1, keepdims=True)
    e = np.where(valid, np.exp(z - m), 0.0)
    p = e / e.sum(axis=1, keepdims=True)
    P = p[idx, t] - p[:, 0]
    return t, L, P


def counts(t, s, tau, gold):
    ov = (t != 0) & (s > tau)
    final = np.where(ov, t, 0)
    base = gold == 0
    return {
        "correct": int((final == gold).sum()),
        "harm": int((base & (final != 0)).sum()),
        "overrides": int(ov.sum()),
        "rescue": int((~base & (final == gold)).sum()),
    }


def ungated(z, gold):
    t = np.argmax(z.astype(np.float64), axis=1)
    return int((t == gold).sum()), int(((gold == 0) & (t != 0)).sum())


def pick_epoch(scores, gold):
    best = None
    for e in range(scores.shape[0]):
        c, h = ungated(scores[e], gold)
        key = (-c, h, e)
        if best is None or key < best[0]:
            best = (key, e)
    return best[1] + 1


def choose(z, gold, rule):
    n0 = int((gold == 0).sum())
    t, L, P = prep(z, gold)
    if rule == "reference_issue21":
        budget = n0 // 400
        cands = ["L"]
    else:
        budget = kmax(n0)
        cands = {"main": ["L", "P"], "fixed_L": ["L"], "fixed_P": ["P"]}[rule]
    results = []
    for name in cands:
        s, grid = (L, L_GRID) if name == "L" else (P, P_GRID)
        for tau in grid:
            c = counts(t, s, tau, gold)
            if c["harm"] <= budget:
                results.append((name, tau, c))
                break
    if not results:
        return budget, None, None
    best = None
    for name, tau, c in results:  # order L then P
        key = (-c["rescue"], c["harm"])
        if best is None or key < best[0]:
            best = (key, name, tau)
    return budget, best[1], best[2]


def apply_gate(z, gold, score, tau):
    t, L, P = prep(z, gold)
    if score is None:
        return counts(t, np.zeros(len(gold)), 1e9, gold)
    return counts(t, L if score == "L" else P, tau, gold)


def crossfit(oof, gold, fold, rule):
    totals = {"correct": 0, "harm": 0, "overrides": 0, "rescue": 0}
    folds = []
    for k in range(5):
        sel = fold != k
        ho = fold == k
        ep = pick_epoch(oof[:, sel], gold[sel])
        budget, score, tau = choose(oof[ep - 1][sel], gold[sel], rule)
        c = apply_gate(oof[ep - 1][ho], gold[ho], score, tau)
        for key in totals:
            totals[key] += c[key]
        folds.append({"fold": k, "epoch": ep, "harm_budget": budget, "score": score, "tau": tau})
    return {"totals": totals, "folds": folds}


def selfcheck(fold, gold):
    rep = json.load(open(os.path.join(ROOT, "reports", "issue-25-confidence-gate.json"), encoding="utf-8"))
    ok = True
    for s in SEEDS:
        oof = np.load(os.path.join(G21, "oof", f"C2-s{s}.npz"))["scores"]
        for rule in ["main", "reference_issue21", "fixed_L", "fixed_P"]:
            mine = crossfit(oof, gold, fold, rule)
            ref = rep["crossfit"][s][rule]
            same = mine["totals"] == ref["totals"]
            for a, b in zip(mine["folds"], ref["folds"]):
                same &= (a["epoch"], a["harm_budget"], a["score"], a["tau"]) == (
                    b["epoch"], b["harm_budget"], b["score"], b["tau"])
            ok &= same
            print("selfcheck", s, rule, "MATCH" if same else "DIFF", mine["totals"])
    print("selfcheck all match:", ok)


def main():
    fold = np.load(os.path.join(G21, "folds.npz"))["fold"]
    pr = np.load(os.path.join(G21, "predictions.npz"))
    gold, dev_gold = pr["train_gold"], pr["dev_gold"]
    if "--selfcheck" in sys.argv:
        selfcheck(fold, gold)
        return
    out_path = os.path.join(G29, "recompute.json")
    if os.path.exists(out_path):
        sys.exit("refusing to overwrite " + out_path)

    teacher_epochs = [dict() for _ in range(5)]
    for s in SEEDS:
        nested = np.load(os.path.join(G29, "nested", f"C2-s{s}.npz"))["scores"]
        for k in range(5):
            sel = fold != k
            teacher_epochs[k][s] = pick_epoch(nested[k][:, sel], gold[sel])

    cf = {}
    students = {}
    for s in SEEDS:
        oof = np.load(os.path.join(G29, "students", f"C2KD-s{s}.npz"))["scores"]
        students[s] = oof
        cf[s] = {r: crossfit(oof, gold, fold, r)
                 for r in ["main", "reference_issue21", "fixed_L", "fixed_P"]}

    oof0 = students[SEEDS[0]]
    final_epoch = pick_epoch(oof0, gold)
    _, fs, ft = choose(oof0[final_epoch - 1], gold, "main")
    final_gate = None if fs is None else {"score": fs, "tau": ft}

    n0 = int((gold == 0).sum())
    nw = len(gold) - n0
    crit = True
    for s in SEEDS:
        t = cf[s]["main"]["totals"]
        crit &= (400 * t["harm"] <= n0 and t["rescue"] >= 3 * t["harm"]
                 and 10 * (t["rescue"] - t["harm"]) >= nw)

    dev = np.load(os.path.join(G29, "final", "dev-logits.npz"))["scores"]
    dev_gated = apply_gate(dev, dev_gold, fs, ft)

    obj = {"comparable": {
        "teacher_epochs": teacher_epochs,
        "crossfit": cf,
        "final_epoch": final_epoch,
        "final_gate": final_gate,
        "criteria_1_to_3_pass": bool(crit),
        "dev_gated": dev_gated,
    }}
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(json.dumps(obj, sort_keys=True))


if __name__ == "__main__":
    main()
