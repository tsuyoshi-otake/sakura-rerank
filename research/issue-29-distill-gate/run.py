"""Issue #29 research-only distillation + confidence-gate experiment (aggregate output only).

A single C2-architecture student learns from the mean logits of the three
Issue #21 C2 models (the Issue #27 ensemble). Training reuses Issue #21's
hash-pinned harness; the gate, threshold, epoch-selection, and counting rules
are Issue #25's, imported from its hash-pinned harness. The frozen split JSONL
is not read and the final holdout is never touched.

Stages (each writes its outputs once and refuses to overwrite them):
  parity            the distillation loop with KL weight 0 reproduces Issue #21's
                    stored C2 OOF logits bitwise (seed 20260814, fold 0, 2 epochs)
  teachers          nested C2 teachers: 3 seeds x 10 fold pairs x 20 epochs
  teacher-select    teacher epochs per outer fold and seed; nested and final teachers
  students          distilled students: 3 seeds x 5 outer folds x 20 epochs (OOF)
  crossfit          Issue #25 cross-fit gate on each student seed's OOF
  select            final student epoch and final gate (seed 20260814, full OOF)
  decide-accuracy   criteria 1-3; must run before any dev access
  final             train the final student; store its torch (GPU) dev logits
  export            FP32/INT8 ONNX and the dev decision parity (criterion 5)
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
import itertools
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ISSUE = 29
EXP = Path(__file__).resolve().parent
REPO = EXP.parents[1]
GEN = REPO / "data" / "generated"
SRC21 = GEN / "issue-21-retrain"
OUT = GEN / f"issue-{ISSUE}-distill-gate"
REPORT = REPO / "reports" / f"issue-{ISSUE}-distill-gate.json"
R2_DIR = GEN / "sakura-rerank-tiny-r2-research"
V1_DIR = GEN / "sakura-rerank-tiny-v1-research"
PLAN_BODY_SHA256 = "93f0ccc4908dbbb07b16ea91733af4393bcb0314c195249dccb3ef442ec2a22d"

H21_PY = SRC21 / "run.py"  # imported from here: its EXP/REPO paths assume this location
H21_TRACKED = REPO / "research" / "issue-21-retrain" / "run.py"
H21_SHA256 = "d0e24a57ccf9d5a1aa5fc3c9de0b3ff4ef8124bd15c126fc47c9c3bfbf55216d"
GATE_PY = REPO / "research" / "issue-25-confidence-gate" / "run.py"
GATE_SHA256 = "4e77fc6ec06c42a4b849e770994bffd4bcbdbab47161a9daa01656416193b7a5"
R2_PY = REPO / "src" / "sakura_rerank" / "research_tiny_r2.py"
R2_PY_SHA256 = "c2ede3575722b0cda97e0da52a04f42c2402db9cf12aec077d63993f09a95f66"
EXTRA_INPUTS = {
    V1_DIR / "train-dev-cache.npz": "41eb7f59c4912d3216836ed9cb153a3e3b952e8673d5fce3e71a020b24781624",
    V1_DIR / "train-dev-cache.manifest.json": "7c8763aab928a8c151ce8a0d68bcb24aa0a8779d47a0eee9b5ea53d2208f8315",
    SRC21 / "costs.npz": "1d802a932a75cf7284f0b7b1a2b2ca7248aece0bd6ecdbbb032cb5485c457bdf",
    R2_DIR / "cost-gap.npz": "1b651e3d7449538bb1f6895bea24fcb44fc8c7cd1f38fa98a60f1f41b6478497",
    R2_DIR / "cost-gap.manifest.json": "89d8744d3798811247b9ca88570c6dfbff7813410d2f4ac5c1064389a4544c1b",
    R2_DIR / "sakura-rerank-tiny-v1-research-r2-fp32.onnx":
        "96d7694cc3759465a95841aa8d4cd62757f302fc13388ca9c38751c2a9ae5c64",
}
R2_FP32 = R2_DIR / "sakura-rerank-tiny-v1-research-r2-fp32.onnx"
KD_WEIGHT = 0.5
TEMPERATURE = 2.0
PAIRS = tuple(itertools.combinations(range(5), 2))  # pair index 0..9 in this order
SEED_STRIDE = 1_000_003
P95_LIMIT_MS = 2.0
WARMUP_RUNS = 100
MEASURED_RUNS = 10_000
DEV_ACCESS_OUTPUTS = ("final.json", "export.json", "fp32-benchmark.report.json", "decision.json",
                      "dev-eval.json")


def _load_pinned(path: Path, expected: str, name: str):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"hash mismatch for {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Verify both pinned harnesses before executing them.
gate = _load_pinned(GATE_PY, GATE_SHA256, "issue25_gate")
if hashlib.sha256(H21_TRACKED.read_bytes()).hexdigest() != H21_SHA256:
    raise RuntimeError("tracked Issue #21 harness differs from the pinned hash")
h21 = _load_pinned(H21_PY, H21_SHA256, "issue21_harness")
HarnessError = gate.HarnessError
SEEDS = gate.SEEDS
ARTIFACT_SEED = gate.ARTIFACT_SEED
FINAL_EPOCHS = gate.FINAL_EPOCHS
FOLDS, EPOCHS, TOP_K = gate.FOLDS, gate.EPOCHS, 6
if (h21.FOLDS, h21.EPOCHS, h21.SEEDS) != (FOLDS, EPOCHS, SEEDS):
    raise RuntimeError("Issue #21 and Issue #25 harness constants disagree")


def pair_seed(seed: int, pair: int) -> int:
    return seed + SEED_STRIDE * (6 + pair)


def verify_inputs() -> None:
    gate.verify_inputs()
    h21.verify_inputs()
    for path, expected in EXTRA_INPUTS.items():
        if gate.sha256_file(path) != expected:
            raise HarnessError(f"hash mismatch for {path.name}")
    if gate.sha256_file(R2_PY) != R2_PY_SHA256:
        raise HarnessError("hash mismatch for research_tiny_r2.py")


def load_train_arrays() -> tuple[dict[str, np.ndarray], np.ndarray]:
    train = h21.load_split("train")  # dev arrays are never loaded here
    with np.load(SRC21 / "costs.npz", allow_pickle=False) as npz:
        costs = np.array(npz["train"])
    return train, h21.recipe_features(train, costs, "C2")


def load_common() -> tuple[np.ndarray, np.ndarray, dict[int, np.ndarray], dict[str, np.ndarray], np.ndarray]:
    fold_of, gold, scores21 = gate.load_train()
    train, features = load_train_arrays()
    if not np.array_equal(train["gold"], gold):
        raise HarnessError("cache gold differs from the Issue #21 predictions")
    return fold_of, gold, scores21, train, features


def ensemble(logits_by_seed: dict[int, np.ndarray]) -> np.ndarray:
    """Element-wise mean of float32 logits in float64 (the Issue #27 ensemble)."""
    return sum(logits_by_seed[seed].astype(np.float64) for seed in SEEDS) / len(SEEDS)


def teacher_probabilities(logits: np.ndarray) -> np.ndarray:
    """softmax(logits / T) in float64, cast to float32; non-finite rows stay NaN."""
    probs = np.full(logits.shape, np.nan, dtype=np.float32)
    rows = np.isfinite(logits).all(axis=1)
    z = logits[rows] / TEMPERATURE
    exp = np.exp(z - z.max(axis=1, keepdims=True))
    probs[rows] = (exp / exp.sum(axis=1, keepdims=True)).astype(np.float32)
    return probs


def distillation_loss(scores, gold, mask, teacher, weight: float):
    """(1 - w) x Issue #21 C2 loss + w x T^2 x KL(teacher || student) at temperature T."""
    import torch

    hard = h21.loss_fn(scores, gold, mask, "C2")
    log_student = torch.log_softmax(scores / TEMPERATURE, dim=1)
    kl = (torch.special.xlogy(teacher, teacher) - teacher * log_student).sum(dim=1).mean()
    return (1.0 - weight) * hard + weight * (TEMPERATURE ** 2) * kl


def distill_epochs(arrays, features, train_rows, seed: int, epochs: int, teacher: np.ndarray, weight: float):
    """Issue #21's train_epochs for C2 with the distillation loss; batch order is unchanged."""
    import torch

    h21.seed_everything(seed)
    device = torch.device("cuda:0")
    model = h21.build_model("C2").to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=h21.LR, weight_decay=h21.WD)
    gold = arrays["gold"]
    eligible = train_rows[gold[train_rows] >= 0]
    if not np.isfinite(teacher[eligible]).all():
        raise HarnessError("a training row has no teacher target")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    for epoch in range(1, epochs + 1):
        model.train()
        order = eligible[torch.randperm(len(eligible), generator=generator).numpy()]
        losses = []
        for start in range(0, len(order), h21.BATCH):
            indices = order[start:start + h21.BATCH]
            inputs, target = h21._tensors(arrays, features, indices, device)
            soft = torch.from_numpy(teacher[indices]).to(device)
            optimizer.zero_grad(set_to_none=True)
            scores = model(*inputs)
            loss = distillation_loss(scores, target, inputs[-1], soft, weight)
            if not torch.isfinite(loss):
                raise HarnessError("non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), h21.CLIP)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        yield epoch, statistics.fmean(losses), model


def final_teacher(scores21: dict[int, np.ndarray]) -> np.ndarray:
    return ensemble({seed: scores21[seed][FINAL_EPOCHS[seed] - 1] for seed in SEEDS})


def require(name: str) -> tuple[dict, str]:
    path = OUT / name
    if not path.exists():
        raise HarnessError(f"{name} is missing; run the earlier stage first")
    return gate.read_bound(path)


def require_parity() -> None:
    parity, _ = require("parity.json")
    if not parity["identical"]:
        raise HarnessError("the parity check failed; the plan stops here")


def require_no_dev_access() -> None:
    for name in DEV_ACCESS_OUTPUTS:
        if (OUT / name).exists():
            raise HarnessError(f"{name} exists; the accuracy decision must precede any dev access")


def load_npz(path: Path, expected_sha: str, key: str) -> np.ndarray:
    if gate.sha256_file(path) != expected_sha:
        raise HarnessError(f"{path.name} changed after it was bound")
    with np.load(path, allow_pickle=False) as npz:
        return np.array(npz[key])


def r2_module():
    if gate.sha256_file(R2_PY) != R2_PY_SHA256:
        raise HarnessError("hash mismatch for research_tiny_r2.py")
    sys.path.insert(0, str(REPO / "src"))
    from sakura_rerank import research_tiny_r2  # noqa: E402

    return research_tiny_r2


def r2_inputs() -> tuple[Path, Path, Path, Path]:
    return (V1_DIR / "train-dev-cache.npz", V1_DIR / "train-dev-cache.manifest.json",
            R2_DIR / "cost-gap.npz", R2_DIR / "cost-gap.manifest.json")


def log(**fields) -> None:
    print(json.dumps(fields, sort_keys=True), flush=True)


# -------------------------------------------------------------------- stages

def stage_parity(_: argparse.Namespace) -> None:
    if (OUT / "parity.json").exists():
        raise HarnessError("refusing to overwrite parity.json")
    verify_inputs()
    fold_of, _, scores21, train, features = load_common()
    fit, held = np.flatnonzero(fold_of != 0), np.flatnonzero(fold_of == 0)
    teacher = teacher_probabilities(final_teacher(scores21))  # any finite target; its weight is 0
    checks = []
    for epoch, loss, model in distill_epochs(train, features, fit, h21.fold_seed(ARTIFACT_SEED, 0), 2,
                                             teacher, 0.0):
        got = h21.score_rows(model, train, features, held)
        stored = scores21[ARTIFACT_SEED][epoch - 1][held]
        checks.append({"epoch": epoch, "bitwise_equal": bool(np.array_equal(got, stored)),
                       "max_abs_diff": float(np.max(np.abs(got - stored)))})
    result = {"seed": ARTIFACT_SEED, "fold": 0, "kd_weight": 0.0, "checks": checks,
              "identical": all(check["bitwise_equal"] for check in checks)}
    digest = gate.write_once(OUT / "parity.json", result)
    log(parity_sha256=digest, **result)
    if not result["identical"]:
        raise HarnessError("the distillation loop does not reproduce Issue #21; stopping as planned")


def stage_teachers(_: argparse.Namespace) -> None:
    require_parity()
    verify_inputs()
    fold_of, _, _, train, features = load_common()
    (OUT / "nested").mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        target = OUT / "nested" / f"C2-s{seed}.npz"
        if target.exists():
            log(stage="teachers", seed=seed, kept_existing=True)
            continue
        nested = np.full((FOLDS, EPOCHS, len(fold_of), TOP_K), np.nan, dtype=np.float32)
        losses = np.zeros((len(PAIRS), EPOCHS))
        started = time.perf_counter()
        for pair, (a, b) in enumerate(PAIRS):
            fit = np.flatnonzero((fold_of != a) & (fold_of != b))
            rows_a, rows_b = np.flatnonzero(fold_of == a), np.flatnonzero(fold_of == b)
            for epoch, loss, model in h21.train_epochs(train, features, fit, "C2", pair_seed(seed, pair), EPOCHS):
                losses[pair, epoch - 1] = loss
                nested[b, epoch - 1, rows_a] = h21.score_rows(model, train, features, rows_a)
                nested[a, epoch - 1, rows_b] = h21.score_rows(model, train, features, rows_b)
            log(stage="teachers", seed=seed, pair=pair, seconds=round(time.perf_counter() - started, 1))
        for k in range(FOLDS):
            if not np.isfinite(nested[k][:, fold_of != k]).all() or not np.isnan(nested[k][:, fold_of == k]).all():
                raise HarnessError("nested teacher logits violate the outer-fold contract")
        h21.save_npz_once(target, scores=nested, pair_losses=losses)
        log(stage="teachers-done", seed=seed, seconds=round(time.perf_counter() - started, 1))


def stage_teacher_select(_: argparse.Namespace) -> None:
    require_parity()
    verify_inputs()
    if (OUT / "teacher-selection.json").exists():
        raise HarnessError("refusing to overwrite teacher-selection.json")
    fold_of, gold, scores21 = gate.load_train()
    nested, nested_sha = {}, {}
    for seed in SEEDS:
        path = OUT / "nested" / f"C2-s{seed}.npz"
        nested_sha[str(seed)] = gate.sha256_file(path)
        with np.load(path, allow_pickle=False) as npz:
            nested[seed] = np.array(npz["scores"])
    teachers = np.full((FOLDS, len(fold_of), TOP_K), np.nan, dtype=np.float64)
    folds = []
    for k in range(FOLDS):
        rows = fold_of != k
        epochs = {seed: gate.choose_epoch(nested[seed][k][:, rows], gold[rows]) for seed in SEEDS}
        teachers[k, rows] = ensemble({seed: nested[seed][k][epochs[seed] - 1][rows] for seed in SEEDS})
        folds.append({"fold": k, "epochs": {str(seed): epochs[seed] for seed in SEEDS},
                      "rows": int(rows.sum()), "baseline_correct": int((gold[rows] == 0).sum()),
                      "ungated": gate.outcome(teachers[k, rows].argmax(axis=1), gold[rows])})
    final = final_teacher(scores21)
    teachers_sha = h21.save_npz_once(OUT / "teachers.npz", nested=teachers, final=final)
    result = {"nested_sha256": nested_sha, "teachers_sha256": teachers_sha, "folds": folds,
              "final": {"epochs": {str(s): e for s, e in FINAL_EPOCHS.items()},
                        "ungated": gate.outcome(final.argmax(axis=1), gold)}}
    digest = gate.write_once(OUT / "teacher-selection.json", result)
    log(teacher_selection_sha256=digest, epochs=[fold["epochs"] for fold in folds])


def stage_students(_: argparse.Namespace) -> None:
    require_parity()
    verify_inputs()
    selection, _ = require("teacher-selection.json")
    teachers = load_npz(OUT / "teachers.npz", selection["teachers_sha256"], "nested")
    fold_of, _, _, train, features = load_common()
    probs = [teacher_probabilities(teachers[k]) for k in range(FOLDS)]
    (OUT / "students").mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        target = OUT / "students" / f"C2KD-s{seed}.npz"
        if target.exists():
            log(stage="students", seed=seed, kept_existing=True)
            continue
        scores = np.full((EPOCHS, len(fold_of), TOP_K), np.nan, dtype=np.float32)
        fold_losses = np.zeros((FOLDS, EPOCHS))
        started = time.perf_counter()
        for k in range(FOLDS):
            fit, held = np.flatnonzero(fold_of != k), np.flatnonzero(fold_of == k)
            for epoch, loss, model in distill_epochs(train, features, fit, h21.fold_seed(seed, k), EPOCHS,
                                                     probs[k], KD_WEIGHT):
                fold_losses[k, epoch - 1] = loss
                scores[epoch - 1, held] = h21.score_rows(model, train, features, held)
            log(stage="students", seed=seed, fold=k, seconds=round(time.perf_counter() - started, 1))
        if not np.isfinite(scores).all():
            raise HarnessError("incomplete student out-of-fold logits")
        h21.save_npz_once(target, scores=scores, fold_losses=fold_losses)
        log(stage="students-done", seed=seed, seconds=round(time.perf_counter() - started, 1))


def load_students(selection: dict | None = None) -> tuple[dict[int, np.ndarray], dict[str, str]]:
    students, shas = {}, {}
    for seed in SEEDS:
        path = OUT / "students" / f"C2KD-s{seed}.npz"
        shas[str(seed)] = gate.sha256_file(path)
        if selection is not None and selection["student_sha256"][str(seed)] != shas[str(seed)]:
            raise HarnessError(f"{path.name} changed after it was bound")
        with np.load(path, allow_pickle=False) as npz:
            students[seed] = np.array(npz["scores"])
        if students[seed].shape != (EPOCHS, gate.TRAIN_COUNT, TOP_K) or not np.isfinite(students[seed]).all():
            raise HarnessError("student OOF logits violate the fixed shape")
    return students, shas


def stage_crossfit(_: argparse.Namespace) -> None:
    require_parity()
    verify_inputs()
    fold_of, gold, _ = gate.load_train()
    students, shas = load_students()
    base_correct = int((gold == 0).sum())
    base_errors = gate.TRAIN_COUNT - base_correct
    result = {"base_correct": base_correct, "base_errors": base_errors, "student_sha256": shas, "seeds": {}}
    for seed in SEEDS:
        per_rule = {name: {"folds": [], "totals": dict.fromkeys(("correct", "harm", "rescue", "overrides"), 0)}
                    for name in gate.RULES}
        for k in range(FOLDS):
            inner = fold_of != k
            outer = ~inner
            epoch = gate.choose_epoch(students[seed][:, inner], gold[inner])
            n_inner = int((gold[inner] == 0).sum())
            for name, (budget_kind, kinds) in gate.RULES.items():
                budget = gate.budget_for(budget_kind, n_inner)
                chosen = gate.choose_gate(students[seed][epoch - 1][inner], gold[inner], budget, kinds)
                held_out = gate.outcome(gate.apply_gate(students[seed][epoch - 1][outer], chosen), gold[outer])
                per_rule[name]["folds"].append({
                    "fold": k, "epoch": epoch, "inner_baseline_correct": n_inner, "harm_budget": budget,
                    "score": None if chosen is None else chosen["score"],
                    "tau": None if chosen is None else chosen["tau"],
                    "held_out": held_out,
                })
                for field in held_out:
                    per_rule[name]["totals"][field] += held_out[field]
        for name in gate.RULES:
            per_rule[name]["derived"] = gate.derived(per_rule[name]["totals"], base_correct, base_errors)
        result["seeds"][str(seed)] = per_rule
    digest = gate.write_once(OUT / "crossfit.json", result)
    log(crossfit_sha256=digest)


def stage_select(_: argparse.Namespace) -> None:
    require_parity()
    verify_inputs()
    crossfit, crossfit_sha = require("crossfit.json")
    _, gold, scores21 = gate.load_train()
    students, _ = load_students(crossfit)
    base_correct = int((gold == 0).sum())
    epoch = gate.choose_epoch(students[ARTIFACT_SEED], gold)
    logits = students[ARTIFACT_SEED][epoch - 1]
    result = {"crossfit_sha256": crossfit_sha, "base_correct": base_correct, "seed": ARTIFACT_SEED,
              "epoch": epoch}
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
    reference = {}
    for seed in SEEDS:
        student_epoch = gate.choose_epoch(students[seed], gold)
        reference[str(seed)] = {
            "student": {"epoch": student_epoch,
                        "ungated": gate.outcome(students[seed][student_epoch - 1].argmax(axis=1), gold)},
            "issue21_c2": {"epoch": FINAL_EPOCHS[seed],
                           "ungated": gate.outcome(scores21[seed][FINAL_EPOCHS[seed] - 1].argmax(axis=1), gold)},
        }
    result["reference_ungated"] = reference
    digest = gate.write_once(OUT / "selection.json", result)
    log(selection_sha256=digest, epoch=epoch, gate=result["main"]["gate"])


def stage_decide_accuracy(_: argparse.Namespace) -> None:
    require_no_dev_access()
    crossfit, crossfit_sha = require("crossfit.json")
    selection, selection_sha = require("selection.json")
    if selection["crossfit_sha256"] != crossfit_sha:
        raise HarnessError("selection is not bound to the current crossfit")
    per_seed = {seed: body["main"]["derived"]["criteria"] for seed, body in crossfit["seeds"].items()}
    names = next(iter(per_seed.values())).keys()
    criteria = {name: all(per_seed[seed][name] for seed in per_seed) for name in names}
    decision = {"crossfit_sha256": crossfit_sha, "selection_sha256": selection_sha,
                "per_seed_criteria": per_seed, "criteria_1_to_3": criteria,
                "criteria_1_to_3_pass": all(criteria.values())}
    digest = gate.write_once(OUT / "decision-accuracy.json", decision)
    log(decision_accuracy_sha256=digest, **decision)


def stage_final(_: argparse.Namespace) -> None:
    import torch

    require_parity()
    verify_inputs()
    if (OUT / "final.json").exists():
        raise HarnessError("refusing to overwrite final.json")
    accuracy, accuracy_sha = require("decision-accuracy.json")
    selection, _ = gate.read_bound(OUT / "selection.json", accuracy["selection_sha256"])
    teacher_selection, _ = require("teacher-selection.json")
    final = load_npz(OUT / "teachers.npz", teacher_selection["teachers_sha256"], "final")
    _, _, _, train, features = load_common()
    epochs = int(selection["epoch"])
    rows = np.arange(gate.TRAIN_COUNT)
    for epoch, loss, model in distill_epochs(train, features, rows, ARTIFACT_SEED, epochs,
                                             teacher_probabilities(final), KD_WEIGHT):
        pass
    checkpoint = OUT / "final" / f"student-s{ARTIFACT_SEED}.pt"
    if checkpoint.exists():
        raise HarnessError(f"refusing to overwrite {checkpoint.name}")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"recipe": "C2-distilled", "seed": ARTIFACT_SEED, "epoch": epochs, "kd_weight": KD_WEIGHT,
                "temperature": TEMPERATURE,
                "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()}}, checkpoint)
    dev = h21.load_split("dev")
    with np.load(SRC21 / "costs.npz", allow_pickle=False) as npz:
        dev_costs = np.array(npz["dev"])
    dev_logits = h21.score_rows(model, dev, h21.recipe_features(dev, dev_costs, "C2"),
                                np.arange(gate.DEV_COUNT))
    dev_sha = h21.save_npz_once(OUT / "final" / "dev-logits.npz", scores=dev_logits)
    result = {"decision_accuracy_sha256": accuracy_sha, "seed": ARTIFACT_SEED, "epoch": epochs,
              "last_train_loss": round(loss, 8), "checkpoint_sha256": gate.sha256_file(checkpoint),
              "dev_logits_sha256": dev_sha}
    digest = gate.write_once(OUT / "final.json", result)
    log(final_sha256=digest, **result)


def stage_export(_: argparse.Namespace) -> None:
    import onnx
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    verify_inputs()
    if (OUT / "export.json").exists():
        raise HarnessError("refusing to overwrite export.json")
    final_record, final_sha = require("final.json")
    accuracy, accuracy_sha = gate.read_bound(OUT / "decision-accuracy.json", final_record["decision_accuracy_sha256"])
    selection, _ = gate.read_bound(OUT / "selection.json", accuracy["selection_sha256"])
    checkpoint = OUT / "final" / f"student-s{ARTIFACT_SEED}.pt"
    if gate.sha256_file(checkpoint) != final_record["checkpoint_sha256"]:
        raise HarnessError("the final checkpoint changed after it was bound")
    stored = load_npz(OUT / "final" / "dev-logits.npz", final_record["dev_logits_sha256"], "scores")
    r2 = r2_module()
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = r2.build_model()
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    fp32_path, int8_path = OUT / "student-fp32.onnx", OUT / "student-int8.onnx"
    for path in (fp32_path, int8_path):
        if path.exists():
            raise HarnessError(f"refusing to overwrite {path.name}")
    dynamic_axes = {name: {0: "batch"} for name in r2.INPUT_NAMES}
    dynamic_axes["scores"] = {0: "batch"}
    torch.onnx.export(model, r2._example_inputs(1), fp32_path, input_names=list(r2.INPUT_NAMES),
                      output_names=["scores"], dynamic_axes=dynamic_axes, opset_version=18,
                      do_constant_folding=True, dynamo=False)
    onnx.checker.check_model(onnx.load(fp32_path))
    quantize_dynamic(fp32_path, int8_path, weight_type=QuantType.QInt8, per_channel=True, reduce_range=False)
    onnx.checker.check_model(onnx.load(int8_path))
    values = r2.load_inputs(*r2_inputs())
    batches = [{name: values[f"dev_{name}"][start:start + r2.BATCH_SIZE] for name in r2.INPUT_NAMES}
               for start in range(0, gate.DEV_COUNT, r2.BATCH_SIZE)]
    with torch.inference_mode():
        torch_logits = np.concatenate([model(*(torch.from_numpy(b[n]) for n in r2.INPUT_NAMES)).numpy()
                                       for b in batches])
    onnx_logits = {}
    for label, path in (("fp32", fp32_path), ("int8", int8_path)):
        session = r2._cpu_session(path)
        onnx_logits[label] = np.concatenate([session.run(["scores"], b)[0] for b in batches])
        del session
    final_gate = selection["main"]["gate"]
    decision = {name: gate.apply_gate(array, final_gate) for name, array in
                (("stored", stored), ("torch", torch_logits), ("fp32", onnx_logits["fp32"]),
                 ("int8", onnx_logits["int8"]))}
    result = {
        "decision_accuracy_sha256": accuracy_sha, "final_sha256": final_sha,
        "final_gate": None if final_gate is None else {"score": final_gate["score"], "tau": final_gate["tau"]},
        "onnx": {label: {"file": path.name, "bytes": path.stat().st_size, "sha256": gate.sha256_file(path)}
                 for label, path in (("fp32", fp32_path), ("int8", int8_path))},
        "checkpoint_sha256": final_record["checkpoint_sha256"],
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
    log(export_sha256=digest, parity=result["parity"])


def stage_benchmark(_: argparse.Namespace) -> None:
    export, _ = require("export.json")
    r2 = r2_module()
    targets = (("fp32", OUT / "student-fp32.onnx", export["onnx"]["fp32"]["sha256"]),
               ("int8", OUT / "student-int8.onnx", export["onnx"]["int8"]["sha256"]),
               ("r2-single-fp32", R2_FP32, EXTRA_INPUTS[R2_FP32]))
    for label, path, expected in targets:
        report_path = OUT / f"{label}-benchmark.report.json"
        if report_path.exists():
            raise HarnessError(f"refusing to overwrite {report_path.name}")
        if gate.sha256_file(path) != expected:
            raise HarnessError(f"hash mismatch for {path.name}")
        report = r2.benchmark_onnx(path, *r2_inputs(), report_path,
                                   warmup_runs=WARMUP_RUNS, measured_runs=MEASURED_RUNS)
        log(label=label, latency_ms=report["latency_ms"], failures=report["contract"]["failure_count"])


def stage_decide(_: argparse.Namespace) -> None:
    if (OUT / "dev-eval.json").exists():
        raise HarnessError("dev was already evaluated; the decision must precede it")
    accuracy, accuracy_sha = require("decision-accuracy.json")
    export, export_sha = require("export.json")
    if export["decision_accuracy_sha256"] != accuracy_sha:
        raise HarnessError("export is not bound to the accuracy decision")
    benchmark, benchmark_sha = require("fp32-benchmark.report.json")
    if benchmark["model"]["sha256"] != export["onnx"]["fp32"]["sha256"]:
        raise HarnessError("benchmark measured a different FP32 file")
    contract = benchmark["contract"]
    if (contract["warmup_runs"], contract["measured_runs"], contract["failure_count"], contract["batch_size"],
            contract["ort_intra_op_threads"], contract["ort_inter_op_threads"]) != (WARMUP_RUNS, MEASURED_RUNS,
                                                                                    0, 1, 1, 1):
        raise HarnessError("benchmark contract differs from the plan")
    criteria = {
        **accuracy["criteria_1_to_3"],
        "fp32_student_p95_at_most_2_ms": benchmark["latency_ms"]["p95"] <= P95_LIMIT_MS,
        "fp32_decisions_equal_stored_on_all_dev_rows": export["criterion_5_pass"],
    }
    decision = {"decision_accuracy_sha256": accuracy_sha, "export_sha256": export_sha,
                "fp32_benchmark_sha256": benchmark_sha, "criteria": criteria,
                "adopted": all(criteria.values())}
    digest = gate.write_once(OUT / "decision.json", decision)
    log(decision_sha256=digest, adopted=decision["adopted"], criteria=criteria)


def stage_eval_dev(_: argparse.Namespace) -> None:
    gate.verify_inputs()
    if (OUT / "dev-eval.json").exists():
        raise HarnessError("dev has already been evaluated once")
    decision, decision_sha = require("decision.json")
    accuracy, _ = gate.read_bound(OUT / "decision-accuracy.json", decision["decision_accuracy_sha256"])
    selection, selection_sha = gate.read_bound(OUT / "selection.json", accuracy["selection_sha256"])
    final_record, _ = require("final.json")
    logits = load_npz(OUT / "final" / "dev-logits.npz", final_record["dev_logits_sha256"], "scores")
    with np.load(SRC21 / "predictions.npz", allow_pickle=False) as npz:
        dev_gold = np.array(npz["dev_gold"])
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
        "harm_below_limit_one_sided_p": float(gate.binom_cdf_exact(gated_outcome["harm"], base_correct,
                                                                   gate.HARM_RATE)),
    }
    digest = gate.write_once(OUT / "dev-eval.json", result)
    log(dev_eval_sha256=digest)


def _comparable(teacher_selection: dict, crossfit: dict, selection: dict, accuracy: dict,
                dev_eval: dict) -> dict:
    """The fields the independent recomputation must reproduce exactly."""
    return {
        "teacher_epochs": [fold["epochs"] for fold in teacher_selection["folds"]],
        "crossfit": {seed: {rule: {"totals": body["totals"],
                                   "folds": [{f: fold[f] for f in ("fold", "epoch", "harm_budget", "score", "tau")}
                                             for fold in body["folds"]]}
                            for rule, body in rules.items()}
                     for seed, rules in crossfit["seeds"].items()},
        "final_epoch": selection["epoch"],
        "final_gate": None if selection["main"]["gate"] is None
        else {f: selection["main"]["gate"][f] for f in ("score", "tau")},
        "criteria_1_to_3_pass": accuracy["criteria_1_to_3_pass"],
        "dev_gated": dev_eval["gated"],
    }


def stage_publish(_: argparse.Namespace) -> None:
    if REPORT.exists():
        raise HarnessError("refusing to overwrite the tracked report")
    parity, parity_sha = require("parity.json")
    teacher_selection, teacher_selection_sha = require("teacher-selection.json")
    crossfit, crossfit_sha = require("crossfit.json")
    selection, selection_sha = require("selection.json")
    accuracy, accuracy_sha = require("decision-accuracy.json")
    final_record, final_sha = require("final.json")
    export, export_sha = require("export.json")
    decision, decision_sha = require("decision.json")
    dev_eval, dev_eval_sha = require("dev-eval.json")
    if (accuracy["crossfit_sha256"], accuracy["selection_sha256"]) != (crossfit_sha, selection_sha):
        raise HarnessError("accuracy decision is not bound to the current crossfit/selection")
    if (final_record["decision_accuracy_sha256"], export["final_sha256"]) != (accuracy_sha, final_sha):
        raise HarnessError("final student or export is not bound to the accuracy decision")
    if (decision["decision_accuracy_sha256"], decision["export_sha256"]) != (accuracy_sha, export_sha):
        raise HarnessError("decision is not bound to the accuracy decision and export")
    if dev_eval["decision_sha256"] != decision_sha:
        raise HarnessError("dev evaluation is not bound to the decision")
    load_students(crossfit)
    benchmarks = {}
    for label in ("fp32", "int8", "r2-single-fp32"):
        bench, bench_sha = require(f"{label}-benchmark.report.json")
        benchmarks[label] = {"latency_ms": bench["latency_ms"], "model_sha256": bench["model"]["sha256"],
                             "contract": bench["contract"], "report_sha256": bench_sha}
    if benchmarks["fp32"]["report_sha256"] != decision["fp32_benchmark_sha256"]:
        raise HarnessError("decision is not bound to the FP32 benchmark")
    recompute, recompute_sha = require("recompute.json")
    expected = _comparable(teacher_selection, crossfit, selection, accuracy, dev_eval)
    if gate.canonical(recompute["comparable"]) != gate.canonical(expected):
        raise HarnessError("independent recomputation disagrees")
    report = {
        "schema_version": 1,
        "report_kind": f"sakura_rerank_issue{ISSUE}_distill_gate",
        "issue": ISSUE,
        "status": "research_only_gate_a_failed",
        "final_holdout_used": False,
        "production_change_authorized": False,
        "artifact_distribution_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
        "plan_body_sha256": PLAN_BODY_SHA256,
        "inputs": {**gate.INPUTS, **{path.name: digest for path, digest in EXTRA_INPUTS.items()},
                   "issue21_run_py": H21_SHA256, "issue25_run_py": GATE_SHA256,
                   "research_tiny_r2_py": R2_PY_SHA256},
        "protocol": {
            "seeds": list(SEEDS), "artifact_seed": ARTIFACT_SEED,
            "teacher": "mean of float64-converted logits of the three C2 models",
            "nested_teacher_pairs": [list(pair) for pair in PAIRS],
            "nested_teacher_seed": "seed + 1000003 * (6 + pair index)",
            "student_loss": "(1 - w) * Issue #21 C2 loss + w * T^2 * KL(teacher || student)",
            "kd_weight": KD_WEIGHT, "temperature": TEMPERATURE,
            "gate_rules": "Issue #25 run.py, imported by hash",
            "training": "Issue #21 run.py, imported by hash",
            "p95_limit_ms": P95_LIMIT_MS, "warmup_runs": WARMUP_RUNS, "measured_runs": MEASURED_RUNS,
            "accuracy_decision_written_before_dev": True, "dev_evaluations": 1,
        },
        "train": {"row_count": gate.TRAIN_COUNT, "baseline_correct": crossfit["base_correct"],
                  "baseline_errors": crossfit["base_errors"]},
        "dev": {"row_count": gate.DEV_COUNT, "baseline_correct": dev_eval["base_correct"],
                "baseline_errors": dev_eval["base_errors"]},
        "parity": parity,
        # "rows" is a forbidden report key (it names row-level data elsewhere); this one is a count.
        "teachers": {"folds": [{("row_count" if key == "rows" else key): value for key, value in fold.items()}
                               for fold in teacher_selection["folds"]],
                     "final": teacher_selection["final"]},
        "crossfit": crossfit["seeds"],
        "final_selection": {k: v for k, v in selection.items() if k not in ("crossfit_sha256", "base_correct")},
        "final_student": {k: v for k, v in final_record.items() if k != "decision_accuracy_sha256"},
        "export": {k: v for k, v in export.items() if k not in ("decision_accuracy_sha256", "final_sha256")},
        "benchmarks": benchmarks,
        "decision": {"per_seed_criteria": accuracy["per_seed_criteria"], "criteria": decision["criteria"],
                     "adopted": decision["adopted"]},
        "dev_reference": {k: v for k, v in dev_eval.items() if k not in ("decision_sha256", "selection_sha256")},
        "independent_recomputation": {"matches": True, "script_sha256": gate.sha256_file(EXP / "recompute.py"),
                                      "output_sha256": recompute_sha},
        "artifacts": {"run_py_sha256": gate.sha256_file(Path(__file__)), "parity_sha256": parity_sha,
                      "nested_teacher_sha256": teacher_selection["nested_sha256"],
                      "teachers_sha256": teacher_selection["teachers_sha256"],
                      "teacher_selection_sha256": teacher_selection_sha,
                      "student_oof_sha256": crossfit["student_sha256"], "crossfit_sha256": crossfit_sha,
                      "selection_sha256": selection_sha, "decision_accuracy_sha256": accuracy_sha,
                      "final_sha256": final_sha, "export_sha256": export_sha, "decision_sha256": decision_sha,
                      "dev_eval_sha256": dev_eval_sha},
    }
    gate.write_once(REPORT, report)
    log(report=REPORT.name, adopted=decision["adopted"])


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    stages = {"parity": stage_parity, "teachers": stage_teachers, "teacher-select": stage_teacher_select,
              "students": stage_students, "crossfit": stage_crossfit, "select": stage_select,
              "decide-accuracy": stage_decide_accuracy, "final": stage_final, "export": stage_export,
              "benchmark": stage_benchmark, "decide": stage_decide, "eval-dev": stage_eval_dev,
              "publish": stage_publish}
    for name in stages:
        sub.add_parser(name)
    args = parser.parse_args()
    if PLAN_BODY_SHA256 == "PENDING":
        raise HarnessError("register the plan first")
    stages[args.stage](args)


if __name__ == "__main__":
    main()
