"""Single preregistered trial: quarantine, original-input checks, fresh closure."""
from collections import Counter, defaultdict
import hashlib
import json
import subprocess
import time

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.consumed_source import PERMITTED, quarantine_units, target_terminal, unit_key, verify_consumption
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.relation_witnesses import component_labels
from consumption_common import (ROOT, PLAN, PLAN_COMMIT, ANNOTATIONS, boundary, load_inventory,
    source_identity, read_work, compressed_rows, write_rows, read_json, save, sha)

CODE = ("src/sakura_rerank/data/consumed_source.py", "research/issue-32-consumed-source/consumption_common.py",
        "research/issue-32-consumed-source/run_trial.py")


def run():
    graph, identity, roles, cohorts, plan = load_inventory()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    print(json.dumps(dict(stage="paragraph_taint_closure", nodes=len(graph.records))), flush=True)
    content = component_labels(graph, ("paragraph", "sentence_exact", "sentence_near", "input"))
    decisions, unit_counts = quarantine_units(graph.records, identity, content)
    targets = list(compressed_rows(ANNOTATIONS / "prepared/targets.jsonl.gz"))
    terminals = [dict(stable_id=r["stable_id"], unit_id=unit_key(r["source"]), status=target_terminal(r, decisions)) for r in targets]
    selected = {r["stable_id"] for r in terminals if r["status"] == PERMITTED}
    old = read_json(ANNOTATIONS / "isolated/relations.json")
    strict = {r["stable_id"] for r in targets if r["stable_id"] not in old["excluded"]}
    if not strict <= selected:
        raise ValueError("consumption_lost_prior_strictly_isolated_target")
    active = [r for r in graph.records if r["population"] == "historical"
        or (r["population"] == "source_coverage" and decisions[unit_key(r["source"])]["status"] == PERMITTED)
        or r["stable_id"] in selected]
    if any(r["stable_id"] in cohorts and cohorts[r["stable_id"]].startswith("old_train/") for r in active):
        raise ValueError("consumption_unused_pool_entered_proposed_scope")
    print(json.dumps(dict(stage="fresh_consumed_scope_closure", proposed_targets=len(selected), active_nodes=len(active),
        unit_statuses=unit_counts)), flush=True)
    # Reconstruct from nodes. Filtering old star edges after deletion is unsound.
    excluded, components, audit = isolate_annotations(active)
    if excluded or len(components) != len(selected) or set(components) != selected:
        raise ValueError("consumption_proposed_scope_still_touches_history")
    by_work = defaultdict(list)
    for row in targets:
        if row["stable_id"] in selected:
            by_work[row["source_id"]].append(row)
    evidence, occurrence_counts, seen_units = [], Counter(), set()
    _, receipts, selection = source_identity()
    for receipt in receipts:
        work = selection[receipt["work_id"]]
        raw = read_work(receipt, work)
        if hashlib.sha256(raw).hexdigest() != receipt["decoded_sha256"]:
            raise ValueError("consumption_original_work_revision_changed")
        paragraphs, _ = paragraphs_with_ruby(raw)
        for paragraph in paragraphs:
            source = dict(article_id="aozora-work-" + work["work_id"], paragraph_hash=text_sha256(paragraph["text"]))
            key = unit_key(source)
            decision = decisions.get(key)
            occurrence_counts[decision["status"] if decision else "missing_full_source_coverage"] += 1
            if decision:
                seen_units.add(key)
        for row in by_work.get(work["work_id"], ()):
            pi = row["paragraph_index"]
            if not 0 <= pi < len(paragraphs):
                raise ValueError("consumption_original_paragraph_missing")
            evidence.append(verify_consumption(row, decisions[unit_key(row["source"])], paragraphs[pi],
                work_id=work["work_id"], author_id=work["author_id"], revision=receipt["decoded_sha256"],
                paragraph_index=pi, consumer="source_verification"))
    original = read_json(ANNOTATIONS / "preparation.json")
    if (seen_units != set(decisions) or len(evidence) != len(selected)
            or sum(occurrence_counts.values()) != original["frozen_cleaner_counts"]["paragraphs_retained"]):
        raise ValueError("consumption_original_coverage_or_count_differs")
    evidence.sort(key=lambda row: row["stable_id"])
    artifacts = dict(units=write_rows("unit-decisions", (decisions[k] for k in sorted(decisions))),
        targets=write_rows("target-terminals", sorted(terminals, key=lambda r: r["stable_id"])),
        consumption=write_rows("consumption-evidence", evidence))
    save(ROOT / "proposed-components.json", components)
    artifacts["components"] = dict(path="proposed-components.json", sha256=sha(ROOT / "proposed-components.json"))
    result = dict(kind="prospective_consumed_paragraph_trial", status="verified_scope_not_admitted", plan_commit=PLAN_COMMIT,
        plan_sha256=sha(PLAN), execution_commit=head, implementation={p: sha(p) for p in CODE}, artifacts=artifacts,
        original_annotation_slots=original["counts"]["terminals"], original_extraction_terminal_counts=original["terminal_counts"],
        original_provisional_targets=len(targets), target_terminal_counts=dict(Counter(r["status"] for r in terminals)),
        unique_source_units=len(decisions), unit_terminal_counts=unit_counts, original_paragraph_occurrences=dict(occurrence_counts),
        proposed_targets=len(selected), prior_strict_targets=len(strict), newly_isolated_under_changed_consumption_scope=len(selected - strict),
        source_works=len(by_work), source_authors=len({r["author_id"] for r in targets if r["stable_id"] in selected}),
        proposed_training_components=len(set(components.values())), independently_source_checked_rows=len(evidence),
        full_historical_nodes=len(roles), old_unused_pool_nodes_retained_in_taint_analysis=plan["population"]["old_unused_pool"],
        old_unused_pool_nodes_in_consumed_scope=0, active_nodes=len(active), rebuilt_scope_audit=audit,
        consumption_receipt_aggregate=canonical_json_hash(evidence), model_fits=0, model_inferences=0,
        new_native_requests=0, final_test_used=False, gold_certified=False, training_labels_admitted=0,
        legacy_exclusions_restored=0, safety_threshold=.0025,
        interpretation="A separately declared prospective consumed-source scope, not a claim that the old full-source exclusions were false. Whole quarantined paragraphs remain in the immutable inventory, but are not proposed inputs. No model/cache/body/checkpoint consumer is enabled and no candidate presence or label correctness is certified.")
    save(ROOT / "report.json", result)
    save("reports/issue-32-consumed-source-v1.json", result)
    return {k: result[k] for k in ("status", "unique_source_units", "unit_terminal_counts", "target_terminal_counts",
        "proposed_targets", "prior_strict_targets", "newly_isolated_under_changed_consumption_scope", "active_nodes")}


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    execution = ROOT / "execution.json"
    if execution.exists() or (ROOT / "report.json").exists():
        raise ValueError("consumption_attempt_already_terminal")
    started = time.monotonic()
    try:
        output = run()
    except Exception as error:
        save(execution, dict(status="failed", error_type=type(error).__name__, elapsed_seconds=round(time.monotonic() - started, 3)))
        print(json.dumps(dict(status="failed", error_type=type(error).__name__)), flush=True)
        raise SystemExit(1) from None
    save(execution, dict(status="complete", elapsed_seconds=round(time.monotonic() - started, 3), report_sha256=sha(ROOT / "report.json")))
    print(json.dumps(output), flush=True)
