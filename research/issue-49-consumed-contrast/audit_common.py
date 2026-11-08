"""Authenticate the unchanged consumption scope and prior candidate receipts."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.reference_probe import authenticate_identity

sys.path.insert(0, "research/issue-32-consumed-source")
try:
    import consumption_common as source
finally:
    sys.path.pop(0)
sys.path.insert(0, "research/issue-48-contrast-data")
try:
    from audit_capacity import authenticate_candidates
finally:
    sys.path.pop(0)

ROOT = Path("data/generated/issue-49-consumed-contrast-v1/attempt-02")
PLAN = Path("research/issue-49-consumed-contrast/plan-v1.json")
PLAN_COMMIT = "784bd2da86d6fbcae39b966dcc57939ceb7c7bbb"
BINDING = Path("manifests/consumed-contrast-forward-v1.json")
boundary, read_json, save, sha = source.boundary, source.read_json, source.save, source.sha


def scope():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, digest in plan["inputs"].items():
        if sha(path) != digest:
            raise ValueError("consumed_contrast_frozen_input_changed")
    report = read_json(source.ROOT / "report.json")
    verified = read_json(source.ROOT / "verification.json")
    if verified["status"] != "passed" or verified["report_sha256"] != sha(source.ROOT / "report.json"):
        raise ValueError("consumed_contrast_scope_unverified")
    for receipt in report["artifacts"].values():
        if sha(source.ROOT / receipt["path"]) != receipt["sha256"]:
            raise ValueError("consumed_contrast_scope_artifact_changed")
    receipts = {r["stable_id"]: r for r in source.read_rows(report["artifacts"]["consumption"])}
    units = {r["unit_id"]: r for r in source.read_rows(report["artifacts"]["units"])}
    components = read_json(source.ROOT / report["artifacts"]["components"]["path"])
    targets = [dict(r, candidate_request_id="growth-reading-" + canonical_json_hash(r["reading"]))
               for r in source.compressed_rows(source.ANNOTATIONS / "prepared/targets.jsonl.gz") if r["stable_id"] in receipts]
    if (len(targets) != plan["population"]["targets"] or len(receipts) != len(targets)
            or set(components) != set(receipts) or {r["stable_id"] for r in targets} != set(receipts)):
        raise ValueError("consumed_contrast_population_changed")
    return plan, targets, components, receipts, units


def identity():
    return authenticate_identity(boundary.IDENTITY, read_json(PLAN)["inputs"][str(boundary.IDENTITY).replace("\\", "/")],
                                 boundary.BINARY, boundary.DICTIONARY)


def old_annotation_snapshots(identity_value):
    """Reauthenticate all original #49 requests, including terminal coverage."""
    old = source.ANNOTATIONS
    report = read_json(old / "candidate-report.json")
    if sha(old / "forward-execution.json") != report["execution_sha256"]:
        raise ValueError("consumed_contrast_old_execution_changed")
    bound = read_json("manifests/annotation-first-forward-v1.json")
    for name, digest in bound["artifacts"].items():
        if sha(old / name) != digest:
            raise ValueError("consumed_contrast_old_request_changed")
    requests = [json.loads(line) for line in (old / "new-requests.jsonl").read_bytes().splitlines()]
    execution = read_json(old / "forward-execution.json")
    if execution["not_attempted"] or len(execution["attempts"]) != len(requests):
        raise ValueError("consumed_contrast_old_requests_incomplete")
    snapshots = {}
    for index, attempt in enumerate(execution["attempts"]):
        directory = old / "candidates" / f"request-{index:04d}"
        if (attempt["index"] != index or attempt["status"] != "complete"
                or sha(directory / "execution.json") != attempt["execution_sha256"]):
            raise ValueError("consumed_contrast_old_receipt_changed")
        raw = canonical_json_bytes(requests[index]) + b"\n"
        snapshot = boundary.native.validate_result(directory, raw, identity_value)[0]
        snapshots[snapshot["stable_id"]] = snapshot
    return snapshots


def prior_evidence(targets):
    prior_plan = read_json("research/issue-48-contrast-data/plan-v2.json")
    proof, counts = authenticate_candidates(targets, prior_plan)
    if counts.get("failed_requests", 0):
        raise ValueError("consumed_contrast_old_failure_not_new_request")
    snapshots = old_annotation_snapshots(identity())
    needed = defaultdict(dict)
    for row in targets:
        needed[row["candidate_request_id"]][row["target"]] = row["reading"]
    reused = set()
    for request_id, snapshot in snapshots.items():
        for target, reading in needed.get(request_id, {}).items():
            if reading != snapshot["reading"]:
                raise ValueError("consumed_contrast_old_reading_changed")
            observed = candidate_evidence(target, snapshot)
            previous = proof[(request_id, target)]
            if previous["status"] != "acquisition_missing" and previous != observed:
                raise ValueError("consumed_contrast_cache_conflict")
            proof[(request_id, target)] = observed
            reused.add(request_id)
    return proof, dict(original_train=counts, original_annotation_readings=len(reused))


def write_rows(name, rows):
    path = ROOT / (name + ".jsonl.gz")
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as stream:
        for row in rows:
            stream.write(canonical_json_bytes(row) + b"\n")
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("consumed_contrast_artifact_bound")
    return dict(path=path.name, sha256=sha(path))


def read_rows(receipt):
    path = ROOT / receipt["path"]
    if path.parent != ROOT or sha(path) != receipt["sha256"]:
        raise ValueError("consumed_contrast_artifact_changed")
    return source.compressed_rows(path)
