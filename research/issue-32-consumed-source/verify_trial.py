"""Reverse taint/active closure and independent raw-line consumption recount."""
from collections import Counter, defaultdict
import hashlib
import json
import re

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256
from sakura_rerank.data.splitter import _UnionFind
from consumption_common import (ROOT, ANNOTATIONS, load_inventory, source_identity, read_work,
    compressed_rows, read_rows, read_json, save, sha)


def key(source):
    return "consumed-unit-" + canonical_json_hash([source["article_id"], source["paragraph_hash"]])


def verify():
    graph, identity, roles, cohorts, _ = load_inventory()
    report, execution = read_json(ROOT / "report.json"), read_json(ROOT / "execution.json")
    if execution["status"] != "complete" or execution["report_sha256"] != sha(ROOT / "report.json"):
        raise ValueError("consumption_verification_execution_differs")
    for path, expected in report["implementation"].items():
        if sha(path) != expected:
            raise ValueError("consumption_frozen_implementation_changed")
    units = {r["unit_id"]: r for r in read_rows(report["artifacts"]["units"])}
    terminals = list(read_rows(report["artifacts"]["targets"]))
    receipts = list(read_rows(report["artifacts"]["consumption"]))
    if len(units) != report["unique_source_units"] or len(terminals) != report["original_provisional_targets"]:
        raise ValueError("consumption_ledger_denominator_differs")
    union = _UnionFind(len(graph.records))
    for edge in range(len(graph.left) - 1, -1, -1):
        if graph.kinds[edge] >= 2:  # real input, paragraph, exact sentence, near sentence
            union.union(graph.left[edge], graph.right[edge])
    history = [i for i, row in enumerate(graph.records) if row["stable_id"] in roles]
    text_roots, identity_roots = {union.find(i) for i in history}, {identity[i] for i in history}
    independent = {}
    for index in range(len(graph.records) - 1, -1, -1):
        row = graph.records[index]
        if row["population"] != "source_coverage":
            continue
        source = row["source"]
        unit = independent.setdefault(key(source), dict(unit_id=key(source), article_id=source["article_id"],
            paragraph_hash=source["paragraph_hash"], source_nodes=0, identity_relation=False, content_or_input_relation=False))
        unit["source_nodes"] += 1
        unit["identity_relation"] = unit["identity_relation"] or identity[index] in identity_roots
        unit["content_or_input_relation"] = unit["content_or_input_relation"] or union.find(index) in text_roots
    for unit in independent.values():
        unit["status"] = ("quarantined_identity" if unit["identity_relation"] else "quarantined_content_or_input"
                          if unit["content_or_input_relation"] else "isolated_for_source_verification")
    if independent != units or dict(Counter(r["status"] for r in units.values())) != report["unit_terminal_counts"]:
        raise ValueError("consumption_reverse_unit_quarantine_differs")
    targets = list(compressed_rows(ANNOTATIONS / "prepared/targets.jsonl.gz"))
    expected_terminals, selected = [], {}
    for row in targets:
        unit_id = key(row["source"])
        status = units.get(unit_id, {}).get("status", "missing_full_source_coverage")
        expected_terminals.append(dict(stable_id=row["stable_id"], unit_id=unit_id, status=status))
        if status == "isolated_for_source_verification":
            selected[row["stable_id"]] = row
    if (sorted(expected_terminals, key=lambda r: r["stable_id"]) != terminals
            or len(selected) != report["proposed_targets"]
            or dict(Counter(r["status"] for r in terminals)) != report["target_terminal_counts"]):
        raise ValueError("consumption_target_ledger_recount_differs")
    old = read_json(ANNOTATIONS / "isolated/relations.json")
    strict = {r["stable_id"] for r in targets if r["stable_id"] not in old["excluded"]}
    if (not strict <= set(selected) or len(strict) != report["prior_strict_targets"]
            or len(set(selected) - strict) != report["newly_isolated_under_changed_consumption_scope"]):
        raise ValueError("consumption_scope_comparison_differs")
    active = [row for row in reversed(graph.records) if row["population"] == "historical"
        or (row["population"] == "source_coverage" and units[key(row["source"])]["status"] == "isolated_for_source_verification")
        or row["stable_id"] in selected]
    if any(cohorts.get(r["stable_id"], "").startswith("old_train/") for r in active):
        raise ValueError("consumption_unconsumed_pool_active")
    print(json.dumps(dict(stage="reverse_fresh_consumed_closure", active_nodes=len(active), proposed_targets=len(selected))), flush=True)
    excluded, components, audit = isolate_annotations(active)
    component_receipt = report["artifacts"]["components"]
    if (sha(ROOT / component_receipt["path"]) != component_receipt["sha256"] or excluded
            or components != read_json(ROOT / component_receipt["path"]) or audit != report["rebuilt_scope_audit"]):
        raise ValueError("consumption_reverse_active_closure_differs")
    grouped = defaultdict(list)
    for row in selected.values():
        grouped[row["source_id"]].append(row)
    expected_evidence, occurrences, seen_units = [], Counter(), set()
    _, source_receipts, selection = source_identity()
    for source in source_receipts:
        work = selection[source["work_id"]]
        raw = read_work(source, work)
        if hashlib.sha256(raw).hexdigest() != source["decoded_sha256"]:
            raise ValueError("consumption_verifier_original_revision_differs")
        lines = raw.decode("cp932").splitlines()
        paragraphs, _ = paragraphs_with_ruby(raw)
        for paragraph in paragraphs:
            unit_id = key(dict(article_id="aozora-work-" + work["work_id"], paragraph_hash=text_sha256(paragraph["text"])))
            decision = units.get(unit_id)
            occurrences[decision["status"] if decision else "missing_full_source_coverage"] += 1
            if decision:
                seen_units.add(unit_id)
        for row in grouped.get(work["work_id"], ()):
            line = lines[row["source_line_number"]]
            stripped = line.strip()
            text = re.sub(r"《[^《》]*》", "", stripped).replace("｜", "")
            annotations = list(re.finditer(r"《([^《》]*)》", stripped))
            annotation = annotations[row["annotation_index"]]
            raw_reading = annotation.group(1)
            reading = "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in raw_reading)
            prefix = re.sub(r"《[^《》]*》", "", stripped[:annotation.start()]).replace("｜", "")
            start, end = row["paragraph_start"], row["paragraph_end"]
            context, target = text[max(0, start - 64):start], text[start:end]
            if (row["source_revision"] != source["decoded_sha256"] or row["source"]["paragraph_hash"] != text_sha256(text)
                    or row["source_line_sha256"] != text_sha256(line) or len(prefix) != end
                    or row["left_context"] != context or row["target"] != target or row["reading"] != reading
                    or row["raw_annotation_reading"] != raw_reading or row["training_eligible"] is not False
                    or row["independent_gold_eligible"] is not False):
                raise ValueError("consumption_independent_raw_line_check_differs")
            expected_evidence.append(dict(stable_id=row["stable_id"], unit_id=key(row["source"]), consumer="source_verification",
                source_revision=source["decoded_sha256"], source_line_sha256=text_sha256(line), paragraph_index=row["paragraph_index"],
                context_start=max(0, start - 64), target_start=start, target_end=end, context_sha256=text_sha256(context),
                target_sha256=text_sha256(target), reading_sha256=text_sha256(reading),
                input_and_label_sha256=canonical_json_hash([context, reading, target]), training_eligible=False, independent_gold_eligible=False))
    expected_evidence.sort(key=lambda row: row["stable_id"])
    if receipts != expected_evidence or canonical_json_hash(receipts) != report["consumption_receipt_aggregate"]:
        raise ValueError("consumption_original_input_receipt_recount_differs")
    preparation = read_json(ANNOTATIONS / "preparation.json")
    if (seen_units != set(units) or dict(occurrences) != report["original_paragraph_occurrences"]
            or sum(occurrences.values()) != preparation["frozen_cleaner_counts"]["paragraphs_retained"]
            or report["original_annotation_slots"] != preparation["counts"]["terminals"]
            or report["original_extraction_terminal_counts"] != preparation["terminal_counts"]):
        raise ValueError("consumption_original_occurrence_denominators_differ")
    if (len(grouped) != report["source_works"] or len({r["author_id"] for r in selected.values()}) != report["source_authors"]
            or len(set(components.values())) != report["proposed_training_components"]):
        raise ValueError("consumption_source_capacity_recount_differs")
    result = dict(kind="prospective_consumed_source_verification", status="passed", original_nodes=len(graph.records),
        active_nodes=len(active), unique_units_verified=len(units), target_terminals_verified=len(terminals),
        independently_checked_raw_inputs=len(receipts), original_paragraph_occurrences_verified=sum(occurrences.values()),
        original_annotation_slots_preserved=preparation["counts"]["terminals"],
        reverse_fresh_closure_equal=True, historical_connections=0,
        prior_strict_targets_preserved=len(strict), report_sha256=sha(ROOT / "report.json"), script_sha256=sha(__file__),
        training_labels_admitted=0, legacy_exclusions_restored=0, final_test_used=False, gold_certified=False, model_fits=0, model_inferences=0)
    save(ROOT / "verification.json", result)
    save("reports/issue-32-consumed-source-verification-v1.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(verify()))
