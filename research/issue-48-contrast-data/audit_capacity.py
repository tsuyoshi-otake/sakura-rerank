"""Authenticate train-only inputs, then measure contrast capacity and evidence."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from sakura_rerank.data.contrast_capacity import (
    QUALITY_AXES, balanced_selections, candidate_evidence, profile, review_flags,
)
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.reference_probe import authenticate_identity, validate_probe_records

sys.path.insert(0, "research/issue-41-language-pretraining")
try:
    from language_common import ROOT as LANGUAGE_ROOT, TRAIN_ROOT, boundary, read_json, rows, save, sha
    from prepare_language import admitted_fragments
finally:
    sys.path.pop(0)

ROOT = Path("data/generated/issue-48-contrast-data-v1")
PLAN = Path("research/issue-48-contrast-data/plan-v2.json")
POLICY = Path("research/issue-48-contrast-data/quality-policy-v1.md")
PLAN_COMMIT = "986f77208b4cabf5b308fb114602cf15faf2a380"
PRIOR_COMMIT = "f38066ac0f1a2d992bc31abf34d4930356f13c9f"
IMPLEMENTATION = ("research/issue-48-contrast-data/audit_capacity.py",
                  "src/sakura_rerank/data/contrast_capacity.py")


def authenticate_sources():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    boundary.committed(POLICY, PLAN_COMMIT)
    recipe = plan["source"]
    if (sha(recipe["path"]) != recipe["sha256"]
            or sha(recipe["preparation"]) != recipe["preparation_sha256"]
            or sha(recipe["history_replay"].split(":")[0]) != recipe["history_script_sha256"]):
        raise ValueError("contrast_source_binding_changed")
    prep = read_json(recipe["preparation"])
    if prep != read_json(LANGUAGE_ROOT / "language-preparation.json"):
        raise ValueError("contrast_language_preparation_changed")
    # Reauthenticate the latest evaluation history as exclusion evidence only.
    cohort = json.loads(boundary.committed("manifests/language-research-cohort-v1.json", PRIOR_COMMIT))
    if sha(LANGUAGE_ROOT / "preparation.json") != cohort["preparation_sha256"]:
        raise ValueError("contrast_latest_history_preparation_changed")
    for name, expected in read_json(LANGUAGE_ROOT / "preparation.json")["artifacts"].items():
        if sha(LANGUAGE_ROOT / (name + ".jsonl")) != expected:
            raise ValueError("contrast_latest_history_artifact_changed")
    relations_path = LANGUAGE_ROOT / "lm-source-relations.json"
    if sha(relations_path) != prep["artifacts"][relations_path.name]:
        raise ValueError("contrast_source_relations_changed")
    selected, excluded, components, history = admitted_fragments()
    regenerated = hashlib.sha256()
    for row in selected:
        regenerated.update(canonical_json_bytes(row) + b"\n")
    if (len(selected) != recipe["rows"] or regenerated.hexdigest() != recipe["sha256"]
            or history != prep["source_isolation"]
            or dict(excluded=excluded, components=components) != read_json(relations_path)):
        raise ValueError("contrast_history_closure_replay_differs")
    return plan, selected, components, history


def authenticate_candidates(selected, plan):
    receipt_path = Path(plan["candidate_receipt"]["path"])
    if sha(receipt_path) != plan["candidate_receipt"]["sha256"]:
        raise ValueError("contrast_candidate_execution_changed")
    acquired = read_json(receipt_path)
    binding_path = Path("manifests/data-growth-input-reservations-v2.json")
    binding_raw = boundary.committed(binding_path, acquired["input_commit"])
    binding = json.loads(binding_raw)
    if (hashlib.sha256(binding_raw).hexdigest() != acquired["input_binding_sha256"]
            or binding_raw != (TRAIN_ROOT / "isolation/execution.json").read_bytes()
            or acquired["status"] != "complete" or binding["status"] != "complete"):
        raise ValueError("contrast_candidate_input_binding_changed")
    for name in ("requests", "selected"):
        if sha(TRAIN_ROOT / "isolation" / (name + ".jsonl")) != binding[name + "_sha256"]:
            raise ValueError("contrast_candidate_input_changed")
    identity = authenticate_identity(boundary.IDENTITY, acquired["identity_sha256"],
                                     boundary.BINARY, boundary.DICTIONARY)
    requests = list(rows(TRAIN_ROOT / "isolation/requests.jsonl"))
    if len(requests) != binding["unique_readings"] or len(acquired["batches"]) != (len(requests) + 99) // 100:
        raise ValueError("contrast_candidate_batch_accounting")
    required = defaultdict(dict)
    for row in selected:
        if row["candidate_request_id"] != "growth-reading-" + canonical_json_hash(row["reading"]):
            raise ValueError("contrast_target_request_differs")
        required[row["candidate_request_id"]][row["target"]] = row["reading"]
    proof, counts = {}, Counter()
    for offset in range(0, len(requests), 100):
        index = offset // 100
        directory = TRAIN_ROOT / "candidates" / f"batch-{index:05d}"
        commitment = acquired["batches"][index]
        if commitment["index"] != index or sha(directory / "execution.json") != commitment["execution_sha256"]:
            raise ValueError(f"contrast_candidate_receipt_changed_batch_{index}")
        receipt = read_json(directory / "execution.json")
        batch = requests[offset:offset + 100]
        input_raw = b"".join(canonical_json_bytes(r) + b"\n" for r in batch)
        if (receipt["request_count"] != len(batch)
                or receipt["input_sha256"] != hashlib.sha256(input_raw).hexdigest()
                or (directory / "input.jsonl").read_bytes() != input_raw
                or read_json(directory / "identity.json") != identity):
            raise ValueError(f"contrast_candidate_request_changed_batch_{index}")
        if receipt["status"] != "complete":
            counts["failed_requests"] += len(batch)
            continue
        raw = (directory / "output.jsonl").read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["output_sha256"]:
            raise ValueError(f"contrast_candidate_output_changed_batch_{index}")
        validated = validate_probe_records(raw, batch, identity)
        counts["validated_requests"] += len(validated)
        # All batch bytes are authenticated. Only train-request surfaces enter
        # the evidence map; no evaluation target list is loaded or matched.
        for snapshot in validated:
            needed = required.get(snapshot["stable_id"])
            if needed is None:
                continue
            counts["train_readings"] += 1
            for target, reading in needed.items():
                if snapshot["reading"] != reading:
                    raise ValueError("contrast_reading_join_differs")
                proof[(snapshot["stable_id"], target)] = candidate_evidence(target, snapshot)
    if counts["validated_requests"] + counts["failed_requests"] != len(requests):
        raise ValueError("contrast_candidate_terminal_accounting")
    for request, forms in required.items():
        for target in forms:
            proof.setdefault((request, target), candidate_evidence(target, None))
    return proof, dict(counts)


def evidence_ledger(selected, components, proof):
    previous = "0" * 64
    policy_hash = sha(POLICY)
    path = ROOT / "evidence.jsonl"
    staging = ROOT / "evidence.pending"
    count = 0
    try:
        with staging.open("xb") as stream:
            for row in sorted(selected, key=lambda r: r["stable_id"]):
                record = dict(index=count, stable_id=row["stable_id"], source_row_sha256=canonical_json_hash(row),
                    source_component=components[row["stable_id"]], policy_sha256=policy_hash,
                    reading_provenance="dictionary_unique_surface_lookup_not_contextual_annotation",
                    source_span_offsets_retained=False, review_flags=list(review_flags(row)),
                    quality={axis: "unresolved" for axis in QUALITY_AXES},
                    candidate=proof[(row["candidate_request_id"], row["target"])],
                    previous_record_sha256=previous)
                previous = canonical_json_hash(record)
                record["record_sha256"] = previous
                stream.write(canonical_json_bytes(record) + b"\n")
                count += 1
        if path.exists():
            if sha(path) != sha(staging):
                raise ValueError("contrast_immutable_evidence_differs")
        else:
            staging.rename(path)
        return dict(rows=count, sha256=sha(path), last_record_sha256=previous,
                    policy_sha256=policy_hash, plan_sha256=sha(PLAN))
    finally:
        if staging.exists():
            staging.unlink()


def analyze(selected, components, proof, plan):
    all_summary, all_witnesses = profile(selected, components)
    statuses, ranks, presence = Counter(), Counter(), Counter()
    eligible, per_corpus = [], defaultdict(Counter)
    for row in selected:
        observed = proof[(row["candidate_request_id"], row["target"])]
        statuses[observed["status"]] += 1
        per_corpus[row["corpus"]][observed["status"]] += 1
        ranks[str(observed["unique_target_rank"])] += 1
        presence.update(k for k, yes in observed["presence"].items() if yes)
        if observed["eligible"]:
            eligible.append(row)
    summaries = {"all_train": all_summary}
    witness_sets = {"all_train": all_witnesses}
    selections = {}
    if eligible:
        summaries["candidate_eligible"], witness_sets["candidate_eligible"] = profile(eligible, components)
        control, contrast, reserved, capacity = balanced_selections(eligible, components, plan["selection"]["corpus_quotas"])
        if control:
            by_id = {r["stable_id"]: r for r in eligible}
            for name, identities in (("control", control), ("contrast", contrast)):
                selections[name] = identities
                summaries[name], witness_sets[name] = profile([by_id[s] for s in identities], components)
            capacity["quantity_signal_pass"] = (summaries["control"]["four_component_witnessed_readings"] > 0
                and summaries["contrast"]["four_component_witnessed_readings"] >=
                2 * summaries["control"]["four_component_witnessed_readings"])
            selections["reserved_quartets"] = reserved
    else:
        capacity = dict(status="insufficient_quantity", quantity_signal_pass=False)
    capacity.setdefault("quantity_signal_pass", False)
    capacity.update(quality_status="unresolved_quality", admitted_new_training_rows=0,
                    fit_authorized=False, fit_count=0)
    result = dict(populations=summaries, candidate_statuses=dict(statuses),
        candidate_statuses_per_corpus={k: dict(v) for k, v in per_corpus.items()},
        source_presence_denominator=len(selected), source_presence_counts=dict(presence),
        unique_target_rank_counts=dict(ranks), capacity=capacity)
    return result, witness_sets, selections


def run():
    ROOT.mkdir(exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    implementation = {p: sha(p) for p in IMPLEMENTATION}
    for path in IMPLEMENTATION:
        boundary.committed(path, head)
    plan, selected, components, history = authenticate_sources()
    save(ROOT / "history-replay.json", dict(status="passed", history=history,
        source_sha256=plan["source"]["sha256"], relation_sha256=sha(LANGUAGE_ROOT / "lm-source-relations.json")))
    print(json.dumps(dict(stage="contrast_train_candidates", train_rows=len(selected))), flush=True)
    proof, candidate_auth = authenticate_candidates(selected, plan)
    result, witnesses, selections = analyze(selected, components, proof, plan)
    ledger = evidence_ledger(selected, components, proof)
    save(ROOT / "witnesses.json", witnesses)
    save(ROOT / "selection-identities.json", selections)
    save(ROOT / "evidence-manifest.json", ledger)
    result.update(kind="train_only_contrast_feasibility", status="unresolved_quality_do_not_fit",
        plan_commit=PLAN_COMMIT, plan_sha256=sha(PLAN), policy_sha256=sha(POLICY),
        execution_commit=head, implementation=implementation, candidate_authentication=candidate_auth,
        source_sha256=plan["source"]["sha256"], history_replayed=True,
        artifacts={name: sha(ROOT / name) for name in ("history-replay.json", "witnesses.json",
                   "selection-identities.json", "evidence-manifest.json", "evidence.jsonl")},
        model_fits=0, model_inferences=0, evaluation_words_used_for_selection=False,
        gold_certified=False, final_test_used=False, safety_threshold=.0025,
        interpretation="Literal source-form and conservative witness counts, not semantic contrast certification or accuracy. Quality flags overlap and are not error rates.")
    save(ROOT / "report.json", result)
    save("reports/issue-48-contrast-capacity-v1.json", result)
    return {k: result[k] for k in ("status", "populations", "candidate_statuses", "source_presence_counts", "capacity")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", choices=("initial-r2", "replay-r2"), required=True)
    attempt = parser.parse_args().attempt
    ROOT.mkdir(exist_ok=True)
    receipt_path = ROOT / ("execution-" + attempt + ".json")
    if receipt_path.exists():
        raise SystemExit("immutable_execution_already_exists")
    started = time.monotonic()
    try:
        summary = run()
    except Exception as error:
        receipt = dict(status="failed", error_type=type(error).__name__,
                       elapsed_seconds=round(time.monotonic() - started, 3))
        save(receipt_path, receipt)
        print(json.dumps(receipt))
        raise SystemExit(1) from None
    else:
        save(receipt_path, dict(status="complete", report_sha256=sha(ROOT / "report.json"),
                               elapsed_seconds=round(time.monotonic() - started, 3)))
        print(json.dumps(summary, ensure_ascii=True))
