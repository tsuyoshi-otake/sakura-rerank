"""Research-only Sakura-Rerank-Tiny-v1 revision 2 (Issue #21).

Revision 2 is the recipe adopted by Issue #21's pre-registered retraining
experiment (``reports/issue-21-retrain-experiment.json``).  Relative to the v1
prototype in :mod:`sakura_rerank.research_tiny` it changes exactly four things:

* a seventh candidate feature, the absolute local-cost gap to the cheapest
  candidate, ``-log1p((cost_i - min cost) / 1000)``.  v1 normalizes local cost
  per row, which hides how large that gap is;
* dropout 0.1 after both scorer activations (inactive at inference);
* label smoothing 0.05 spread over the valid candidates only;
* a fixed epoch count chosen from grouped out-of-fold train predictions, so dev
  is evaluated once after training and selects nothing.

Character hashing, the v1 numeric cache, the network shape, the optimizer, and
the seed come from ``research_tiny``.  That module must stay byte-identical
because the v1 model manifest binds its SHA-256, so its fixed cache loader,
batching, and evaluation are reused instead of copied.  The cost-gap column is
a sidecar array bound to the v1 cache by hash and verified against the source
rows one by one.

Like v1, this lane cannot claim Gate A/B/C or production readiness.
Final-holdout lines are skipped by their split token before JSON parsing.
Latency is timed around ``InferenceSession.run`` only: v1's benchmark also
timed re-reading every dev array from the ``.npz`` for each run.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Mapping

from sakura_rerank import research_tiny as v1
from sakura_rerank.atomic_io import write_bytes_atomic, write_bytes_pair_atomic
from sakura_rerank.data.contracts import validate_record


SCHEMA_VERSION = 1
STATUS = "research_only_gate_a_failed"
MODEL_NAME = "Sakura-Rerank-Tiny-v1-research-r2"
MODEL_CONTRACT_VERSION = 2
FEATURE_DIM = v1.FEATURE_DIM + 1
COST_GAP_INDEX = v1.FEATURE_DIM
COST_GAP_SCALE = 1_000.0
COST_GAP_DEFINITION = "-log1p((local_cost_i - min_j local_cost_j) / 1000)"
DROPOUT = 0.1
LABEL_SMOOTHING = 0.05
SEED = v1.SEED
# Issue #21 froze nine epochs for this seed from grouped 5-fold out-of-fold
# train predictions before dev was evaluated.
EPOCHS = 9
BATCH_SIZE = 256
LEARNING_RATE = 0.001
WEIGHT_DECAY = 0.01
GRADIENT_CLIP_NORM = 1.0
HOLDOUT_SPLIT_TOKEN = b'"split":"final-holdout"'
HOLDOUT_COUNT = 3_576
ISSUE = 21
ADOPTED_RECIPE = "C2"
EXPERIMENT_REPORT_KIND = "sakura_rerank_issue21_retraining_experiment"
COST_GAP_MANIFEST_KIND = "sakura_rerank_tiny_r2_cost_gap_features"
TIMING_SCOPE = "inference_session_run_only_inputs_prebuilt"
INPUT_NAMES = (
    "context_ids",
    "context_lengths",
    "reading_ids",
    "reading_lengths",
    "candidate_ids",
    "candidate_lengths",
    "features",
    "candidate_mask",
)
# Field names that would carry dataset text or row identities.  No document
# this module writes may contain one at any depth.
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {"query", "document", "text", "surface", "reading", "left_context", "stable_id", "rows", "notes"}
)
# Report subtrees copied into the published manifest/decision report must have
# exactly these fields.  A leaf names its allowed JSON types exactly (``bool`` is
# not an ``int`` here), lists hold strings only, and strings stay short.
MAX_COPIED_STRING_LENGTH = 128
_INT = (int,)
_FLOAT = (float,)
_BOOL = (bool,)
_STR = (str,)
_STRINGS = (list,)
_BINDING_SHAPE = {"file": _STR, "bytes": _INT, "sha256": _STR}
_PARITY_SHAPE = {
    "fixture": {"max_absolute_error": _FLOAT, "top1_equal": _BOOL},
    "dev": {
        "record_count": _INT,
        "max_absolute_error": _FLOAT,
        "top1_mismatch_count": _INT,
        "top1_equal": _BOOL,
    },
}
_EXPORT_ARTIFACTS_SHAPE = {
    label: {**_BINDING_SHAPE, "parity": _PARITY_SHAPE} for label in ("fp32", "int8")
}
_ENVIRONMENT_SHAPE = {
    "python": _STR,
    "torch": _STR,
    "cuda": _STR,
    "gpu": _STR,
    "gpu_total_memory_bytes": _INT,
    "peak_allocated_bytes": _INT,
    "deterministic_algorithms": _BOOL,
}
_QUALITY_SHAPE = {
    "record_count": _INT,
    "oracle_count": _INT,
    "top1_correct": _INT,
    "top1_accuracy": _FLOAT,
    "mrr": _FLOAT,
    "ndcg_at_6": _FLOAT,
    "baseline_top1_correct": _INT,
    "baseline_top1_accuracy": _FLOAT,
    "rescue_count": _INT,
    "harm_count": _INT,
    # v1.ranking_metrics reports no ratio when there is no harm.
    "rescue_harm_ratio": (float, type(None)),
}
_LATENCY_SHAPE = dict.fromkeys(("mean", "p50", "p95", "p99", "max"), _FLOAT)
_BENCHMARK_CONTRACT_SHAPE = {
    "platform": _STR,
    "processor": _STR,
    "gpu_disabled": _BOOL,
    "provider": _STRINGS,
    "batch_size": _INT,
    "ort_intra_op_threads": _INT,
    "ort_inter_op_threads": _INT,
    "warmup_runs": _INT,
    "measured_runs": _INT,
    "failure_count": _INT,
    "timing_scope": _STR,
    "final_holdout_used": _BOOL,
}


class ResearchTinyR2Error(v1.ResearchTinyError):
    """A fixed revision-2 research contract was violated."""


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def _aggregate_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Return canonical bytes for a document that has no dataset-text field."""
    if not FORBIDDEN_OUTPUT_KEYS.isdisjoint(_keys(document)):
        raise ResearchTinyR2Error("output document contains a dataset-text field")
    return v1.canonical_json_bytes(document)


