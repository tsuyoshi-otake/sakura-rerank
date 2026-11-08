"""Posthoc diagnostics only: no fitting, threshold search, or Gold admission."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

GROWTH = Path("data/generated/issue-33-data-growth-v2")
PLAN = Path("research/issue-33-fundamentals/plan.json")
PLAN_COMMIT = "dd58b70"
sys.path.insert(0, str(Path("research/issue-33-data-growth").resolve()))
from train import authenticate_fit, harness  # noqa: E402


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_once(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def outcomes(scores, arrays, gated=False):
    if not np.isfinite(scores).all():
        raise ValueError("nonfinite_scores")
    valid = arrays["candidate_mask"]
    if scores.shape != valid.shape or not valid.any(axis=1).all():
        raise ValueError("invalid_candidate_shape_or_empty_row")
    row = np.arange(len(scores))
    winner = np.where(valid, scores, -np.inf).argmax(axis=1)
    margin = scores[row, winner] - scores[:, 0]
    if gated:
        winner = np.where(margin > 1.7, winner, 0)
    correct = arrays["correct_mask"][row, winner]
    base = arrays["correct_mask"][:, 0]
    changed = ~arrays["baseline_equivalent"][row, winner]
    rescue = ~base & correct
    harm = base & ~correct
    wrong = ~base & ~correct & changed
    counts = {"rows": len(scores), "correct": int(correct.sum()),
              "changed": int(changed.sum()), "rescue": int(rescue.sum()),
              "harm": int(harm.sum()), "wrong_to_wrong": int(wrong.sum())}
    if counts["correct"] != int(base.sum()) + counts["rescue"] - counts["harm"]:
        raise ValueError("outcome_partition_mismatch")
    return counts, winner, correct, margin, (rescue, harm, wrong)


def shuffled_context(arrays, metadata, seed):
    groups = defaultdict(list)
    for i, row in enumerate(metadata):
        n = row["context_chars"]
        groups[(row["corpus"], 0 if n < 16 else 1 if n < 32 else 2)].append(i)
    rng = np.random.Generator(np.random.PCG64(seed))
    donor = np.arange(len(metadata))
    for indices in groups.values():
        if len(indices) < 2:
            raise ValueError("shuffle_group_too_small")
        order = rng.permutation(indices)
        donor[order] = np.roll(order, int(rng.integers(1, len(order))))
    if np.any(donor == np.arange(len(metadata))) or len(set(donor)) != len(donor):
        raise ValueError("invalid_derangement")
    out = dict(arrays)
    out["context_ids"] = arrays["context_ids"][donor].copy()
    out["context_lengths"] = arrays["context_lengths"][donor].copy()
    return out, donor


def variants(arrays, metadata):
    yield "intact", arrays
    empty = dict(arrays)
    empty["context_ids"] = np.zeros_like(arrays["context_ids"])
    empty["context_lengths"] = np.zeros_like(arrays["context_lengths"])
    yield "empty", empty
    tail = dict(arrays)
    tail["context_ids"] = np.zeros_like(arrays["context_ids"])
    tail["context_lengths"] = np.minimum(arrays["context_lengths"], 8)
    for i, length in enumerate(arrays["context_lengths"]):
        size = min(int(length), 8)
        tail["context_ids"][i, :size] = arrays["context_ids"][i, int(length)-size:int(length)]
    yield "tail8", tail
    for seed in (20261105, 20261106, 20261107):
        yield f"shuffle{seed}", shuffled_context(arrays, metadata, seed)[0]


def saved_diagnostics(scores, arrays):
    base = arrays["correct_mask"][:, 0]
    present = arrays["correct_mask"].any(axis=1)
    correct = []
    by_model = {}
    for name, values in scores.items():
        raw, winner, right, margin, flags = outcomes(values, arrays)
        gated, gated_winner, _, _, _ = outcomes(values, arrays, True)
        correct.append(right)
        bins = []
        changed = ~arrays["baseline_equivalent"][np.arange(len(values)), winner]
        for lower, upper in zip((0, .5, 1, 1.7, 3), (.5, 1, 1.7, 3, math.inf)):
            take = changed & (margin > lower) & (margin <= upper)
            bins.append(dict(lower_exclusive=lower, upper_inclusive=None if math.isinf(upper) else upper,
                             changes=int(take.sum()), rescue=int((take & flags[0]).sum()),
                             harm=int((take & flags[1]).sum()), wrong_to_wrong=int((take & flags[2]).sum())))
        # Exact score ties can choose a different surface at margin zero.
        ties = changed & (margin == 0)
        if sum(x["changes"] for x in bins) + int(ties.sum()) != raw["changed"]:
            raise ValueError("margin_partition_mismatch")
        by_model[name] = dict(ungated=raw, gated=gated, margin_bins=bins, changed_at_zero_margin=int(ties.sum()),
            blocked_rescues=raw["rescue"]-gated["rescue"], prevented_harms=raw["harm"]-gated["harm"],
            perfect_apply_or_keep_ceiling_correct=int(base.sum())+raw["rescue"],
            no_candidate_or_top6_miss=int((~present).sum()),
            top6_present_rank_errors=int((present & ~right).sum()),
            oracle_present_baseline_wrong_no_correct_proposal=int((present & ~base & ~right).sum()))
    matrix = np.asarray(correct)
    any_correct = matrix.any(axis=0)
    return dict(models=by_model, overlap=dict(
        all_models_wrong=int((~any_correct).sum()),
        all_models_wrong_but_top6_present=int((~any_correct & present).sum()),
        all_models_wrong_despite_baseline_correct=int((~any_correct & base).sum()),
        any_model_correct=int(any_correct.sum()),
        label_aware_model_or_baseline_selection_ceiling_correct=int((any_correct | base).sum()),
        baseline_wrong_rescued_by_any_model=int((any_correct & ~base).sum()),
        baseline_wrong_top6_present_rescued_by_no_model=int((~base & present & ~any_correct).sum())))


def input_diagnostics(arrays, metadata):
    selection = json.loads((GROWTH / "isolation/execution.json").read_bytes())
    if sha(GROWTH / "isolation/selected.jsonl") != selection["selected_sha256"]:
        raise ValueError("selected_inputs_changed")
    targets = {}
    with (GROWTH / "isolation/selected.jsonl").open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            if row["population"] == "evaluation":
                targets[row["stable_id"]] = row
    if len(targets) != len(metadata) or set(targets) != {r["stable_id"] for r in metadata}:
        raise ValueError("source_population_mismatch")
    requested = {r["candidate_request_id"] for r in targets.values()}
    snapshots = {}
    identity = re.compile(rb'(?<!\\)"stable_id":"([^"\\]+)"')
    acquired = json.loads((GROWTH / "candidates/execution.json").read_bytes())
    for batch in acquired["batches"]:
        directory = GROWTH / "candidates" / f"batch-{batch['index']:05d}"
        if sha(directory / "execution.json") != batch["execution_sha256"]:
            raise ValueError("candidate_receipt_changed")
        receipt = json.loads((directory / "execution.json").read_bytes())
        if receipt["status"] != "complete" or sha(directory / "output.jsonl") != receipt["output_sha256"]:
            raise ValueError("candidate_snapshot_failed_or_changed")
        with (directory / "output.jsonl").open("rb") as stream:
            for line in stream:
                match = identity.search(line)
                if match and match[1].decode("ascii") in requested:
                    row = json.loads(line)
                    snapshots[row["stable_id"]] = row
    readings, inputs = defaultdict(Counter), defaultdict(Counter)
    buckets = defaultdict(set)
    context_origins = Counter()
    collisions = 0
    surfaces = 0
    source_presence = Counter()
    for i, meta in enumerate(metadata):
        row = targets[meta["stable_id"]]
        context_origins[row["context_origin"]] += 1
        readings[row["reading"]][row["target"]] += 1
        inputs[(row["left_context"], row["reading"])][row["target"]] += 1
        candidates = snapshots[row["candidate_request_id"]]["candidate_snapshots"]["training_top32"]["candidates"]
        top = candidates[:6]
        for k in (1, 5, 6, 10, 32):
            source_presence[str(k)] += row["target"] in [c["surface"] for c in candidates[:k]]
        # Raw surfaces independently validate the numeric equivalence masks.
        for j, candidate in enumerate(top):
            if bool(arrays["correct_mask"][i, j]) != (candidate["surface"] == row["target"]):
                raise ValueError("numeric_label_mismatch")
            if bool(arrays["baseline_equivalent"][i, j]) != (candidate["surface"] == top[0]["surface"]):
                raise ValueError("numeric_surface_equivalence_mismatch")
        texts = [row["left_context"][:64], row["reading"][:32]] + [c["surface"][:32] for c in top]
        for text in texts:
            for char in text:
                buckets[((ord(char) * 2654435761) % 13311) + 1].add(ord(char))
        for j in range(len(top)):
            for k in range(j):
                if top[j]["surface"] != top[k]["surface"] and np.array_equal(arrays["candidate_ids"][i,j], arrays["candidate_ids"][i,k]):
                    collisions += 1
        surfaces += len(top)
    def conflict_summary(groups):
        conflicts = [c for c in groups.values() if len(c) > 1]
        return dict(groups=len(groups), conflicting_groups=len(conflicts),
                    rows_in_conflicting_groups=sum(sum(c.values()) for c in conflicts),
                    empirical_majority_label_ceiling_correct=sum(max(c.values()) for c in groups.values()))
    valid = arrays["candidate_mask"]
    features = arrays["features"][valid]
    return dict(rows=len(metadata), source_exact_presence=dict(source_presence),
        reading_only=conflict_summary(readings), exact_observable_input=conflict_summary(inputs),
        context_origins=dict(context_origins), unique_characters=sum(len(s) for s in buckets.values()),
        character_hash_buckets=len(buckets), collision_buckets=sum(len(s)>1 for s in buckets.values()),
        distinct_characters_in_collision_buckets=sum(len(s) for s in buckets.values() if len(s)>1),
        within_row_distinct_candidate_surfaces_with_identical_token_ids=collisions,
        candidate_surfaces=surfaces, candidate_surfaces_truncated=sum(r["candidate_surfaces_truncated"] for r in metadata),
        reading_over9=sum(r["reading_chars"]>9 for r in metadata),
        common_prefix_feature_zero=int((features[:,4]==0).sum()),
        system_dictionary_feature_one=int((features[:,5]==1).sum()),
        feature_unique_values=[len(np.unique(features[:,i])) for i in range(7)])


def run(output):
    import torch
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if subprocess.check_output(["git", "show", PLAN_COMMIT+":"+PLAN.as_posix()], timeout=30) != PLAN.read_bytes():
        raise ValueError("diagnostic_plan_changed")
    plan = json.loads(PLAN.read_bytes())
    binding, fit_plan = authenticate_fit(plan["fit_commit"])
    if dict(torch=torch.__version__,numpy=np.__version__,python=sys.version.split()[0]) != binding["environment"]:
        raise ValueError("diagnostic_environment_changed")
    if sha(GROWTH/"evaluation/scores.npz") != plan["scores_sha256"]:
        raise ValueError("saved_scores_changed")
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(kind="fundamental_accuracy_diagnostic", status="failed", plan_sha256=sha(PLAN),
        script_sha256=sha(__file__), research_head=subprocess.check_output(["git","rev-parse","HEAD"],text=True,timeout=30).strip(),
        population=plan["population"], posthoc=True, training_runs=0, threshold_selection=False,
        new_final_test_used=False, gold_certified=False, environment=binding["environment"],
        input_scores_sha256=plan["scores_sha256"], context_runs=[])
    started = time.monotonic()
    try:
        with np.load(GROWTH/"cache/evaluation.npz",allow_pickle=False) as z:
            arrays = {k:np.array(z[k]) for k in z.files}
        with np.load(GROWTH/"evaluation/scores.npz",allow_pickle=False) as z:
            saved = {k:np.array(z[k]) for k in z.files}
        metadata = [json.loads(line) for line in (GROWTH/"cache/evaluation-metadata.jsonl").read_bytes().splitlines()]
        if len(metadata) != 4000 or len(saved) != 10:
            raise ValueError("fixed_population_changed")
        original = json.loads(Path("reports/issue-33-data-growth-model-v2.json").read_bytes())
        receipt["saved_scores"] = saved_diagnostics(saved, arrays)
        for name, row in receipt["saved_scores"]["models"].items():
            for mode in ("ungated","gated"):
                for key,value in row[mode].items():
                    if original["models"][mode+"/"+name][key] != value:
                        raise ValueError("original_point_report_mismatch")
        receipt["inputs"] = input_diagnostics(arrays,metadata)
        if receipt["inputs"]["source_exact_presence"] != original["source_exact_presence"]:
            raise ValueError("original_oracle_mismatch")
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        h21 = harness()
        training = json.loads((GROWTH/"training/execution.json").read_bytes())
        models = [dict(name="reference",path=Path(fit_plan["training"]["initial_checkpoint"]),sha256=fit_plan["training"]["initial_checkpoint_sha256"])]
        for fit in training["models"]:
            directory = GROWTH/"training"/fit["name"]
            if sha(directory/"execution.json") != fit["execution_sha256"]:
                raise ValueError("fit_receipt_changed")
            models.append(dict(name=fit["name"],path=directory/"model.pt",sha256=fit["checkpoint_sha256"]))
        diagnostic_scores = {}
        for item in models:
            if time.monotonic()-started > 900:
                raise TimeoutError("diagnostic_wall_time_bound")
            if sha(item["path"]) != item["sha256"]:
                raise ValueError("checkpoint_changed")
            model = h21.build_model("C2")
            model.load_state_dict(torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"],strict=True)
            model = model.to("cuda:0")
            for variant, modified in variants(arrays,metadata):
                values = h21.score_rows(model, modified, modified["features"], np.arange(len(metadata)))
                key = item["name"]+"/"+variant
                diagnostic_scores[key] = values
                entry = dict(model=item["name"],variant=variant,checkpoint_sha256=item["sha256"],modes={})
                for mode in ("ungated","gated"):
                    count, pred, right, _, _ = outcomes(values,arrays,mode=="gated")
                    _, old_pred, old_right, _, _ = outcomes(saved[item["name"]],arrays,mode=="gated")
                    count.update(changed_winners=int((pred!=old_pred).sum()),
                                 intact_only_correct=int((old_right & ~right).sum()),
                                 diagnostic_only_correct=int((right & ~old_right).sum()))
                    entry["modes"][mode] = count
                    if variant == "intact" and not np.array_equal(pred,old_pred):
                        raise ValueError("intact_prediction_reproduction_failed")
                if variant == "intact":
                    error = float(np.abs(values-saved[item["name"]]).max())
                    entry["max_absolute_score_difference"] = error
                    if error > 1e-5:
                        raise ValueError("intact_score_reproduction_failed")
                receipt["context_runs"].append(entry)
            print(json.dumps(dict(stage="context_diagnostic",completed_models=len(receipt["context_runs"])//6,total_models=10)),flush=True)
            del model
        with (output/"scores.npz").open("xb") as stream:
            np.savez_compressed(stream,**diagnostic_scores)
        receipt.update(status="passed",diagnostic_scores_sha256=sha(output/"scores.npz"),point_reports_verified=20)
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic()-started,3)
        write_once(output/"report.json",receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(dict(status=result["status"],context_runs=len(result["context_runs"]),elapsed_seconds=result["elapsed_seconds"])))
