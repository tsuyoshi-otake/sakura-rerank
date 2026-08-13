"""Research-only Sakura-Rerank-Tiny-v1 training and ONNX export.

This lane is deliberately unable to claim Gate A/B or production readiness.
It consumes only train/dev rows from the frozen v5 container and records every
artifact by hash.  The final holdout is never placed in the numeric cache.
"""

from __future__ import annotations

import argparse
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
from typing import Any, Iterable, Mapping

from sakura_rerank.atomic_io import write_bytes_atomic, write_bytes_pair_atomic
from sakura_rerank.data.contracts import validate_record


SCHEMA_VERSION = 1
MODEL_NAME = "Sakura-Rerank-Tiny-v1-research-prototype"
MODEL_CONTRACT_VERSION = 1
DATASET_CONTENT_SHA256 = "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"
TRAIN_COUNT = 12_516
DEV_COUNT = 1_788
TOP_K = 6
CONTEXT_LENGTH = 64
READING_LENGTH = 32
SURFACE_LENGTH = 32
VOCAB_SIZE = 13_312
EMBEDDING_DIM = 128
HIDDEN_DIM = 128
GRU_LAYERS = 1
FEATURE_DIM = 6
SEED = 20_260_814
EXPECTED_GATE_STATUS = "gate_a_failed"


