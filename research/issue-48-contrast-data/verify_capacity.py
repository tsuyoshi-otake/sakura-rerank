"""Recount all saved planning evidence without reading evaluation targets."""
from collections import Counter, defaultdict
import json

from sakura_rerank.data.contracts import canonical_json_hash
from audit_capacity import ROOT, PLAN, POLICY, LANGUAGE_ROOT, analyze, read_json, rows, save, sha


def recount_profile(population, components, summary):
    forms = defaultdict(Counter)
    inputs = defaultdict(Counter)
    for row in population:
        forms[row["reading"]][row["target"]] += 1
        inputs[(row["left_context"], row["reading"])][row["target"]] += 1
    independent = dict(rows=len(population), readings=len(forms),
        single_form_readings=sum(len(c) == 1 for c in forms.values()),
        single_form_rows=sum(sum(c.values()) for c in forms.values() if len(c) == 1),
        multiple_form_readings=sum(len(c) > 1 for c in forms.values()),
        multiple_form_rows=sum(sum(c.values()) for c in forms.values() if len(c) > 1),
        in_sample_reading_majority_rows=sum(max(c.values()) for c in forms.values()),
        source_documents=len({r["source"]["article_id"] for r in population}),
        source_components=len({components[r["stable_id"]] for r in population}),
        corpus_counts=dict(Counter(r["corpus"] for r in population)))
    if any(summary[k] != value for k, value in independent.items()):
        raise ValueError("contrast_independent_profile_recount_differs")
    conflicts = summary["input_conflicts"]
    if (conflicts["rows"] != len(population) or conflicts["unique_inputs"] != len(inputs)
            or conflicts["duplicate_groups"] != sum(sum(c.values()) > 1 for c in inputs.values())
            or conflicts["contradictory_groups"] != sum(len(c) > 1 for c in inputs.values())
            or conflicts["unavoidable_source_disagreements"] != sum(sum(c.values()) - max(c.values()) for c in inputs.values())):
        raise ValueError("contrast_independent_conflict_recount_differs")
    return len(independent) + 5


def check_quartets(groups, by_id, components, *, independent):
    seen = set()
    for group in groups:
        chosen = [by_id[s] for s in group["stable_ids"]]
        if (len(chosen) != 4 or len({r["stable_id"] for r in chosen}) != 4
                or len({r["reading"] for r in chosen}) != 1
                or sorted(Counter(r["target"] for r in chosen).values()) != [2, 2]
                or len({r["left_context"] for r in chosen}) != 4
                or len({r["source"]["article_id"] for r in chosen}) != 4
                or group["reading_sha256"] != canonical_json_hash(chosen[0]["reading"])
                or group["reading_sha256"] in seen
                or (independent and len({components[r["stable_id"]] for r in chosen}) != 4)):
            raise ValueError("contrast_witness_invariant_differs")
        seen.add(group["reading_sha256"])
    return len(groups)


