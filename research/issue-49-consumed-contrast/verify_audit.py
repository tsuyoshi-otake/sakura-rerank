"""Direct receipt/position checks and a separate candidate-presence recount."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from sakura_rerank.data.annotation_contrast import profile
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.contrast_capacity import review_flags
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.reference_probe import validate_probe_records
from audit_common import source, boundary, read_json, read_rows, save, sha
from forward_batches import ROOT, PREPARED, BINDING, authenticate
from batch_execution import REJECTION


def original_classes(char):
    if not char:
        return "paragraph_boundary"
    if re.fullmatch(r"[\u3400-\u9fff\U00020000-\U0003134f]", char):
        return "kanji_range"
    if re.fullmatch(r"[ぁ-ゖ]", char):
        return "hiragana"
    if re.fullmatch(r"[ァ-ヺｦ-ﾝ]", char):
        return "katakana"
    if char.isspace():
        return "whitespace"
    return "punctuation" if unicodedata.category(char)[0] == "P" else "other"


def verify_observations(targets, observations):
    grouped = defaultdict(list)
    for row in targets:
        grouped[row["source_id"]].append(row)
    _, receipts, selection = source.source_identity()
    verified = set()
    for receipt in receipts:
        work = selection[receipt["work_id"]]
        raw = source.read_work(receipt, work)
        if hashlib.sha256(raw).hexdigest() != receipt["decoded_sha256"]:
            raise ValueError("contrast_verifier_original_revision_changed")
        paragraphs, _ = paragraphs_with_ruby(raw)
        for row in grouped.get(work["work_id"], ()):
            text = paragraphs[row["paragraph_index"]]["text"]
            start, end = row["paragraph_start"], row["paragraph_end"]
            if text[start:end] != row["target"] or text[max(0,start-64):start] != row["left_context"]:
                raise ValueError("contrast_verifier_original_input_changed")
            classes = dict(zip(("left","first","last","right"), map(original_classes,
                (text[start-1:start] if start else "",text[start],text[end-1],text[end:end+1]))))
            flags = set(review_flags(row))
            if classes["last"] == "kanji_range" and classes["right"] == "hiragana":
                flags.add("right_hiragana_after_kanji")
            if classes["last"] == classes["right"] == "kanji_range":
                flags.add("right_kanji_adjacency")
            if re.search("[ゐゑヰヱ]", row["raw_annotation_reading"]):
                flags.add("explicit_historical_kana_marker")
            expected = dict(stable_id=row["stable_id"], annotation_kind=row["annotation_kind"],
                            classes=classes,flags=sorted(flags),ime_input_unit="unresolved")
            if expected != observations[row["stable_id"]]:
                raise ValueError("contrast_verifier_source_observation_differs")
            verified.add(row["stable_id"])
    if verified != set(observations):
        raise ValueError("contrast_verifier_observation_denominator_differs")


def snapshots(targets, identity, execution, requests):
    wanted = {r["candidate_request_id"] for r in targets}
    result = {}
    old_plan = read_json("research/issue-48-contrast-data/plan-v2.json")
    receipt_path = Path(old_plan["candidate_receipt"]["path"])
    if sha(receipt_path) != old_plan["candidate_receipt"]["sha256"]:
        raise ValueError("contrast_verifier_prior_execution_changed")
    previous = read_json(receipt_path)
    train = receipt_path.parent.parent
    original = json.loads(boundary.committed("manifests/data-growth-input-reservations-v2.json", previous["input_commit"]))
    if sha(train / "isolation/requests.jsonl") != original["requests_sha256"]:
        raise ValueError("contrast_verifier_prior_requests_changed")
    prior_requests = [json.loads(line) for line in (train / "isolation/requests.jsonl").read_bytes().splitlines()]
    for offset in range(0,len(prior_requests),100):
        batch = prior_requests[offset:offset+100]
        if not wanted & {r["stable_id"] for r in batch}:
            continue
        directory = train / "candidates" / f"batch-{offset//100:05d}"
        if sha(directory / "execution.json") != previous["batches"][offset//100]["execution_sha256"]:
            raise ValueError("contrast_verifier_prior_batch_changed")
        receipt = read_json(directory / "execution.json")
        raw = b"".join(canonical_json_bytes(r)+b"\n" for r in batch)
        if (receipt["status"] != "complete" or (directory / "input.jsonl").read_bytes() != raw
                or sha(directory / "output.jsonl") != receipt["output_sha256"]):
            raise ValueError("contrast_verifier_prior_native_bytes_changed")
        for row in validate_probe_records((directory/"output.jsonl").read_bytes(),batch,identity):
            if row["stable_id"] in wanted:
                result[row["stable_id"]] = row
    old = source.ANNOTATIONS
    old_report = read_json(old/"candidate-report.json")
    if sha(old/"forward-execution.json") != old_report["execution_sha256"]:
        raise ValueError("contrast_verifier_annotation_execution_changed")
    old_execution = read_json(old/"forward-execution.json")
    old_requests = [json.loads(line) for line in (old/"new-requests.jsonl").read_bytes().splitlines()]
    old_bound = read_json("manifests/annotation-first-forward-v1.json")
    if sha(old/"new-requests.jsonl") != old_bound["artifacts"]["new-requests.jsonl"]:
        raise ValueError("contrast_verifier_annotation_requests_changed")
    for index, attempt in enumerate(old_execution["attempts"]):
        directory = old/"candidates"/f"request-{index:04d}"
        if attempt["index"] != index or sha(directory/"execution.json") != attempt["execution_sha256"]:
            raise ValueError("contrast_verifier_annotation_receipt_changed")
        receipt = read_json(directory/"execution.json")
        raw = canonical_json_bytes(old_requests[index])+b"\n"
        if (receipt["status"] != "complete" or (directory/"input.jsonl").read_bytes() != raw
                or sha(directory/"output.jsonl") != receipt["output_sha256"]):
            raise ValueError("contrast_verifier_annotation_native_bytes_changed")
        row = boundary.native.validate_result(directory,raw,identity)[0]
        if row["stable_id"] in wanted:
            result[row["stable_id"]] = row
    outcomes, attempted = Counter(), 0
    for index, attempt in enumerate(execution["attempts"]):
        batch = requests[index*100:index*100+100]
        if attempt["index"] != index or attempt["offset"] != index*100 or attempt["request_count"] != len(batch):
            raise ValueError("contrast_verifier_batch_coverage_differs")
        attempted += len(batch)
        outcomes[attempt["status"]] += len(batch)
        if attempt["status"] == "failed_without_receipt":
            continue
        directory = ROOT/"candidates"/f"batch-{index:05d}"
        if sha(directory/"execution.json") != attempt["execution_sha256"]:
            raise ValueError("contrast_verifier_new_receipt_changed")
        receipt = read_json(directory/"execution.json")
        raw = b"".join(canonical_json_bytes(r)+b"\n" for r in batch)
        if (receipt["status"] != attempt["status"] or receipt["request_count"] != len(batch)
                or receipt["input_sha256"] != hashlib.sha256(raw).hexdigest()):
            raise ValueError("contrast_verifier_new_input_binding_changed")
        if receipt["status"] == "complete":
            if (directory/"input.jsonl").read_bytes() != raw or sha(directory/"output.jsonl") != receipt["output_sha256"]:
                raise ValueError("contrast_verifier_new_native_bytes_changed")
            for row in boundary.native.validate_result(directory,raw,identity):
                if row["stable_id"] in result:
                    raise ValueError("contrast_verifier_new_request_was_reusable")
                result[row["stable_id"]] = row
        elif receipt["status"] == "candidate_count_rejected":
            if ((directory/"stderr.log").read_bytes() != REJECTION or (directory/"output.jsonl").exists()
                    or (directory/"native-report.json").exists()):
                raise ValueError("contrast_verifier_rejection_differs")
    if attempted+execution["not_attempted"] != len(requests) or dict(outcomes) != execution["request_outcomes"]:
        raise ValueError("contrast_verifier_terminal_denominator_differs")
    return result


def direct_evidence(target, snapshot):
    if snapshot is None:
        return dict(status="acquisition_missing",eligible=False,presence={str(k):False for k in (1,5,6,10,32)},
                    unique_target_rank=None,candidate_count=0,truncated_candidates=0)
    candidates = snapshot["candidate_snapshots"]["training_top32"]["candidates"]
    top = candidates[:6]
    if snapshot["candidate_snapshots"]["production_top6"]["candidates"] != top:
        raise ValueError("contrast_verifier_top6_prefix_differs")
    matches = [i+1 for i,c in enumerate(candidates) if c["surface"] == target]
    positive = [c for c in top if c["surface"] == target]
    truncated = sum(len(c["surface"]) > 32 for c in top)
    status = ("fewer_than_two_candidates" if len(top)<2 else "source_target_missing_or_nonunique_top6" if len(positive)!=1
        else "source_target_non_dictionary_path" if any(s["source_category"]!="system_dictionary" for s in positive[0]["segments"])
        else "target_or_candidate_truncation" if len(target)>32 or truncated else "eligible")
    return dict(status=status,eligible=status=="eligible",presence={str(k):any(i<=k for i in matches) for k in (1,5,6,10,32)},
                unique_target_rank=matches[0] if len(matches)==1 else None,candidate_count=len(candidates),truncated_candidates=truncated)


def verify_witnesses(targets, components, groups):
    rows = {r["stable_id"]:r for r in targets}
    for kind, witnesses in groups.items():
        for witness in witnesses:
            chosen = [rows[s] for s in witness["stable_ids"]]
            reading = {r["reading"] for r in chosen}
            units = {components[r["stable_id"]] if kind=="component" else r["source"]["article_id"] for r in chosen}
            if (len(chosen)!=4 or len({r["stable_id"] for r in chosen})!=4 or len(units)!=4
                    or len({r["left_context"] for r in chosen})!=4 or len(reading)!=1
                    or sorted(Counter(r["target"] for r in chosen).values())!=[2,2]
                    or canonical_json_hash(next(iter(reading))) != witness["reading_sha256"]):
                raise ValueError("contrast_verifier_invalid_quartet")


def run():
    execution = read_json(ROOT/"execution.json")
    _, identity, targets, components, prepared, requests = authenticate(execution["binding_commit"])
    report = read_json(ROOT/"report.json")
    if (read_json(ROOT/"stage-execution.json")["status"] != "complete"
            or report["targets"] != len(targets) or report["new_requests"] != len(requests)
            or report["original_annotation_slots"] != prepared["original_annotation_slots"]
            or report["original_provisional_targets"] != prepared["original_provisional_targets"]
            or report["native_request_outcomes"] != execution["request_outcomes"]
            or report["not_attempted_requests"] != execution["not_attempted"]):
        raise ValueError("contrast_verifier_execution_denominator_differs")
    for receipt in prepared["artifacts"].values():
        if sha(PREPARED/receipt["path"]) != receipt["sha256"]:
            raise ValueError("contrast_verifier_prepared_artifact_changed")
    for name, field in (("execution.json","execution_sha256"),("candidate-evidence.json","evidence_sha256"),("supported-witnesses.json","witnesses_sha256")):
        if sha(ROOT/name) != report[field]:
            raise ValueError("contrast_verifier_final_artifact_changed")
    observations = {r["stable_id"]:r for r in read_rows(prepared["artifacts"]["observations"])}
    verify_observations(targets,observations)
    print(json.dumps(dict(stage="reauthenticate_all_native_snapshots",targets=len(targets))),flush=True)
    actual = snapshots(targets,identity,execution,requests)
    evidence = read_json(ROOT/"candidate-evidence.json")
    saved = {r["stable_id"]:r for r in evidence}
    if len(saved)!=len(evidence) or set(saved)!={r["stable_id"] for r in targets}:
        raise ValueError("contrast_verifier_evidence_denominator_differs")
    counts, presence, supported = Counter(), Counter(), []
    for row in reversed(targets):
        request_id = row["candidate_request_id"]
        snapshot = actual.get(request_id)
        if snapshot is not None and snapshot["reading"] != row["reading"]:
            raise ValueError("contrast_verifier_reading_join_differs")
        expected = direct_evidence(row["target"],snapshot)
        if saved[row["stable_id"]] != dict(stable_id=row["stable_id"],candidate_request_id=request_id,evidence=expected):
            raise ValueError("contrast_verifier_candidate_evidence_differs")
        counts[expected["status"]]+=1
        presence.update(k for k,found in expected["presence"].items() if found)
        if expected["eligible"]:
            supported.append(row)
    if counts!=Counter(report["candidate_statuses"]) or {str(k):presence[str(k)] for k in (1,5,6,10,32)}!=report["source_exact_presence"]:
        raise ValueError("contrast_verifier_candidate_aggregate_differs")
    for rows, field, path in ((targets[::-1],"source_profile",PREPARED/"source-witnesses.json"),
                              (supported,"candidate_supported_profile",ROOT/"supported-witnesses.json")):
        calculated, groups = profile(rows,components,observations)
        if calculated!=report[field] or groups!=read_json(path):
            raise ValueError("contrast_verifier_reverse_profile_differs")
        verify_witnesses(rows,components,groups)
    result = dict(kind="consumed_contrast_verification",status="passed",source_observations_verified=len(observations),
        targets_independently_recounted=len(targets),native_snapshots_reauthenticated=len(actual),source_presence=dict(presence),
        candidate_supported_rows=len(supported),all_quartets_verified=True,reverse_profiles_equal=True,
        report_sha256=sha(ROOT/"report.json"),binding_sha256=sha(BINDING),script_sha256=sha(__file__),
        original_slots_preserved=report["original_annotation_slots"],model_fits=0,model_inferences=0,
        training_labels_admitted=0,gold_certified=False,final_test_used=False)
    save(ROOT/"verification.json",result)
    save("reports/issue-49-consumed-contrast-verification-v2.json",result)
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
