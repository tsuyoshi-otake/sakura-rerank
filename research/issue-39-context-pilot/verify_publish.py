"""Independent scalar candidate recount and aggregate-only pilot publication."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import unicodedata

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import authenticate_identity
from acquire import ROOT,PLAN,authenticate,sha
from forward import BINARY,DICTIONARY,IDENTITY,validate_result
from prepare import generate


def run():
    plan,selection=authenticate()
    acquisition=json.loads((ROOT/"acquisition.json").read_bytes())
    targets=[json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    regenerated=generate(selection,acquisition)
    for name,rows in zip(("targets","requests"),regenerated):
        raw=b"".join(canonical_json_bytes(r)+b"\n" for r in rows)
        if raw!=(ROOT/(name+".jsonl")).read_bytes():raise ValueError("frozen_extraction_recount_differs")
    execution=json.loads((ROOT/"forward-execution.json").read_bytes())
    if execution["status"]!="complete" or sha(ROOT/"measurement.json")!=execution["measurement_sha256"]:
        raise ValueError("completed_forward_receipt_required")
    identity=authenticate_identity(IDENTITY,plan["converter"]["identity_sha256"],BINARY,DICTIONARY)
    snapshots={}
    for batch in execution["batches"]:
        directory=ROOT/"candidates"/f"batch-{batch['index']:03d}"
        if sha(directory/"execution.json")!=batch["execution_sha256"]:raise ValueError("batch_receipt_changed")
        receipt=json.loads((directory/"execution.json").read_bytes())
        if receipt["status"]!="complete":continue
        records=validate_result(directory,(directory/"input.jsonl").read_bytes(),identity)
        if sha(directory/"output.jsonl")!=receipt["output_sha256"]:raise ValueError("candidate_bytes_changed")
        snapshots.update({r["stable_id"]:r["candidate_snapshots"]["training_top32"]["candidates"] for r in records})
    counts=defaultdict(Counter);oracles=defaultdict(Counter);ranks=Counter();paths=Counter();by_reading=defaultdict(list)
    units={};annotation=Counter();classes=Counter()
    for row in targets:
        policy=row["policy"];c=counts[policy];c["slots"]+=1;c["status/"+row["status"]]+=1
        if "reading" in row:
            c["target_defined"]+=1;c["reading_over9"]+=len(row["reading"])>9;c["reading_over32"]+=len(row["reading"])>32
            c["context_empty"]+=len(row["left_context"])==0;c["context_under8"]+=len(row["left_context"])<8
            c["multiple_morphemes"]+=row["morphemes"]>1;c["named_entity"]+=row["named_entity"]
            c["within_existing_model_bounds"]+=len(row["reading"])<=32 and len(row["target"])<=32
            by_reading[row["reading"]].append(row)
        if row["status"]=="special_reading_annotation":
            doc=row["document_id"]
            if doc not in units:units[doc]=annotation_units(doc,(ROOT/"source"/(doc+".knp")).read_bytes())
            span=units[doc][row["annotation_unit"]][row["start_morpheme"]:row["end_morpheme"]]
            others=[t for t in span if not all("\u3041"<=ch<="\u3096" or ch=="\u30fc" for ch in t["reading"])]
            literal=all(t["surface"]==t["reading"] and all(unicodedata.category(ch)[0] in "PS" for ch in t["reading"]) for t in others)
            annotation["punctuation_or_symbol_literal_only" if literal else "other_or_nonliteral_annotation"]+=1
            classes.update({unicodedata.category(ch) for ch in row["reading"] if not ("\u3041"<=ch<="\u3096" or ch=="\u30fc")})
        candidate_rows=snapshots.get(row.get("request_id"))
        if candidate_rows is None:
            c["unmeasured"]+=1;continue
        c["measured"]+=1
        positions=[i+1 for i,candidate in enumerate(candidate_rows) if candidate["surface"]==row["target"]]
        for k in (1,5,6,10,32):oracles[policy][str(k)]+=int(any(rank<=k for rank in positions))
        if not positions:c["measured_top32_missing"]+=1;continue
        c["top32_present"]+=1;c["top32_nonunique_surface"]+=len(positions)>1;ranks[str(positions[0])]+=1
        segments=candidate_rows[positions[0]-1]["segments"]
        paths["all_dictionary" if all(s["source_category"]=="system_dictionary" for s in segments) else "includes_fallback_or_other"]+=1
        paths["single_segment" if len(segments)==1 else "multiple_segments"]+=1
    measurement=json.loads((ROOT/"measurement.json").read_bytes())
    if {p:dict(c) for p,c in counts.items()}!=measurement["by_policy"]:
        raise ValueError("scalar_status_counts_differ")
    if {p:dict(c) for p,c in oracles.items()}!=measurement["source_exact_presence_counts"] or dict(ranks)!=measurement["target_rank_counts"] or dict(paths)!=measurement["matched_path_counts"]:
        raise ValueError("scalar_candidate_counts_differ")
    contrasts=[g for g in by_reading.values() if len({r["target"] for r in g})>1 and len({r["left_context"] for r in g})>1]
    if len(contrasts)!=measurement["same_reading_different_surface_context_groups"] or sum(map(len,contrasts))!=measurement["contrast_group_slots"]:
        raise ValueError("contrast_recount_differs")
    history=json.loads((ROOT/"history-audit.json").read_bytes())
    if history["status"]!="complete" or sha(ROOT/"history-relations.json")!=history["relations_sha256"]:
        raise ValueError("history_audit_not_complete")
    relations=json.loads((ROOT/"history-relations.json").read_bytes())
    if len(relations["excluded"])!=history["slots_touching_history"] or len(relations["components"])!=1000:
        raise ValueError("history_count_reconciliation_failed")
    result=dict(measurement,acquisition={k:acquisition[k] for k in ("received","requested","source_bytes","elapsed_seconds","automatic_retries","replacements")},
        annotation_diagnostic=dict(exclusive_slot_classes=dict(annotation),overlapping_unicode_categories=dict(classes),
            policy_changed=False,interpretation="Literal punctuation evidence is not an IME input-boundary decision; no reading was repaired or re-forwarded"),
        history=history,plan_commit="0f8c5af08f730b83a1d6352776b0960be2299eda",plan_sha256=sha(PLAN),
        source_readme_sha256=plan["source_readme_sha256"],source_commit=plan["source_commit"],
        acquisition_receipt_sha256=sha(ROOT/"acquisition.json"),forward_receipt_sha256=sha(ROOT/"forward-execution.json"),
        forward_elapsed_seconds=execution["elapsed_seconds"],targets_sha256=sha(ROOT/"targets.jsonl"),
        input_sha256=sha(ROOT/"input-binding.json"),source_text_redistributed=False,model_fits=0,model_predictions=0,
        safety_threshold=.0025,independent_human_gold=False,final_test_used=False)
    raw=canonical_json_bytes(result)+b"\n"
    write_once(ROOT/"report.json",raw);write_once(Path("reports/issue-39-context-pilot-v1.json"),raw)
    verification=dict(kind="context_pilot_verification",status="passed",slots=1000,source_documents_authenticated=250,
        fixed_target_regeneration_byte_equal=True,validated_candidate_batches=len(execution["batches"]),
        source_presence_counts_recounted=20,all_policy_statuses_recounted=True,contrast_groups_recounted=True,
        history_count_reconciled=True,report_sha256=sha(ROOT/"report.json"),new_converter_runs=0,model_fits=0,
        method="Scalar raw-candidate surface comparisons separate from the aggregate implementation; source semantics remain uncertified")
    raw=canonical_json_bytes(verification)+b"\n"
    write_once(ROOT/"verification.json",raw);write_once(Path("reports/issue-39-context-pilot-verification-v1.json"),raw)
    print(json.dumps(verification))


if __name__=="__main__":run()
