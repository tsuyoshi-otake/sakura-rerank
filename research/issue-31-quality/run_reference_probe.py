"""Execute committed probe identities on fixed regression or annotation requests."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_jsonl_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import (
    authenticate_identity, compare_candidates, selected_legacy_records, validate_probe_records,
)

ROOT = Path("data/generated/issue-31-reference-exporter-v1")
DICTIONARY = Path("data/generated/issue-31-exporter-restoration-v1/system.dic")
BINDING = Path("manifests/reference-probe-identity-v1.json")
SELECTION_SHA = "96b7f11e66c46619ea145d2cc425928d4805b3cefa961c9c0616734921479b44"
KWDLC_REQUEST_SHA = "411b41590e7b5037f6f18b546280a1617b36b9243caffc7b36b0aa0c0e09dcf0"
KWDLC_TARGET_SHA = "f80a3e2661de574074d00fad7dbc7e7e2e92824a54b2db43483f1bb36c22fa74"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pinned(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("input_hash_differs")
    return raw


def legacy_inputs():
    selection = json.loads(pinned(ROOT / "train-selection.json", SELECTION_SHA))
    legacy = selected_legacy_records(Path("data/generated/issue15-v5-slot120/frozen-split.jsonl"), selection)
    raw = canonical_jsonl_bytes([dict(stable_id=r["stable_id"], reading=r["reading"]) for r in legacy])
    if raw != (ROOT / "legacy-requests.jsonl").read_bytes() or canonical_jsonl_bytes(legacy) != (ROOT / "legacy-reference.jsonl").read_bytes():
        raise ValueError("prepared_regression_changed")
    return legacy, raw


def validate_result(directory: Path, requests_raw: bytes, identity: dict) -> list[dict]:
    raw = (directory / "output.jsonl").read_bytes()
    requests = [json.loads(line) for line in requests_raw.splitlines()]
    rows = validate_probe_records(raw, requests, identity)
    statuses = Counter(row["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"] for row in rows)
    expected = dict(dictionary_sha256=identity["dictionary_sha256"], exporter_binary_sha256=identity["exporter_binary_sha256"],
        exporter_git_sha=identity["exporter_git_sha"], effective_converter_bound=32, requested_limit=32,
        input_sha256=digest(requests_raw), output_sha256=digest(raw), record_count=len(requests),
        search_exhausted_record_count=statuses["search_exhausted"], truncated_record_count=statuses["truncated"],
        total_candidate_count=sum(len(row["candidate_snapshots"]["training_top32"]["candidates"]) for row in rows),
        status="exported", verification_status="unverified")
    if json.loads((directory / "native-report.json").read_bytes()) != expected:
        raise ValueError("native_report_differs_from_validated_output")
    return rows


def execute(mode: str, requests_raw: bytes, identity: dict, binding_sha: str):
    directory = ROOT / mode
    directory.mkdir()
    receipt = dict(kind="reference_probe_execution", mode=mode, request_count=len(requests_raw.splitlines()),
        binding_sha256=binding_sha, requests_sha256=digest(requests_raw), timeout_seconds=120,
        status="failed", measured_count=0, legacy_training_eligible=False)
    start = time.monotonic()
    try:
        write_once(directory / "input.jsonl", requests_raw)
        write_once(directory / "runtime-manifest.json", canonical_json_bytes(identity) + b"\n")
        command = [str((ROOT / "probe-exporter.exe").resolve()), "--input", str((directory / "input.jsonl").resolve()),
            "--dictionary", str(DICTIONARY.resolve()), "--output", str((directory / "output.jsonl").resolve()),
            "--report", str((directory / "native-report.json").resolve()),
            "--identity-manifest", str((directory / "runtime-manifest.json").resolve()), "--limit", "32"]
        with (directory / "stdout.log").open("xb") as out, (directory / "stderr.log").open("xb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                receipt["exit_code"] = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=True, timeout=30)
                process.wait(timeout=30)
                raise ValueError("converter_timeout") from None
        if receipt["exit_code"]:
            raise ValueError("converter_failed")
        authenticate_identity(BINDING, binding_sha, ROOT / "probe-exporter.exe", DICTIONARY)
        rows = validate_result(directory, requests_raw, identity)
        receipt.update(status="complete", measured_count=len(rows), output_sha256=digest((directory / "output.jsonl").read_bytes()))
        return rows
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - start, 3)
        write_once(directory / "execution.json", canonical_json_bytes(receipt) + b"\n")


def run(mode: str, binding_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", binding_commit):
        raise ValueError("binding_commit_required")
    committed = subprocess.check_output(["git", "show", binding_commit + ":" + BINDING.as_posix()], timeout=30)
    binding_sha = digest(committed)
    identity = authenticate_identity(BINDING, binding_sha, ROOT / "probe-exporter.exe", DICTIONARY)
    legacy, requests_raw = legacy_inputs()
    if mode == "regression":
        rows = execute(mode, requests_raw, identity, binding_sha)
        result = dict(compare_candidates(legacy, rows), kind="reference_probe_regression", binding_commit=binding_commit,
                      binding_sha256=binding_sha, requests_sha256=digest(requests_raw), dev_or_holdout_parsed=False)
        write_once(ROOT / "regression.json", canonical_json_bytes(result) + b"\n")
        return result
    # Recheck recorded regression output, rather than trusting a mutable pass flag.
    regression = validate_result(ROOT / "regression", requests_raw, identity)
    comparison = compare_candidates(legacy, regression)
    if not comparison["passed"]:
        raise ValueError("legacy_candidate_disagreement_blocks_probe")
    receipt = json.loads((ROOT / "regression/execution.json").read_bytes())
    if receipt["status"] != "complete" or receipt["binding_sha256"] != binding_sha:
        raise ValueError("completed_bound_regression_required")
    probe_root = Path("data/generated/issue-31-kwdlc-probe-v1")
    if mode == "kwdlc-b" and not (ROOT / "kwdlc-a/execution.json").is_file():
        raise ValueError("first_probe_execution_required")
    request_raw = pinned(probe_root / "requests-r2.jsonl", KWDLC_REQUEST_SHA)
    targets = [json.loads(line) for line in pinned(probe_root / "targets-r2.jsonl", KWDLC_TARGET_SHA).splitlines()]
    rows = execute(mode, request_raw, identity, binding_sha)
    if mode == "kwdlc-b" and (ROOT / "kwdlc-a/output.jsonl").read_bytes() != (ROOT / mode / "output.jsonl").read_bytes():
        raise ValueError("repeated_probe_output_differs")
    expected = {row["stable_id"]: row for row in targets}
    if len(expected) != 50 or {row["stable_id"] for row in rows} != set(expected):
        raise ValueError("fixed_annotation_population_differs")
    counts, terminals, rank_counts = Counter(), Counter(), Counter()
    for row in rows:
        snapshot = row["candidate_snapshots"]["training_top32"]
        surfaces = [candidate["surface"] for candidate in snapshot["candidates"]]
        target = expected[row["stable_id"]]["surface"]
        found = surfaces.index(target) + 1 if target in surfaces else None
        rank_counts[str(found) if found is not None else "absent"] += 1
        for k in (1, 5, 6, 10, 32):
            counts[str(k)] += int(found is not None and found <= k)
        terminals[snapshot["exporter_run"]["result_status"]] += 1
    result = dict(kind="external_annotation_reference_probe", mode=mode, binding_commit=binding_commit,
        binding_sha256=binding_sha, denominator=50, measured=50, execution_failures=0,
        source_exact_presence=dict(counts), source_rank_distribution=dict(sorted(rank_counts.items())),
        terminal_counts=dict(terminals), output_sha256=digest((ROOT / mode / "output.jsonl").read_bytes()),
        absent_from_top32=50-counts["32"], present_below_rank1=counts["32"]-counts["1"],
        interpretation="Source-annotation surface presence, not independently certified Gold or model accuracy",
        independently_certified_labels=0, gate_a_pass=False, labels_changed=False, models_trained=0, new_final_test_used=False)
    write_once(ROOT / (mode + ".json"), canonical_json_bytes(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("regression", "kwdlc-a", "kwdlc-b"), required=True)
    parser.add_argument("--binding-commit", required=True)
    args = parser.parse_args()
    result = run(args.mode, args.binding_commit)
    print(canonical_json_bytes(result).decode("utf-8"))
    if args.mode == "regression" and not result["passed"]:
        sys.exit(3)
