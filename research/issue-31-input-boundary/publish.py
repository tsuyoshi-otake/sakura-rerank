"""Independent scalar recount of saved evidence; no converter execution or label edits."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from common import (ROOT, PLAN, PLAN_COMMIT, BINDING, authenticate_input, authenticate_population, committed,
                    identity, jsonl, load_old_snapshots, load_script, native, pilot, sha)

R2 = ROOT / "isolated-r2"
EXECUTION_COMMIT = "d6dfea8989e89705dba898de57b1441512409b70"
INPUT_COMMIT = "c5dead92e5c4ca704cf6259fb8a678d01b280b40"


def composed_top1(view, candidates):
    if view["status"] != "ready":
        return None
    if any(p["kind"] == "convert" and p["request_id"] not in candidates for p in view["parts"]):
        return None
    text, wanted = "", ""
    for part in view["parts"]:
        if part["kind"] == "literal":
            text += part["text"]
            wanted += part["text"]
        else:
            rows = candidates[part["request_id"]]
            if not rows:
                return False
            text += rows[0]["surface"]
            wanted += part["target"]
    return text == wanted


def publish(path, value):
    raw = canonical_json_bytes(value)+b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("published_evidence_changed")
    else:
        write_once(path, raw)


def run():
    plan, _, _ = authenticate_population()
    binding = authenticate_input(INPUT_COMMIT)
    for path in ("research/issue-31-input-boundary/isolation-r2.json", "research/issue-31-input-boundary/isolated_forward.py"):
        committed(path, EXECUTION_COMMIT)
    prepare = load_script("boundary_preparation_replay", "research/issue-31-input-boundary/prepare.py")
    for name, regenerated in zip(("targets", "requests", "new-requests"), prepare.generate()):
        if jsonl(regenerated) != (ROOT/(name+".jsonl")).read_bytes():
            raise ValueError("input_regeneration_differs")
    converter_identity = identity()
    records = load_old_snapshots(converter_identity)
    execution = json.loads((R2/"execution.json").read_bytes())
    if (execution["execution_commit"] != EXECUTION_COMMIT or execution["status"] != "complete"
            or execution["not_attempted"] != 0 or execution["input_binding_sha256"] != sha(BINDING)
            or execution["first_attempt_receipt_sha256"] != sha(ROOT/"execution.json")
            or execution["measurement_sha256"] != sha(R2/"measurement.json")):
        raise ValueError("execution_evidence_differs")
    first = json.loads((ROOT/"execution.json").read_bytes())
    if first["status"] != "partial" or first["failed_requests"] != 100 or first["not_attempted_requests"] != 1326:
        raise ValueError("original_failure_record_changed")
    requests = [json.loads(line) for line in (ROOT/"new-requests.jsonl").read_bytes().splitlines()]
    if [a["index"] for a in execution["attempts"]] != list(range(len(requests))):
        raise ValueError("terminal_request_accounting_differs")
    rejected, terminal_counts, rejection_shapes = set(), Counter(), Counter()
    for attempt, request in zip(execution["attempts"], requests):
        directory = R2/"candidates"/f"request-{attempt['index']:04d}"
        if (sha(directory/"execution.json") != attempt["execution_sha256"]
                or (directory/"input.jsonl").read_bytes() != jsonl([request])
                or json.loads((directory/"identity.json").read_bytes()) != converter_identity):
            raise ValueError("isolated_request_binding_differs")
        terminal = json.loads((directory/"execution.json").read_bytes())
        if (terminal["stable_id"] != request["stable_id"] or terminal["status"] != attempt["status"]
                or terminal["input_sha256"] != sha(directory/"input.jsonl")):
            raise ValueError("isolated_terminal_differs")
        terminal_counts[terminal["status"]] += 1
        if terminal["status"] == "complete":
            if terminal["exit_code"] != 0 or sha(directory/"output.jsonl") != terminal["output_sha256"]:
                raise ValueError("isolated_output_changed")
            record = native.validate_result(directory, (directory/"input.jsonl").read_bytes(), converter_identity)[0]
            records[request["stable_id"]] = record
        elif terminal["status"] == "candidate_count_rejected":
            if (terminal["exit_code"] != 2 or (directory/"stderr.log").read_bytes() !=
                    b"research exporter failed: converter returned an invalid candidate count\n"
                    or (directory/"output.jsonl").exists() or (directory/"native-report.json").exists()
                    or terminal["stderr_sha256"] != sha(directory/"stderr.log")):
                raise ValueError("rejection_evidence_differs")
            rejected.add(request["stable_id"])
            reading = request["reading"]
            rejection_shapes["phonetic_only" if all("\u3041" <= c <= "\u3096" or c == "ー" for c in reading) else "includes_literal"] += 1
            rejection_shapes["length_1" if len(reading) == 1 else "length_2plus"] += 1
        else:
            raise ValueError("unexpected_terminal_status")
    if dict(terminal_counts) != execution["counts"]:
        raise ValueError("execution_totals_differ")
    targets = [json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    candidates = {key: row["candidate_snapshots"]["training_top32"]["candidates"] for key, row in records.items()}
    counts, cross, top1 = defaultdict(Counter), Counter(), Counter()
    token_counts, extra = Counter(), Counter()
    for row in targets:
        token_counts.update(row["token_classes"])
        extra["literal_slots"] += row["token_classes"].get("literal", 0) > 0
        extra["ready_literal_slots"] += row["status"] == "ready" and row["token_classes"].get("literal", 0) > 0
        states = {}
        for name, view in row["views"].items():
            key = row["policy"]+"/"+name
            c = counts[key]
            c["slots"] += 1
            c["original_ready"] += row["original_status"] == "ready_for_forward_check"
            parts = [p for p in view["parts"] if p["kind"] == "convert"]
            if view["status"] != "ready":
                status = view["status"]
            elif any(p["request_id"] not in candidates for p in parts):
                status = "unmeasured"
            else:
                status = "measured"
            c[status] += 1
            present = {}
            if status == "measured":
                c["conversion_parts"] += len(parts)
                for k in (1, 5, 6, 10, 32):
                    found = all(any(candidate["surface"] == p["target"] for candidate in candidates[p["request_id"]][:k]) for p in parts)
                    present[str(k)] = found
                    c["source_supported_at_"+str(k)] += found
                    if row["original_status"] == "ready_for_forward_check":
                        c["original_ready_supported_at_"+str(k)] += found
                actual = composed_top1(view, candidates)
                top1[key] += actual
                extra["composed_vs_all_parts_top1_differences"] += actual != present["1"]
            states[name] = (status, present)
        if states["whole"][0] == "measured" and not states["whole"][1]["32"]:
            cross["whole_top32_missing"] += 1
            if row["original_status"] == "ready_for_forward_check":
                cross["original_ready_whole_top32_missing"] += 1
            for name in ("literal_split", "morpheme_diagnostic"):
                status, presence = states[name]
                outcome = "unmeasured" if status != "measured" else "all_supported" if presence["32"] else "component_missing"
                cross[name+"/"+outcome] += 1
                if row["original_status"] == "ready_for_forward_check":
                    cross["original_ready/"+name+"/"+outcome] += 1
    measurement = json.loads((R2/"measurement.json").read_bytes())
    if measurement["by_policy_view"] != {k:dict(v) for k,v in counts.items()} or measurement["whole_miss_component_support"] != dict(cross):
        raise ValueError("independent_scalar_recount_differs")
    old = json.loads((pilot.ROOT/"report.json").read_bytes())
    for policy, values in old["source_exact_presence_counts"].items():
        for k, number in values.items():
            if counts[policy+"/whole"]["original_ready_supported_at_"+k] != number:
                raise ValueError("original_747_presence_changed")
    report = dict(measurement, kind="input_boundary_research_report", plan_commit=PLAN_COMMIT,
        population_commit=plan["population_commit"],
        original_population=1000, input_commit=INPUT_COMMIT, execution_commit=EXECUTION_COMMIT,
        original_failure=dict(failed_requests=100, not_attempted_requests=1326, authenticated_new_snapshots=0),
        new_requests=len(requests), reused_requests=binding["reused_requests"], request_outcomes=dict(terminal_counts),
        rejection_shapes=dict(rejection_shapes), annotation_counts=dict(token_counts), slot_diagnostics=dict(extra),
        composed_top1_counts=dict(top1), elapsed_seconds=execution["elapsed_seconds"],
        search_statuses=dict(Counter(r["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"] for r in records.values())),
        original_747_presence_unchanged=True, model_fits=0, model_predictions=0, independent_human_gold=0,
        final_test_used=False, safety_threshold=0.0025, source_text_redistributed=False,
        observed_ime_boundaries=False, final_quality_certified=False,
        artifacts=dict(plan_sha256=sha(PLAN), input_binding_sha256=sha(BINDING),
            first_execution_sha256=sha(ROOT/"execution.json"), isolated_execution_sha256=sha(R2/"execution.json"),
            measurement_sha256=sha(R2/"measurement.json")))
    publish(ROOT/"report.json", report)
    publish(Path("reports/issue-31-input-boundary-v1.json"), report)
    verification = dict(kind="input_boundary_verification", status="pass", slots=1000,
        old_slots_regenerated=True, new_views_regenerated=True, authenticated_reused_snapshots=722,
        isolated_terminal_requests=len(requests), independent_scalar_recount=True,
        original_747_presence_unchanged=True, rejected_inputs_kept_unmeasured=True,
        report_sha256=sha(ROOT/"report.json"), script_sha256=sha(__file__))
    publish(ROOT/"verification-r2.json", verification)
    publish(Path("reports/issue-31-input-boundary-verification-r2.json"), verification)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({k:result[k] for k in ("slots", "request_outcomes", "rejection_shapes", "whole_miss_component_support", "slot_diagnostics")}))
