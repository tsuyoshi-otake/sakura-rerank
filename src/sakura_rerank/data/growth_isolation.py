"""Research source/input isolation without admitting weak labels as legacy Gold."""
from collections import Counter, defaultdict
import json
import re

from .contracts import canonical_json_hash
from .growth_corpus import history_metadata
from .splitter import _build_leakage_components, _UnionFind, _union_groups

JSON_STRING = rb'"(?:[^"\\]|\\.)*"'
SESSION = re.compile(rb'"session":\{"left_context":(' + JSON_STRING + rb'),"left_context_policy":' + JSON_STRING + rb',"session_id":' + JSON_STRING + rb'\}')
READING = re.compile(rb',"reading":(' + JSON_STRING + rb'),"record_type":')


def historical_input_metadata(line):
    """Hash only the bounded input; never deserialize gold/candidate objects."""
    row = history_metadata(line)
    contexts, readings = SESSION.findall(line), READING.findall(line)
    if len(contexts) != 1 or len(readings) != 1:
        raise ValueError("historical_input_markers_differ")
    context, reading = json.loads(contexts[0]), json.loads(readings[0])
    if not len(context) <= 64 or not 1 <= len(reading) <= 128:
        raise ValueError("historical_input_outside_bound")
    row["input_hash"] = canonical_json_hash([context, reading])
    row["stable_id"] = "frozen-input-" + row["stable_id"]
    return row


def validate_metadata(row):
    if row.get("population") not in ("historical", "train", "evaluation"):
        raise ValueError("isolation_population_differs")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", row["stable_id"]):
        raise ValueError("isolation_identity_invalid")
    source = row["source"]
    if not isinstance(source["article_id"], str) or not 1 <= len(source["article_id"]) <= 256:
        raise ValueError("source_group_invalid")
    cluster = source["template_cluster_id"]
    if cluster is not None and (not isinstance(cluster, str) or not 1 <= len(cluster) <= 256):
        raise ValueError("source_cluster_invalid")
    hashes = source["sentence_shingle_hashes"]
    if not isinstance(hashes, list) or not 1 <= len(hashes) <= 512 or hashes != sorted(set(hashes)):
        raise ValueError("source_shingles_invalid")
    for value in [source["paragraph_hash"], source["sentence_hash"], *hashes]:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("source_hash_invalid")
    key = row.get("input_hash")
    if key is not None and not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("input_hash_invalid")
    if row["population"] != "historical" and key is None:
        raise ValueError("new_population_input_hash_required")


def isolate(records):
    """Quarantine every new member of a component touching history or both splits.

    The source-only core is deliberately shared with the existing splitter.
    This boundary validates its own weak-supervision metadata and does not call,
    weaken or impersonate the legacy label-admission contract.
    """
    if not 1 <= len(records) <= 500_000:
        raise ValueError("isolation_record_bound")
    ids = set()
    for row in records:
        validate_metadata(row)
        if row["stable_id"] in ids:
            raise ValueError("isolation_duplicate_identity")
        ids.add(row["stable_id"])
    leakage = _build_leakage_components(records, near_duplicate_threshold=0.8)
    union = _UnionFind(len(records))
    _union_groups(union, {str(i): members for i, members in enumerate(leakage.component_records)})
    exact = defaultdict(list)
    for i, row in enumerate(records):
        if row.get("input_hash") is not None:
            exact[row["input_hash"]].append(i)
    duplicates = _union_groups(union, exact)
    excluded, components, counts, sizes = {}, {}, Counter(), []
    for members in union.groups().values():
        populations = {records[i]["population"] for i in members}
        reason = "historical_relation" if "historical" in populations else (
            "cross_partition_relation" if len(populations) > 1 else None)
        component = canonical_json_hash(sorted(records[i]["stable_id"] for i in members))
        sizes.append(len(members))
        for i in members:
            row = records[i]
            if row["population"] == "historical":
                continue
            components[row["stable_id"]] = component
            if reason:
                excluded[row["stable_id"]] = reason
            counts[row["population"] + "/" + (reason or "retained")] += 1
    return excluded, components, dict(counts=dict(sorted(counts.items())),
        components=len(sizes), largest_component=max(sizes),
        near_pairs=leakage.near_pair_count, near_signature_comparisons=leakage.near_signature_comparison_count,
        exact_input_duplicate_groups=duplicates, raw_text_in_report=False)
