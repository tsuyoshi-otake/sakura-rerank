"""Full-source history isolation and fixed main/contrast selection for #41."""
import argparse
from collections import Counter
import json
import time

from sakura_rerank.data.context_contrasts import extract_pool,select_contrasts
from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.kwdlc_probe import ProbeError,blob_sha1,write_once
from language_common import ROOT,PRIOR_ROOT,PLAN,bound_plan,context_history,read_json,rows,save,sha,jsonl
from acquire_sources import PLAN_COMMIT


def source_history():
    historical,proof=context_history.load_history()
    for row in rows(PRIOR_ROOT/"source-coverage.jsonl"):
        historical.append(dict(row,population="historical"))
    for row in rows(PRIOR_ROOT/"pool.jsonl"):
        historical.append(dict(stable_id="exposed-context-"+row["stable_id"],population="historical",source=row["source"],
                               input_hash=canonical_json_hash([row["left_context"],row["reading"]])))
    proof["context40"]=dict(source_units_sha256=sha(PRIOR_ROOT/"source-coverage.jsonl"),pool_sha256=sha(PRIOR_ROOT/"pool.jsonl"))
    if len({r["stable_id"] for r in historical})!=len(historical):raise ValueError("language_history_duplicate_ids")
    return historical,proof


def generate():
    plan=bound_plan(PLAN_COMMIT);selection=read_json(ROOT/"selection.json");acquisition=read_json(ROOT/"acquisition.json")
    if (acquisition["identity"]["selection_sha256"]!=plan["selection_sha256"]
            or acquisition["identity"]["plan_sha256"]!=sha(PLAN)
            or [a["index"] for a in acquisition["attempts"]]!=list(range(1000))):raise ValueError("language_acquisition_accounting")
    pool=[];slots=[];coverage=[];counts=Counter()
    for doc,attempt in zip(selection["documents"],acquisition["attempts"]):
        slot=dict(document_id=doc["document_id"],target_id=None,status=attempt["status"])
        if doc["document_id"]!=attempt["document_id"]:raise ValueError("document_order_changed")
        if attempt["status"]!="received":slots.append(slot);continue
        path=ROOT/"source"/(doc["document_id"]+".knp");raw=path.read_bytes()
        if len(raw)!=doc["bytes"] or blob_sha1(raw)!=doc["git_blob_sha1"] or sha(path)!=attempt["sha256"]:raise ValueError("language_source_changed")
        try:
            targets,statuses=extract_pool(doc["document_id"],raw,lexical_basis="original_lemma")
            units=annotation_units(doc["document_id"],raw)
        except (ProbeError,UnicodeError) as error:
            slot.update(status="parse_failure",error_type=type(error).__name__);slots.append(slot);continue
        counts.update(statuses);pool.extend(targets)
        for index,unit in enumerate(units):
            coverage.append(dict(stable_id="language-source-unit-"+canonical_json_hash([doc["document_id"],index]),
                population="source_coverage",source=context_history.source_metadata(doc["document_id"],unit)))
        if targets:
            chosen=min(targets,key=lambda r:canonical_json_hash([20261105,"language-main",r["stable_id"]]))
            slot.update(status="eligible_before_history",target_id=chosen["stable_id"])
        else:slot["status"]="no_eligible_target"
        slots.append(slot)
    if len(pool)>100000 or len(slots)!=1000:raise ValueError("language_population_bound")
    return pool,slots,coverage,dict(counts)


def prepare():
    first=generate()
    if first!=generate():raise ValueError("language_extraction_not_deterministic")
    for name,data in zip(("pool","main-slots","source-coverage"),first[:3]):write_once(ROOT/(name+".jsonl"),jsonl(data))
    result=dict(kind="language_research_source_preparation",pool_rows=len(first[0]),main_slots=len(first[1]),source_units=len(first[2]),
        extraction_counts=first[3],artifacts={name:sha(ROOT/(name+".jsonl")) for name in ("pool","main-slots","source-coverage")},
        acquisition_sha256=sha(ROOT/"acquisition.json"),plan_sha256=sha(PLAN),script_sha256=sha(__file__),deterministic_replay=True)
    save(ROOT/"preparation.json",result)
    return {k:result[k] for k in ("pool_rows","main_slots","source_units")}


