"""Freeze source-isolated main and contrast targets before any model prediction."""
from collections import Counter
import json
from pathlib import Path
import time

from sakura_rerank.data.context_contrasts import select_contrasts
from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.kwdlc_probe import write_once
from acquire import ROOT,PLAN,PLAN_COMMIT,authenticate,sha
from feasibility import boundary
from history import load_history


def run():
    plan,_=authenticate()
    prep=json.loads((ROOT/"preparation.json").read_bytes())
    for name,expected in prep["artifacts"].items():
        if sha(ROOT/(name+".jsonl"))!=expected:raise ValueError("prepared_input_changed")
    for path,expected in prep["code"].items():
        if sha(path)!=expected:raise ValueError("prepared_implementation_changed")
    pool,main,coverage=([json.loads(line) for line in (ROOT/(name+".jsonl")).read_bytes().splitlines()]
                        for name in ("pool","main-slots","source-coverage"))
    historical,proof=load_history()
    metadata=[dict(stable_id=r["stable_id"],population="evaluation",source=r["source"],
                   input_hash=canonical_json_hash([r["left_context"],r["reading"]])) for r in pool]
    start=time.monotonic()
    print(json.dumps(dict(stage="full_source_history_closure",historical=len(historical),new_targets=len(metadata),source_only=len(coverage))),flush=True)
    excluded,components,audit=isolate_with_source_coverage(historical+metadata+coverage)
    elapsed=round(time.monotonic()-start,3)
    by_document={}
    for row in pool:
        state=row["stable_id"] in excluded
        if row["document_id"] in by_document and by_document[row["document_id"]]!=state:
            raise ValueError("document_source_closure_inconsistent")
        by_document[row["document_id"]]=state
    retained=[r for r in pool if r["stable_id"] not in excluded]
    contrasts,contrast_counts=select_contrasts(retained,maximum_groups=100)
    if select_contrasts(list(reversed(retained)),maximum_groups=100)!=(contrasts,contrast_counts):
        raise ValueError("contrast_selection_replay_differs")
    for slot in main:
        if slot["status"]=="eligible_before_history":
            slot["status"]="historical_relation" if slot["target_id"] in excluded else "retained"
    main_ids={slot["target_id"] for slot in main if slot["status"]=="retained"}
    contrast_by_id={r["stable_id"]:r["contrast_group"] for r in contrasts}
    selected=[]
    for row in sorted(retained,key=lambda r:r["stable_id"]):
        roles=[]
        if row["stable_id"] in main_ids:roles.append("main")
        if row["stable_id"] in contrast_by_id:roles.append("contrast")
        if roles:selected.append(dict(row,roles=roles,source_component=components[row["stable_id"]],contrast_group=contrast_by_id.get(row["stable_id"])))
    thresholds=plan["readiness"]
    ready=(len(main_ids)>=thresholds["retained_main_slots_minimum"]
           and contrast_counts["selected_groups"]>=thresholds["contrast_groups_minimum"]
           and len(contrasts)>=thresholds["contrast_rows_minimum"])
    if len(selected)>thresholds["unique_selected_targets_maximum"]:raise ValueError("selected_target_bound")
    for name,rows in (("selected",selected),("main-terminal",main)):
        write_once(ROOT/(name+".jsonl"),boundary.jsonl(rows))
    write_once(ROOT/"source-relations.json",canonical_json_bytes(dict(excluded=excluded,components=components))+b"\n")
    result=dict(kind="unused_context_cohort_binding",status="ready_for_forward_plan" if ready else "insufficient_do_not_train",
        plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),selection_sha256=sha(ROOT/"selection.json"),
        preparation_sha256=sha(ROOT/"preparation.json"),acquisition_sha256=sha(ROOT/"acquisition.json"),
        artifacts={name:sha(ROOT/(name+extension)) for name,extension in (("selected",".jsonl"),("main-terminal",".jsonl"),("source-relations",".json"))},
        history=proof,historical_records=len(historical),pool_rows=len(pool),retained_pool_rows=len(retained),
        quarantined_pool_rows=len(excluded),full_source_units=len(coverage),main_slots=1000,
        main_statuses=dict(Counter(s["status"] for s in main)),contrast_counts=contrast_counts,
        selected_unique_rows=len(selected),selected_source_components=len({r["source_component"] for r in selected}),
        audit=audit,audit_elapsed_seconds=elapsed,model_fits=0,model_predictions=0,converter_queries=0,
        gold_certified=False,independent_final_test=False,safety_threshold=.0025,
        code={p:sha(p) for p in ("src/sakura_rerank/data/context_source_isolation.py","research/issue-40-context-contrast/isolate_select.py")},
        caveat="Source-form research target only; lemma differences are not semantic or IME-intent certification. Isolation covers named known history, not all private/external corpora.")
    write_once(ROOT/"cohort-binding.json",canonical_json_bytes(result)+b"\n")
    write_once(Path("manifests/context-contrast-cohort-v1.json"),canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("status","pool_rows","retained_pool_rows","main_statuses","contrast_counts","selected_unique_rows","audit_elapsed_seconds")}))
