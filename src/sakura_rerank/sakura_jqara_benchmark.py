"""Out-of-domain JQaRA benchmark adapter for Sakura-Rerank-Tiny-v1.

The production model ranks up to six IME candidates.  JQaRA instead supplies
independent query-document pairs.  This adapter therefore scores every pair as
one real candidate plus five masked candidates, so the final NDCG@10 ordering
does not depend on arbitrary six-item chunk boundaries.  The result is a
diagnostic, not Gate B evidence or a production claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from sakura_rerank.atomic_io import write_bytes_atomic
from sakura_rerank.research_tiny import (
    CONTEXT_LENGTH,
    FEATURE_DIM,
    MODEL_NAME,
    READING_LENGTH,
    SURFACE_LENGTH,
    TOP_K,
    character_ids,
)


SCHEMA_VERSION = 1
MODEL_PARAMETERS = 1_861_377
MODEL_SHA256 = "b3fe1e0aa7229edfd0760162d648f10328b0d75224a9cd49f2ba986b7db2ccbd"
MODEL_BYTES = 7_466_707
TASK = {
    "name": "JQaRARerankingLite",
    "dataset": "mteb/JQaRARerankingLite",
    "revision": "d23d3ad479f74824ed126052e810eac47e685558",
    "split": "test",
    "pairs": 91_353,
    "main_score": "ndcg_at_10",
}
SCORED_PAIR_COUNT = 98_941


class SakuraJQaRAError(RuntimeError):
    """The fixed out-of-domain benchmark contract was violated."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pair_inputs(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Map query-document pairs to the immutable single-candidate adapter."""
    import numpy as np

    count = len(pairs)
    context_ids = np.zeros((count, CONTEXT_LENGTH), dtype=np.int64)
    context_lengths = np.zeros(count, dtype=np.int64)
    reading_ids = np.zeros((count, READING_LENGTH), dtype=np.int64)
    reading_lengths = np.zeros(count, dtype=np.int64)
    candidate_ids = np.zeros((count, TOP_K, SURFACE_LENGTH), dtype=np.int64)
    candidate_lengths = np.zeros((count, TOP_K), dtype=np.int64)
    features = np.zeros((count, TOP_K, FEATURE_DIM), dtype=np.float32)
    candidate_mask = np.zeros((count, TOP_K), dtype=np.bool_)
    for index, pair in enumerate(pairs):
        if (
            not isinstance(pair, (tuple, list))
            or len(pair) != 2
            or not all(isinstance(value, str) and value for value in pair)
        ):
            raise SakuraJQaRAError("each benchmark pair must contain non-empty strings")
        query, document = pair
        context, context_length = character_ids(query, CONTEXT_LENGTH)
        # JQaRA has no kana-reading field. Reusing the query in this encoder is
        # deterministic but explicitly out of the model's training distribution.
        reading, reading_length = character_ids(query, READING_LENGTH)
        candidate, candidate_length = character_ids(document, SURFACE_LENGTH)
        context_ids[index] = context
        context_lengths[index] = context_length
        reading_ids[index] = reading
        reading_lengths[index] = reading_length
        candidate_ids[index, 0] = candidate
        candidate_lengths[index, 0] = candidate_length
        candidate_mask[index, 0] = True
    return {
        "context_ids": context_ids,
        "context_lengths": context_lengths,
        "reading_ids": reading_ids,
        "reading_lengths": reading_lengths,
        "candidate_ids": candidate_ids,
        "candidate_lengths": candidate_lengths,
        "features": features,
        "candidate_mask": candidate_mask,
    }


class SakuraPairScorer:
    """Minimal sentence-transformers-compatible local ONNX scorer."""

    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        if model_path.stat().st_size != MODEL_BYTES or sha256_file(model_path) != MODEL_SHA256:
            raise SakuraJQaRAError("Sakura ONNX identity differs from the pinned export")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise SakuraJQaRAError("benchmark unexpectedly enabled a non-CPU provider")
        self.pair_count = 0
        self.query_context_truncated_count = 0
        self.query_reading_truncated_count = 0
        self.document_truncated_count = 0

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int = 256,
        show_progress_bar: bool = False,
        **_: Any,
    ) -> Any:
        del show_progress_bar
        import numpy as np

        if batch_size < 1:
            raise SakuraJQaRAError("batch size must be positive")
        pair_list = list(pairs)
        scores = []
        for start in range(0, len(pair_list), batch_size):
            batch = pair_list[start : start + batch_size]
            inputs = build_pair_inputs(batch)
            output = self.session.run(["scores"], inputs)[0]
            if output.shape != (len(batch), TOP_K) or not np.isfinite(output[:, 0]).all():
                raise SakuraJQaRAError("Sakura ONNX produced invalid pair scores")
            scores.append(output[:, 0])
            self.pair_count += len(batch)
            self.query_context_truncated_count += sum(len(query) > CONTEXT_LENGTH for query, _ in batch)
            self.query_reading_truncated_count += sum(len(query) > READING_LENGTH for query, _ in batch)
            self.document_truncated_count += sum(len(document) > SURFACE_LENGTH for _, document in batch)
        return np.concatenate(scores) if scores else np.empty(0, dtype=np.float32)