def _same_json(left: Any, right: Any) -> bool:
    """Compare as canonical JSON, so ``false`` and ``0`` stay different."""
    return v1.canonical_json_bytes(left) == v1.canonical_json_bytes(right)


def _require_shape(value: Any, shape: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Return ``value`` when its fields and leaf types equal ``shape``'s.

    A copied report subtree therefore cannot carry an extra field, a nested
    payload, a long text value, or ``false`` where a count is expected.
    """
    if not isinstance(value, dict) or set(value) != set(shape):
        raise ResearchTinyR2Error(f"{name} fields differ from the fixed contract")
    for key, spec in shape.items():
        child = value[key]
        if isinstance(spec, dict):
            _require_shape(child, spec, f"{name}.{key}")
            continue
        if type(child) not in spec:
            raise ResearchTinyR2Error(f"{name}.{key} has a JSON type outside the fixed contract")
        if type(child) is list and not all(type(item) is str for item in child):
            raise ResearchTinyR2Error(f"{name}.{key} must list strings only")
        strings = child if type(child) is list else [child]
        if any(type(item) is str and len(item) > MAX_COPIED_STRING_LENGTH for item in strings):
            raise ResearchTinyR2Error(f"{name}.{key} is longer than the fixed contract allows")
    return value


def cost_gap_features(candidates: list[Mapping[str, Any]]) -> list[float]:
    """Return each candidate's absolute local-cost gap to the cheapest one.

    The cheapest candidate maps to zero and larger gaps are more negative, so a
    5-point gap and a 5,000-point gap stay distinguishable.  v1's per-row
    min-max feature maps both to the same value.
    """
    import numpy as np

    costs = np.asarray(
        [float(candidate["local_cost"]) for candidate in candidates], dtype=np.float64
    )
    if costs.size == 0 or not np.isfinite(costs).all():
        raise ResearchTinyR2Error("local costs must be finite and non-empty")
    return [float(value) for value in -np.log1p((costs - costs.min()) / COST_GAP_SCALE)]


def candidate_features(reading: str, candidates: list[Mapping[str, Any]]) -> list[list[float]]:
    """Return v1's six candidate features followed by the cost-gap feature."""
    return [
        row + [gap]
        for row, gap in zip(
            v1.candidate_features(reading, candidates),
            cost_gap_features(candidates),
            strict=True,
        )
    ]


def build_model() -> Any:
    import torch
    from torch import nn

    hidden = v1.HIDDEN_DIM

    class SakuraRerankTinyR2(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            # Same construction order as v1, so seeded initialization lines up.
            self.embedding = nn.Embedding(v1.VOCAB_SIZE, v1.EMBEDDING_DIM, padding_idx=0)
            self.encoder = nn.GRU(
                v1.EMBEDDING_DIM,
                hidden,
                num_layers=v1.GRU_LAYERS,
                batch_first=True,
            )
            self.scorer = nn.Sequential(
                nn.Linear(hidden * 3 + FEATURE_DIM, hidden),
                nn.SiLU(),
                nn.Dropout(DROPOUT),
                nn.Linear(hidden, 64),
                nn.SiLU(),
                nn.Dropout(DROPOUT),
                nn.Linear(64, 1),
            )

        def encode(self, ids: Any, lengths: Any) -> Any:
            output, _ = self.encoder(self.embedding(ids))
            index = torch.clamp(lengths - 1, min=0)
            gathered = output.gather(1, index.view(-1, 1, 1).expand(-1, 1, hidden)).squeeze(1)
            return gathered * (lengths > 0).to(gathered.dtype).unsqueeze(1)

        def forward(
            self,
            context_ids: Any,
            context_lengths: Any,
            reading_ids: Any,
            reading_lengths: Any,
            candidate_ids: Any,
            candidate_lengths: Any,
            features: Any,
            candidate_mask: Any,
        ) -> Any:
            batch = context_ids.shape[0]
            context = self.encode(context_ids, context_lengths)
            reading = self.encode(reading_ids, reading_lengths)
            candidates = self.encode(
                candidate_ids.reshape(batch * v1.TOP_K, v1.SURFACE_LENGTH),
                candidate_lengths.reshape(batch * v1.TOP_K),
            ).reshape(batch, v1.TOP_K, hidden)
            joined = torch.cat(
                (
                    context.unsqueeze(1).expand(-1, v1.TOP_K, -1),
                    reading.unsqueeze(1).expand(-1, v1.TOP_K, -1),
                    candidates,
                    features,
                ),
                dim=2,
            )
            residual = self.scorer(joined).squeeze(2)
            scores = features[:, :, 0] * 2.0 + residual
            return scores.masked_fill(~candidate_mask, -10_000.0)

    return SakuraRerankTinyR2()


def smoothed_listwise_loss(scores: Any, gold: Any, candidate_mask: Any) -> Any:
    """Cross-entropy against gold weighted 1 - LABEL_SMOOTHING plus an even
    LABEL_SMOOTHING spread over the valid candidates only.

    ``gold`` must index a valid candidate: rows without an oracle candidate are
    excluded from training before this is called.  Padding receives no target
    mass, so its masked score never enters the loss.
    """
    import torch
    from torch.nn import functional

    log_probs = torch.log_softmax(scores, dim=1)
    valid = candidate_mask.to(log_probs.dtype)
    target = valid * (LABEL_SMOOTHING / valid.sum(dim=1, keepdim=True))
    target = target + (1.0 - LABEL_SMOOTHING) * functional.one_hot(gold, v1.TOP_K).to(
        log_probs.dtype
    )
    return -(target * log_probs).sum(dim=1).mean()


def _train_dev_row(line: bytes) -> dict[str, Any] | None:
    """Parse one frozen-split line, or return None for a final-holdout line.

    Final-holdout lines are recognized by their exact split token and are never
    decoded or parsed.  Every other line must be a train or dev row, so a
    holdout row spelled differently fails closed instead of being read.
    """
    if HOLDOUT_SPLIT_TOKEN in line:
        return None
    try:
        raw = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchTinyR2Error("dataset contains invalid JSON") from error
    if not isinstance(raw, dict) or raw.get("split") not in ("train", "dev"):
        raise ResearchTinyR2Error("dataset row is outside the train/dev contract")
    return raw


def _cost_gap_manifest(
    source: Mapping[str, Any],
    cache: Path,
    cache_manifest: Path,
    cost_gap: Path,
) -> dict[str, Any]:
    """The complete sidecar manifest; only the source binding is passed in."""
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": COST_GAP_MANIFEST_KIND,
        "status": STATUS,
        "source": dict(source),
        "v1_numeric_cache": {
            "file": cache.name,
            "sha256": v1.sha256_file(cache),
            "manifest_sha256": v1.sha256_file(cache_manifest),
        },
        "cost_gap": _file_binding(cost_gap),
        "feature": {
            "index": COST_GAP_INDEX,
            "definition": COST_GAP_DEFINITION,
            "padding_value": 0.0,
        },
        "alignment_with_v1_cache": {
            "v1_features_equal": True,
            "candidate_mask_equal": True,
            "gold_equal": True,
        },
        "splits": {"train": v1.TRAIN_COUNT, "dev": v1.DEV_COUNT},
        "final_holdout": {
            "source_lines_skipped_by_split_token": HOLDOUT_COUNT,
            "rows_in_sidecar": 0,
            "used_for_training_or_selection": False,
        },
        "raw_text_in_manifest": False,
        "raw_stable_ids_in_manifest": False,
    }


def prepare_cost_gap(
    source: Path,
    cache: Path,
    cache_manifest: Path,
    output: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Write the cost-gap sidecar after verifying every row against the v1 cache."""
    import numpy as np

    if v1.sha256_file(source) != v1.DATASET_CONTENT_SHA256:
        raise ResearchTinyR2Error("source differs from the frozen v5 split")
    cached, _ = v1._load_cache(cache, cache_manifest)
    try:
        reference = {
            split: {
                name: cached[f"{split}_{name}"] for name in ("features", "candidate_mask", "gold")
            }
            for split in ("train", "dev")
        }
    finally:
        cached.close()
    expected = {"train": v1.TRAIN_COUNT, "dev": v1.DEV_COUNT}
    gaps = {
        split: np.zeros((count, v1.TOP_K), dtype=np.float32) for split, count in expected.items()
    }
    offsets = {"train": 0, "dev": 0}
    holdout_skipped = 0
    with source.open("rb") as rows:
        for line in rows:
            raw = _train_dev_row(line)
            if raw is None:
                holdout_skipped += 1
                continue
            record = validate_record(raw)
            if record["is_fixture"] or not record["training_eligible"]:
                raise ResearchTinyR2Error("cost-gap sidecar accepts eligible non-fixture rows only")
            split = raw["split"]
            index = offsets[split]
            if index >= expected[split]:
                raise ResearchTinyR2Error("split exceeds its pinned record count")
            candidates = record["candidate_snapshots"]["production_top6"]["candidates"]
            count = len(candidates)
            if not 2 <= count <= v1.TOP_K:
                raise ResearchTinyR2Error("candidate count outside production top-6 contract")
            features = np.asarray(
                candidate_features(record["reading"], candidates), dtype=np.float64
            )
            cached_split = reference[split]
            gold = int(record["gold_index"])
            if (
                not np.array_equal(
                    features[:, :COST_GAP_INDEX].astype(np.float32),
                    cached_split["features"][index, :count],
                )
                or not np.array_equal(
                    cached_split["candidate_mask"][index], np.arange(v1.TOP_K) < count
                )
                or (gold if gold < count else -1) != int(cached_split["gold"][index])
            ):
                raise ResearchTinyR2Error("source row does not align with the v1 numeric cache")
            gaps[split][index, :count] = features[:, COST_GAP_INDEX]
            offsets[split] += 1
    if offsets != expected or holdout_skipped != HOLDOUT_COUNT:
        raise ResearchTinyR2Error("frozen split counts differ from the pinned contract")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp.npz")
    np.savez(temporary, train_cost_gap=gaps["train"], dev_cost_gap=gaps["dev"])
    os.replace(temporary, output)
    manifest = _cost_gap_manifest(
        {"file": source.name, "bytes": source.stat().st_size, "sha256": v1.DATASET_CONTENT_SHA256},
        cache,
        cache_manifest,
        output,
    )
    write_bytes_atomic(manifest_path, _aggregate_json_bytes(manifest), create_parent=True)
    return manifest


def load_inputs(
    cache: Path,
    cache_manifest: Path,
    cost_gap: Path,
    cost_gap_manifest: Path,
) -> dict[str, Any]:
    """Return the v1 cache arrays with the cost-gap column appended to features."""
    import numpy as np

    raw_manifest = cost_gap_manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    if raw_manifest != v1.canonical_json_bytes(manifest):
        raise ResearchTinyR2Error("cost-gap manifest is not canonical JSON plus LF")
    source = manifest.get("source") if isinstance(manifest, dict) else None
    # Every field is pinned byte for byte; only the source file name and size
    # come from the manifest itself, because the source is not an input here.
    if (
        not isinstance(source, dict)
        or set(source) != set(_BINDING_SHAPE)
        or source["sha256"] != v1.DATASET_CONTENT_SHA256
        or raw_manifest
        != v1.canonical_json_bytes(_cost_gap_manifest(source, cache, cache_manifest, cost_gap))
    ):
        raise ResearchTinyR2Error("cost-gap manifest violates the fixed contract")
    cached, _ = v1._load_cache(cache, cache_manifest)
    try:
        values = {name: cached[name] for name in cached.files}
    finally:
        cached.close()
    with np.load(cost_gap, allow_pickle=False) as sidecar:
        if set(sidecar.files) != {"train_cost_gap", "dev_cost_gap"}:
            raise ResearchTinyR2Error("cost-gap fields differ from the fixed contract")
        for split, count in (("train", v1.TRAIN_COUNT), ("dev", v1.DEV_COUNT)):
            gap = sidecar[f"{split}_cost_gap"]
            valid = values[f"{split}_candidate_mask"]
            if (
                gap.shape != (count, v1.TOP_K)
                or gap.dtype != np.float32
                or not np.isfinite(gap).all()
                or np.any(gap > 0)
                or np.any(gap[~valid] != 0)
            ):
                raise ResearchTinyR2Error("cost-gap values violate the fixed contract")
            values[f"{split}_features"] = np.concatenate(
                (values[f"{split}_features"], gap[:, :, None]), axis=2
            )
    return values


def _rounded(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: round(value, 10) if isinstance(value, float) else value
        for key, value in metrics.items()
    }


def _recipe() -> dict[str, Any]:
    return {
        "issue": ISSUE,
        "adopted_recipe": ADOPTED_RECIPE,
        "feature_dim": FEATURE_DIM,
        "cost_gap_feature": {"index": COST_GAP_INDEX, "definition": COST_GAP_DEFINITION},
        "scorer_dropout": DROPOUT,
        "label_smoothing": LABEL_SMOOTHING,
        "label_smoothing_support": "valid_candidates_only",
        "epochs": EPOCHS,
        "epoch_selection": "issue_21_grouped_5_fold_out_of_fold_train_predictions",
        "dev_used_for_selection": False,
    }


def _hyperparameters() -> dict[str, Any]:
    return {
        "epochs": EPOCHS,
        "batch_size": BATCH_SIZE,
        "learning_rate": LEARNING_RATE,
        "optimizer": "AdamW",
        "weight_decay": WEIGHT_DECAY,
        "gradient_clip_norm": GRADIENT_CLIP_NORM,
    }


def _file_binding(path: Path) -> dict[str, Any]:
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": v1.sha256_file(path)}


def train_model(
    cache: Path,
    cache_manifest: Path,
    cost_gap: Path,
    cost_gap_manifest: Path,
    checkpoint: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Train the fixed revision-2 recipe and evaluate dev once afterwards."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import numpy as np
    import torch

    if not torch.cuda.is_available():
        raise ResearchTinyR2Error("CUDA is required for the approved training run")
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.use_deterministic_algorithms(True)
    values = load_inputs(cache, cache_manifest, cost_gap, cost_gap_manifest)
    device = torch.device("cuda:0")
    model = build_model().to(device)
    parameter_count = v1.model_parameter_count(model)
    if not 1_800_000 <= parameter_count <= 2_100_000:
        raise ResearchTinyR2Error("model is outside the approximately 2M parameter budget")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    eligible = np.flatnonzero(values["train_gold"] >= 0)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    history = []
    started = time.perf_counter()
    for epoch in range(1, EPOCHS + 1):
        model.train()
        order = eligible[torch.randperm(len(eligible), generator=generator).numpy()]
        losses = []
        for start in range(0, len(order), BATCH_SIZE):
            batch = v1._batch(values, "train", order[start : start + BATCH_SIZE], device)
            optimizer.zero_grad(set_to_none=True)
            scores = model(*batch[:-1])
            loss = smoothed_listwise_loss(scores, batch[-1], batch[-2])
            if not torch.isfinite(loss):
                raise ResearchTinyR2Error("training produced a non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRADIENT_CLIP_NORM)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        history.append({"epoch": epoch, "train_loss": round(statistics.fmean(losses), 8)})
        print(json.dumps(history[-1], sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    # The only dev evaluation, after the fixed final epoch; it selects nothing.
    dev = v1._evaluate(model, values, "dev", device, BATCH_SIZE)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    temporary = checkpoint.with_name(checkpoint.name + ".tmp")
    torch.save(
        {
            "schema_version": SCHEMA_VERSION,
            "model_contract_version": MODEL_CONTRACT_VERSION,
            "model_name": MODEL_NAME,
            "parameter_count": parameter_count,
            "epoch": EPOCHS,
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        },
        temporary,
    )
    os.replace(temporary, checkpoint)
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_r2_training",
        "status": STATUS,
        "gate_a_status": v1.EXPECTED_GATE_STATUS,
        "model_name": MODEL_NAME,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "parameter_count": parameter_count,
        "seed": SEED,
        "data": {
            "cache_manifest_sha256": v1.sha256_file(cache_manifest),
            "cache_sha256": v1.sha256_file(cache),
            "cost_gap_manifest_sha256": v1.sha256_file(cost_gap_manifest),
            "cost_gap_sha256": v1.sha256_file(cost_gap),
            "train_count": v1.TRAIN_COUNT,
            "dev_count": v1.DEV_COUNT,
            "final_holdout_used": False,
        },
        "recipe": _recipe(),
        "hyperparameters": _hyperparameters(),
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
            "deterministic_algorithms": True,
        },
        "history": history,
        "dev_single_evaluation": _rounded(dev),
        "checkpoint": _file_binding(checkpoint),
        "wall_time_seconds": round(elapsed, 6),
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(report_path, _aggregate_json_bytes(report), create_parent=True)
    return report


def _example_inputs(batch_size: int = 1) -> tuple[Any, ...]:
    import torch

    inputs = list(v1._example_inputs(batch_size))
    gap = torch.zeros((batch_size, v1.TOP_K, 1), dtype=torch.float32)
    for candidate in range(v1.TOP_K):
        gap[:, candidate, 0] = -math.log1p(candidate * 100 / COST_GAP_SCALE)
    inputs[6] = torch.cat((inputs[6], gap), dim=2)
    return tuple(inputs)


@contextlib.contextmanager
def _gpus_hidden() -> Iterator[None]:
    """Hide every GPU from ORT for the benchmark, then restore the caller's value.

    This is what the benchmark contract's ``gpu_disabled`` field records, as in
    v1; the CPU-only provider list is checked separately.
    """
    previous = os.environ.get("CUDA_VISIBLE_DEVICES")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = previous


def _cpu_session(path: Path) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def export_onnx(
    checkpoint: Path,
    cache: Path,
    cache_manifest: Path,
    cost_gap: Path,
    cost_gap_manifest: Path,
    fp32_path: Path,
    int8_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Export FP32/INT8 ONNX and compare top-1 with PyTorch on every dev row."""
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    if fp32_path.resolve() == int8_path.resolve():
        raise ResearchTinyR2Error("FP32 and INT8 exports need distinct paths")
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("model_name") != MODEL_NAME
        or payload.get("model_contract_version") != MODEL_CONTRACT_VERSION
        or payload.get("epoch") != EPOCHS
    ):
        raise ResearchTinyR2Error("checkpoint identity differs from the model contract")
    model = build_model()
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    parameter_count = v1.model_parameter_count(model)
    if payload.get("parameter_count") != parameter_count:
        raise ResearchTinyR2Error("checkpoint parameter count differs from its weights")
    values = load_inputs(cache, cache_manifest, cost_gap, cost_gap_manifest)
    fp32_path.parent.mkdir(parents=True, exist_ok=True)
    int8_path.parent.mkdir(parents=True, exist_ok=True)
    # Both models are built and checked under temporary names and reach their
    # final names together only after the parity gate passes.
    fp32_temporary = fp32_path.with_name(fp32_path.name + ".tmp.onnx")
    int8_temporary = int8_path.with_name(int8_path.name + ".tmp.onnx")
    try:
        # ONNX's GRU exporter requires the trace batch to be one when the batch
        # dimension is dynamic and no explicit initial state is exposed.
        fixture = _example_inputs(1)
        dynamic_axes = {name: {0: "batch"} for name in INPUT_NAMES}
        dynamic_axes["scores"] = {0: "batch"}
        torch.onnx.export(
            model,
            fixture,
            fp32_temporary,
            input_names=list(INPUT_NAMES),
            output_names=["scores"],
            dynamic_axes=dynamic_axes,
            opset_version=18,
            do_constant_folding=True,
            dynamo=False,
        )
        onnx.checker.check_model(onnx.load(fp32_temporary))
        quantize_dynamic(
            fp32_temporary,
            int8_temporary,
            weight_type=QuantType.QInt8,
            per_channel=True,
            reduce_range=False,
        )
        onnx.checker.check_model(onnx.load(int8_temporary))
        dev_batches = [
            {name: values[f"dev_{name}"][start : start + BATCH_SIZE] for name in INPUT_NAMES}
            for start in range(0, v1.DEV_COUNT, BATCH_SIZE)
        ]
        with torch.inference_mode():
            fixture_expected = model(*fixture).numpy()
            dev_expected = np.concatenate(
                [
                    model(*(torch.from_numpy(batch[name]) for name in INPUT_NAMES)).numpy()
                    for batch in dev_batches
                ]
            )
        fixture_feed = {
            name: value.numpy() for name, value in zip(INPUT_NAMES, fixture, strict=True)
        }
        parity = {}
        for label, path in (("fp32", fp32_temporary), ("int8", int8_temporary)):
            session = _cpu_session(path)
            fixture_actual = session.run(["scores"], fixture_feed)[0]
            dev_actual = np.concatenate(
                [session.run(["scores"], batch)[0] for batch in dev_batches]
            )
            mismatches = int(np.sum(dev_expected.argmax(axis=1) != dev_actual.argmax(axis=1)))
            parity[label] = {
                "fixture": {
                    "max_absolute_error": float(np.max(np.abs(fixture_expected - fixture_actual))),
                    "top1_equal": bool(
                        np.array_equal(
                            fixture_expected.argmax(axis=1), fixture_actual.argmax(axis=1)
                        )
                    ),
                },
                "dev": {
                    "record_count": int(len(dev_actual)),
                    "max_absolute_error": float(np.max(np.abs(dev_expected - dev_actual))),
                    "top1_mismatch_count": mismatches,
                    "top1_equal": mismatches == 0,
                },
            }
            del session
        if not (
            parity["fp32"]["fixture"]["top1_equal"]
            and parity["int8"]["fixture"]["top1_equal"]
            and parity["fp32"]["dev"]["top1_equal"]
        ):
            raise ResearchTinyR2Error("ONNX export changed top-1")
        write_bytes_pair_atomic(
            fp32_path,
            fp32_temporary.read_bytes(),
            int8_path,
            int8_temporary.read_bytes(),
        )
    finally:
        # A leftover temporary never carries a final name; a failed cleanup must
        # not replace the error that is already propagating.
        for temporary in (fp32_temporary, int8_temporary):
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_r2_onnx_export",
        "status": STATUS,
        "model_name": MODEL_NAME,
        "checkpoint_sha256": v1.sha256_file(checkpoint),
        "parameter_count": parameter_count,
        "opset": 18,
        "artifacts": {
            label: {**_file_binding(path), "parity": parity[label]}
            for label, path in (("fp32", fp32_path), ("int8", int8_path))
        },
        "software": {
            "torch": torch.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": ort.__version__,
        },
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(report_path, _aggregate_json_bytes(report), create_parent=True)
    return report


def benchmark_onnx(
    model_path: Path,
    cache: Path,
    cache_manifest: Path,
    cost_gap: Path,
    cost_gap_manifest: Path,
    report_path: Path,
    *,
    warmup_runs: int,
    measured_runs: int,
) -> dict[str, Any]:
    """Measure Windows CPU batch-one latency and ORT dev quality."""
    import numpy as np

    if warmup_runs < 1 or measured_runs < 10_000:
        raise ResearchTinyR2Error("benchmark requires warmup and at least 10,000 runs")
    values = load_inputs(cache, cache_manifest, cost_gap, cost_gap_manifest)
    dev = {name: values[f"dev_{name}"] for name in INPUT_NAMES}
    # Feeds are views of in-memory arrays built before timing, so the clock
    # covers model work only.
    feeds = [
        {name: dev[name][index : index + 1] for name in INPUT_NAMES}
        for index in range(v1.DEV_COUNT)
    ]
    with _gpus_hidden():
        session = _cpu_session(model_path)
        for index in range(warmup_runs):
            session.run(["scores"], feeds[index % v1.DEV_COUNT])
        timings = []
        failures = 0
        for index in range(measured_runs):
            feed = feeds[index % v1.DEV_COUNT]
            before = time.perf_counter_ns()
            try:
                result = session.run(["scores"], feed)[0]
                elapsed_ns = time.perf_counter_ns() - before
                if result.shape != (1, v1.TOP_K) or not np.isfinite(result).all():
                    raise ResearchTinyR2Error("ORT returned an invalid score tensor")
            except Exception:
                failures += 1
            else:
                timings.append(elapsed_ns / 1_000_000)
        if failures or len(timings) != measured_runs:
            raise ResearchTinyR2Error("ORT benchmark contained failures")
        scores = [
            session.run(
                ["scores"], {name: dev[name][start : start + BATCH_SIZE] for name in INPUT_NAMES}
            )[0]
            for start in range(0, v1.DEV_COUNT, BATCH_SIZE)
        ]
        providers = session.get_providers()
    ordered = sorted(timings)

    def percentile(proportion: float) -> float:
        return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]

    quality = v1.ranking_metrics(np.concatenate(scores), values["dev_gold"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_r2_onnx_dev_benchmark",
        "status": STATUS,
        "model_name": MODEL_NAME,
        "model": _file_binding(model_path),
        "quality": _rounded(quality),
        "latency_ms": {
            "mean": round(statistics.fmean(timings), 6),
            "p50": round(percentile(0.50), 6),
            "p95": round(percentile(0.95), 6),
            "p99": round(percentile(0.99), 6),
            "max": round(max(timings), 6),
        },
        "contract": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "gpu_disabled": True,
            "provider": providers,
            "batch_size": 1,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "failure_count": failures,
            "timing_scope": TIMING_SCOPE,
            "final_holdout_used": False,
        },
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(report_path, _aggregate_json_bytes(report), create_parent=True)
    return report


def _read_report(path: Path, kind: str) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchTinyR2Error(f"invalid JSON report: {path.name}") from error
    if raw != v1.canonical_json_bytes(value):
        raise ResearchTinyR2Error(f"report is not canonical JSON plus LF: {path.name}")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("report_kind") != kind
        or value.get("status") != STATUS
        or value.get("raw_text_in_report") is not False
        or value.get("raw_stable_ids_in_report") is not False
    ):
        raise ResearchTinyR2Error(f"unexpected report contract: {path.name}")
    return raw, value


