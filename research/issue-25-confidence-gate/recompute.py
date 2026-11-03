"""Independent recomputation of Issue #25 (cross-fit confidence gate)."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "data" / "generated" / "issue-21-retrain"
OUT = ROOT / "data" / "generated" / "issue-25-confidence-gate" / "recompute.json"
SEEDS = [20260814, 20261103, 20261104]
HASHES = {
    "folds.npz": "0fb609ad40b4aaf18051b2886ca76cf71a635b970f2becba22aab0569b3502cc",
    "oof/C2-s20260814.npz": "d9f1bda4dd659ebb9ac621285ef3e48eec6ffb95c4b8648de2ff522055f1b3d5",
    "oof/C2-s20261103.npz": "a3a6f8e87432557db36bdb904ef02910dae6ed559475b435a1d900c17125ca55",
    "oof/C2-s20261104.npz": "f4e0761a4a2949af5914c15fbc300115c513f2f7649744a2645eb9c97ed6a740",
    "predictions.npz": "3be6ad904fd669b088ebfe9553bdc1f83c83f3ca29b077480167c30eb7392e52",
    "selection.json": "c47996ba0aa3d4f8435524fef3ccaea6d8c2e965b7753149f02647e6c4e430a6",
}
TAUS = {
    "L": [round(0.1 * i, 1) for i in range(81)],
    "P": [round(0.01 * i, 2) for i in range(101)],
}


def kmax(n):
    """max k with P(Bin(n,1/400) <= k) <= 0.05, exact integers. -1 if none."""
    limit = 400 ** n  # accept iff 20 * sum_{i<=k} C(n,i) 399^(n-i) <= 400^n
    s, best = 0, -1
    for k in range(n + 1):
        s += math.comb(n, k) * 399 ** (n - k)
        if 20 * s <= limit:
            best = k
        else:
            break
    return best


def outcome(pred, gold):
    correct = (gold >= 0) & (pred == gold)
    return {
        "correct": int(correct.sum()),
        "harm": int(((gold == 0) & ~correct).sum()),
        "rescue": int(((gold != 0) & correct).sum()),
        "overrides": int((pred != 0).sum()),
    }


def top_and_scores(logits):
    z = logits.astype(np.float64)
    t = np.argmax(z, axis=1)
    idx = np.arange(len(z))
    zl = z[idx, t] - z[:, 0]
    e = np.exp(z - z.max(axis=1, keepdims=True))
    p = e / e.sum(axis=1, keepdims=True)
    return t, {"L": zl, "P": p[idx, t] - p[:, 0]}


def gate_pred(t, sc, tau):
    return np.where(sc > tau, t, 0)


def pick_tau(t, sc, gold, name, budget):
    """Smallest tau on the grid with harm <= budget; None if none."""
    for tau in TAUS[name]:
        o = outcome(gate_pred(t, sc[name], tau), gold)
        if o["harm"] <= budget:
            return tau, o
    return None


def choose(t, sc, gold, names, budget_fn):
    n = int((gold == 0).sum())
    budget = budget_fn(n)
    cands = []
    for name in names:
        r = pick_tau(t, sc, gold, name, budget)
        if r is not None:
            cands.append((-r[1]["rescue"], r[1]["harm"], 0 if name == "L" else 1, name, r[0]))
    if not cands:
        return budget, None, None
    cands.sort()
    return budget, cands[0][3], cands[0][4]


def pick_epoch(scores, gold):
    best = None
    for e in range(scores.shape[0]):
        o = outcome(np.argmax(scores[e].astype(np.float64), axis=1), gold)
        key = (-o["correct"], o["harm"], e)
        if best is None or key < best:
            best = key
    return best[2]  # 0-based


RULES = {
    "main": (("L", "P"), kmax),
    "reference_issue21": (("L",), lambda n: n // 400),
    "fixed_L": (("L",), kmax),
    "fixed_P": (("P",), kmax),
}


def main():
    for rel, h in HASHES.items():
        got = hashlib.sha256((IN / rel).read_bytes()).hexdigest()
        if got != h:
            raise SystemExit(f"hash mismatch: {rel}")
    folds = np.load(IN / "folds.npz")["fold"]
    pred_npz = np.load(IN / "predictions.npz")
    train_gold = pred_npz["train_gold"]
    dev_gold = pred_npz["dev_gold"]
    sel = json.loads((IN / "selection.json").read_text(encoding="utf-8"))
    n_all = int((train_gold == 0).sum())
    n_wrong = int((train_gold != 0).sum())
    assert len(train_gold) == 12516 and n_all == 11120 and n_wrong == 1396

    crossfit, final_gates, dev_gated = {}, {}, {}
    for seed in SEEDS:
        oof = np.load(IN / "oof" / f"C2-s{seed}.npz")["scores"]
        crossfit[str(seed)] = {r: {"totals": dict(correct=0, harm=0, rescue=0, overrides=0), "folds": []} for r in RULES}
        for k in range(5):
            inner = folds != k
            outer = folds == k
            e = pick_epoch(oof[:, inner, :], train_gold[inner])
            ti, si = top_and_scores(oof[e][inner])
            to, so = top_and_scores(oof[e][outer])
            for rule, (names, bfn) in RULES.items():
                budget, name, tau = choose(ti, si, train_gold[inner], names, bfn)
                if name is None:
                    pred = np.zeros(int(outer.sum()), dtype=np.int64)
                else:
                    pred = gate_pred(to, so[name], tau)
                o = outcome(pred, train_gold[outer])
                c = crossfit[str(seed)][rule]
                for key in o:
                    c["totals"][key] += o[key]
                c["folds"].append({"fold": k, "epoch": e + 1, "harm_budget": budget,
                                   "score": name, "tau": tau})
        # final gate
        ep = int(sel["recipes"][f"C2-s{seed}"]["epoch"])
        t, sc = top_and_scores(oof[ep - 1])
        _, name, tau = choose(t, sc, train_gold, RULES["main"][0], kmax)
        final_gates[str(seed)] = None if name is None else {"score": name, "tau": tau}
        dz = pred_npz[f"dev_C2-s{seed}"]
        td, sd = top_and_scores(dz)
        pred = np.zeros(len(dz), dtype=np.int64) if name is None else gate_pred(td, sd[name], tau)
        dev_gated[str(seed)] = outcome(pred, dev_gold)

    adopted = True
    for seed in SEEDS:
        t = crossfit[str(seed)]["main"]["totals"]
        ok = (400 * t["harm"] <= n_all and t["rescue"] >= 3 * t["harm"]
              and 10 * (t["rescue"] - t["harm"]) >= n_wrong)
        adopted = adopted and ok

    obj = {"comparable": {"crossfit": crossfit, "final_gates": final_gates,
                          "adopted": adopted, "dev_gated": dev_gated},
           "script": "recompute.py"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "x", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    for seed in SEEDS:
        print(seed, crossfit[str(seed)]["main"]["totals"])
    print("adopted", adopted)


main()
