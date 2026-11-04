"""Separate, hash-bound research reference checks; never legacy dataset admission.

The shared candidate/snapshot feature validator is reused without changing its
rules. Provenance and artifact admission belong to this probe boundary instead.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from collections import Counter

from .contracts import (
    canonical_json_hash,
    _require_identifier, _require_string, _validate_snapshot,
)
from .research_exporter import validate_export_records

SOURCE_COMMIT = "5eefa2ffe15297e563da281432cece56049a1b09"
DICTIONARY_SHA = "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad"
SOURCE_SHA = "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"
SEED = 20261104
MAX_BYTES = 512 * 1024 * 1024
MAX_LINE = 256 * 1024
MAX_ROWS = 100_000
RECORD_TYPE = "research_probe_converter_snapshot"


def _scan(path: Path, expected_sha: str, selected: set[str] | None = None):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("source_file_outside_bound")
    digest, counts, ids, kept = hashlib.sha256(), Counter(), set(), []
    size = 0
    with path.open("rb") as stream:
        while line := stream.readline(MAX_LINE + 1):
            size += len(line)
            if len(line) > MAX_LINE or size > MAX_BYTES or sum(counts.values()) >= MAX_ROWS:
                raise ValueError("source_stream_outside_bound")
            digest.update(line)
            split = [name for name in ("train", "dev", "final-holdout")
                     if b',"split":"' + name.encode() + b'",' in line]
            if len(split) != 1:
                raise ValueError("canonical_split_marker_required")
            counts[split[0]] += 1
            if split[0] != "train":
                continue
            matches = re.findall(rb'(?<!\\)"stable_id":"([^"\\]+)"', line)
            if len(matches) != 1:
                raise ValueError("one_canonical_identity_required")
            stable = _require_identifier(matches[0].decode("ascii"), "stable_id")
            if stable in ids:
                raise ValueError("duplicate_train_identity")
            ids.add(stable)
            if selected is not None and stable in selected:
                kept.append(line)
    if digest.hexdigest() != expected_sha:
        raise ValueError("source_hash_differs")
    if selected is not None and (not selected <= ids or len(kept) != len(selected)):
        raise ValueError("selected_train_population_missing")
    return ids, dict(sorted(counts.items())), kept


def select_train_ids(path: Path, expected_sha: str, count: int = 100) -> dict:
    """Read only canonical split/ID markers; no JSON or candidate parsing."""
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("selection_count_outside_bound")
    ids, counts, _ = _scan(path, expected_sha)
    if len(ids) < count:
        raise ValueError("insufficient_train_population")
    selected = sorted(ids, key=lambda stable: (canonical_json_hash([SEED, stable]), stable))[:count]
    return dict(kind="reference_probe_train_selection", schema_version=1, seed=SEED,
                source_sha256=expected_sha, split_counts=counts,
                train_ids_sha256=canonical_json_hash(sorted(ids)),
                selected_ids=selected, selected_ids_sha256=canonical_json_hash(selected),
                candidate_contents_parsed=False, dev_or_holdout_parsed=False)


def selected_legacy_records(path: Path, selection: dict) -> list[dict]:
    ids = selection["selected_ids"]
    if (not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids)
            or canonical_json_hash(ids) != selection["selected_ids_sha256"]):
        raise ValueError("selection_identity_differs")
    _, _, raw = _scan(path, selection["source_sha256"], set(ids))
    records = []
    for line in raw:
        row = json.loads(line)
        if row["split"] != "train" or row["is_fixture"] or row["training_eligible"] is not True:
            raise ValueError("selected_record_is_not_real_eligible_train")
        records.append(dict(schema_version=3, record_type="research_converter_snapshot",
            stable_id=row["stable_id"], reading=row["reading"],
            converter_provenance=row["converter_provenance"], candidate_snapshots=row["candidate_snapshots"]))
    return validate_export_records(sorted(records, key=lambda row: row["stable_id"]))


def authenticate_identity(path: Path, expected_sha: str, binary: Path, dictionary: Path) -> dict:
    """Expected receipt hash must come from a separately committed measurement."""
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("identity_commitment_differs")
    binding = json.loads(raw)
    if (binding.get("kind") != "reference_probe_identity_binding" or binding.get("schema_version") != 1
            or binding.get("legacy_training_eligible") is not False):
        raise ValueError("probe_binding_contract_differs")
    identity = binding["runtime_manifest"]
    if (identity["manifest_kind"] != "research_probe_top32_exporter"
            or identity["verification_status"] != "unverified"
            or identity["sakura_input_head"] != SOURCE_COMMIT or identity["dictionary_sha256"] != DICTIONARY_SHA
            or identity["effective_converter_bound"] != 32 or identity["requested_limit"] != 32
            or identity["user_dictionary_enabled"] is not False):
        raise ValueError("probe_identity_differs")
    builds = binding["independent_builds"]
    if (len(builds) != 2 or len({b["build_id"] for b in builds}) != 2
            or any(b["status"] != "built" or b["binary_sha256"] != identity["exporter_binary_sha256"]
                   or b["recipe_git_sha"] != identity["exporter_git_sha"] for b in builds)):
        raise ValueError("independent_build_evidence_differs")
    for file, expected in ((binary, identity["exporter_binary_sha256"]), (dictionary, DICTIONARY_SHA)):
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("runtime_artifact_hash_differs")
    return identity


def validate_probe_records(raw: bytes, requests: list[dict], identity: dict) -> list[dict]:
    if not raw or len(raw) > 32 * 1024 * 1024 or not 1 <= len(requests) <= 100:
        raise ValueError("probe_batch_outside_bound")
    expected = {r["stable_id"]: r["reading"] for r in requests}
    if len(expected) != len(requests):
        raise ValueError("duplicate_request")
    rows = []
    for line in raw.splitlines():
        if len(line) > MAX_LINE or len(rows) >= len(requests):
            raise ValueError("probe_output_outside_bound")
        row = json.loads(line)
        if (set(row) != {"schema_version", "record_type", "stable_id", "reading", "converter_provenance", "candidate_snapshots"}
                or type(row["schema_version"]) is not int or row["schema_version"] != 3
                or row["record_type"] != RECORD_TYPE):
            raise ValueError("probe_record_contract_differs")
        stable = _require_identifier(row["stable_id"], "stable_id")
        reading = _require_string(row["reading"], "reading", max_chars=128)
        if expected.get(stable) != reading:
            raise ValueError("request_output_binding_differs")
        provenance = dict(kind="sakura_input_converter_export", sakura_input_head=SOURCE_COMMIT,
                          dictionary_sha256=DICTIONARY_SHA, feature_contract_version=1)
        if row["converter_provenance"] != provenance:
            raise ValueError("probe_provenance_differs")
        snapshots = row["candidate_snapshots"]
        if set(snapshots) != {"training_top32", "production_top6"}:
            raise ValueError("probe_snapshot_keys_differ")
        full = _validate_snapshot(snapshots["training_top32"], "probe.top32", limit=32, reading=reading,
            is_fixture=False, converter_provenance=provenance, require_exporter_run=True)
        prefix = _validate_snapshot(snapshots["production_top6"], "probe.top6", limit=6, reading=reading,
            is_fixture=False, converter_provenance=provenance)
        run = full["exporter_run"]
        if (run["exporter_git_sha"] != identity["exporter_git_sha"]
                or run["exporter_binary_sha256"] != identity["exporter_binary_sha256"]
                or run["verification_status"] != "unverified" or run["effective_converter_bound"] != 32
                or prefix["candidates"] != full["candidates"][:6]):
            raise ValueError("probe_execution_identity_or_prefix_differs")
        rows.append(row)
    if [row["stable_id"] for row in rows] != sorted(expected):
        raise ValueError("output_population_or_order_differs")
    return rows


def compare_candidates(legacy: list[dict], probe: list[dict]) -> dict:
    if [r["stable_id"] for r in legacy] != [r["stable_id"] for r in probe] or not legacy:
        raise ValueError("comparison_population_differs")
    outcomes = Counter()
    for before, after in zip(legacy, probe):
        failures = []
        if before["reading"] != after["reading"]:
            failures.append("reading")
        for name in ("training_top32", "production_top6"):
            left, right = before["candidate_snapshots"][name], after["candidate_snapshots"][name]
            for field in ("limit", "source", "feature_contract_version", "reading", "candidates"):
                if left[field] != right[field]:
                    failures.append(name + "." + field)
        left, right = (r["candidate_snapshots"]["training_top32"]["exporter_run"] for r in (before, after))
        for field in ("contract_version", "requested_limit", "effective_converter_bound", "returned_count", "result_status"):
            if left[field] != right[field]:
                failures.append("run." + field)
        outcomes.update(failures or ["exact_candidate_and_terminal_match"])
    matched = outcomes["exact_candidate_and_terminal_match"]
    return dict(denominator=len(legacy), matched=matched, mismatched=len(legacy)-matched,
        differences=dict(sorted(outcomes.items())), passed=matched==len(legacy),
        declared_provenance_changes=["sakura_input_head", "record_type", "exporter_git_sha",
                                     "exporter_binary_sha256", "verification_status", "content_sha256"],
        historical_binary_equivalence_proven=False)
