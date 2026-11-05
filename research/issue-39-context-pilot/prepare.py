"""Freeze all pilot target slots before converter outcomes; audit known history."""
from collections import Counter
import gzip
import json
from pathlib import Path
import time

from sakura_rerank.data.context_pilot import extract_slots,empty_slots,annotation_units
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash,sentence_shingle_hashes,text_sha256
from sakura_rerank.data.growth_isolation import historical_input_metadata,isolate
from sakura_rerank.data.kwdlc_probe import ProbeError,blob_sha1,write_once
from acquire import ROOT,PLAN,authenticate,sha


def generate(selection,acquisition):
    attempts=acquisition["attempts"]
    if acquisition["status"]!="complete" or len(attempts)!=250 or [r["index"] for r in attempts]!=list(range(250)):
        raise ValueError("acquisition_terminal_accounting_differs")
    rows=[]
    for doc,attempt in zip(selection["documents"],attempts):
        if attempt["status"]!="received":
            rows.extend(empty_slots(doc["document_id"],"acquisition_failed" if attempt["status"]=="failed" else "acquisition_not_attempted"))
            continue
        path=ROOT/"source"/(doc["document_id"]+".knp")
        raw=path.read_bytes()
        if len(raw)!=doc["bytes"] or blob_sha1(raw)!=doc["git_blob_sha1"] or sha(path)!=attempt["sha256"]:
            raise ValueError("source_bytes_changed")
        try:
            part=extract_slots(doc["document_id"],raw)
        except (ProbeError,UnicodeError) as error:
            part=empty_slots(doc["document_id"],"parse_failure",attempt["sha256"])
            for row in part:row["failure_code"]=str(error) if isinstance(error,ProbeError) else "invalid_utf8"
        rows.extend(part)
    if len(rows)!=1000 or len({r["stable_id"] for r in rows})!=1000:
        raise ValueError("target_slot_accounting_differs")
    requests={}
    for row in rows:
        if row["status"]=="ready_for_forward_check":
            key="pilot-reading-"+canonical_json_hash(row["reading"])
            row["request_id"]=key;requests[key]=dict(stable_id=key,reading=row["reading"])
    return rows,[requests[k] for k in sorted(requests)]


def extract():
    _,selection=authenticate()
    acquired=json.loads((ROOT/"acquisition.json").read_bytes())
    if acquired["selection_sha256"]!=sha(ROOT/"selection.json") or acquired["plan_sha256"]!=sha(PLAN):
        raise ValueError("acquisition_identity_differs")
    first=generate(selection,acquired);second=generate(selection,acquired)
    raw=[b"".join(canonical_json_bytes(r)+b"\n" for r in rows) for rows in first]
    if raw!=[b"".join(canonical_json_bytes(r)+b"\n" for r in rows) for rows in second]:
        raise ValueError("extraction_replay_differs")
    for name,content in zip(("targets.jsonl","requests.jsonl"),raw):write_once(ROOT/name,content)
    result=dict(kind="context_pilot_input_binding",status="complete",plan_sha256=sha(PLAN),
        selection_sha256=sha(ROOT/"selection.json"),acquisition_sha256=sha(ROOT/"acquisition.json"),
        targets_sha256=sha(ROOT/"targets.jsonl"),requests_sha256=sha(ROOT/"requests.jsonl"),
        extractor_sha256=sha("src/sakura_rerank/data/context_pilot.py"),
        legacy_format_reader_sha256=sha("src/sakura_rerank/data/kwdlc_probe.py"),
        slots=1000,documents=250,unique_readings=len(first[1]),
        statuses=dict(Counter(r["status"] for r in first[0])),extraction_replay_byte_equal=True,
        converter_outcomes_seen=False,gold_certified=False,training_eligible=False,independent_test=False)
    write_once(ROOT/"input-binding.json",canonical_json_bytes(result)+b"\n")
    write_once(Path("manifests/context-pilot-input-v1.json"),canonical_json_bytes(result)+b"\n")
    return result


