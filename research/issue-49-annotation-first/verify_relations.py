"""Recount exact memberships with tuple keys and reversed historical order."""
from collections import Counter, defaultdict
import json

from sakura_rerank.data.contracts import canonical_json_hash
from annotation_common import ROOT, compressed_rows, history_and_original_train, read_json, save, sha
from audit_relations import historical_roles
from prepare_annotations import verified_preparation


def run():
    verified_preparation()
    report = read_json(ROOT / "relation-audit.json")
    if sha(ROOT / "relation-witnesses.json") != report["witnesses_sha256"]:
        raise ValueError("relation_witnesses_changed")
    witnesses = read_json(ROOT / "relation-witnesses.json")
    history, old_train, _ = history_and_original_train()
    roles = historical_roles(history)
    if dict(Counter(roles.values())) != report["historical_roles"]:
        raise ValueError("relation_role_recount_differs")
    h_paragraphs, h_signatures = defaultdict(set), defaultdict(set)
    for row in reversed(history):
        source = row["source"]
        h_paragraphs[source["paragraph_hash"]].add(row["stable_id"])
        signature = tuple(sorted(set(source["sentence_shingle_hashes"])))
        if signature:
            h_signatures[signature].add(row["stable_id"])
    actual = {}
    for row in compressed_rows(ROOT / "prepared/coverage.jsonl.gz"):
        source = row["source"]
        for kind, key, index, text_hash in (
                ("paragraph", source["paragraph_hash"], h_paragraphs, source["paragraph_hash"]),
                ("sentence_signature", tuple(sorted(set(source["sentence_shingle_hashes"]))), h_signatures, source["sentence_hash"])):
            if key not in index:
                continue
            normalized_key = canonical_json_hash(list(key)) if kind == "sentence_signature" else key
            members = actual.setdefault((kind, normalized_key), dict(historical_ids=index[key], coverage_ids=set(), works=set(), text_hashes=set()))
            members["coverage_ids"].add(row["stable_id"])
            members["works"].add(source["article_id"])
            members["text_hashes"].add(text_hash)
    if len(actual) != len(witnesses["groups"]):
        raise ValueError("relation_shared_group_count_differs")
    for group in witnesses["groups"]:
        measured = actual[(group["kind"], group["key"])]
        if any(set(group[name]) != values for name, values in measured.items()):
            raise ValueError("relation_shared_membership_differs")
    relation = read_json(ROOT / "isolated/relations.json")
    newly = set(read_json(ROOT / "isolated/newly-connected-old-train.json"))
    old_counts, new_counts, occupancy = Counter(), Counter(), defaultdict(Counter)
    for population, records in (("old_train", reversed(old_train)), ("new_annotation", compressed_rows(ROOT / "prepared/targets.jsonl.gz"))):
        for row in records:
            key = row["stable_id"]
            state = "excluded" if key in relation["excluded"] else "retained"
            occupancy[relation["components"][key]][population + "/" + state] += 1
            if population == "new_annotation":
                new_counts[state] += 1
                continue
            corpus = "aozora" if row["source"]["article_id"].startswith("aozora-work-") else "wikipedia"
            old_counts[corpus + "/" + state] += 1
            if key in newly:
                old_counts[corpus + "/newly_connected"] += 1
                occupancy[relation["components"][key]]["old_train/newly_connected"] += 1
    if (dict(old_counts) != report["old_train_counts"] or dict(new_counts) != report["new_annotation_counts"]
            or occupancy != witnesses["component_occupancy"]):
        raise ValueError("relation_training_occupancy_recount_differs")
    result = dict(kind="annotation_relation_verification", status="passed", shared_groups=len(actual),
        historical_rows=len(history), original_train_rows=len(old_train), new_target_rows=sum(new_counts.values()),
        exact_memberships_and_component_occupancy_equal=True, rules_unchanged=True, exclusions_restored=0,
        report_sha256=sha(ROOT / "relation-audit.json"), script_sha256=sha(__file__),
        model_fits=0, model_inferences=0, final_test_used=False, gold_certified=False)
    save(ROOT / "relation-verification.json", result)
    save("reports/issue-49-annotation-relation-verification-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
