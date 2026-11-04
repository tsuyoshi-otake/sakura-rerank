"""Read-only feasibility audit of the exposed train pilot; never certifies Gold.

Run from the repository root with PYTHONPATH=src. Requires the original ignored
pilot artifacts. Prints aggregate JSON only; no raw text, IDs or model scores.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from sakura_rerank.data.ai_six_axis_review import load_inputs, summarize
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.pilot_doubt_evidence import run as verify_doubt
from sakura_rerank.evaluation_statistics import wilson95

BASE = Path("data/generated/issue15-v5-slot120")
SIX = Path("data/generated/issue-31-ai-six-axis-v1")
PACKET = Path("data/generated/issue-31-gold-pilot-v1")
MACHINE = Path("reports/issue-31-machine-evidence-v1.json")
EVIDENCE = Path("data/generated/issue-31-machine-evidence-v1/evidence.jsonl")
PRIOR = Path("reports/issue-31-ai-six-axis-v1.json")
SUPPLEMENT = Path("data/generated/issue-31-doubt-evidence-v1/supplement.json")
PINS = Path(__file__).with_name("inputs-v1.json")


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("unexpected analysis input size")
    return json.loads(path.read_bytes())


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def flags(axes):
    ordinary = {"reading": "compatible", "input_unit": "whole_plausible",
                "context": "usable", "meaning": "supported", "spelling": "ordinary_plausible"}
    return {key for key in ordinary if axes[key] != ordinary[key]}


def profile(decisions):
    sets = {case: flags(row["axes"]) for case, row in decisions.items()}
    preconditions = {"reading", "input_unit", "context", "meaning"}
    return {
        "n": len(sets),
        "all_five_ordinary_or_supported": sum(not value for value in sets.values()),
        "any_nonordinary_axis": sum(bool(value) for value in sets.values()),
        "any_unresolved_precondition": sum(bool(value & preconditions) for value in sets.values()),
        "all_four_preconditions_supported": sum(not value & preconditions for value in sets.values()),
        "spelling_only_nonordinary": sum(value == {"spelling"} for value in sets.values()),
        "unresolved_meaning_without_reading_boundary_context_flag": sum(value & preconditions == {"meaning"} for value in sets.values()),
        "flag_counts_overlap": {axis: sum(axis in value for value in sets.values()) for axis in sorted(preconditions | {"spelling"})},
        "flags_are_not_label_errors": True,
    }


def main():
    pins = read_json(PINS)
    for path, expected in pins["sha256"].items():
        if hash_file(path) != expected:
            raise ValueError("pinned input changed: " + path)
    manifest, queue, machine, machine_sha = load_inputs(PACKET, MACHINE, EVIDENCE)
    prior = read_json(PRIOR)
    checked = summarize(SIX, queue, manifest, machine, machine_sha, previous=prior)
    if checked != {k: v for k, v in prior.items() if k != "baseline_comparison"}:
        raise ValueError("six-axis evidence differs")
    if prior["amendment_sha256"] or prior["pending"]:
        raise ValueError("this fixed analysis expects the complete unamended snapshot")
    decisions = {}
    for name in sorted(prior["batch_sha256"]):
        for decision in read_json(SIX / name)["decisions"]:
            if decision["case_id"] in decisions:
                raise ValueError("duplicate case")
            decisions[decision["case_id"]] = decision
    if set(decisions) != set(queue) or len(decisions) != 1000:
        raise ValueError("pilot coverage changed")
    result = profile(decisions)
    # Independent representation: aggregate compressed axis combinations, not rows.
    for key in ("any_unresolved_precondition", "all_five_ordinary_or_supported",
                "spelling_only_nonordinary", "unresolved_meaning_without_reading_boundary_context_flag"):
        weighted = sum(profile({"synthetic": {"axes": item["axes"]}})[key] * item["count"]
                       for item in prior["axis_combinations"])
        if result[key] != weighted:
            raise AssertionError("row/combinations reconciliation failed")
    doubt = verify_doubt(SimpleNamespace(packet=PACKET, machine_report=MACHINE, machine_evidence=EVIDENCE,
        reviews=SIX, prior_report=PRIOR, dictionary=Path("data/generated/system-dictionary-index.jsonl"),
        dictionary_manifest=Path("manifests/system-dictionary-index-verified.json"), supplement=SUPPLEMENT))
    if doubt != read_json("reports/issue-31-doubt-evidence-v1.json"):
        raise ValueError("doubt evidence changed")
    supplement = read_json(SUPPLEMENT)
    ext = [row for row in supplement["decisions"] if row["outcome"].startswith("external_")]
    for row in ext:
        if row["prior_decision_sha256"] != canonical_json_hash(decisions[row["case_id"]]):
            raise ValueError("external evidence join mismatch")
    acquisition = read_json(BASE / "source-spans-a.report.json")
    tier = read_json(BASE / "tier-a-a.report.json")
    partition = read_json("reports/issue-15-v5-admissibility-gate-a-evidence.json")["partition"]
    buckets = {key: value["record_count"] for key, value in partition["buckets"].items()}
    if sum(buckets.values()) != partition["source_dataset_record_count"]:
        raise AssertionError("partition denominator mismatch")
    if tier["input_record_count"] != acquisition["record_count"] or tier["accepted_record_count"] + tier["rejected_record_count"] != tier["input_record_count"]:
        raise AssertionError("generation denominator mismatch")
    source_path = "src/sakura_rerank/data/tier_a.py"
    historical = subprocess.check_output(["git", "show", acquisition["extractor_git_sha"] + ":" + source_path]).decode("utf-8")
    def function_tree(source):
        module = ast.parse(source)
        return ast.dump(next(node for node in module.body if isinstance(node, ast.FunctionDef)
                             and node.name == "generate_tier_a_records"), include_attributes=False)
    if function_tree(historical) != function_tree(Path(source_path).read_text(encoding="utf-8")):
        raise ValueError("generation logic differs from frozen source")
    scenarios = []
    for n in (1000, 3000):
        allowed = max(errors for errors in range(n // 200 + 1)
                      if (n-errors)/n >= .995 and wilson95(n-errors, n)[0] >= .99)
        scenarios.append({"hypothetical_independently_verified_n": n,
                          "maximum_incorrect_for_both_quality_thresholds": allowed,
                          "wilson_lower_at_boundary": wilson95(n-allowed, n)[0],
                          "actual_pilot_certification": False})
    audit = read_json("reports/issue-15-tier-a-owner-authorized-audit-v5.json")
    report = {
        "kind": "existing_pilot_evidence_feasibility_not_gold", "schema_version": 1,
        "input_manifest_sha256": hash_file(PINS), "case_profile": result,
        "machine_exact_cases": len(machine),
        "machine_exact_with_unresolved_preconditions": result["any_unresolved_precondition"],
        "external_reading_evidence_cases": len(ext),
        "external_reading_outcomes": dict(sorted(Counter(row["outcome"] for row in ext).items())),
        "external_evidence_selection": "five cases within the deliberately flagged fifty, not a random quality audit",
        "independently_certified_full_labels": 0, "label_accuracy_estimate": None,
        "label_accuracy_confidence_interval": None, "quality_threshold_scenarios": scenarios,
        "generation_selection": {
            "eligible_dictionary_surfaces": acquisition["eligible_dictionary_surface_count"],
            "sampled_source_spans": acquisition["record_count"],
            "tier_a_accepted": tier["accepted_record_count"], "tier_a_rejections": tier["rejection_counts"],
            "normalized_top32_gold_presence_required_by_construction": True,
            "frozen_generation_function_ast_matches": True,
            "ai_partition_input": partition["source_dataset_record_count"], "ai_partition_buckets": buckets,
            "ai_unanimous_retention": buckets["eligible_unanimous_valid"] / partition["source_dataset_record_count"],
            "old_holdout_ai_audit": {key: audit[key] for key in (
                "completed_record_count", "valid_record_count", "invalid_record_count", "verdict_counts")},
            "oracle_is_general_traffic_estimate": False,
        },
        "raw_text_in_report": False, "raw_stable_ids_in_report": False,
        "new_test_used": False, "labels_changed": False, "models_executed": False,
        "gate_a_pass": False, "safety_threshold": .0025,
    }
    print(canonical_json_bytes(report).decode("utf-8"))


if __name__ == "__main__":
    main()