class ResearchTinyError(RuntimeError):
    """A fixed research-model contract was violated."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        .encode("utf-8")
        + b"\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def character_ids(text: str, limit: int) -> tuple[list[int], int]:
    chars = list(text[:limit])
    # Fixed collision-bounded character hashing avoids a mutable vocabulary
    # artifact. Zero remains the padding ID.
    values = [((ord(char) * 2_654_435_761) % (VOCAB_SIZE - 1)) + 1 for char in chars]
    return values + [0] * (limit - len(values)), len(values)


def _common_prefix_ratio(left: str, right: str) -> float:
    matched = 0
    for a, b in zip(left, right):
        if a != b:
            break
        matched += 1
    return matched / max(len(left), len(right), 1)


def candidate_features(reading: str, candidates: list[Mapping[str, Any]]) -> list[list[float]]:
    costs = [float(candidate["local_cost"]) for candidate in candidates]
    minimum = min(costs)
    span = max(max(costs) - minimum, 1.0)
    features = []
    for index, candidate in enumerate(candidates):
        surface = str(candidate["surface"])
        category = str(candidate["source_category"])
        features.append(
            [
                -(costs[index] - minimum) / span,
                -index / max(TOP_K - 1, 1),
                min(len(candidate["segments"]), 8) / 8.0,
                len(surface) / SURFACE_LENGTH,
                _common_prefix_ratio(reading, surface),
                1.0 if category == "system_dictionary" else 0.0,
            ]
        )
    return features


def build_model() -> Any:
    import torch
    from torch import nn

    class SakuraRerankTiny(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = nn.Embedding(VOCAB_SIZE, EMBEDDING_DIM, padding_idx=0)
            self.encoder = nn.GRU(
                EMBEDDING_DIM,
                HIDDEN_DIM,
                num_layers=GRU_LAYERS,
                batch_first=True,
            )
            self.scorer = nn.Sequential(
                nn.Linear(HIDDEN_DIM * 3 + FEATURE_DIM, HIDDEN_DIM),
                nn.SiLU(),
                nn.Linear(HIDDEN_DIM, 64),
                nn.SiLU(),
                nn.Linear(64, 1),
            )

        def encode(self, ids: Any, lengths: Any) -> Any:
            output, _ = self.encoder(self.embedding(ids))
            index = torch.clamp(lengths - 1, min=0)
            gathered = output.gather(
                1, index.view(-1, 1, 1).expand(-1, 1, HIDDEN_DIM)
            ).squeeze(1)
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
                candidate_ids.reshape(batch * TOP_K, SURFACE_LENGTH),
                candidate_lengths.reshape(batch * TOP_K),
            ).reshape(batch, TOP_K, HIDDEN_DIM)
            repeated_context = context.unsqueeze(1).expand(-1, TOP_K, -1)
            repeated_reading = reading.unsqueeze(1).expand(-1, TOP_K, -1)
            joined = torch.cat(
                (repeated_context, repeated_reading, candidates, features), dim=2
            )
            residual = self.scorer(joined).squeeze(2)
            scores = features[:, :, 0] * 2.0 + residual
            return scores.masked_fill(~candidate_mask, -10_000.0)

    return SakuraRerankTiny()


def model_parameter_count(model: Any) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def _empty_split_arrays(count: int) -> dict[str, Any]:
    import numpy as np

    return {
        "context_ids": np.zeros((count, CONTEXT_LENGTH), dtype=np.int64),
        "context_lengths": np.zeros(count, dtype=np.int64),
        "reading_ids": np.zeros((count, READING_LENGTH), dtype=np.int64),
        "reading_lengths": np.zeros(count, dtype=np.int64),
        "candidate_ids": np.zeros(
            (count, TOP_K, SURFACE_LENGTH), dtype=np.int64
        ),
        "candidate_lengths": np.zeros((count, TOP_K), dtype=np.int64),
        "features": np.zeros((count, TOP_K, FEATURE_DIM), dtype=np.float32),
        "candidate_mask": np.zeros((count, TOP_K), dtype=np.bool_),
        "gold": np.full(count, -1, dtype=np.int64),
    }


def prepare_cache(source: Path, output: Path, manifest_path: Path) -> dict[str, Any]:
    import numpy as np

    expected = {"train": TRAIN_COUNT, "dev": DEV_COUNT}
    arrays = {split: _empty_split_arrays(count) for split, count in expected.items()}
    offsets = {"train": 0, "dev": 0}
    holdout_seen = 0
    with source.open("r", encoding="utf-8", newline="") as rows:
        for line in rows:
            try:
                raw_record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ResearchTinyError("dataset contains invalid JSON") from error
            split = raw_record.get("split")
            if split == "final-holdout":
                holdout_seen += 1
                continue
            if split not in arrays:
                raise ResearchTinyError("dataset contains an unsupported split")
            record = validate_record(raw_record)
            if record["is_fixture"] or not record["training_eligible"]:
                raise ResearchTinyError("train/dev cache accepts eligible non-fixture rows only")
            index = offsets[split]
            if index >= expected[split]:
                raise ResearchTinyError("split exceeds its pinned record count")
            target = arrays[split]
            context_ids, context_length = character_ids(
                record["session"]["left_context"], CONTEXT_LENGTH
            )
            reading_ids, reading_length = character_ids(record["reading"], READING_LENGTH)
            candidates = record["candidate_snapshots"]["production_top6"]["candidates"]
            if not 2 <= len(candidates) <= TOP_K:
                raise ResearchTinyError("candidate count outside production top-6 contract")
            target["context_ids"][index] = context_ids
            target["context_lengths"][index] = context_length
            target["reading_ids"][index] = reading_ids
            target["reading_lengths"][index] = reading_length
            target["features"][index, : len(candidates)] = candidate_features(
                record["reading"], candidates
            )
            target["candidate_mask"][index, : len(candidates)] = True
            for candidate_index, candidate in enumerate(candidates):
                ids, length = character_ids(candidate["surface"], SURFACE_LENGTH)
                target["candidate_ids"][index, candidate_index] = ids
                target["candidate_lengths"][index, candidate_index] = length
            gold = int(record["gold_index"])
            target["gold"][index] = gold if gold < len(candidates) else -1
            offsets[split] += 1
    if offsets != expected or holdout_seen != 3_576:
        raise ResearchTinyError("frozen split counts differ from the pinned contract")
    payload = {
        f"{split}_{name}": value
        for split, split_arrays in arrays.items()
        for name, value in split_arrays.items()
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp.npz")
    np.savez(temporary, **payload)
    os.replace(temporary, output)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": "sakura_rerank_tiny_numeric_cache",
        "status": "research_only_gate_a_failed",
        "source": {
            "file": source.name,
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
            "dataset_content_sha256": DATASET_CONTENT_SHA256,
        },
        "cache": {
            "file": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        },
        "splits": expected,
        "final_holdout": {
            "source_rows_seen_and_discarded": holdout_seen,
            "rows_in_cache": 0,
            "used_for_training_or_selection": False,
        },
        "shape": {
            "top_k": TOP_K,
            "context_length": CONTEXT_LENGTH,
            "reading_length": READING_LENGTH,
            "surface_length": SURFACE_LENGTH,
            "feature_dim": FEATURE_DIM,
            "vocab_size": VOCAB_SIZE,
            "character_hash": "unicode_scalar_multiplicative_modulo_v1",
        },
        "raw_text_in_manifest": False,
        "raw_stable_ids_in_manifest": False,
    }
    write_bytes_atomic(manifest_path, canonical_json_bytes(manifest), create_parent=True)
    return manifest


def _load_cache(cache: Path, manifest_path: Path) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    if raw_manifest != canonical_json_bytes(manifest):
        raise ResearchTinyError("cache manifest is not canonical JSON plus LF")
    if (
        manifest.get("manifest_kind") != "sakura_rerank_tiny_numeric_cache"
        or manifest.get("splits") != {"dev": DEV_COUNT, "train": TRAIN_COUNT}
        or manifest.get("final_holdout", {}).get("rows_in_cache") != 0
        or manifest.get("final_holdout", {}).get("used_for_training_or_selection") is not False
        or manifest.get("cache", {}).get("sha256") != sha256_file(cache)
        or manifest.get("shape", {}).get("vocab_size") != VOCAB_SIZE
        or manifest.get("shape", {}).get("character_hash")
        != "unicode_scalar_multiplicative_modulo_v1"
    ):
        raise ResearchTinyError("numeric cache manifest violates the fixed contract")
    arrays = np.load(cache, allow_pickle=False)
    expected_names = {
        f"{split}_{name}"
        for split in ("train", "dev")
        for name in (
            "context_ids",
            "context_lengths",
            "reading_ids",
            "reading_lengths",
            "candidate_ids",
            "candidate_lengths",
            "features",
            "candidate_mask",
            "gold",
        )
    }
    if set(arrays.files) != expected_names:
        raise ResearchTinyError("numeric cache fields differ from the fixed contract")
    return arrays, manifest


def _batch(arrays: Any, split: str, indices: Any, device: Any) -> tuple[Any, ...]:
    import torch

    names = (
        "context_ids",
        "context_lengths",
        "reading_ids",
        "reading_lengths",
        "candidate_ids",
        "candidate_lengths",
        "features",
        "candidate_mask",
        "gold",
    )
    return tuple(
        torch.from_numpy(arrays[f"{split}_{name}"][indices]).to(device)
        for name in names
    )


def ranking_metrics(scores: Any, gold: Any) -> dict[str, float | int | None]:
    import numpy as np

    scores = np.asarray(scores)
    gold = np.asarray(gold)
    count = len(gold)
    prediction = scores.argmax(axis=1)
    oracle = gold >= 0
    correct = oracle & (prediction == gold)
    baseline_correct = gold == 0
    reciprocal = np.zeros(count, dtype=np.float64)
    ndcg = np.zeros(count, dtype=np.float64)
    for index in np.flatnonzero(oracle):
        order = np.argsort(-scores[index], kind="stable")
        rank = int(np.flatnonzero(order == gold[index])[0])
        reciprocal[index] = 1.0 / (rank + 1)
        ndcg[index] = 1.0 / math.log2(rank + 2)
    rescue = int(np.sum(~baseline_correct & correct))
    harm = int(np.sum(baseline_correct & ~correct))
    return {
        "record_count": count,
        "oracle_count": int(np.sum(oracle)),
        "top1_correct": int(np.sum(correct)),
        "top1_accuracy": float(np.mean(correct)),
        "mrr": float(np.mean(reciprocal)),
        "ndcg_at_6": float(np.mean(ndcg)),
        "baseline_top1_correct": int(np.sum(baseline_correct)),
        "baseline_top1_accuracy": float(np.mean(baseline_correct)),
        "rescue_count": rescue,
        "harm_count": harm,
        "rescue_harm_ratio": float(rescue / harm) if harm else None,
    }


def _evaluate(model: Any, arrays: Any, split: str, device: Any, batch_size: int) -> dict[str, Any]:
    import numpy as np
    import torch

    model.eval()
    all_scores = []
    all_gold = []
    count = len(arrays[f"{split}_gold"])
    with torch.inference_mode():
        for start in range(0, count, batch_size):
            indices = np.arange(start, min(start + batch_size, count))
            batch = _batch(arrays, split, indices, device)
            scores = model(*batch[:-1])
            all_scores.append(scores.float().cpu().numpy())
            all_gold.append(batch[-1].cpu().numpy())
    return ranking_metrics(np.concatenate(all_scores), np.concatenate(all_gold))


def train_model(
    cache: Path,
    cache_manifest: Path,
    checkpoint: Path,
    report_path: Path,
    *,
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> dict[str, Any]:
    if epochs < 1 or batch_size < 1 or learning_rate <= 0:
        raise ResearchTinyError("training hyperparameters are invalid")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import numpy as np
    import torch
    from torch.nn import functional as functional

    if not torch.cuda.is_available():
        raise ResearchTinyError("CUDA is required for the approved training run")
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.use_deterministic_algorithms(True)
    arrays, manifest = _load_cache(cache, cache_manifest)
    device = torch.device("cuda:0")
    model = build_model().to(device)
    parameter_count = model_parameter_count(model)
    if not 1_800_000 <= parameter_count <= 2_100_000:
        raise ResearchTinyError("model is outside the approximately 2M parameter budget")
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    train_gold = arrays["train_gold"]
    eligible_indices = np.flatnonzero(train_gold >= 0)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    history = []
    best_key: tuple[float, int, float] | None = None
    best_epoch = 0
    started = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        order = eligible_indices[
            torch.randperm(len(eligible_indices), generator=generator).numpy()
        ]
        losses = []
        for start in range(0, len(order), batch_size):
            indices = order[start : start + batch_size]
            batch = _batch(arrays, "train", indices, device)
            optimizer.zero_grad(set_to_none=True)
            scores = model(*batch[:-1])
            loss = functional.cross_entropy(scores, batch[-1])
            if not torch.isfinite(loss):
                raise ResearchTinyError("training produced a non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        dev = _evaluate(model, arrays, "dev", device, batch_size)
        epoch_report = {
            "epoch": epoch,
            "train_loss": round(statistics.fmean(losses), 8),
            "dev": {key: round(value, 10) if isinstance(value, float) else value for key, value in dev.items()},
        }
        history.append(epoch_report)
        key = (float(dev["top1_accuracy"]), -int(dev["harm_count"]), float(dev["mrr"]))
        if best_key is None or key > best_key:
            best_key = key
            best_epoch = epoch
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint.with_name(checkpoint.name + ".tmp")
            torch.save(
                {
                    "schema_version": SCHEMA_VERSION,
                    "model_contract_version": MODEL_CONTRACT_VERSION,
                    "model_name": MODEL_NAME,
                    "parameter_count": parameter_count,
                    "epoch": epoch,
                    "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
                },
                temporary,
            )
            os.replace(temporary, checkpoint)
        print(json.dumps(epoch_report, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_training",
        "status": "research_only_gate_a_failed",
        "gate_a_status": EXPECTED_GATE_STATUS,
        "model_name": MODEL_NAME,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "parameter_count": parameter_count,
        "seed": SEED,
        "data": {
            "cache_manifest_sha256": sha256_file(cache_manifest),
            "cache_sha256": sha256_file(cache),
            "train_count": TRAIN_COUNT,
            "dev_count": DEV_COUNT,
            "final_holdout_used": False,
        },
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "optimizer": "AdamW",
            "weight_decay": 0.01,
            "gradient_clip_norm": 1.0,
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
            "deterministic_algorithms": True,
        },
        "best_epoch": best_epoch,
        "best_dev": history[best_epoch - 1]["dev"],
        "history": history,
        "checkpoint": {
            "file": checkpoint.name,
            "bytes": checkpoint.stat().st_size,
            "sha256": sha256_file(checkpoint),
        },
        "wall_time_seconds": round(elapsed, 6),
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(report_path, canonical_json_bytes(report), create_parent=True)
    arrays.close()
    return report


def _example_inputs(batch_size: int = 2) -> tuple[Any, ...]:
    import torch

    context_ids = torch.zeros((batch_size, CONTEXT_LENGTH), dtype=torch.int64)
    context_ids[:, :3] = torch.tensor([101, 202, 303])
    reading_ids = torch.zeros((batch_size, READING_LENGTH), dtype=torch.int64)
    reading_ids[:, :2] = torch.tensor([404, 505])
    candidate_ids = torch.zeros(
        (batch_size, TOP_K, SURFACE_LENGTH), dtype=torch.int64
    )
    features = torch.zeros((batch_size, TOP_K, FEATURE_DIM), dtype=torch.float32)
    for candidate in range(TOP_K):
        candidate_ids[:, candidate, :2] = torch.tensor(
            [600 + candidate, 700 + candidate]
        )
        features[:, candidate, 0] = -candidate / (TOP_K - 1)
        features[:, candidate, 1] = -candidate / (TOP_K - 1)
    return (
        context_ids,
        torch.full((batch_size,), 3, dtype=torch.int64),
        reading_ids,
        torch.full((batch_size,), 2, dtype=torch.int64),
        candidate_ids,
        torch.full((batch_size, TOP_K), 2, dtype=torch.int64),
        features,
        torch.ones((batch_size, TOP_K), dtype=torch.bool),
    )


def export_onnx(
    checkpoint: Path,
    fp32_path: Path,
    int8_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (
        payload.get("model_name") != MODEL_NAME
        or payload.get("model_contract_version") != MODEL_CONTRACT_VERSION
    ):
        raise ResearchTinyError("checkpoint identity differs from the model contract")
    model = build_model()
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    fp32_path.parent.mkdir(parents=True, exist_ok=True)
    # ONNX's GRU exporter requires the trace batch to be one when the batch
    # dimension is dynamic and no explicit initial state is exposed.
    inputs = _example_inputs(1)
    input_names = [
        "context_ids",
        "context_lengths",
        "reading_ids",
        "reading_lengths",
        "candidate_ids",
        "candidate_lengths",
        "features",
        "candidate_mask",
    ]
    dynamic_axes = {name: {0: "batch"} for name in input_names}
    dynamic_axes["scores"] = {0: "batch"}
    torch.onnx.export(
        model,
        inputs,
        fp32_path,
        input_names=input_names,
        output_names=["scores"],
        dynamic_axes=dynamic_axes,
        opset_version=18,
        do_constant_folding=True,
        dynamo=False,
    )
    onnx.checker.check_model(onnx.load(fp32_path))
    quantize_dynamic(
        fp32_path,
        int8_path,
        weight_type=QuantType.QInt8,
        per_channel=True,
        reduce_range=False,
    )
    onnx.checker.check_model(onnx.load(int8_path))
    expected = model(*inputs).detach().numpy()
    feed = {name: value.numpy() for name, value in zip(input_names, inputs, strict=True)}
    parity = {}
    for label, path in (("fp32", fp32_path), ("int8", int8_path)):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        actual = session.run(["scores"], feed)[0]
        parity[label] = {
            "max_absolute_error": float(np.max(np.abs(expected - actual))),
            "top1_equal": bool(np.array_equal(expected.argmax(1), actual.argmax(1))),
        }
    if not parity["fp32"]["top1_equal"] or not parity["int8"]["top1_equal"]:
        raise ResearchTinyError("ONNX export changed fixture top-1")
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_onnx_export",
        "status": "research_only_gate_a_failed",
        "model_name": MODEL_NAME,
        "checkpoint_sha256": sha256_file(checkpoint),
        "parameter_count": payload["parameter_count"],
        "opset": 18,
        "artifacts": {
            label: {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "parity": parity[label],
            }
            for label, path in (("fp32", fp32_path), ("int8", int8_path))
        },
        "software": {
            "torch": torch.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": ort.__version__,
        },
        "raw_text_in_report": False,
    }
    write_bytes_atomic(report_path, canonical_json_bytes(report), create_parent=True)
    return report


def benchmark_onnx(
    model_path: Path,
    cache: Path,
    cache_manifest: Path,
    report_path: Path,
    *,
    warmup_runs: int,
    measured_runs: int,
) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as ort

    if warmup_runs < 1 or measured_runs < 10_000:
        raise ResearchTinyError("benchmark requires warmup and at least 10,000 runs")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    arrays, _ = _load_cache(cache, cache_manifest)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    names = (
        "context_ids",
        "context_lengths",
        "reading_ids",
        "reading_lengths",
        "candidate_ids",
        "candidate_lengths",
        "features",
        "candidate_mask",
    )
    def feed(index: int) -> dict[str, Any]:
        return {name: arrays[f"dev_{name}"][index : index + 1] for name in names}
    for index in range(warmup_runs):
        session.run(["scores"], feed(index % DEV_COUNT))
    timings = []
    failures = 0
    for index in range(measured_runs):
        before = time.perf_counter_ns()
        try:
            result = session.run(["scores"], feed(index % DEV_COUNT))[0]
            if result.shape != (1, TOP_K) or not np.isfinite(result).all():
                raise ResearchTinyError("ORT returned an invalid score tensor")
        except Exception:
            failures += 1
        else:
            timings.append((time.perf_counter_ns() - before) / 1_000_000)
    if failures or len(timings) != measured_runs:
        raise ResearchTinyError("ORT benchmark contained failures")
    ordered = sorted(timings)
    def percentile(proportion: float) -> float:
        return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]
    scores = []
    for start in range(0, DEV_COUNT, 256):
        batch_feed = {
            name: arrays[f"dev_{name}"][start : min(start + 256, DEV_COUNT)]
            for name in names
        }
        scores.append(session.run(["scores"], batch_feed)[0])
    quality = ranking_metrics(np.concatenate(scores), arrays["dev_gold"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_onnx_dev_benchmark",
        "status": "research_only_gate_a_failed",
        "model_name": MODEL_NAME,
        "model": {
            "file": model_path.name,
            "bytes": model_path.stat().st_size,
            "sha256": sha256_file(model_path),
        },
        "quality": {
            key: round(value, 10) if isinstance(value, float) else value
            for key, value in quality.items()
        },
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
            "provider": session.get_providers(),
            "batch_size": 1,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "failure_count": failures,
            "final_holdout_used": False,
        },
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(report_path, canonical_json_bytes(report), create_parent=True)
    arrays.close()
    return report


def _read_canonical_report(path: Path, kind: str) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchTinyError(f"invalid JSON report: {path}") from error
    if raw != canonical_json_bytes(value):
        raise ResearchTinyError(f"report is not canonical JSON plus LF: {path}")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("report_kind") != kind
        or value.get("status") != "research_only_gate_a_failed"
        or value.get("raw_text_in_report") is not False
    ):
        raise ResearchTinyError(f"unexpected report contract: {path}")
    return value


def publish_evidence(
    cache_manifest_path: Path,
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
    if len(base_git_sha) != 40 or any(char not in "0123456789abcdef" for char in base_git_sha):
        raise ResearchTinyError("base Git SHA must be lowercase hexadecimal")
    if not nvidia_driver or len(nvidia_driver) > 32:
        raise ResearchTinyError("NVIDIA driver identity is invalid")
    cache_raw = cache_manifest_path.read_bytes()
    cache_manifest = json.loads(cache_raw)
    if cache_raw != canonical_json_bytes(cache_manifest):
        raise ResearchTinyError("cache manifest is not canonical JSON plus LF")
    if (
        cache_manifest.get("status") != "research_only_gate_a_failed"
        or cache_manifest.get("source", {}).get("sha256") != DATASET_CONTENT_SHA256
        or cache_manifest.get("splits") != {"dev": DEV_COUNT, "train": TRAIN_COUNT}
        or cache_manifest.get("final_holdout", {}).get("rows_in_cache") != 0
        or cache_manifest.get("final_holdout", {}).get("used_for_training_or_selection") is not False
    ):
        raise ResearchTinyError("cache evidence violates the fixed split contract")
    training = _read_canonical_report(training_path, "sakura_rerank_tiny_training")
    export = _read_canonical_report(export_path, "sakura_rerank_tiny_onnx_export")
    fp32 = _read_canonical_report(
        fp32_benchmark_path, "sakura_rerank_tiny_onnx_dev_benchmark"
    )
    int8 = _read_canonical_report(
        int8_benchmark_path, "sakura_rerank_tiny_onnx_dev_benchmark"
    )
    if (
        training.get("gate_a_status") != EXPECTED_GATE_STATUS
        or training.get("data", {}).get("final_holdout_used") is not False
        or training.get("data", {}).get("cache_manifest_sha256")
        != hashlib.sha256(cache_raw).hexdigest()
        or training.get("checkpoint", {}).get("sha256") != export.get("checkpoint_sha256")
        or training.get("parameter_count") != export.get("parameter_count")
    ):
        raise ResearchTinyError("training/export evidence linkage is inconsistent")
    artifacts = export["artifacts"]
    if (
        fp32.get("model", {}).get("sha256") != artifacts["fp32"]["sha256"]
        or int8.get("model", {}).get("sha256") != artifacts["int8"]["sha256"]
        or fp32.get("contract", {}).get("final_holdout_used") is not False
        or int8.get("contract", {}).get("final_holdout_used") is not False
    ):
        raise ResearchTinyError("export/benchmark evidence linkage is inconsistent")
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
        ):
            raise ResearchTinyError("benchmark violates the fixed Windows CPU contract")
    source_bindings = {
        label: {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in (
            ("numeric_cache_manifest", cache_manifest_path),
            ("training_report", training_path),
            ("export_report", export_path),
            ("fp32_benchmark_report", fp32_benchmark_path),
            ("int8_benchmark_report", int8_benchmark_path),
        )
    }
    model_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": "sakura_rerank_tiny_model",
        "status": "research_only_gate_a_failed",
        "model_name": MODEL_NAME,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "parameter_count": training["parameter_count"],
        "architecture": {
            "kind": "shared_character_embedding_unidirectional_gru_listwise_residual",
            "vocab_size": VOCAB_SIZE,
            "embedding_dim": EMBEDDING_DIM,
            "hidden_dim": HIDDEN_DIM,
            "gru_layers": GRU_LAYERS,
            "top_k": TOP_K,
            "context_length": CONTEXT_LENGTH,
            "reading_length": READING_LENGTH,
            "surface_length": SURFACE_LENGTH,
            "feature_dim": FEATURE_DIM,
            "character_hash": "unicode_scalar_multiplicative_modulo_v1",
        },
        "data": {
            "dataset_content_sha256": DATASET_CONTENT_SHA256,
            "train_count": TRAIN_COUNT,
            "dev_count": DEV_COUNT,
            "final_holdout_used": False,
            "gate_a_status": EXPECTED_GATE_STATUS,
        },
        "implementation": {
            "file": "src/sakura_rerank/research_tiny.py",
            "sha256": sha256_file(Path(__file__)),
            "base_git_sha": base_git_sha,
            "trained_from_uncommitted_implementation": True,
        },
        "training": {
            "seed": training["seed"],
            "best_epoch": training["best_epoch"],
            "hyperparameters": training["hyperparameters"],
            "environment": {**training["environment"], "nvidia_driver": nvidia_driver},
            "checkpoint": training["checkpoint"],
        },
        "exports": artifacts,
        "source_reports": source_bindings,
        "license_status": "not_selected_no_distribution_authorized",
        "distribution_authorized": False,
        "raw_text_in_manifest": False,
        "raw_stable_ids_in_manifest": False,
    }
    manifest_bytes = canonical_json_bytes(model_manifest)
    fp_quality = fp32["quality"]
    int8_quality = int8["quality"]
    baseline_errors = fp_quality["record_count"] - fp_quality["baseline_top1_correct"]
    fp_errors = fp_quality["record_count"] - fp_quality["top1_correct"]
    relative_error_reduction = (baseline_errors - fp_errors) / baseline_errors
    harm_rate = fp_quality["harm_count"] / fp_quality["baseline_top1_correct"]
    int8_loss_pp = (fp_quality["top1_accuracy"] - int8_quality["top1_accuracy"]) * 100
    decision_report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_research_decision",
        "status": "research_only_gate_a_failed",
        "model_manifest": {
            "file": manifest_path.name,
            "bytes": len(manifest_bytes),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
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
            "checks": {
                "dev_relative_error_reduction_at_least_10_percent": relative_error_reduction >= 0.10,
                "dev_harm_rate_at_most_0_25_percent": harm_rate <= 0.0025,
                "dev_rescue_harm_ratio_at_least_3": (
                    fp_quality["rescue_harm_ratio"] is not None
                    and fp_quality["rescue_harm_ratio"] >= 3
                ),
                "fp32_model_p95_at_most_2_ms": fp32["latency_ms"]["p95"] <= 2,
                "fp32_model_p99_at_most_5_ms": fp32["latency_ms"]["p99"] <= 5,
                "fp32_payload_at_most_8_mib": fp32["model"]["bytes"] <= 8 * 1024 * 1024,
                "int8_top1_loss_at_most_0_2_percentage_points": int8_loss_pp <= 0.2,
                "production_worker_roundtrip_measured": False,
                "production_peak_memory_measured": False,
            },
            "reason": (
                "Gate A already failed; dev is not the frozen final holdout; harm and "
                "latency thresholds are also missed. No production claim is permitted."
            ),
        },
        "final_holdout_used": False,
        "production_change_authorized": False,
        "artifact_distribution_authorized": False,
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_bytes_pair_atomic(
        manifest_path,
        manifest_bytes,
        report_path,
        canonical_json_bytes(decision_report),
    )
    return model_manifest, decision_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--manifest", type=Path, required=True)
    train = commands.add_parser("train")
    train.add_argument("cache", type=Path)
    train.add_argument("checkpoint", type=Path)
    train.add_argument("--cache-manifest", type=Path, required=True)
    train.add_argument("--report", type=Path, required=True)
    train.add_argument("--epochs", type=int, default=20)
    train.add_argument("--batch-size", type=int, default=256)
    train.add_argument("--learning-rate", type=float, default=0.001)
    export = commands.add_parser("export")
    export.add_argument("checkpoint", type=Path)
    export.add_argument("fp32", type=Path)
    export.add_argument("int8", type=Path)
    export.add_argument("--report", type=Path, required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("model", type=Path)
    benchmark.add_argument("cache", type=Path)
    benchmark.add_argument("--cache-manifest", type=Path, required=True)
    benchmark.add_argument("--report", type=Path, required=True)
    benchmark.add_argument("--warmup-runs", type=int, default=100)
    benchmark.add_argument("--measured-runs", type=int, default=10_000)
    evidence = commands.add_parser("publish-evidence")
    evidence.add_argument("--cache-manifest", type=Path, required=True)
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
        if arguments.command == "prepare":
            prepare_cache(arguments.source, arguments.output, arguments.manifest)
            output = arguments.output
        elif arguments.command == "train":
            train_model(
                arguments.cache,
                arguments.cache_manifest,
                arguments.checkpoint,
                arguments.report,
                epochs=arguments.epochs,
                batch_size=arguments.batch_size,
                learning_rate=arguments.learning_rate,
            )
            output = arguments.checkpoint
        elif arguments.command == "export":
            export_onnx(arguments.checkpoint, arguments.fp32, arguments.int8, arguments.report)
            output = arguments.int8
        elif arguments.command == "benchmark":
            benchmark_onnx(
                arguments.model,
                arguments.cache,
                arguments.cache_manifest,
                arguments.report,
                warmup_runs=arguments.warmup_runs,
                measured_runs=arguments.measured_runs,
            )
            output = arguments.report
        else:
            publish_evidence(
                arguments.cache_manifest,
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
    except (ResearchTinyError, OSError, ValueError, KeyError) as error:
        print(f"research tiny failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
