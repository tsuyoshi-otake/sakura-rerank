"""Authenticated metadata population and bounded binary research artifacts."""
from array import array
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_hash

sys.path.insert(0, "research/issue-49-annotation-first")
try:
    from annotation_common import (ROOT as PRIOR, boundary, compressed_rows,
        history_and_original_train, read_json, save, sha)
    from prepare_annotations import verified_preparation
    from audit_relations import historical_roles
finally:
    sys.path.pop(0)

ROOT = Path("data/generated/issue-32-source-relations-v1")
PLAN = Path("research/issue-32-source-relations/plan-v1.json")
PLAN_COMMIT = "fb3b55841ce7b39e99e4ae8d4b61b00a87dce836"
EVALUATION_ROLES = frozenset(("frozen_dev", "frozen_final-holdout", "reserved_growth_evaluation", "exposed_kwdlc_research_evaluation"))


def load_population():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, expected in plan["inputs"].items():
        if sha(path) != expected:
            raise ValueError("relation_diagnostic_bound_input_changed")
    verified_preparation()
    historical, old_train, proof = history_and_original_train()
    if proof != read_json(PRIOR / "isolation.json")["historical"]:
        raise ValueError("relation_diagnostic_history_changed")
    roles = historical_roles(historical)
    cohorts = {r["stable_id"]: "old_train/" + ("aozora" if r["source"]["article_id"].startswith("aozora-work-") else "wikipedia") for r in old_train}
    records = historical + old_train
    records.extend(compressed_rows(PRIOR / "prepared/coverage.jsonl.gz"))
    for row in compressed_rows(PRIOR / "prepared/targets.jsonl.gz"):
        records.append(dict(stable_id=row["stable_id"], population="train", source=row["source"],
            input_hash=canonical_json_hash([row["left_context"], row["reading"]])))
        cohorts[row["stable_id"]] = "new_annotation"
    counts = Counter(r["population"] for r in records)
    expected = plan["population"]
    if (len(records) != expected["total"] or len(historical) != expected["historical"]
            or len(old_train) != expected["old_train"] or counts["source_coverage"] != expected["source_coverage"]
            or counts["train"] != expected["old_train"] + expected["new_annotation"]):
        raise ValueError("relation_diagnostic_population_changed")
    newly = set(read_json(PRIOR / "isolated/newly-connected-old-train.json"))
    return records, roles, cohorts, newly, plan


def scopes(identifier, cohorts, newly):
    cohort = cohorts.get(identifier)
    if cohort is None:
        return ()
    return ((cohort,) if cohort == "new_annotation" else
            ("old_train", cohort) + (("old_train/newly_connected_in_49",) if identifier in newly else ()))


def component_summary(records, labels, roles, cohorts, newly):
    role_sets, sizes = defaultdict(set), Counter(labels)
    for index, row in enumerate(records):
        if row["stable_id"] in roles:
            role_sets[labels[index]].add(roles[row["stable_id"]])
    summary = defaultdict(Counter)
    for row, component in zip(records, labels):
        found = role_sets[component]
        for scope in scopes(row["stable_id"], cohorts, newly):
            counts = summary[scope]
            counts["rows"] += 1
            counts["all_history_connected"] += bool(found)
            counts["explicit_evaluation_connected"] += bool(found & EVALUATION_ROLES)
            counts["known_training_connected"] += "frozen_train" in found
            counts["unknown_history_connected"] += bool(found - EVALUATION_ROLES - {"frozen_train"})
            counts["not_connected_to_any_history"] += not found
    return dict(components=len(sizes), largest_component_nodes=max(sizes.values()), cohorts=dict(summary))


def order_digest(records):
    digest = hashlib.sha256()
    for row in records:
        digest.update(row["stable_id"].encode("ascii") + b"\n")
    return digest.hexdigest()


def write_array(name, values):
    if sys.byteorder != "little" or (values.typecode != "B" and values.itemsize != 4):
        raise ValueError("relation_array_platform_contract")
    path = ROOT / (name + ".gz")
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as stream:
        stream.write(values.tobytes())
    return dict(path=path.name, sha256=sha(path), typecode=values.typecode, count=len(values), byte_order="little")


def read_array(receipt, *, maximum):
    path = ROOT / receipt["path"]
    if (path.parent != ROOT or receipt["typecode"] not in ("I", "i", "B")
            or not 0 <= receipt["count"] <= maximum or receipt["byte_order"] != "little"
            or sha(path) != receipt["sha256"]):
        raise ValueError("relation_array_receipt_invalid")
    values = array(receipt["typecode"])
    if sys.byteorder != "little" or (values.typecode != "B" and values.itemsize != 4):
        raise ValueError("relation_array_platform_contract")
    expected = values.itemsize * receipt["count"]
    with gzip.open(path, "rb") as stream:
        raw = stream.read(expected + 1)
    if len(raw) != expected:
        raise ValueError("relation_array_size_differs")
    values.frombytes(raw)
    return values
