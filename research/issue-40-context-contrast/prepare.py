"""Authenticate each source and retain fixed main slots plus full source coverage."""
from collections import Counter
import json

from sakura_rerank.data.context_contrasts import extract_pool
from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.kwdlc_probe import ProbeError,blob_sha1,write_once
from acquire import ROOT,PLAN,PLAN_COMMIT,authenticate,sha
from feasibility import boundary
from history import source_metadata


def generate():
    plan,selection=authenticate()
    boundary.committed("src/sakura_rerank/data/context_contrasts.py",PLAN_COMMIT)
    acquisition=json.loads((ROOT/"acquisition.json").read_bytes())
    if (acquisition["selection_sha256"]!=sha(ROOT/"selection.json") or acquisition["plan_sha256"]!=sha(PLAN)
            or [a["index"] for a in acquisition["attempts"]]!=list(range(1000))):
        raise ValueError("acquisition_accounting_differs")
    pool,main,coverage=[],[],[];statuses=Counter();documents=Counter()
    for doc,attempt in zip(selection["documents"],acquisition["attempts"]):
        slot=dict(document_id=doc["document_id"],status=attempt["status"],target_id=None)
        if attempt["document_id"]!=doc["document_id"]:raise ValueError("acquisition_order_differs")
        if attempt["status"]!="received":
            main.append(slot);documents[slot["status"]]+=1;continue
        raw=(ROOT/"source"/(doc["document_id"]+".knp")).read_bytes()
        if len(raw)!=doc["bytes"] or blob_sha1(raw)!=doc["git_blob_sha1"] or sha(ROOT/"source"/(doc["document_id"]+".knp"))!=attempt["sha256"]:
            raise ValueError("acquired_source_changed")
        try:
            rows,counts=extract_pool(doc["document_id"],raw,lexical_basis="original_lemma")
            units=annotation_units(doc["document_id"],raw)
        except (ProbeError,UnicodeError) as error:
            slot.update(status="parse_failure",failure_type=type(error).__name__)
            main.append(slot);documents[slot["status"]]+=1;continue
        for index,unit in enumerate(units):
            coverage.append(dict(stable_id="new-context-source-unit-"+canonical_json_hash([doc["document_id"],index]),
                population="source_coverage",source=source_metadata(doc["document_id"],unit)))
        pool.extend(rows);statuses.update(counts)
        if rows:
            target=min(rows,key=lambda r:canonical_json_hash([20261105,"main",r["stable_id"]]))
            slot.update(status="eligible_before_history",target_id=target["stable_id"])
        else:slot["status"]="no_eligible_target"
        main.append(slot);documents[slot["status"]]+=1
    if len(pool)>plan["readiness"]["pool_rows_maximum"] or len(main)!=1000:raise ValueError("prepared_population_outside_bound")
    return pool,main,coverage,dict(extraction_statuses=dict(statuses),document_statuses=dict(documents))


def run():
    first=generate();second=generate()
    if first!=second:raise ValueError("source_preparation_replay_differs")
    for name,rows in zip(("pool","main-slots","source-coverage"),first[:3]):
        write_once(ROOT/(name+".jsonl"),boundary.jsonl(rows))
    result=dict(kind="context_contrast_source_preparation",plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),
        acquisition_sha256=sha(ROOT/"acquisition.json"),selection_sha256=sha(ROOT/"selection.json"),
        pool_rows=len(first[0]),main_slots=len(first[1]),source_only_units=len(first[2]),
        artifacts={name:sha(ROOT/(name+".jsonl")) for name in ("pool","main-slots","source-coverage")},
        code={p:sha(p) for p in ("src/sakura_rerank/data/context_contrasts.py","research/issue-40-context-contrast/prepare.py","research/issue-40-context-contrast/history.py")},
        deterministic_replay=True,**first[3])
    write_once(ROOT/"preparation.json",canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("pool_rows","main_slots","source_only_units","document_statuses")}))
