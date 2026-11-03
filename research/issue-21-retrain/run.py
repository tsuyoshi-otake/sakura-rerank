"""Issue #21 research-only retraining harness (train/dev only, aggregate output).

Stages (each refuses to overwrite its outputs):
  prepare      folds.npz/folds.report.json, costs.npz, alignment report
  reproduce    retrain the original recipe (seed 20260814) without dev and
               compare train loss + epoch-3 weights with the prototype
  cv RECIPE    grouped 5-fold out-of-fold scores for every epoch and seed
  select       freeze epochs and tau from out-of-fold predictions only
  final        train each recipe/seed on all train rows for its frozen epoch
  eval-dev     single dev evaluation bound to the frozen selection hash
  decide       apply the Issue #21 adoption rules mechanically

The final-holdout lines are skipped by their split token before JSON parsing.
Nothing here prints readings, surfaces, contexts, or stable IDs.
"""
from __future__ import annotations

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
REPO = EXP.parents[2]
GEN = REPO / "data" / "generated"
CACHE = GEN / "sakura-rerank-tiny-v1-research" / "train-dev-cache.npz"
CACHE_SHA = "41eb7f59c4912d3216836ed9cb153a3e3b952e8673d5fce3e71a020b24781624"
FROZEN = GEN / "issue15-v5-slot120" / "frozen-split.jsonl"
FROZEN_SHA = "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"
PROTO_DIR = GEN / "sakura-rerank-tiny-v1-research"
PROTO_CKPT_SHA = "d7d58fce6ea00ee577f3b60ac87d179c237730b5814d1dbe5bdd51fa4f1d2fbd"
RESEARCH_TINY = REPO / "src" / "sakura_rerank" / "research_tiny.py"
RESEARCH_TINY_SHA = "a7ca1007ad2981f3008fa9363723f3d5c232213208ee0a4a9f89e572af3b2035"
HOLDOUT_TOKEN = '"split":"final-holdout"'
SEEDS = (20260814, 20261103, 20261104)
RECIPES = ("B0", "C1", "C2")
CANDIDATES = ("C1", "C2")
FOLDS = 5
FOLD_SALT = "issue-21-grouped-folds-v1"
EPOCHS = 20
BATCH = 256
LR = 1e-3
WD = 0.01
CLIP = 1.0
GAP_SCALE = 1000.0
DROPOUT = 0.1
LABEL_SMOOTHING = 0.05
TAU_GRID = tuple(round(0.1 * i, 1) for i in range(61))
HARM_RATE_LIMIT = 0.0025
BONFERRONI_ALPHA = 0.025
INPUT_NAMES = (
    "context_ids", "context_lengths", "reading_ids", "reading_lengths",
    "candidate_ids", "candidate_lengths", "features", "candidate_mask",
)

class HarnessError(RuntimeError):
    pass


# Verify the pinned implementation before importing (and thereby executing) it.
if hashlib.sha256(RESEARCH_TINY.read_bytes()).hexdigest() != RESEARCH_TINY_SHA:
    raise HarnessError("hash mismatch for research_tiny.py")
sys.path.insert(0, str(REPO / "src"))
from sakura_rerank import research_tiny as rt  # noqa: E402


# ---------------------------------------------------------------- utilities

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_once(path: Path, value: object) -> str:
    if path.exists():
        raise HarnessError(f"refusing to overwrite {path.name}")
    data = (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return hashlib.sha256(data).hexdigest()


def save_npz_once(path: Path, **arrays: np.ndarray) -> str:
    if path.exists():
        raise HarnessError(f"refusing to overwrite {path.name}")
    temporary = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)
    return sha256_file(path)


