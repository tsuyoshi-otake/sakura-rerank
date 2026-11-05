"""Bound graph inventory, source provenance and write-once trial artifacts."""
import gzip
import json
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.relation_witnesses import WitnessGraph

sys.path.insert(0, "research/issue-32-source-relations")
try:
    import relation_common as prior
finally:
    sys.path.pop(0)
sys.path.insert(0, "research/issue-49-annotation-first")
try:
    from annotation_common import authenticate as source_identity, read_work, compressed_rows, save, sha, read_json, boundary
finally:
    sys.path.pop(0)

ROOT = Path("data/generated/issue-32-consumed-source-v1")
PLAN = Path("research/issue-32-consumed-source/plan-v1.json")
PLAN_COMMIT = "0956550529066046f4c5d294a4c9ce79412b79de"
ANNOTATIONS = Path("data/generated/issue-49-annotation-first-v1")


def load_inventory():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, expected in plan["inputs"].items():
        if sha(path) != expected:
            raise ValueError("consumption_bound_input_changed")
    records, roles, cohorts, _, _ = prior.load_population()
    records.sort(key=lambda row: row["stable_id"])
    report = read_json(prior.ROOT / "report.json")
    verified = read_json(prior.ROOT / "verification.json")
    if (verified["status"] != "passed" or verified["report_sha256"] != sha(prior.ROOT / "report.json")
            or prior.order_digest(records) != report["node_order_sha256"]):
        raise ValueError("consumption_graph_proof_differs")
    values = {name: prior.read_array(report["artifacts"][name], maximum=4_000_000) for name in ("left", "right", "kinds")}
    graph = WitnessGraph(records, **values, audit=report["graph"])
    identity = prior.read_array(report["artifacts"]["identity"], maximum=1_000_000)
    if len(records) != plan["population"]["nodes"]:
        raise ValueError("consumption_inventory_population_differs")
    return graph, identity, roles, cohorts, plan


def write_rows(name, records):
    path = ROOT / (name + ".jsonl.gz")
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as stream:
        for row in records:
            stream.write(canonical_json_bytes(row) + b"\n")
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("consumption_artifact_size_bound")
    return dict(path=path.name, sha256=sha(path))


def read_rows(receipt):
    path = ROOT / receipt["path"]
    if path.parent != ROOT or sha(path) != receipt["sha256"]:
        raise ValueError("consumption_artifact_changed")
    return compressed_rows(path)