def check_experiment_adoption(experiment: Mapping[str, Any]) -> dict[str, int]:
    """Return the Issue #21 dev outcome of the adopted model, or fail closed.

    The experiment must have adopted this recipe, frozen this module's epoch
    count for this seed, kept the final holdout unused, and matched an
    independent recomputation.
    """
    key = f"{ADOPTED_RECIPE}-s{SEED}"
    try:
        adopted = experiment["decision"]["adopted"]
        epoch = experiment["selection"][key]["epoch"]
        dev = experiment["per_model"][key]["dev"]
        recomputed = experiment["independent_recomputation"]["matches"]
        outcome = {field: dev[field] for field in ("correct", "harm", "rescue")}
    except (KeyError, TypeError) as error:
        raise ResearchTinyR2Error("Issue #21 evidence is incomplete") from error
    if (
        experiment.get("issue") != ISSUE
        or experiment.get("final_holdout_used") is not False
        or adopted != ADOPTED_RECIPE
        or epoch != EPOCHS
        or recomputed is not True
    ):
        raise ResearchTinyR2Error("Issue #21 evidence does not adopt this recipe and epoch")
    if any(type(count) is not int or count < 0 for count in outcome.values()):
        raise ResearchTinyR2Error("Issue #21 dev outcome must be non-negative integer counts")
    return outcome


