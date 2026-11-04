"""Read-only replay of the fixed research-reference evidence; no conversion."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.reference_probe import authenticate_identity
from run_reference_probe import ROOT, BINDING, DICTIONARY, legacy_inputs, validate_result

BINDING_COMMIT = "b12db1c5ab5b0c0ca1337665ec654bf784b1b645"
PROBE = Path("data/generated/issue-31-kwdlc-probe-v1")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def read(path: Path):
    return json.loads(path.read_bytes())


def wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p, d = successes / total, 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [max(0.0, center - radius), min(1.0, center + radius)]


def verify() -> dict:
    committed = subprocess.check_output(
        ["git", "show", BINDING_COMMIT + ":" + BINDING.as_posix()], timeout=30)
    binding_hash = hashlib.sha256(committed).hexdigest()
    identity = authenticate_identity(BINDING, binding_hash, ROOT / "probe-exporter.exe", DICTIONARY)
    binding = json.loads(committed)
    for build in binding["independent_builds"]:
        require(read(ROOT / ("build-" + build["build_id"] + ".json")) == build, "build_receipt_changed")
        require(sha(ROOT / ("build-" + build["build_id"] + ".log")) == build["log_sha256"], "build_log_changed")

    legacy, requests = legacy_inputs()
    regression = validate_result(ROOT / "regression", requests, identity)
    matched = 0
    # Independently compare every candidate dict and the complete search terminal.
    for old, new in zip(legacy, regression, strict=True):
        require(old["stable_id"] == new["stable_id"] and old["reading"] == new["reading"], "regression_population_changed")
        for name in ("training_top32", "production_top6"):
            before, after = old["candidate_snapshots"][name], new["candidate_snapshots"][name]
            require(before["candidates"] == after["candidates"], "candidate_feature_changed")
            for key in ("limit", "source", "feature_contract_version", "reading"):
                require(before[key] == after[key], "snapshot_contract_changed")
        before, after = (r["candidate_snapshots"]["training_top32"]["exporter_run"] for r in (old, new))
        for key in ("contract_version", "requested_limit", "effective_converter_bound", "returned_count", "result_status"):
            require(before[key] == after[key], "search_terminal_changed")
        matched += 1
    require(matched == 100 and read(ROOT / "regression.json")["matched"] == matched, "regression_count_changed")

    prior = read(Path("reports/issue-31-kwdlc-probe-verification-v1.json"))
    for name, digest in prior["old_artifact_hashes_unchanged"].items():
        require(sha(Path(name)) == digest, "historical_artifact_changed")
    for name, digest in prior["retained_probe_artifact_hashes"].items():
        require(sha(PROBE / name) == digest, "annotation_artifact_changed")
    source_hashes = sorted(sha(p) for p in (PROBE / "source").iterdir() if p.is_file())
    require(source_hashes == prior["source_file_sha256_sorted"], "annotation_source_changed")
    require(len(source_hashes) == 50, "annotation_source_population_changed")

    requests = (PROBE / "requests-r2.jsonl").read_bytes()
    targets = {t["stable_id"]: t for t in map(json.loads, (PROBE / "targets-r2.jsonl").read_bytes().splitlines())}
    rows = validate_result(ROOT / "kwdlc-a", requests, identity)
    validate_result(ROOT / "kwdlc-b", requests, identity)
    require((ROOT / "kwdlc-a/output.jsonl").read_bytes() == (ROOT / "kwdlc-b/output.jsonl").read_bytes(), "repeated_output_changed")
    require(len(targets) == len(rows) == 50 and set(targets) == {r["stable_id"] for r in rows}, "annotation_population_changed")
    ranks, terminals, segment_counts, categories = Counter(), Counter(), Counter(), Counter()
    counts = {str(k): 0 for k in (1, 5, 6, 10, 32)}
    for row in rows:
        snapshot = row["candidate_snapshots"]["training_top32"]
        candidates = snapshot["candidates"]
        found = next((i for i, c in enumerate(candidates, 1) if c["surface"] == targets[row["stable_id"]]["surface"]), None)
        ranks[str(found) if found else "absent"] += 1
        terminals[snapshot["exporter_run"]["result_status"]] += 1
        for k in counts:
            counts[k] += int(found is not None and found <= int(k))
        if found:
            candidate = candidates[found - 1]
            segment_counts[str(len(candidate["segments"]))] += 1
            categories[candidate["source_category"]] += 1
    for mode in ("kwdlc-a", "kwdlc-b"):
        summary = read(ROOT / (mode + ".json"))
        require(summary["source_exact_presence"] == counts and summary["source_rank_distribution"] == ranks, "aggregate_rank_disagreement")
        require(summary["terminal_counts"] == terminals and summary["denominator"] == 50, "aggregate_terminal_disagreement")
    executions = {mode: read(ROOT / mode / "execution.json") for mode in ("regression", "kwdlc-a", "kwdlc-b")}
    for mode, receipt in executions.items():
        expected_count = 100 if mode == "regression" else 50
        require(receipt["status"] == "complete" and receipt["measured_count"] == receipt["request_count"] == expected_count, "incomplete_execution")
        require(receipt["exit_code"] == 0 and receipt["binding_sha256"] == binding_hash, "unbound_execution")
        require(receipt["output_sha256"] == sha(ROOT / mode / "output.jsonl"), "execution_output_changed")
    require(not subprocess.check_output(["git", "diff", "4fab57baf5fdbb1730bb780bb6f8021637656bc5", "--",
        "src/sakura_rerank/data/contracts.py", "src/sakura_rerank/data/research_exporter.py"], timeout=30), "legacy_admission_changed")
    return dict(kind="reference_probe_evidence_verification", schema_version=1,
        binding_commit=BINDING_COMMIT, binding_sha256=binding_hash,
        executable_sha256=identity["exporter_binary_sha256"], dictionary_sha256=sha(DICTIONARY),
        build_receipts_match=True, repeated_builds_identical=True, regression_matched=matched,
        regression_mismatched=0, historical_binary_equivalence_proven=False,
        denominator=50, source_exact_presence=counts, rank_distribution=dict(ranks),
        descriptive_source_presence_wilson_95={k: wilson(n, 50) for k, n in counts.items()},
        interval_scope="Descriptive binomial intervals on this fixed selected development population; not Gold accuracy or a population-level IME safety guarantee",
        source_target_path_categories=dict(categories), source_target_segment_counts=dict(segment_counts),
        terminal_counts=dict(terminals), executions=executions, repeated_outputs_identical=True,
        old_artifact_hashes_unchanged=prior["old_artifact_hashes_unchanged"],
        previous_probe_hashes_unchanged=prior["retained_probe_artifact_hashes"],
        source_hashes_unchanged=50, independent_recount_agrees=True,
        legacy_admission_unchanged=True, additional_corpus_requests=0,
        models_trained=0, labels_changed=False, independently_certified_labels=0,
        gate_a_pass=False, new_final_test_used=False, safety_threshold=0.0025)


if __name__ == "__main__":
    print(canonical_json_bytes(verify()).decode("utf-8"))