def calculate():
    bound_plan(PLAN_COMMIT);prep=read_json(ROOT/"preparation.json")
    for name,expected in prep["artifacts"].items():
        if sha(ROOT/(name+".jsonl"))!=expected:raise ValueError("language_prepared_input_changed")
    pool=list(rows(ROOT/"pool.jsonl"));slots=list(rows(ROOT/"main-slots.jsonl"));coverage=list(rows(ROOT/"source-coverage.jsonl"))
    historical,proof=source_history()
    metadata=[dict(stable_id=r["stable_id"],population="evaluation",source=r["source"],
                   input_hash=canonical_json_hash([r["left_context"],r["reading"]])) for r in pool]
    print(json.dumps(dict(stage="language_source_closure",historical=len(historical),pool=len(pool),source_units=len(coverage))),flush=True)
    excluded,components,audit=isolate_with_source_coverage(historical+metadata+coverage)
    retained=[r for r in pool if r["stable_id"] not in excluded]
    contrasts,contrast_counts=select_contrasts(retained,maximum_groups=100)
    if select_contrasts(list(reversed(retained)),maximum_groups=100)!=(contrasts,contrast_counts):raise ValueError("contrast_order_dependence")
    for slot in slots:
        if slot["status"]=="eligible_before_history":slot["status"]="historical_relation" if slot["target_id"] in excluded else "retained"
    main_ids={s["target_id"] for s in slots if s["status"]=="retained"};groups={r["stable_id"]:r["contrast_group"] for r in contrasts}
    selected=[]
    for row in sorted(retained,key=lambda r:r["stable_id"]):
        roles=(["main"] if row["stable_id"] in main_ids else [])+(["contrast"] if row["stable_id"] in groups else [])
        if roles:selected.append(dict(row,roles=roles,source_component=components[row["stable_id"]],contrast_group=groups.get(row["stable_id"])))
    if len(selected)>1400:raise ValueError("selected_population_bound")
    result=dict(kind="language_research_cohort",status="ready" if len(main_ids)>=500 and len(contrasts)>=100 else "insufficient_do_not_train",
        historical_rows=len(historical),pool_rows=len(pool),retained_pool_rows=len(retained),source_units=len(coverage),
        main_slots=len(slots),main_statuses=dict(Counter(s["status"] for s in slots)),contrast_counts=contrast_counts,
        selected_rows=len(selected),audit=audit,history=proof,plan_sha256=sha(PLAN),preparation_sha256=sha(ROOT/"preparation.json"),
        gold_certified=False,final_test_used=False,safety_threshold=.0025)
    return selected,slots,dict(excluded=excluded,components=components),result


def isolate():
    start=time.monotonic();selected,slots,relations,result=calculate()
    for name,data in (("selected",selected),("main-terminal",slots)):write_once(ROOT/(name+".jsonl"),jsonl(data))
    save(ROOT/"source-relations.json",relations)
    result.update(elapsed_seconds=round(time.monotonic()-start,3),script_sha256=sha(__file__),
                  artifacts={name:sha(ROOT/(name+ext)) for name,ext in (("selected",".jsonl"),("main-terminal",".jsonl"),("source-relations",".json"))})
    save(ROOT/"cohort.json",result);save("manifests/language-research-cohort-v1.json",result)
    return {k:result[k] for k in ("status","historical_rows","pool_rows","retained_pool_rows","main_statuses","contrast_counts","selected_rows","elapsed_seconds")}


def verify():
    start=time.monotonic();prepared=generate();saved=read_json(ROOT/"preparation.json")
    for name,data in zip(("pool","main-slots","source-coverage"),prepared[:3]):
        if jsonl(data)!=(ROOT/(name+".jsonl")).read_bytes():raise ValueError("raw_source_replay_differs")
    selected,slots,relations,result=calculate();binding=read_json(ROOT/"cohort.json")
    if jsonl(selected)!=(ROOT/"selected.jsonl").read_bytes() or jsonl(slots)!=(ROOT/"main-terminal.jsonl").read_bytes():raise ValueError("cohort_replay_differs")
    if relations!=read_json(ROOT/"source-relations.json") or any(binding[k]!=v for k,v in result.items()):raise ValueError("closure_replay_differs")
    if saved["extraction_counts"]!=prepared[3]:raise ValueError("extraction_counts_differ")
    report=dict(kind="language_cohort_verification",status="passed",raw_source_replay=True,full_history_replay=True,
        main_slots=len(slots),selected_rows=len(selected),cohort_sha256=sha(ROOT/"cohort.json"),elapsed_seconds=round(time.monotonic()-start,3),
        script_sha256=sha(__file__),gold_certified=False,final_test_used=False)
    save(ROOT/"cohort-verification.json",report);save("reports/issue-41-language-cohort-verification-v1.json",report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("prepare","isolate","verify"))
    args=parser.parse_args();print(json.dumps(dict(prepare=prepare,isolate=isolate,verify=verify)[args.stage]()))
