"""Hash-only history assembly, including every previously exposed KWDLC unit."""
import gzip
import json
from pathlib import Path

from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.growth_isolation import historical_input_metadata
from sakura_rerank.data.kwdlc_probe import blob_sha1
from feasibility import boundary


def source_metadata(document_id,unit):
    sentence="".join(t["surface"] for t in unit)
    return dict(article_id="kwdlc:"+document_id,paragraph_hash=text_sha256(sentence),
        sentence_hash=text_sha256(sentence),sentence_shingle_hashes=sentence_shingle_hashes(sentence),template_cluster_id=None)


def load_history():
    old=json.loads(boundary.committed("reports/issue-39-context-pilot-v1.json","dfb3601062fc5dc6a53d76fb096141d1e10db032"))["history"]["history"]
    history={};proof={}
    def add(row):
        key=row["stable_id"]
        if key in history and history[key]!=row:raise ValueError("historical_identity_conflict")
        history[key]=row
    path=Path("data/generated/issue-33-data-growth-v1/history-source-metadata.jsonl.gz")
    if boundary.sha(path)!=old["six_historical_generations"]["sha256"]:raise ValueError("history_source_changed")
    with gzip.open(path,"rb") as stream:
        for line in stream:add(json.loads(line))
    if len(history)!=old["six_historical_generations"]["unique_rows"]:raise ValueError("history_count_changed")
    proof["six_generations"]=dict(sha256=boundary.sha(path),unique_rows=len(history))
    path=Path("data/generated/issue15-v5-slot120/frozen-split.jsonl")
    if boundary.sha(path)!=old["frozen_input_only"]["sha256"]:raise ValueError("frozen_input_history_changed")
    with path.open("rb") as stream:
        for line in stream:add(historical_input_metadata(line))
    proof["frozen_input_only"]=dict(old["frozen_input_only"])
    for relative in ("issue-33-data-growth-v1/wiki","issue-33-data-growth-v1/aozora-extract","issue-33-data-growth-v2/wiki-extra"):
        path=Path("data/generated")/relative/"targets.jsonl"
        if boundary.sha(path)!=old[relative]["sha256"]:raise ValueError("growth_source_history_changed")
        count=0
        with path.open("rb") as stream:
            for line in stream:
                row=json.loads(line)
                add(dict(stable_id=row["stable_id"],population="historical",source=row["source"],
                    input_hash=canonical_json_hash([row["left_context"],row["reading"]])))
                count+=1
        if count!=old[relative]["rows"]:raise ValueError("growth_source_count_changed")
        proof[relative]=dict(old[relative])
    for root,selection_key,target_file in ((Path("data/generated/issue-31-kwdlc-probe-v1"),"selected_documents","targets-r2.jsonl"),
                                         (boundary.pilot.ROOT,"documents","targets.jsonl")):
        selection=json.loads((root/"selection.json").read_bytes())
        sources={};unit_count=0
        for doc in selection[selection_key]:
            raw=(root/"source"/(doc["document_id"]+".knp")).read_bytes()
            if blob_sha1(raw)!=doc["git_blob_sha1"]:raise ValueError("exposed_source_blob_changed")
            for index,unit in enumerate(annotation_units(doc["document_id"],raw)):
                source=source_metadata(doc["document_id"],unit)
                sources[(doc["document_id"],index)]=source;unit_count+=1
                add(dict(stable_id="exposed-kwdlc-unit-"+canonical_json_hash([doc["document_id"],index]),population="historical",source=source))
        path=root/target_file
        expected=old["old_kwdlc_probe"]["targets_sha256"] if selection_key=="selected_documents" else "08adf8380c474ea4bd4e6c414748ac6c1506ffbf07c23c1ab599fd9afcfe0417"
        if boundary.sha(path)!=expected:raise ValueError("exposed_input_history_changed")
        targets=[json.loads(line) for line in path.read_bytes().splitlines()]
        for row in targets:
            if "reading" not in row:continue
            index=row.get("annotation_unit",row.get("sentence_index"))
            add(dict(stable_id="exposed-kwdlc-input-"+row["stable_id"],population="historical",
                     source=sources[(row["document_id"],index)],input_hash=canonical_json_hash([row["left_context"],row["reading"]])))
        proof[root.name]=dict(documents=len(selection[selection_key]),annotation_units=unit_count,targets_sha256=expected)
    return list(history.values()),proof