def run():
    plan = read_json(PLAN)
    report = read_json(ROOT / "report.json")
    if (sha(PLAN) != report["plan_sha256"] or sha(POLICY) != report["policy_sha256"]
            or sha(plan["source"]["path"]) != report["source_sha256"]):
        raise ValueError("contrast_verification_binding_changed")
    for path, expected in report["implementation"].items():
        if sha(path) != expected:
            raise ValueError("contrast_verification_implementation_changed")
    for name, expected in report["artifacts"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("contrast_verification_artifact_changed")
    selected = list(rows(plan["source"]["path"]))
    by_id = {r["stable_id"]: r for r in selected}
    relations = read_json(LANGUAGE_ROOT / "lm-source-relations.json")
    if sha(LANGUAGE_ROOT / "lm-source-relations.json") != read_json(ROOT / "history-replay.json")["relation_sha256"]:
        raise ValueError("contrast_verification_relations_changed")
    components = relations["components"]
    if len(by_id) != len(selected) or set(by_id) & set(relations["excluded"]):
        raise ValueError("contrast_verification_isolation_differs")
    expected_order = sorted(by_id)
    ledger_manifest = read_json(ROOT / "evidence-manifest.json")
    previous, proof, count = "0" * 64, {}, 0
    for entry in rows(ROOT / "evidence.jsonl"):
        digest = entry.pop("record_sha256")
        stable = entry["stable_id"]
        if (entry["index"] != count or stable != expected_order[count]
                or entry["previous_record_sha256"] != previous
                or canonical_json_hash(entry) != digest
                or entry["source_row_sha256"] != canonical_json_hash(by_id[stable])
                or entry["source_component"] != components[stable]
                or entry["policy_sha256"] != report["policy_sha256"]):
            raise ValueError("contrast_hash_chain_or_provenance_differs")
        if (set(entry["quality"]) != {"contextual_reading", "exact_source_span", "ime_input_boundary", "meaning_and_usage", "orthographic_intent"}
                or set(entry["quality"].values()) != {"unresolved"}
                or entry["source_span_offsets_retained"] is not False
                or entry["reading_provenance"] != "dictionary_unique_surface_lookup_not_contextual_annotation"):
            raise ValueError("contrast_unearned_quality_certification")
        key = (by_id[stable]["candidate_request_id"], by_id[stable]["target"])
        if key in proof and proof[key] != entry["candidate"]:
            raise ValueError("contrast_candidate_evidence_inconsistent")
        proof[key] = entry["candidate"]
        previous = digest
        count += 1
    if (count != len(selected) or count != ledger_manifest["rows"]
            or previous != ledger_manifest["last_record_sha256"]):
        raise ValueError("contrast_hash_chain_tail_differs")
    selection = read_json(ROOT / "selection-identities.json")
    witness_sets = read_json(ROOT / "witnesses.json")
    eligible = [r for r in selected if proof[(r["candidate_request_id"], r["target"])]["eligible"]]
    populations = dict(all_train=selected, candidate_eligible=eligible)
    for name in ("control", "contrast"):
        identities = selection.get(name)
        if identities is not None:
            if len(identities) != len(set(identities)) or len(identities) != 50000:
                raise ValueError("contrast_planning_denominator_differs")
            populations[name] = [by_id[s] for s in identities]
            if Counter(r["corpus"] for r in populations[name]) != plan["selection"]["corpus_quotas"]:
                raise ValueError("contrast_planning_corpus_quota_differs")
    scalar_checks, witness_checks = 0, 0
    for name, population in populations.items():
        scalar_checks += recount_profile(population, components, report["populations"][name])
        members = {r["stable_id"]: r for r in population}
        for unit in ("document", "component"):
            groups = witness_sets[name][unit]
            witness_checks += check_quartets(groups, members, components, independent=(unit == "component"))
            if len(groups) != report["populations"][name][f"four_{unit}_witnessed_readings"]:
                raise ValueError("contrast_witness_denominator_differs")
    reserved = selection.get("reserved_quartets", [])
    if reserved:
        check_quartets(reserved, {s: by_id[s] for s in selection["contrast"]}, components, independent=True)
    # The replay never loads #40/#41 evaluation rows, predictions or error lists.
    replay, replay_witnesses, replay_selection = analyze(selected[::-1], components, proof, plan)
    if (any(report[k] != value for k, value in replay.items())
            or replay_witnesses != witness_sets or replay_selection != selection):
        raise ValueError("contrast_reverse_order_replay_differs")
    common = len(set(selection.get("control", [])) & set(selection.get("contrast", [])))
    result = dict(kind="contrast_capacity_verification", status="passed", rows=count,
        hash_chain_and_tail_verified=True, source_membership_verified=True,
        independent_profile_scalar_checks=scalar_checks, all_saved_quartets_verified=witness_checks,
        reserved_quartets_verified=len(reserved), reverse_order_replay=True,
        shared_control_contrast_rows=common, rows_replaced_in_each_selection=50000-common if selection else None,
        report_sha256=sha(ROOT / "report.json"), verifier_sha256=sha(__file__),
        quality_certified=False, final_test_used=False)
    save(ROOT / "verification.json", result)
    save("reports/issue-48-contrast-verification-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