def require_hash(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise HarnessError(f"hash mismatch for {path.name}")


def verify_inputs() -> None:
    require_hash(CACHE, CACHE_SHA)
    require_hash(RESEARCH_TINY, RESEARCH_TINY_SHA)


def load_split(split: str) -> dict[str, np.ndarray]:
    """Materialize one split's cache arrays once (never the other split)."""
    prefix = split + "_"
    with np.load(CACHE, allow_pickle=False) as npz:
        return {key[len(prefix):]: np.array(npz[key]) for key in npz.files if key.startswith(prefix)}


def iter_rows(splits: tuple[str, ...]):
    """Yield (split, parsed_row) for train/dev rows in file order."""
    with FROZEN.open("r", encoding="utf-8") as handle:
        for line in handle:
            if HOLDOUT_TOKEN in line:
                continue
            row = json.loads(line)
            split = row.get("split")
            if split not in ("train", "dev"):
                raise HarnessError("unexpected split value")
            if split in splits:
                yield split, row


def outcome(pred: np.ndarray, gold: np.ndarray) -> dict[str, int]:
    correct = (gold >= 0) & (pred == gold)
    base = gold == 0
    return {
        "correct": int(correct.sum()),
        "harm": int((base & ~correct).sum()),
        "rescue": int((~base & correct).sum()),
        "overrides": int((pred != 0).sum()),
    }


def gated_prediction(scores: np.ndarray, tau: float) -> np.ndarray:
    pred = scores.argmax(axis=1)
    margin = scores[np.arange(len(scores)), pred] - scores[:, 0]
    return np.where(margin > tau, pred, 0)


def mcnemar_exact(correct_a: np.ndarray, correct_b: np.ndarray) -> dict[str, float | int]:
    """Two-sided exact McNemar test; b = A right & B wrong, c = A wrong & B right."""
    b = int(np.sum(correct_a & ~correct_b))
    c = int(np.sum(~correct_a & correct_b))
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p": 1.0}
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    # Exact rational arithmetic: float(2.0 ** n) overflows once n >= 1024.
    return {"b": b, "c": c, "p": float(min(Fraction(1), Fraction(2 * tail, 1 << n)))}


# ------------------------------------------------------------ model/training

def build_model(recipe: str):
    import torch
    from torch import nn

    if recipe == "B0":
        return rt.build_model()
    feature_dim = rt.FEATURE_DIM + 1
    dropout = DROPOUT if recipe == "C2" else 0.0
    return _variant(feature_dim, dropout)


def _variant(feature_dim: int, dropout: float):
    import torch
    from torch import nn

    hidden = rt.HIDDEN_DIM

    class SakuraRerankTinyVariant(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = nn.Embedding(rt.VOCAB_SIZE, rt.EMBEDDING_DIM, padding_idx=0)
            self.encoder = nn.GRU(rt.EMBEDDING_DIM, hidden, num_layers=rt.GRU_LAYERS, batch_first=True)
            layers: list[nn.Module] = [nn.Linear(hidden * 3 + feature_dim, hidden), nn.SiLU()]
            if dropout:
                layers.append(nn.Dropout(dropout))
            layers += [nn.Linear(hidden, 64), nn.SiLU()]
            if dropout:
                layers.append(nn.Dropout(dropout))
            layers.append(nn.Linear(64, 1))
            self.scorer = nn.Sequential(*layers)

        def encode(self, ids, lengths):
            output, _ = self.encoder(self.embedding(ids))
            index = torch.clamp(lengths - 1, min=0)
            gathered = output.gather(1, index.view(-1, 1, 1).expand(-1, 1, hidden)).squeeze(1)
            return gathered * (lengths > 0).to(gathered.dtype).unsqueeze(1)

        def forward(self, context_ids, context_lengths, reading_ids, reading_lengths,
                    candidate_ids, candidate_lengths, features, candidate_mask):
            batch = context_ids.shape[0]
            context = self.encode(context_ids, context_lengths)
            reading = self.encode(reading_ids, reading_lengths)
            candidates = self.encode(
                candidate_ids.reshape(batch * rt.TOP_K, rt.SURFACE_LENGTH),
                candidate_lengths.reshape(batch * rt.TOP_K),
            ).reshape(batch, rt.TOP_K, hidden)
            joined = torch.cat(
                (context.unsqueeze(1).expand(-1, rt.TOP_K, -1),
                 reading.unsqueeze(1).expand(-1, rt.TOP_K, -1),
                 candidates, features),
                dim=2,
            )
            residual = self.scorer(joined).squeeze(2)
            scores = features[:, :, 0] * 2.0 + residual
            return scores.masked_fill(~candidate_mask, -10_000.0)

    return SakuraRerankTinyVariant()


def recipe_features(arrays: dict[str, np.ndarray], costs: np.ndarray, recipe: str) -> np.ndarray:
    features = arrays["features"]
    if recipe == "B0":
        return features
    mask = arrays["candidate_mask"]
    minimum = np.where(mask, costs, np.inf).min(axis=1, keepdims=True)
    gap = -np.log1p(np.maximum(costs - minimum, 0.0) / GAP_SCALE)
    gap = np.where(mask, gap, 0.0).astype(np.float32)
    return np.concatenate((features, gap[:, :, None]), axis=2)


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)


def _tensors(arrays, features, indices, device):
    import torch

    values = []
    for name in INPUT_NAMES:
        source = features if name == "features" else arrays[name]
        values.append(torch.from_numpy(source[indices]).to(device))
    gold = torch.from_numpy(arrays["gold"][indices]).to(device)
    return values, gold


def loss_fn(scores, gold, mask, recipe: str):
    import torch
    from torch.nn import functional

    if recipe != "C2":
        return functional.cross_entropy(scores, gold)
    log_probs = torch.log_softmax(scores, dim=1)
    valid = mask.to(log_probs.dtype)
    target = valid * (LABEL_SMOOTHING / valid.sum(dim=1, keepdim=True))
    target = target + (1.0 - LABEL_SMOOTHING) * functional.one_hot(gold, rt.TOP_K).to(log_probs.dtype)
    return -(target * log_probs).sum(dim=1).mean()


def train_epochs(arrays, features, train_rows, recipe: str, seed: int, epochs: int):
    """Generator mirroring research_tiny.train_model, minus dev evaluation."""
    import torch

    seed_everything(seed)
    device = torch.device("cuda:0")
    model = build_model(recipe).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    gold = arrays["gold"]
    eligible = train_rows[gold[train_rows] >= 0]
    generator = torch.Generator(device="cpu").manual_seed(seed)
    for epoch in range(1, epochs + 1):
        model.train()
        order = eligible[torch.randperm(len(eligible), generator=generator).numpy()]
        losses = []
        for start in range(0, len(order), BATCH):
            indices = order[start:start + BATCH]
            inputs, target = _tensors(arrays, features, indices, device)
            optimizer.zero_grad(set_to_none=True)
            scores = model(*inputs)
            loss = loss_fn(scores, target, inputs[-1], recipe)
            if not torch.isfinite(loss):
                raise HarnessError("non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        yield epoch, statistics.fmean(losses), model


def score_rows(model, arrays, features, rows) -> np.ndarray:
    import torch

    device = next(model.parameters()).device
    model.eval()
    out = []
    with torch.inference_mode():
        for start in range(0, len(rows), BATCH):
            inputs, _ = _tensors(arrays, features, rows[start:start + BATCH], device)
            out.append(model(*inputs).float().cpu().numpy())
    return np.concatenate(out)


def fold_seed(seed: int, fold: int) -> int:
    return seed + 1_000_003 * (fold + 1)


# ------------------------------------------------------------------ stages

def stage_prepare(_: argparse.Namespace) -> None:
    verify_inputs()
    require_hash(FROZEN, FROZEN_SHA)
    train = load_split("train")
    dev = load_split("dev")
    costs = {"train": np.zeros((len(train["gold"]), rt.TOP_K)), "dev": np.zeros((len(dev["gold"]), rt.TOP_K))}
    arrays = {"train": train, "dev": dev}
    offsets = {"train": 0, "dev": 0}
    keys = []  # per train row: (article, paragraph, template)
    for split, row in iter_rows(("train", "dev")):
        index = offsets[split]
        offsets[split] += 1
        cands = row["candidate_snapshots"]["production_top6"]["candidates"]
        feats = np.asarray(rt.candidate_features(row["reading"], cands), dtype=np.float32)
        if not np.array_equal(feats, arrays[split]["features"][index, : len(cands)]):
            raise HarnessError("feature alignment failed")
        gold = int(row["gold_index"])
        if (gold if gold < len(cands) else -1) != int(arrays[split]["gold"][index]):
            raise HarnessError("gold alignment failed")
        costs[split][index, : len(cands)] = [float(c["local_cost"]) for c in cands]
        if split == "train":
            source = row["source"]
            keys.append((source["article_id"], source["paragraph_hash"], source.get("template_cluster_id")))
    if offsets != {"train": len(train["gold"]), "dev": len(dev["gold"])}:
        raise HarnessError("row count mismatch")
    # Union-find over shared article, paragraph, or template cluster.
    parent = list(range(len(keys)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first_seen: dict[tuple[str, str], int] = {}
    for index, (article, paragraph, template) in enumerate(keys):
        for kind, value in (("a", article), ("p", paragraph), ("t", template)):
            if value is None:
                continue
            key = (kind, str(value))
            if key in first_seen:
                ra, rb = find(first_seen[key]), find(index)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            else:
                first_seen[key] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(keys)):
        groups.setdefault(find(index), []).append(index)
    ordered = sorted(
        groups.values(),
        key=lambda rows: (-len(rows), hashlib.sha256(f"{FOLD_SALT}:{min(rows)}".encode()).hexdigest()),
    )
    fold_of = np.full(len(keys), -1, dtype=np.int64)
    sizes = [0] * FOLDS
    for rows in ordered:
        target = min(range(FOLDS), key=lambda f: (sizes[f], f))
        fold_of[rows] = target
        sizes[target] += len(rows)
    gold = train["gold"]
    report = {
        "train_rows": len(keys),
        "groups": len(groups),
        "largest_group_rows": max(len(rows) for rows in groups.values()),
        "fold_rows": sizes,
        "fold_baseline_correct": [int(np.sum((fold_of == f) & (gold == 0))) for f in range(FOLDS)],
        "fold_no_oracle": [int(np.sum((fold_of == f) & (gold < 0))) for f in range(FOLDS)],
        "grouping_keys": ["source.article_id", "source.paragraph_hash", "source.template_cluster_id (non-null)"],
        "final_holdout_lines_skipped_by_token": True,
        "feature_and_gold_alignment_verified": True,
        "inputs": {"cache_sha256": CACHE_SHA, "frozen_split_sha256": FROZEN_SHA, "research_tiny_sha256": RESEARCH_TINY_SHA},
        "raw_text_in_report": False,
    }
    report["folds_npz_sha256"] = save_npz_once(EXP / "folds.npz", fold=fold_of)
    report["costs_npz_sha256"] = save_npz_once(EXP / "costs.npz", train=costs["train"], dev=costs["dev"])
    write_json_once(EXP / "prepare.report.json", report)
    print(json.dumps({k: report[k] for k in ("groups", "largest_group_rows", "fold_rows")}))


def stage_check_cache(_: argparse.Namespace) -> None:
    """Read-only check of candidate masks and zero padding against the source rows."""
    verify_inputs()
    require_hash(FROZEN, FROZEN_SHA)
    arrays = {"train": load_split("train"), "dev": load_split("dev")}
    with np.load(EXP / "costs.npz", allow_pickle=False) as npz:
        costs = {"train": np.array(npz["train"]), "dev": np.array(npz["dev"])}
    offsets = {"train": 0, "dev": 0}
    counts = {"train": {}, "dev": {}}
    for split, row in iter_rows(("train", "dev")):
        index = offsets[split]
        offsets[split] += 1
        n = len(row["candidate_snapshots"]["production_top6"]["candidates"])
        if not 2 <= n <= rt.TOP_K:
            raise HarnessError("candidate count outside 2..TOP_K")
        a = arrays[split]
        if not np.array_equal(a["candidate_mask"][index], np.arange(rt.TOP_K) < n):
            raise HarnessError("candidate mask misaligned")
        if np.any(a["features"][index, n:] != 0) or np.any(costs[split][index, n:] != 0):
            raise HarnessError("non-zero padding in features or costs")
        if np.any(a["candidate_lengths"][index, n:] != 0) or np.any(a["candidate_ids"][index, n:] != 0):
            raise HarnessError("non-zero padding in candidate ids")
        counts[split][n] = counts[split].get(n, 0) + 1
    if offsets != {s: len(arrays[s]["gold"]) for s in offsets}:
        raise HarnessError("row count mismatch")
    report = {"candidate_count_histogram": {s: {str(k): v for k, v in sorted(c.items())} for s, c in counts.items()},
              "mask_and_padding_verified": True, "raw_text_in_report": False}
    write_json_once(EXP / "cache-check.report.json", report)
    print(json.dumps(report))


def stage_reproduce(_: argparse.Namespace) -> None:
    import torch

    verify_inputs()
    require_hash(PROTO_DIR / "sakura-rerank-tiny-v1-research.pt", PROTO_CKPT_SHA)
    # Replication self-test: the variant class with 6 features and no dropout
    # must equal research_tiny.build_model() in parameters and outputs.
    seed_everything(SEEDS[0])
    reference = rt.build_model()
    seed_everything(SEEDS[0])
    replica = _variant(rt.FEATURE_DIM, 0.0)
    ref_state, rep_state = reference.state_dict(), replica.state_dict()
    if list(ref_state) != list(rep_state) or not all(torch.equal(ref_state[k], rep_state[k]) for k in ref_state):
        raise HarnessError("variant replica does not match research_tiny.build_model")
    sample = rt._example_inputs(4)
    reference.eval(); replica.eval()
    with torch.inference_mode():
        if not torch.equal(reference(*sample), replica(*sample)):
            raise HarnessError("variant replica forward differs")
    train = load_split("train")
    rows = np.arange(len(train["gold"]))
    losses, epoch3_state = [], None
    for epoch, loss, model in train_epochs(train, train["features"], rows, "B0", SEEDS[0], EPOCHS):
        losses.append(round(loss, 8))
        if epoch == 3:
            epoch3_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        print(json.dumps({"stage": "reproduce", "epoch": epoch, "train_loss": round(loss, 8)}), flush=True)
    original = json.loads((PROTO_DIR / "training.report.json").read_text(encoding="utf-8"))
    expected = [entry["train_loss"] for entry in original["history"]]
    checkpoint = torch.load(PROTO_DIR / "sakura-rerank-tiny-v1-research.pt", map_location="cpu", weights_only=True)
    proto_state = checkpoint["state_dict"]
    tensors_equal = list(proto_state) == list(epoch3_state) and all(
        torch.equal(proto_state[k], epoch3_state[k]) for k in proto_state
    )
    target = EXP / "reproduction-epoch3.pt"
    if target.exists():
        raise HarnessError("refusing to overwrite reproduction-epoch3.pt")
    torch.save({"epoch": 3, "state_dict": epoch3_state}, target)
    report = {
        "train_loss": losses,
        "original_train_loss": expected,
        "all_losses_equal": losses == expected,
        "first_loss_mismatch_epoch": next((i + 1 for i, (a, b) in enumerate(zip(losses, expected)) if a != b), None),
        "epoch3_state_equal_to_prototype": tensors_equal,
        "variant_replica_self_test": True,
        "dev_used": False,
        "environment": {"python": sys.version.split()[0], "torch": torch.__version__,
                        "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0)},
        "reproduction_epoch3_sha256": sha256_file(target),
    }
    write_json_once(EXP / "reproduction.report.json", report)
    print(json.dumps({k: report[k] for k in ("all_losses_equal", "first_loss_mismatch_epoch", "epoch3_state_equal_to_prototype")}))


def stage_cv(args: argparse.Namespace) -> None:
    verify_inputs()
    recipe = args.recipe
    if recipe not in RECIPES:
        raise HarnessError("unknown recipe")
    train = load_split("train")  # dev arrays are never loaded here
    with np.load(EXP / "costs.npz", allow_pickle=False) as npz:
        costs = np.array(npz["train"])
    with np.load(EXP / "folds.npz", allow_pickle=False) as npz:
        fold_of = np.array(npz["fold"])
    features = recipe_features(train, costs, recipe)
    out_dir = EXP / "oof"
    out_dir.mkdir(exist_ok=True)
    for seed in SEEDS:
        target = out_dir / f"{recipe}-s{seed}.npz"
        if target.exists():
            raise HarnessError(f"refusing to overwrite {target.name}")
        scores = np.full((EPOCHS, len(fold_of), rt.TOP_K), np.nan, dtype=np.float32)
        fold_losses = np.zeros((FOLDS, EPOCHS))
        started = time.perf_counter()
        for fold in range(FOLDS):
            fit_rows = np.flatnonzero(fold_of != fold)
            val_rows = np.flatnonzero(fold_of == fold)
            for epoch, loss, model in train_epochs(train, features, fit_rows, recipe, fold_seed(seed, fold), EPOCHS):
                fold_losses[fold, epoch - 1] = loss
                scores[epoch - 1, val_rows] = score_rows(model, train, features, val_rows)
            fold_pred = scores[:, val_rows].argmax(axis=2)
            best = max(outcome(fold_pred[e], train["gold"][val_rows])["correct"] for e in range(EPOCHS))
            print(json.dumps({"stage": "cv", "recipe": recipe, "seed": seed, "fold": fold,
                              "best_epoch_correct_in_fold": best, "rows": int(len(val_rows))}), flush=True)
        if np.isnan(scores).any():
            raise HarnessError("incomplete out-of-fold scores")
        save_npz_once(target, scores=scores, fold_losses=fold_losses)
        print(json.dumps({"stage": "cv-done", "recipe": recipe, "seed": seed,
                          "seconds": round(time.perf_counter() - started, 1)}), flush=True)


def _choose_epoch(per_epoch: list[dict[str, int]]) -> int:
    return min(range(len(per_epoch)), key=lambda e: (-per_epoch[e]["correct"], per_epoch[e]["harm"], e)) + 1


def _choose_tau(scores: np.ndarray, gold: np.ndarray) -> tuple[float | None, int]:
    limit = int(math.floor(HARM_RATE_LIMIT * int(np.sum(gold == 0))))
    for tau in TAU_GRID:
        if outcome(gated_prediction(scores, tau), gold)["harm"] <= limit:
            return tau, limit
    return None, limit


def stage_select(_: argparse.Namespace) -> None:
    verify_inputs()
    gold = load_split("train")["gold"]
    selection = {"rule": {"epoch": "max pooled OOF correct, then fewer harm, then earlier",
                          "tau": f"smallest tau in 0.0..6.0 step 0.1 with OOF harm <= floor({HARM_RATE_LIMIT} * OOF baseline-correct)"},
                 "recipes": {}, "oof_files": {}}
    for recipe in RECIPES:
        for seed in SEEDS:
            path = EXP / "oof" / f"{recipe}-s{seed}.npz"
            selection["oof_files"][path.name] = sha256_file(path)
            with np.load(path, allow_pickle=False) as npz:
                scores = np.array(npz["scores"])
            per_epoch = [outcome(scores[e].argmax(axis=1), gold) for e in range(EPOCHS)]
            epoch = _choose_epoch(per_epoch)
            tau, limit = _choose_tau(scores[epoch - 1], gold)
            selection["recipes"][f"{recipe}-s{seed}"] = {
                "epoch": epoch, "tau": tau, "harm_limit": limit, "oof_per_epoch": per_epoch,
            }
    digest = write_json_once(EXP / "selection.json", selection)
    print(json.dumps({"selection_sha256": digest,
                      "epochs": {k: v["epoch"] for k, v in selection["recipes"].items()},
                      "tau": {k: v["tau"] for k, v in selection["recipes"].items()}}))


def stage_final(_: argparse.Namespace) -> None:
    import torch

    verify_inputs()
    selection = json.loads((EXP / "selection.json").read_text(encoding="utf-8"))
    train = load_split("train")  # dev arrays are never loaded here
    with np.load(EXP / "costs.npz", allow_pickle=False) as npz:
        costs = np.array(npz["train"])
    out_dir = EXP / "final"
    out_dir.mkdir(exist_ok=True)
    rows = np.arange(len(train["gold"]))
    for recipe in RECIPES:
        features = recipe_features(train, costs, recipe)
        for seed in SEEDS:
            key = f"{recipe}-s{seed}"
            target = out_dir / f"{key}.pt"
            if target.exists():
                raise HarnessError(f"refusing to overwrite {target.name}")
            epochs = int(selection["recipes"][key]["epoch"])
            for epoch, loss, model in train_epochs(train, features, rows, recipe, seed, epochs):
                pass
            torch.save({"recipe": recipe, "seed": seed, "epoch": epochs,
                        "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()}}, target)
            print(json.dumps({"stage": "final", "model": key, "epoch": epochs, "last_train_loss": round(loss, 8)}), flush=True)


def stage_eval_dev(_: argparse.Namespace) -> None:
    import torch

    verify_inputs()
    target = EXP / "dev-eval.json"
    # Either artifact means dev scores were already computed once.
    if target.exists() or (EXP / "predictions.npz").exists():
        raise HarnessError("dev has already been evaluated once")
    selection_sha = sha256_file(EXP / "selection.json")
    selection = json.loads((EXP / "selection.json").read_text(encoding="utf-8"))
    train_gold = load_split("train")["gold"]
    dev = load_split("dev")
    with np.load(EXP / "costs.npz", allow_pickle=False) as npz:
        dev_costs = np.array(npz["dev"])
    device = torch.device("cuda:0")
    arrays_out = {"train_gold": train_gold, "dev_gold": dev["gold"]}
    metrics = {}
    for recipe in RECIPES:
        features = recipe_features(dev, dev_costs, recipe)
        for seed in SEEDS:
            key = f"{recipe}-s{seed}"
            chosen = selection["recipes"][key]
            checkpoint = torch.load(EXP / "final" / f"{key}.pt", map_location="cpu", weights_only=True)
            if (checkpoint["recipe"], int(checkpoint["seed"]), int(checkpoint["epoch"])) != (recipe, seed, int(chosen["epoch"])):
                raise HarnessError(f"checkpoint metadata does not match the frozen selection for {key}")
            model = build_model(recipe)
            model.load_state_dict(checkpoint["state_dict"])
            model.to(device)
            dev_scores = score_rows(model, dev, features, np.arange(len(dev["gold"])))
            with np.load(EXP / "oof" / f"{key}.npz", allow_pickle=False) as npz:
                oof_scores = np.array(npz["scores"][chosen["epoch"] - 1])
            arrays_out[f"oof_{key}"] = oof_scores
            arrays_out[f"dev_{key}"] = dev_scores
            entry = {"epoch": chosen["epoch"], "tau": chosen["tau"],
                     "dev": outcome(dev_scores.argmax(axis=1), dev["gold"])}
            if chosen["tau"] is not None:
                entry["dev_tau_gated"] = outcome(gated_prediction(dev_scores, chosen["tau"]), dev["gold"])
            metrics[key] = entry
    predictions_sha = save_npz_once(EXP / "predictions.npz", **arrays_out)
    write_json_once(target, {"selection_sha256": selection_sha, "predictions_sha256": predictions_sha,
                             "metrics": metrics, "raw_text_in_report": False})
    print(json.dumps({k: v["dev"] for k, v in metrics.items()}))


def stage_decide(_: argparse.Namespace) -> None:
    dev_eval = json.loads((EXP / "dev-eval.json").read_text(encoding="utf-8"))
    if (dev_eval["selection_sha256"] != sha256_file(EXP / "selection.json")
            or dev_eval["predictions_sha256"] != sha256_file(EXP / "predictions.npz")):
        raise HarnessError("selection or predictions changed after the dev evaluation")
    with np.load(EXP / "predictions.npz", allow_pickle=False) as npz:
        arrays = {k: np.array(npz[k]) for k in npz.files}
    train_gold, dev_gold = arrays["train_gold"], arrays["dev_gold"]
    selection = json.loads((EXP / "selection.json").read_text(encoding="utf-8"))
    per_model = {}
    correct = {}
    for recipe in RECIPES:
        for seed in SEEDS:
            key = f"{recipe}-s{seed}"
            oof_pred = arrays[f"oof_{key}"].argmax(axis=1)
            dev_pred = arrays[f"dev_{key}"].argmax(axis=1)
            correct[("oof", key)] = (train_gold >= 0) & (oof_pred == train_gold)
            correct[("dev", key)] = (dev_gold >= 0) & (dev_pred == dev_gold)
            per_model[key] = {"epoch": selection["recipes"][key]["epoch"], "tau": selection["recipes"][key]["tau"],
                              "oof": outcome(oof_pred, train_gold), "dev": outcome(dev_pred, dev_gold)}
            tau = selection["recipes"][key]["tau"]
            if tau is not None:
                per_model[key]["oof_tau_gated"] = outcome(gated_prediction(arrays[f"oof_{key}"], tau), train_gold)
                per_model[key]["dev_tau_gated"] = outcome(gated_prediction(arrays[f"dev_{key}"], tau), dev_gold)

    def mean(recipe: str, split: str, field: str) -> float:
        return statistics.fmean(per_model[f"{recipe}-s{s}"][split][field] for s in SEEDS)

    candidates = {}
    for cand in CANDIDATES:
        tests = {f"oof-s{s}": mcnemar_exact(correct[("oof", f"{cand}-s{s}")], correct[("oof", f"B0-s{s}")]) for s in SEEDS}
        dev_tests = {f"dev-s{s}": mcnemar_exact(correct[("dev", f"{cand}-s{s}")], correct[("dev", f"B0-s{s}")]) for s in SEEDS}
        oof_more_all = all(per_model[f"{cand}-s{s}"]["oof"]["correct"] > per_model[f"B0-s{s}"]["oof"]["correct"] for s in SEEDS)
        oof_significant = sum(tests[f"oof-s{s}"]["p"] < BONFERRONI_ALPHA for s in SEEDS)
        oof_harm_ok = mean(cand, "oof", "harm") <= mean("B0", "oof", "harm")
        dev_correct_ok = mean(cand, "dev", "correct") >= mean("B0", "dev", "correct")
        dev_harm_ok = mean(cand, "dev", "harm") <= mean("B0", "dev", "harm")
        oof_pass = oof_more_all and oof_significant >= 2 and oof_harm_ok
        candidates[cand] = {
            "mcnemar_oof_vs_B0_gating": tests,
            "mcnemar_dev_vs_B0_informational": dev_tests,
            "oof_more_correct_all_seeds": oof_more_all,
            "oof_seeds_p_below_alpha": oof_significant,
            "oof_mean_harm_not_higher": oof_harm_ok,
            "oof_condition": oof_pass,
            "dev_mean_correct_not_lower": dev_correct_ok,
            "dev_mean_harm_not_higher": dev_harm_ok,
            "dev_condition": dev_correct_ok and dev_harm_ok,
            "passes": oof_pass and dev_correct_ok and dev_harm_ok,
            "mean_oof_correct": mean(cand, "oof", "correct"),
        }
    passing = [c for c in CANDIDATES if candidates[c]["passes"]]
    adopted = None
    if passing:
        adopted = sorted(passing, key=lambda c: (-candidates[c]["mean_oof_correct"], CANDIDATES.index(c)))[0]
    means = {r: {split: {f: mean(r, split, f) for f in ("correct", "harm", "rescue")} for split in ("oof", "dev")} for r in RECIPES}
    results = {
        "issue": 21,
        "status": "research_only_gate_a_failed",
        "final_holdout_used": False,
        "alpha_bonferroni": BONFERRONI_ALPHA,
        "seeds": list(SEEDS),
        "per_model": per_model,
        "means": means,
        "candidates": candidates,
        "decision": {"passing": passing, "adopted": adopted},
        "inputs": {"selection_sha256": sha256_file(EXP / "selection.json"),
                   "predictions_sha256": sha256_file(EXP / "predictions.npz")},
        "raw_text_in_report": False,
    }
    write_json_once(EXP / "results.json", results)
    print(json.dumps({"means": means, "decision": results["decision"],
                      "conditions": {c: {k: candidates[c][k] for k in ("oof_condition", "dev_condition", "oof_seeds_p_below_alpha")} for c in CANDIDATES}}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "check-cache", "reproduce", "select", "final", "eval-dev", "decide"):
        sub.add_parser(name)
    cv = sub.add_parser("cv")
    cv.add_argument("recipe", choices=RECIPES)
    args = parser.parse_args()
    handlers = {"prepare": stage_prepare, "check-cache": stage_check_cache, "reproduce": stage_reproduce,
                "cv": stage_cv, "select": stage_select,
                "final": stage_final, "eval-dev": stage_eval_dev, "decide": stage_decide}
    handlers[args.stage](args)


if __name__ == "__main__":
    main()