def _model_meta() -> Any:
    from mteb.models import ModelMeta

    return ModelMeta(
        loader=None,
        name="local/sakura-rerank-tiny-v1-research-prototype",
        revision=MODEL_SHA256,
        release_date="2026-08-14",
        languages=["jpn-Jpan"],
        n_parameters=MODEL_PARAMETERS,
        memory_usage_mb=MODEL_BYTES / 1_000_000,
        max_tokens=CONTEXT_LENGTH + READING_LENGTH + SURFACE_LENGTH,
        embed_dim=None,
        license="not specified",
        open_weights=False,
        public_training_code=None,
        public_training_data=False,
        framework=["PyTorch"],
        reference=None,
        similarity_fn_name=None,
        use_instructions=False,
        training_datasets=set(),
        adapted_from=None,
        is_cross_encoder=True,
    )


def run_benchmark(
    model_path: Path,
    output: Path,
    result_cache: Path,
    *,
    batch_size: int = 256,
) -> dict[str, Any]:
    if batch_size < 1 or batch_size > 1024:
        raise SakuraJQaRAError("evaluation batch size must be in 1..1024")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from mteb import __version__ as mteb_version
    from mteb import evaluate, get_tasks
    from mteb.cache import ResultCache
    from mteb.models import CrossEncoderWrapper

    tasks = get_tasks(tasks=[TASK["name"]])
    if len(tasks) != 1:
        raise SakuraJQaRAError("MTEB did not resolve exactly one JQaRA task")
    task = tasks[0]
    measured = {
        "name": task.metadata.name,
        "dataset": task.metadata.dataset["path"],
        "revision": task.metadata.dataset["revision"],
        "split": task.metadata.eval_splits[0],
        "pairs": task.metadata.n_samples[task.metadata.eval_splits[0]],
        "main_score": task.metadata.main_score,
    }
    if measured != TASK:
        raise SakuraJQaRAError("installed JQaRA task metadata differs from the pinned contract")
    scorer = SakuraPairScorer(model_path)
    wrapped = CrossEncoderWrapper.__new__(CrossEncoderWrapper)
    wrapped.model = scorer
    wrapped.mteb_model_meta = _model_meta()
    started = time.perf_counter()
    result = evaluate(
        wrapped,
        tasks,
        cache=ResultCache(result_cache),
        overwrite_strategy="always",
        encode_kwargs={"batch_size": batch_size, "show_progress_bar": True},
        show_progress_bar=True,
    )
    elapsed = time.perf_counter() - started
    if len(result.task_results) != 1:
        raise SakuraJQaRAError("MTEB returned an unexpected task-result count")
    task_result = result.task_results[0]
    split_scores = task_result.scores[TASK["split"]]
    if len(split_scores) != 1:
        raise SakuraJQaRAError("MTEB returned an unexpected score shape")
    score = split_scores[0].get(TASK["main_score"])
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        raise SakuraJQaRAError("MTEB result lacks a finite NDCG@10 score")
    if scorer.pair_count != SCORED_PAIR_COUNT:
        raise SakuraJQaRAError(
            "adapter scored-pair count differs from the pinned evaluator behavior: "
            f"expected {SCORED_PAIR_COUNT}, got {scorer.pair_count}"
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "sakura_rerank_tiny_jqara_out_of_domain",
        "status": "research_only_out_of_domain",
        "model": {
            "name": MODEL_NAME,
            "parameters": MODEL_PARAMETERS,
            "file": model_path.name,
            "bytes": model_path.stat().st_size,
            "sha256": sha256_file(model_path),
        },
        "task": {
            **TASK,
            "score": round(float(score), 10),
            "evaluation_time_seconds": round(float(task_result.evaluation_time), 6),
        },
        "adapter": {
            "kind": "pointwise_single_real_candidate_plus_five_masked_v1",
            "query_to_left_context": True,
            "query_to_reading_encoder": True,
            "candidate_features": "all_zero",
            "context_character_limit": CONTEXT_LENGTH,
            "reading_character_limit": READING_LENGTH,
            "document_character_limit": SURFACE_LENGTH,
            "pair_count": scorer.pair_count,
            "task_metadata_pair_count": TASK["pairs"],
            "query_context_truncated_count": scorer.query_context_truncated_count,
            "query_reading_truncated_count": scorer.query_reading_truncated_count,
            "document_truncated_count": scorer.document_truncated_count,
        },
        "inference": {
            "backend": "onnxruntime",
            "provider": "CPUExecutionProvider",
            "gpu_disabled": True,
            "ort_intra_op_threads": 1,
            "ort_inter_op_threads": 1,
            "evaluation_batch_size": batch_size,
        },
        "software": {"mteb": mteb_version, "python": platform.python_version()},
        "wall_time_seconds": round(elapsed, 6),
        "limitations": {
            "ime_input_contract_matched": False,
            "general_ir_training_performed": False,
            "directly_comparable_to_native_cross_encoders": False,
            "gate_b_evidence": False,
            "production_change_authorized": False,
            "artifact_distribution_authorized": False,
            "final_holdout_used": False,
        },
        "raw_text_in_report": False,
        "raw_stable_ids_in_report": False,
    }
    write_bytes_atomic(output, canonical_json_bytes(report), create_parent=True)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--result-cache", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        run_benchmark(
            arguments.model,
            arguments.output,
            arguments.result_cache,
            batch_size=arguments.batch_size,
        )
    except (SakuraJQaRAError, OSError, ValueError, KeyError) as error:
        print(f"Sakura JQaRA benchmark failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