def audit():
    authenticate()
    start=time.monotonic()
    binding=json.loads((ROOT/"input-binding.json").read_bytes())
    if sha(ROOT/"targets.jsonl")!=binding["targets_sha256"]:raise ValueError("targets_changed")
    history={};sources={}
    original=Path("data/generated/issue-33-data-growth-v1/history-source-metadata.jsonl.gz")
    if sha(original)!="e09e6df646f3c5f5c30d1056698f2918c99b09f6de2f73d96aed21c0cf99a272":
        raise ValueError("historical_metadata_changed")
    with gzip.open(original,"rb") as stream:
        for line in stream:
            row=json.loads(line)
            if row["stable_id"] in history and history[row["stable_id"]]!=row:raise ValueError("historical_identity_conflict")
            history[row["stable_id"]]=row
    sources["six_historical_generations"]=dict(sha256=sha(original),unique_rows=len(history))
    frozen=Path("data/generated/issue15-v5-slot120/frozen-split.jsonl")
    if sha(frozen)!="0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82":raise ValueError("frozen_history_changed")
    count=0
    with frozen.open("rb") as stream:
        for line in stream:
            row=historical_input_metadata(line);history[row["stable_id"]]=row;count+=1
    sources["frozen_input_only"]=dict(sha256=sha(frozen),rows=count,labels_candidates_decoded=False)
    for relative in ("issue-33-data-growth-v1/wiki","issue-33-data-growth-v1/aozora-extract","issue-33-data-growth-v2/wiki-extra"):
        directory=Path("data/generated")/relative
        execution=json.loads((directory/"execution.json").read_bytes());path=directory/"targets.jsonl"
        if execution["status"]!="complete" or sha(path)!=execution["targets_sha256"]:raise ValueError("growth_history_changed")
        count=0
        with path.open("rb") as stream:
            for line in stream:
                target=json.loads(line)
                row=dict(stable_id=target["stable_id"],source=target["source"],population="historical",
                         input_hash=canonical_json_hash([target["left_context"],target["reading"]]))
                if row["stable_id"] in history and history[row["stable_id"]]!=row:raise ValueError("growth_identity_conflict")
                history[row["stable_id"]]=row;count+=1
        sources[relative]=dict(sha256=sha(path),rows=count)
    old_root=Path("data/generated/issue-31-kwdlc-probe-v1")
    old_targets=[json.loads(line) for line in (old_root/"targets-r2.jsonl").read_bytes().splitlines()]
    if sha(old_root/"targets-r2.jsonl")!="f80a3e2661de574074d00fad7dbc7e7e2e92824a54b2db43483f1bb36c22fa74":
        raise ValueError("old_kwdlc_targets_changed")
    for doc in json.loads((old_root/"selection.json").read_bytes())["selected_documents"]:
        raw=(old_root/"source"/(doc["document_id"]+".knp")).read_bytes()
        if blob_sha1(raw)!=doc["git_blob_sha1"]:raise ValueError("old_kwdlc_source_changed")
        for i,unit in enumerate(annotation_units(doc["document_id"],raw)):
            text="".join(t["surface"] for t in unit)
            key="old-kwdlc-unit-"+canonical_json_hash([doc["document_id"],i])
            history[key]=dict(stable_id=key,population="historical",source=dict(article_id="kwdlc:"+doc["document_id"],
                paragraph_hash=text_sha256(text),sentence_hash=text_sha256(text),sentence_shingle_hashes=sentence_shingle_hashes(text),template_cluster_id=None))
        for target in old_targets:
            if target["document_id"]==doc["document_id"]:
                key="old-kwdlc-input-"+target["stable_id"]
                source=history["old-kwdlc-unit-"+canonical_json_hash([doc["document_id"],target["sentence_index"]])]["source"]
                history[key]=dict(stable_id=key,population="historical",source=source,input_hash=canonical_json_hash([target["left_context"],target["reading"]]))
    sources["old_kwdlc_probe"]=dict(documents=50,targets_sha256=sha(old_root/"targets-r2.jsonl"))
    targets=[json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    new=[dict(stable_id=r["stable_id"],population="evaluation",source=r["source"],
              input_hash=canonical_json_hash([r["left_context"],r["reading"]])) for r in targets if "source" in r]
    print(json.dumps(dict(stage="history_closure",historical=len(history),new=len(new))),flush=True)
    excluded,components,counts=isolate(list(history.values())+new)
    write_once(ROOT/"history-relations.json",canonical_json_bytes(dict(excluded=excluded,components=components))+b"\n")
    result=dict(kind="context_pilot_history_audit",status="complete",input_binding_sha256=sha(ROOT/"input-binding.json"),
        history=sources,historical_records=len(history),target_slots=1000,source_defined_slots=len(new),
        slots_touching_history=len(excluded),isolated_slots=len(new)-len(excluded),
        undefined_source_slots=1000-len(new),audit=counts,relations_sha256=sha(ROOT/"history-relations.json"),
        any_slots_removed=False,labels_candidates_from_old_evaluation_decoded=False,
        coverage_limit="Named source generations and input histories only; no claim of every external/private corpus or independently certified evaluation population",
        gold_certified=False,independent_test=False,elapsed_seconds=round(time.monotonic()-start,3))
    write_once(ROOT/"history-audit.json",canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=["extract","audit"])
    args=parser.parse_args();r=extract() if args.stage=="extract" else audit()
    print(json.dumps({k:r[k] for k in ("status","slots","unique_readings","statuses","slots_touching_history","isolated_slots","elapsed_seconds") if k in r}))
