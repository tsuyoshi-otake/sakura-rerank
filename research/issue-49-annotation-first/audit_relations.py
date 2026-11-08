"""Read-only, preregistered provenance diagnostics; never relax isolation."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.growth_corpus import ID_PATTERN
from sakura_rerank.data.jawiki_preprocess import _sentences
from annotation_common import (ROOT, authenticate, boundary, compressed_rows,
    history_and_original_train, read_json, read_work, rows, save, sha)
from prepare_annotations import verified_preparation

PLAN = Path("research/issue-49-annotation-first/relation-audit-plan-v1.json")
PLAN_COMMIT = "3b75b80ea0f0f2561f6248a07dcdda5a9b52fc39"
FROZEN = Path("data/generated/issue15-v5-slot120/frozen-split.jsonl")
FROZEN_SHA = "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"
SPLIT = re.compile(rb'(?<!\\)"split":"([a-z-]+)"')


def historical_roles(history):
    if sha(FROZEN) != FROZEN_SHA:
        raise ValueError("relation_role_source_changed")
    frozen = {}
    with FROZEN.open("rb") as stream:
        for line in stream:
            identifiers, splits = ID_PATTERN.findall(line), SPLIT.findall(line)
            if len(identifiers) != 1 or len(splits) != 1 or splits[0] not in (b"train", b"dev", b"final-holdout"):
                raise ValueError("relation_role_markers_differ")
            key = "frozen-input-" + identifiers[0].decode("ascii")
            if key in frozen:
                raise ValueError("relation_role_duplicate_id")
            frozen[key] = "frozen_" + splits[0].decode("ascii")
    if len(frozen) != 17880:
        raise ValueError("relation_role_population_differs")
    context_units = {r["stable_id"] for r in rows("data/generated/issue-40-context-contrast-v1/source-coverage.jsonl")}
    roles = {}
    for row in history:
        key = row["stable_id"]
        if key in frozen:
            role = frozen[key]
        elif key.startswith("history-"):
            role = "six_generations_split_unknown"
        elif key.startswith("growth-"):
            role = "reserved_growth_evaluation"
        elif key in context_units or key.startswith(("exposed-kwdlc-", "exposed-context-", "language-source-unit-", "language-eval-history-")):
            role = "exposed_kwdlc_research_evaluation"
        else:
            role = "unclassified_history_do_not_reuse"
        roles[key] = role
    if not set(frozen) <= set(roles):
        raise ValueError("relation_frozen_roles_not_in_history")
    return roles


def relation_keys(row):
    source = row["source"]
    return {"paragraph": source["paragraph_hash"],
            "sentence_signature": canonical_json_hash(sorted(set(source["sentence_shingle_hashes"])))}


def shared_groups(history, coverage):
    """O(total signature bytes + membership count); no Cartesian pair expansion."""
    indices = {kind: defaultdict(list) for kind in ("paragraph", "sentence_signature")}
    for row in history:
        for kind, key in relation_keys(row).items():
            if kind == "sentence_signature" and not row["source"]["sentence_shingle_hashes"]:
                continue
            indices[kind][key].append(row["stable_id"])
    shared = {}
    for row in coverage:
        for kind, key in relation_keys(row).items():
            if key not in indices[kind]:
                continue
            group = shared.setdefault((kind, key), dict(kind=kind, key=key,
                historical_ids=sorted(indices[kind][key]), coverage_ids=[], works=set(), text_hashes=set()))
            group["coverage_ids"].append(row["stable_id"])
            group["works"].add(row["source"]["article_id"])
            group["text_hashes"].add(row["source"]["paragraph_hash" if kind == "paragraph" else "sentence_hash"])
    return [dict(g, coverage_ids=sorted(g["coverage_ids"]), works=sorted(g["works"]), text_hashes=sorted(g["text_hashes"]))
            for _, g in sorted(shared.items())]


def describe(text):
    counts = Counter()
    for char in text:
        category = unicodedata.category(char)
        if char.isspace():
            kind = "whitespace"
        elif "ぁ" <= char <= "ゖ":
            kind = "hiragana"
        elif "ァ" <= char <= "ヺ" or "ｦ" <= char <= "ﾟ":
            kind = "katakana"
        elif "CJK" in unicodedata.name(char, "") or char in "々〆〇":
            kind = "han"
        elif category[0] in "PSN":
            kind = {"P": "punctuation", "S": "symbol", "N": "number"}[category[0]]
        elif "LATIN" in unicodedata.name(char, ""):
            kind = "latin"
        else:
            kind = "other_letter" if category[0] == "L" else "other"
        counts[kind] += 1
    length = len(text)
    return dict(length=length, length_bin="0..4" if length <= 4 else "5..9" if length <= 9 else "10..19" if length <= 19 else "20+",
                characters=dict(counts), punctuation_symbols_whitespace_only=set(counts) <= {"punctuation", "symbol", "whitespace"})


def recover_descriptions(groups):
    wanted = {value for group in groups for value in group["text_hashes"]}
    found = {}
    _, receipts, selection = authenticate()
    for receipt in receipts:
        raw = read_work(receipt, selection[receipt["work_id"]])
        if hashlib.sha256(raw).hexdigest() != receipt["decoded_sha256"]:
            raise ValueError("relation_original_revision_changed")
        paragraphs, _ = paragraphs_with_ruby(raw)
        for paragraph in paragraphs:
            text = paragraph["text"]
            key = text_sha256(text)
            if key in wanted:
                found[key] = describe(text)
            for _, sentence in _sentences(text):
                pieces = [sentence] if len(sentence) <= 512 else (sentence[i:i + 512] for i in range(0, len(sentence), 256))
                for piece in pieces:
                    key = text_sha256(piece)
                    if key in wanted:
                        found[key] = describe(piece)
    if set(found) != wanted:
        raise ValueError("relation_shared_original_text_missing")
    return found


def run():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, expected in plan["inputs"].items():
        if sha(path) != expected:
            raise ValueError("relation_bound_input_changed")
    verified_preparation()
    history, old_train, _ = history_and_original_train()
    roles = historical_roles(history)
    groups = shared_groups(history, compressed_rows(ROOT / "prepared/coverage.jsonl.gz"))
    descriptions = recover_descriptions(groups)
    relation = read_json(ROOT / "isolated/relations.json")
    excluded, components = relation["excluded"], relation["components"]
    newly = set(read_json(ROOT / "isolated/newly-connected-old-train.json"))
    occupancy = defaultdict(Counter)
    old_counts, new_counts = Counter(), Counter()
    article_components = {}
    for population, records in (("old_train", old_train), ("new_annotation", compressed_rows(ROOT / "prepared/targets.jsonl.gz"))):
        for row in records:
            key = row["stable_id"]
            component = components[key]
            state = "excluded" if key in excluded else "retained"
            article = row["source"]["article_id"]
            if article in article_components and article_components[article] != component:
                raise ValueError("relation_article_component_conflict")
            article_components[article] = component
            corpus = "aozora" if article.startswith("aozora-work-") else "wikipedia"
            occupancy[component][population + "/" + state] += 1
            if population == "old_train":
                old_counts[corpus + "/" + state] += 1
                if key in newly:
                    old_counts[corpus + "/newly_connected"] += 1
                    occupancy[component]["old_train/newly_connected"] += 1
            else:
                new_counts[state] += 1
    summaries = {}
    for kind in ("paragraph", "sentence_signature"):
        selected = [g for g in groups if g["kind"] == kind]
        text_ids = {v for g in selected for v in g["text_hashes"]}
        historical_ids = {v for g in selected for v in g["historical_ids"]}
        chars = Counter()
        for key in text_ids:
            chars.update(descriptions[key]["characters"])
        role_groups = Counter()
        for group in selected:
            role_groups.update({roles[key] for key in group["historical_ids"]})
        summaries[kind] = dict(groups=len(selected), unique_original_strings=len(text_ids),
            length_bins=dict(Counter(descriptions[key]["length_bin"] for key in text_ids)),
            punctuation_symbols_whitespace_only_strings=sum(descriptions[k]["punctuation_symbols_whitespace_only"] for k in text_ids),
            characters=dict(chars), unique_historical_members_by_role=dict(Counter(roles[k] for k in historical_ids)),
            groups_by_role_nonexclusive=dict(role_groups),
            source_works=len({v for g in selected for v in g["works"]}),
            directly_touched_training_components=len({article_components[v] for g in selected for v in g["works"]}))
    if summaries["paragraph"]["groups"] != read_json(ROOT / "isolation.json")["audit"]["historical_coverage_shared_paragraph_groups"]:
        raise ValueError("relation_exact_paragraph_recount_differs")
    save(ROOT / "relation-witnesses.json", dict(groups=groups, descriptions=descriptions, component_occupancy=occupancy))
    result = dict(kind="annotation_relation_diagnostics", status="complete", plan_commit=PLAN_COMMIT,
        plan_sha256=sha(PLAN), script_sha256=sha(__file__), witnesses_sha256=sha(ROOT / "relation-witnesses.json"),
        historical_roles=dict(Counter(roles.values())), exact_shared_relations=summaries,
        old_train_counts=dict(old_counts), new_annotation_counts=dict(new_counts),
        excluded_training_components=sum(any(key.endswith("/excluded") for key in counts) for counts in occupancy.values()),
        largest_excluded_components=sorted((dict(counts) for counts in occupancy.values() if any(key.endswith("/excluded") for key in counts)),
            key=lambda counts: sum(v for k, v in counts.items() if k.endswith("/excluded")), reverse=True)[:5],
        frozen_role_source_sha256=FROZEN_SHA, rules_unchanged=True, exclusions_restored=0,
        interpretation="Exact shared groups are only a subset of the full transitive Jaccard>=0.8 graph. Component occupancy is not causal attribution, and historical relation is not equivalent to an evaluation leak. Role lookup reads only IDs/split markers, never Gold or candidates.",
        model_fits=0, model_inferences=0, final_test_used=False, gold_certified=False)
    save(ROOT / "relation-audit.json", result)
    save("reports/issue-49-annotation-relations-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
