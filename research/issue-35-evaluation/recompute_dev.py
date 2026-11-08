"""Validate the new evaluator against pinned historical scores, never Test.

The Issue-21 C2 score artifact is a historical recipe reference, not a fresh
execution or per-row parity proof of the separately exported r2 model binary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from sakura_rerank.data.contracts import canonical_json_bytes, validate_record
from sakura_rerank.data.splitter import evaluation_component_keys
from sakura_rerank.evaluation_metrics import EvaluationCase, EvaluationRun, Observation, evaluate_runs
from sakura_rerank.research_tiny import (
    CONTEXT_LENGTH, READING_LENGTH, SURFACE_LENGTH, character_ids, candidate_features,
)

ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "data/generated/issue15-v5-slot120/frozen-split.jsonl": "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82",
    "data/generated/sakura-rerank-tiny-v1-research/train-dev-cache.npz": "41eb7f59c4912d3216836ed9cb153a3e3b952e8673d5fce3e71a020b24781624",
    "data/generated/issue-21-retrain/predictions.npz": "3be6ad904fd669b088ebfe9553bdc1f83c83f3ca29b077480167c30eb7392e52",
    "data/generated/issue-29-distill-gate/final/dev-logits.npz": "6f62a0173d2a9b967f866a357704fb79886c37ff5c339f92413bc8e21eeb7c11",
    "reports/issue-21-retrain-experiment.json": "c5bbc7c02d5b331c193b25982f8b0f9fc5ac14af06add6e2ab51f6691d149374",
    "reports/issue-29-distill-gate.json": "42fbc5af761194b01375dd71e6e34a71ea028a9d9f5337e4c861ee25cbaebed3",
}


def recompute() -> dict:
    for name, digest in PINS.items():
        with (ROOT/name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("historical artifact commitment mismatch")
    records = []
    skipped = {"train": 0, "final-holdout": 0}
    with (ROOT/next(iter(PINS))).open("rb") as stream:
        while line := stream.readline(256*1024+1):
            if len(line) > 256*1024:
                raise ValueError("row byte bound exceeded")
            skip = next((role for role in skipped if f',"split":"{role}",'.encode() in line), None)
            if skip:
                skipped[skip] += 1
                continue
            row = validate_record(json.loads(line))
            if row["split"] != "dev":
                raise ValueError("unexpected population; do not parse Test")
            records.append(row)
    if len(records) != 1788 or skipped != {"train": 12516, "final-holdout": 3576}:
        raise ValueError("historical population count mismatch")
    component_keys = evaluation_component_keys(records)
    with np.load(ROOT/"data/generated/sakura-rerank-tiny-v1-research/train-dev-cache.npz", allow_pickle=False) as archive:
        cache = {name[4:]: archive[name] for name in archive.files if name.startswith("dev_")}
    # Prove alignment from every feature tensor, not just a repeated gold-index
    # vector. No train cache tensor or holdout JSON is parsed.
    for i, row in enumerate(records):
        candidates = row["candidate_snapshots"]["production_top6"]["candidates"]
        for prefix, text, limit in (("context", row["session"]["left_context"], CONTEXT_LENGTH),
                                    ("reading", row["reading"], READING_LENGTH)):
            ids, length = character_ids(text, limit)
            np.testing.assert_array_equal(cache[prefix+"_ids"][i], ids)
            assert cache[prefix+"_lengths"][i] == length
        for j, candidate in enumerate(candidates):
            ids, length = character_ids(candidate["surface"], SURFACE_LENGTH)
            np.testing.assert_array_equal(cache["candidate_ids"][i, j], ids)
            assert cache["candidate_lengths"][i, j] == length
        np.testing.assert_array_equal(cache["candidate_mask"][i], np.arange(6) < len(candidates))
        for name in ("candidate_ids", "candidate_lengths", "features"):
            assert not np.any(cache[name][i, len(candidates):])
        np.testing.assert_array_equal(cache["features"][i, :len(candidates)],
                                      np.asarray(candidate_features(row["reading"], candidates), dtype=np.float32))
        assert cache["gold"][i] == (row["gold_index"] if row["gold_index"] < len(candidates) else -1)
    with np.load(ROOT/"data/generated/issue-21-retrain/predictions.npz", allow_pickle=False) as archive:
        c2 = archive["dev_C2-s20260814"].astype(np.float64)
        np.testing.assert_array_equal(archive["dev_gold"], cache["gold"])
    with np.load(ROOT/"data/generated/issue-29-distill-gate/final/dev-logits.npz", allow_pickle=False) as archive:
        student = archive["scores"].astype(np.float64)
    selection21 = json.loads((ROOT/"reports/issue-21-retrain-experiment.json").read_bytes())["selection"]["C2-s20260814"]
    selection29 = json.loads((ROOT/"reports/issue-29-distill-gate.json").read_bytes())["final_selection"]
    assert selection21["epoch"] == 9 and selection21["tau"] == 2.7
    assert selection29["epoch"] == 15 and selection29["main"]["gate"]["score"] == "L"
    assert selection29["main"]["gate"]["tau"] == 1.7
    cases = [EvaluationCase(
        hashlib.sha256(row["stable_id"].encode()).hexdigest(), component_keys[row["stable_id"]],
        tuple(c["surface"] for c in row["candidate_snapshots"]["training_top32"]["candidates"]),
        row["gold_surface"],
    ) for row in records]
    runs = {}
    for name, scores, threshold in (("issue21-C2", c2, 2.7), ("issue29", student, 1.7)):
        if scores.shape != (1788, 6) or not np.isfinite(scores).all():
            raise ValueError("saved score contract mismatch")
        ungated, gated = {}, {}
        for i, case in enumerate(cases):
            count = min(6, len(case.candidates))
            order = tuple(int(index) for index in np.argsort(-scores[i, :count], kind="stable"))
            ungated[case.case_key] = Observation("applied", order)
            allowed = order[0] != 0 and scores[i, order[0]]-scores[i, 0] > threshold
            gated[case.case_key] = ungated[case.case_key] if allowed else Observation("abstained")
        runs[name+"-ungated"] = EvaluationRun(ungated, True)
        runs[name+"-gated"] = EvaluationRun(gated, True)
    family = [(name, "baseline") for name in runs]
    family += [("issue29-ungated", "issue21-C2-ungated"), ("issue29-gated", "issue21-C2-gated")]
    result = evaluate_runs(cases, runs, comparisons=family)
    return {"scope": "historical dev metric verification; not independent evaluation",
            "observation_origin": "reconstructed offline score decisions; not runtime failure telemetry",
            "component_scope": "supplied historical dev only; not proof of full-history independence",
            "source_hashes": PINS, "skip_before_json": skipped,
            "dev_tensor_alignment_verified": True, "threshold_selection_performed": False,
            "models_executed": False, "labels_changed": False,
            "v1_and_exported_r2_binary_parity_not_checked": True, "evaluation": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("historical verification output already exists")
    result = recompute()
    with args.output.open("xb") as stream:
        stream.write(canonical_json_bytes(result)+b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"rows": result["evaluation"]["record_count"],
                      "release_eligible": False, "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
