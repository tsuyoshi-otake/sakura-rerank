"""Independent recomputation of the Issue #27 ensemble-gate counts (numpy + stdlib)."""
import hashlib, json, sys
from fractions import Fraction
from math import comb
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data/generated/issue-21-retrain"
OUT = ROOT / "data/generated/issue-27-ensemble-gate/recompute.json"
HASHES = {
    "folds.npz": "0fb609ad40b4aaf18051b2886ca76cf71a635b970f2becba22aab0569b3502cc",
    "oof/C2-s20260814.npz": "d9f1bda4dd659ebb9ac621285ef3e48eec6ffb95c4b8648de2ff522055f1b3d5",
    "oof/C2-s20261103.npz": "a3a6f8e87432557db36bdb904ef02910dae6ed559475b435a1d900c17125ca55",
    "oof/C2-s20261104.npz": "f4e0761a4a2949af5914c15fbc300115c513f2f7649744a2645eb9c97ed6a740",
    "predictions.npz": "3be6ad904fd669b088ebfe9553bdc1f83c83f3ca29b077480167c30eb7392e52",
}
SEEDS = [20260814, 20261103, 20261104]
FINAL_EPOCH = {20260814: 9, 20261103: 8, 20261104: 10}
GRID = {"L": [round(i / 10, 1) for i in range(81)], "P": [round(i / 100, 2) for i in range(101)]}


def kmax(n):
    p, q = Fraction(1, 400), Fraction(399, 400)
    best, cdf = None, Fraction(0)
    for k in range(n + 1):
        cdf += comb(n, k) * p**k * q ** (n - k)
        if cdf <= Fraction(1, 20):
            best = k
        else:
            break
    return best


def scores(z):
    t = z.argmax(1)
    r = np.arange(len(z))
    L = z[r, t] - z[:, 0]
    e = np.exp(z - z.max(1, keepdims=True))
    p = e / e.sum(1, keepdims=True)
    P = p[r, t] - p[:, 0]
    return t, {"L": L, "P": P}


def count(t, s, gold, tau):
    ov = (t != 0) if tau is None else ((t != 0) & (s > tau))
    if tau is None:
        ov = np.zeros(len(t), bool)
    pred = np.where(ov, t, 0)
    return {"correct": int((pred == gold).sum()),
            "harm": int(((gold == 0) & (pred != 0)).sum()),
            "overrides": int(ov.sum()),
            "rescue": int(((gold != 0) & (pred == gold)).sum())}


def best_tau(t, S, gold, score, budget):
    for tau in GRID[score]:  # smallest admissible
        c = count(t, S[score], gold, tau)
        if c["harm"] <= budget:
            return tau, c
    return None, None


def select(z, gold, rule):
    """returns (score, tau, budget); tau None => no override"""
    t, S = scores(z)
    n = int((gold == 0).sum())
    if rule == "reference_issue21":
        b = n // 400
        tau, _ = best_tau(t, S, gold, "L", b)
        return ("L" if tau is not None else None), tau, b
    b = kmax(n)
    cands = [sc for sc in ("L", "P") if rule in ("main", "fixed_" + sc)]
    best = None
    for sc in cands:  # L first => wins ties
        tau, c = best_tau(t, S, gold, sc, b)
        if tau is None:
            continue
        key = (-c["rescue"], c["harm"])
        if best is None or key < best[0]:
            best = (key, sc, tau)
    if best is None:
        return None, None, b
    return best[1], best[2], b


def apply(z, gold, score, tau):
    t, S = scores(z)
    if tau is None:
        return count(t, S["L"], gold, None)
    return count(t, S[score], gold, tau)


def pick_epoch(sc20, gold):
    best = None
    for e in range(sc20.shape[0]):
        t = sc20[e].astype(np.float64).argmax(1)
        c = int((t == gold).sum())
        h = int(((gold == 0) & (t != 0)).sum())
        key = (-c, h, e)
        if best is None or key < best[0]:
            best = (key, e)
    return best[1] + 1


def main(seeds=SEEDS, write=True):
    for rel, h in HASHES.items():
        got = hashlib.sha256((D / rel).read_bytes()).hexdigest()
        if got != h:
            sys.exit(f"hash mismatch {rel}")
    fold = np.load(D / "folds.npz")["fold"]
    pr = np.load(D / "predictions.npz")
    gold, dgold = pr["train_gold"], pr["dev_gold"]
    oof = {s: np.load(D / f"oof/C2-s{s}.npz")["scores"] for s in seeds}
    res = {}
    for rule in ("main", "reference_issue21", "fixed_L", "fixed_P"):
        tot = {"correct": 0, "harm": 0, "overrides": 0, "rescue": 0}
        folds = []
        for k in range(5):
            inn, out = fold != k, fold == k
            ep = {s: pick_epoch(oof[s][:, inn, :].astype(np.float64), gold[inn]) for s in seeds}
            zi = np.mean([oof[s][ep[s] - 1][inn].astype(np.float64) for s in seeds], axis=0)
            zo = np.mean([oof[s][ep[s] - 1][out].astype(np.float64) for s in seeds], axis=0)
            sc, tau, b = select(zi, gold[inn], rule)
            c = apply(zo, gold[out], sc, tau)
            for key in tot:
                tot[key] += c[key]
            folds.append({"fold": k, "epochs": {str(s): ep[s] for s in seeds},
                          "harm_budget": b, "score": sc, "tau": tau})
        res[rule] = {"totals": tot, "folds": folds}
    zf = np.mean([oof[s][FINAL_EPOCH[s] - 1].astype(np.float64) for s in seeds], axis=0)
    sc, tau, b = select(zf, gold, "main")
    fg = None if tau is None else {"score": sc, "tau": tau}
    m = res["main"]["totals"]
    n_wrong = int((gold != 0).sum()); n_right = int((gold == 0).sum())
    crit = (400 * m["harm"] <= n_right and m["rescue"] >= 3 * m["harm"]
            and 10 * (m["rescue"] - m["harm"]) >= n_wrong)
    zd = np.mean([pr[f"dev_C2-s{s}"].astype(np.float64) for s in seeds], axis=0)
    dev = apply(zd, dgold, sc, tau)
    obj = {"comparable": {"crossfit": res, "final_gate": fg,
                          "criteria_1_to_3_pass": bool(crit), "dev_gated": dev}}
    extra = {"n_right": n_right, "n_wrong": n_wrong}
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    if write:
        if OUT.exists():
            sys.exit("refusing to overwrite")
        OUT.write_text(s, encoding="utf-8", newline="\n")
    return obj, extra


if __name__ == "__main__":
    if len(sys.argv) > 1:  # debug: single seed, no write
        o, ex = main([int(sys.argv[1])], write=False)
        print(json.dumps(o["comparable"]["crossfit"]))
    else:
        o, ex = main()
        print(json.dumps(o, sort_keys=True), ex)