def publish_evidence(
    cache_manifest_path: Path,
    cost_gap_manifest_path: Path,
    experiment_path: Path,
    training_path: Path,
    export_path: Path,
    fp32_benchmark_path: Path,
    int8_benchmark_path: Path,
    manifest_path: Path,
    report_path: Path,
    *,
    base_git_sha: str,
    nvidia_driver: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind every revision-2 artifact by hash and record the fail-closed gates.

    Nothing is written unless every input passes; the model manifest and the
    decision report are then published together.
    """
    if len(base_git_sha) != 40 or any(char not in "0123456789abcdef" for char in base_git_sha):
        raise ResearchTinyR2Error("base Git SHA must be lowercase hexadecimal")
    if not nvidia_driver or len(nvidia_driver) > 32:
        raise ResearchTinyR2Error("NVIDIA driver identity is invalid")
    try:
        model_manifest, decision_report = _evidence_documents(
            cache_manifest_path,
            cost_gap_manifest_path,
            experiment_path,
            training_path,
            export_path,
            fp32_benchmark_path,
            int8_benchmark_path,
            manifest_path.name,
            base_git_sha=base_git_sha,
            nvidia_driver=nvidia_driver,
        )
    except (AttributeError, KeyError, TypeError) as error:
        # The inputs are parsed JSON, so these mean a field has the wrong shape.
        raise ResearchTinyR2Error(
            f"revision-2 evidence is malformed ({type(error).__name__})"
        ) from error
    manifest_bytes = _aggregate_json_bytes(model_manifest)
    report_bytes = _aggregate_json_bytes(decision_report)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_bytes_pair_atomic(manifest_path, manifest_bytes, report_path, report_bytes)
    return model_manifest, decision_report


def _evidence_documents(
    cache_manifest_path: Path,
    cost_gap_manifest_path: Path,
    experiment_path: Path,
    training_path: Path,
    export_path: Path,
    fp32_benchmark_path: Path,
    int8_benchmark_path: Path,
    manifest_name: str,
    *,
    base_git_sha: str,
    nvidia_driver: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate every input report and build the manifest and decision report."""
    cache_raw = cache_manifest_path.read_bytes()
    cache_manifest = json.loads(cache_raw)
    gap_raw = cost_gap_manifest_path.read_bytes()
    gap_manifest = json.loads(gap_raw)
    if cache_raw != v1.canonical_json_bytes(cache_manifest) or gap_raw != v1.canonical_json_bytes(
        gap_manifest
    ):
        raise ResearchTinyR2Error("input manifests are not canonical JSON plus LF")
    if (
        cache_manifest.get("status") != STATUS
        or cache_manifest.get("source", {}).get("sha256") != v1.DATASET_CONTENT_SHA256
        or cache_manifest.get("splits") != {"dev": v1.DEV_COUNT, "train": v1.TRAIN_COUNT}
        or cache_manifest.get("final_holdout", {}).get("rows_in_cache") != 0
        or cache_manifest.get("final_holdout", {}).get("used_for_training_or_selection") is not False
        or gap_manifest.get("manifest_kind") != COST_GAP_MANIFEST_KIND
        or gap_manifest.get("status") != STATUS
        or gap_manifest.get("v1_numeric_cache", {}).get("sha256")
        != cache_manifest.get("cache", {}).get("sha256")
        or gap_manifest.get("v1_numeric_cache", {}).get("manifest_sha256")
        != hashlib.sha256(cache_raw).hexdigest()
        or gap_manifest.get("final_holdout", {}).get("rows_in_sidecar") != 0
        or gap_manifest.get("final_holdout", {}).get("used_for_training_or_selection") is not False
    ):
        raise ResearchTinyR2Error("input evidence violates the fixed split contract")
    experiment_raw, experiment = _read_report(experiment_path, EXPERIMENT_REPORT_KIND)
    evaluated_dev = check_experiment_adoption(experiment)
    _, training = _read_report(training_path, "sakura_rerank_tiny_r2_training")
    _, export = _read_report(export_path, "sakura_rerank_tiny_r2_onnx_export")
    _, fp32 = _read_report(fp32_benchmark_path, "sakura_rerank_tiny_r2_onnx_dev_benchmark")
    _, int8 = _read_report(int8_benchmark_path, "sakura_rerank_tiny_r2_onnx_dev_benchmark")
    single_dev = training.get("dev_single_evaluation", {})
    environment = _require_shape(training.get("environment"), _ENVIRONMENT_SHAPE, "environment")
    checkpoint = _require_shape(training.get("checkpoint"), _BINDING_SHAPE, "checkpoint")
    artifacts = _require_shape(export.get("artifacts"), _EXPORT_ARTIFACTS_SHAPE, "artifacts")
    for label, benchmark in (("fp32", fp32), ("int8", int8)):
        _require_shape(benchmark.get("model"), _BINDING_SHAPE, f"{label}.model")
        _require_shape(benchmark.get("quality"), _QUALITY_SHAPE, f"{label}.quality")
        _require_shape(benchmark.get("latency_ms"), _LATENCY_SHAPE, f"{label}.latency_ms")
        _require_shape(benchmark.get("contract"), _BENCHMARK_CONTRACT_SHAPE, f"{label}.contract")
    if (
        any(report.get("model_name") != MODEL_NAME for report in (training, export, fp32, int8))
        or training.get("gate_a_status") != v1.EXPECTED_GATE_STATUS
        or training.get("seed") != SEED
        or training.get("data", {}).get("final_holdout_used") is not False
        or training.get("data", {}).get("cache_manifest_sha256")
        != hashlib.sha256(cache_raw).hexdigest()
        or training.get("data", {}).get("cost_gap_manifest_sha256")
        != hashlib.sha256(gap_raw).hexdigest()
        or not _same_json(training.get("recipe"), _recipe())
        or not _same_json(training.get("hyperparameters"), _hyperparameters())
        or checkpoint["sha256"] != export.get("checkpoint_sha256")
        or training.get("parameter_count") != export.get("parameter_count")
        or (
            single_dev.get("top1_correct"),
            single_dev.get("harm_count"),
            single_dev.get("rescue_count"),
        )
        != (evaluated_dev["correct"], evaluated_dev["harm"], evaluated_dev["rescue"])
    ):
        raise ResearchTinyR2Error("training evidence does not reproduce the adopted model")
    if (
        artifacts["fp32"]["parity"]["dev"]["top1_equal"] is not True
        or fp32.get("model", {}).get("sha256") != artifacts["fp32"]["sha256"]
        or int8.get("model", {}).get("sha256") != artifacts["int8"]["sha256"]
    ):
        raise ResearchTinyR2Error("export/benchmark evidence linkage is inconsistent")
    for benchmark in (fp32, int8):
        contract = benchmark["contract"]
        if (
            contract.get("gpu_disabled") is not True
            or contract.get("provider") != ["CPUExecutionProvider"]
            or contract.get("batch_size") != 1
            or contract.get("ort_intra_op_threads") != 1
            or contract.get("ort_inter_op_threads") != 1
            or contract.get("warmup_runs", 0) < 1
            or contract.get("measured_runs", 0) < 10_000
            or contract.get("failure_count") != 0
            or contract.get("timing_scope") != TIMING_SCOPE
            or contract.get("final_holdout_used") is not False
        ):
            raise ResearchTinyR2Error("benchmark violates the fixed Windows CPU contract")
    source_bindings = {
        label: _file_binding(path)
        for label, path in (
            ("numeric_cache_manifest", cache_manifest_path),
            ("cost_gap_manifest", cost_gap_manifest_path),
            ("issue_21_experiment_report", experiment_path),
            ("training_report", training_path),
            ("export_report", export_path),
            ("fp32_benchmark_report", fp32_benchmark_path),
            ("int8_benchmark_report", int8_benchmark_path),
        )
    }
    model_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": "sakura_rerank_tiny_r2_model",
        "status": STATUS,
        "model_name": MODEL_NAME,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "parameter_count": training["parameter_count"],
        "architecture": {
            "kind": "shared_character_embedding_unidirectional_gru_listwise_residual",
            "vocab_size": v1.VOCAB_SIZE,
            "embedding_dim": v1.EMBEDDING_DIM,
            "hidden_dim": v1.HIDDEN_DIM,
            "gru_layers": v1.GRU_LAYERS,
            "top_k": v1.TOP_K,
            "context_length": v1.CONTEXT_LENGTH,
            "reading_length": v1.READING_LENGTH,
            "surface_length": v1.SURFACE_LENGTH,
            "feature_dim": FEATURE_DIM,
            "character_hash": "unicode_scalar_multiplicative_modulo_v1",
        },
        "recipe": _recipe(),
        "data": {
            "dataset_content_sha256": v1.DATASET_CONTENT_SHA256,
            "train_count": v1.TRAIN_COUNT,
            "dev_count": v1.DEV_COUNT,
            "final_holdout_used": False,
            "gate_a_status": v1.EXPECTED_GATE_STATUS,
        },
        "implementation": {
            "file": "src/sakura_rerank/research_tiny_r2.py",
            "sha256": v1.sha256_file(Path(__file__)),
            "v1_dependency": {
                "file": "src/sakura_rerank/research_tiny.py",
                "sha256": v1.sha256_file(Path(v1.__file__)),
            },
            "base_git_sha": base_git_sha,
            "trained_from_uncommitted_implementation": True,
        },
        "training": {
            "seed": SEED,
            "epochs": EPOCHS,
            "hyperparameters": _hyperparameters(),
            "environment": {**environment, "nvidia_driver": nvidia_driver},
            "checkpoint": checkpoint,
        },
        "exports": artifacts,
        "source_reports": source_bindings,
        "license_status": "not_selected_no_distribution_authorized",
        "distribution_authorized": False,
        "raw_text_in_manifest": False,
        "raw_stable_ids_in_manifest": False,
    }
    manifest_bytes = _aggregate_json_bytes(model_manifest)
    fp_quality = fp32["quality"]
    int8_quality = int8["quality"]
    if (
        fp_quality["record_count"] != v1.DEV_COUNT
        or int8_quality["record_count"] != v1.DEV_COUNT
        or not 0 < fp_quality["baseline_top1_correct"] < v1.DEV_COUNT
    ):
        # This also keeps both rate denominators positive.
        raise ResearchTinyR2Error("dev quality counts violate the fixed contract")
    baseline_errors = fp_quality["record_count"] - fp_quality["baseline_top1_correct"]
    fp_errors = fp_quality["record_count"] - fp_quality["top1_correct"]
    relative_error_reduction = (baseline_errors - fp_errors) / baseline_errors
    harm_rate = fp_quality["harm_count"] / fp_quality["baseline_top1_correct"]
    int8_loss_pp = (fp_quality["top1_accuracy"] - int8_quality["top1_accuracy"]) * 100
    checks = {
        "dev_relative_error_reduction_at_least_10_percent": relative_error_reduction >= 0.10,
        "dev_harm_rate_at_most_0_25_percent": harm_rate <= 0.0025,
        "dev_rescue_harm_ratio_at_least_3": (
            fp_quality["rescue_harm_ratio"] is not None and fp_quality["rescue_harm_ratio"] >= 3
        ),
        "fp32_model_p95_at_most_2_ms": fp32["latency_ms"]["p95"] <= 2,
        "fp32_model_p99_at_most_5_ms": fp32["latency_ms"]["p99"] <= 5,
        "fp32_payload_at_most_8_mib": fp32["model"]["bytes"] <= 8 * 1024 * 1024,
        "int8_top1_loss_at_most_0_2_percentage_points": int8_loss_pp <= 0.2,
        "production_worker_roundtrip_measured": False,
        "production_peak_memory_measured": False,
    }
    unmet = sorted(name for name, passed in checks.items() if not passed)
    decision_report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_r2_research_decision",
        "status": STATUS,
        "model_name": MODEL_NAME,
        "model_manifest": {
            "file": manifest_name,
            "bytes": len(manifest_bytes),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "issue_21_adoption": {
            "experiment_report_sha256": hashlib.sha256(experiment_raw).hexdigest(),
            "adopted_recipe": ADOPTED_RECIPE,
            "seed": SEED,
            "epochs": EPOCHS,
            "pytorch_dev_outcome_reproduced": True,
        },
        "quality_dev_only": {
            "fp32": fp_quality,
            "int8": int8_quality,
            "relative_error_reduction": round(relative_error_reduction, 10),
            "baseline_correct_harm_rate": round(harm_rate, 10),
            "int8_top1_loss_percentage_points": round(int8_loss_pp, 10),
        },
        "windows_cpu_batch_one": {
            "fp32": {"model": fp32["model"], "latency_ms": fp32["latency_ms"]},
            "int8": {"model": int8["model"], "latency_ms": int8["latency_ms"]},
            "contract": fp32["contract"],
        },
        "gates": {
            "gate_a_pass": False,
            "gate_b_pass": False,
            "gate_c_pass": False,
            "checks": checks,
            "unmet_checks": unmet,
            "reason": (
                "Gate A already failed and dev is not the frozen final holdout, so no "
                "production claim is permitted regardless of the dev checks."
            ),
        },
        "final_holdout_used": False,
        "production_change_authorized": False,
        "artifact_distribution_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    return model_manifest, decision_report


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--cache-manifest", type=Path, required=True)
    parser.add_argument("--cost-gap", type=Path, required=True)
    parser.add_argument("--cost-gap-manifest", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-cost-gap")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--cache", type=Path, required=True)
    prepare.add_argument("--cache-manifest", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    train = commands.add_parser("train")
    train.add_argument("checkpoint", type=Path)
    _add_inputs(train)
    train.add_argument("--report", type=Path, required=True)
    export = commands.add_parser("export")
    export.add_argument("checkpoint", type=Path)
    export.add_argument("fp32", type=Path)
    export.add_argument("int8", type=Path)
    _add_inputs(export)
    export.add_argument("--report", type=Path, required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("model", type=Path)
    _add_inputs(benchmark)
    benchmark.add_argument("--report", type=Path, required=True)
    benchmark.add_argument("--warmup-runs", type=int, default=100)
    benchmark.add_argument("--measured-runs", type=int, default=10_000)
    evidence = commands.add_parser("publish-evidence")
    evidence.add_argument("--cache-manifest", type=Path, required=True)
    evidence.add_argument("--cost-gap-manifest", type=Path, required=True)
    evidence.add_argument("--experiment-report", type=Path, required=True)
    evidence.add_argument("--training-report", type=Path, required=True)
    evidence.add_argument("--export-report", type=Path, required=True)
    evidence.add_argument("--fp32-benchmark", type=Path, required=True)
    evidence.add_argument("--int8-benchmark", type=Path, required=True)
    evidence.add_argument("--manifest", type=Path, required=True)
    evidence.add_argument("--report", type=Path, required=True)
    evidence.add_argument("--base-git-sha", required=True)
    evidence.add_argument("--nvidia-driver", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare-cost-gap":
            prepare_cost_gap(
                arguments.source,
                arguments.cache,
                arguments.cache_manifest,
                arguments.output,
                arguments.manifest,
            )
            output = arguments.output
        elif arguments.command == "train":
            train_model(
                arguments.cache,
                arguments.cache_manifest,
                arguments.cost_gap,
                arguments.cost_gap_manifest,
                arguments.checkpoint,
                arguments.report,
            )
            output = arguments.checkpoint
        elif arguments.command == "export":
            export_onnx(
                arguments.checkpoint,
                arguments.cache,
                arguments.cache_manifest,
                arguments.cost_gap,
                arguments.cost_gap_manifest,
                arguments.fp32,
                arguments.int8,
                arguments.report,
            )
            output = arguments.int8
        elif arguments.command == "benchmark":
            benchmark_onnx(
                arguments.model,
                arguments.cache,
                arguments.cache_manifest,
                arguments.cost_gap,
                arguments.cost_gap_manifest,
                arguments.report,
                warmup_runs=arguments.warmup_runs,
                measured_runs=arguments.measured_runs,
            )
            output = arguments.report
        else:
            publish_evidence(
                arguments.cache_manifest,
                arguments.cost_gap_manifest,
                arguments.experiment_report,
                arguments.training_report,
                arguments.export_report,
                arguments.fp32_benchmark,
                arguments.int8_benchmark,
                arguments.manifest,
                arguments.report,
                base_git_sha=arguments.base_git_sha,
                nvidia_driver=arguments.nvidia_driver,
            )
            output = arguments.report
    except (v1.ResearchTinyError, OSError, ValueError, KeyError) as error:
        print(f"research tiny r2 failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
