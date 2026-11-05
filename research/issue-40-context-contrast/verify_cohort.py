"""Recount fixed cohort identities and replay full source closure without models."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import time

from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.kwdlc_probe import write_once
from acquire import ROOT,authenticate,sha
from feasibility import boundary
from history import load_history
from prepare import generate


def run():
    plan,_=authenticate()
    binding=json.loads((ROOT/"cohort-binding.json").read_bytes())
    if Path("manifests/context-contrast-cohort-v1.json").read_bytes()!=(ROOT/"cohort-binding.json").read_bytes():
        raise ValueError("cohort_binding_differs")
    prep=json.loads((ROOT/"preparation.json").read_bytes())
    for name,expected in binding["artifacts"].items():
        extension=".json" if name=="source-relations" else ".jsonl"
        if sha(ROOT/(name+extension))!=expected:raise ValueError("cohort_artifact_changed")
    for path,expected in {**prep["code"],**binding["code"]}.items():
        if sha(path)!=expected:raise ValueError("cohort_implementation_changed")
    pool,main,coverage,counts=generate()
    for name,rows in zip(("pool","main-slots","source-coverage"),(pool,main,coverage)):
        if boundary.jsonl(rows)!=(ROOT/(name+".jsonl")).read_bytes():raise ValueError("cohort_extraction_replay_differs")
    if counts["extraction_statuses"]!=prep["extraction_statuses"] or counts["document_statuses"]!=prep["document_statuses"]:
        raise ValueError("preparation_counts_differ")
    historical,proof=load_history()
    if proof!=binding["history"] or len(historical)!=binding["historical_records"]:raise ValueError("history_proof_differs")
    metadata=[dict(stable_id=r["stable_id"],population="evaluation",source=r["source"],
                   input_hash=canonical_json_hash([r["left_context"],r["reading"]])) for r in pool]
    start=time.monotonic()
    print(json.dumps(dict(stage="verify_source_closure",records=len(historical)+len(metadata)+len(coverage))),flush=True)
    excluded,components,audit=isolate_with_source_coverage(historical+metadata+coverage)
    if (canonical_json_bytes(dict(excluded=excluded,components=components))+b"\n"!=(ROOT/"source-relations.json").read_bytes()
            or audit!=binding["audit"]):raise ValueError("source_closure_replay_differs")
    selected=[json.loads(line) for line in (ROOT/"selected.jsonl").read_bytes().splitlines()]
    terminal=[json.loads(line) for line in (ROOT/"main-terminal.jsonl").read_bytes().splitlines()]
    by_id={r["stable_id"]:r for r in pool};by_doc=defaultdict(list)
    for row in pool:by_doc[row["document_id"]].append(row)
    if len(by_id)!=len(pool) or len({r["stable_id"] for r in selected})!=len(selected):raise ValueError("target_duplicates")
    main_ids=set()
    for before,after in zip(main,terminal):
        expected=dict(before)
        if by_doc[before["document_id"]]:
            wanted=min(by_doc[before["document_id"]],key=lambda r:canonical_json_hash([20261105,"main",r["stable_id"]]))
            if before["target_id"]!=wanted["stable_id"]:raise ValueError("main_selection_rule_differs")
        if before["status"]=="eligible_before_history":
            expected["status"]="historical_relation" if before["target_id"] in excluded else "retained"
        if expected!=after:raise ValueError("main_terminal_differs")
        if after["status"]=="retained":main_ids.add(after["target_id"])
    if len(terminal)!=1000 or Counter(r["status"] for r in terminal)!=binding["main_statuses"]:raise ValueError("main_denominator_differs")
    groups=defaultdict(list);actual_main=set()
    for row in selected:
        original={k:v for k,v in row.items() if k not in ("roles","source_component","contrast_group")}
        if original!=by_id[row["stable_id"]] or row["stable_id"] in excluded or row["source_component"]!=components[row["stable_id"]]:
            raise ValueError("selected_target_or_source_changed")
        if "main" in row["roles"]:actual_main.add(row["stable_id"])
        if "contrast" in row["roles"]:groups[row["contrast_group"]].append(row)
    if actual_main!=main_ids:raise ValueError("main_population_changed")
    for group in groups.values():
        if (len(group)!=4 or len({r["document_id"] for r in group})!=4 or len({r["left_context"] for r in group})!=4
                or len({(r["reading"],r["pos"],r["lexical_basis"]) for r in group})!=1
                or sorted(Counter(r["target"] for r in group).values())!=[2,2]
                or sorted(Counter(r["lexical_key"] for r in group).values())!=[2,2]):
            raise ValueError("contrast_quartet_contract_differs")
    if len(groups)!=binding["contrast_counts"]["selected_groups"] or len(selected)!=binding["selected_unique_rows"]:
        raise ValueError("contrast_denominator_differs")
    ready=(len(main_ids)>=plan["readiness"]["retained_main_slots_minimum"] and len(groups)>=25 and 4*len(groups)>=100)
    if (binding["status"]=="ready_for_forward_plan")!=ready:raise ValueError("readiness_status_differs")
    result=dict(kind="context_cohort_verification",status="pass",source_documents=1000,main_retained=len(main_ids),
        contrast_groups=len(groups),contrast_rows=4*len(groups),unique_targets=len(selected),
        raw_source_replay=True,full_source_closure_replay=True,independent_quartet_main_recount=True,
        source_only_input_edges=0,cohort_binding_sha256=sha(ROOT/"cohort-binding.json"),
        script_sha256=sha(__file__),closure_seconds=round(time.monotonic()-start,3),
        model_predictions=0,model_fits=0,final_test_used=False,gold_certified=False)
    for path in (ROOT/"verification.json",Path("reports/issue-40-context-cohort-verification-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("status","main_retained","contrast_groups","contrast_rows","unique_targets","closure_seconds")}))
