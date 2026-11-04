"""Read-only relation ablations; never change the registered population or fit."""
from collections import Counter, defaultdict
import argparse
import gzip
import json
import time

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.growth_isolation import historical_input_metadata, validate_metadata
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.splitter import _build_leakage_components, _UnionFind, _union_groups
from isolate import FROZEN, FROZEN_SHA, lines
from prepare_sources import ROOT, sha


def summarize(union, rows):
    counts=Counter(); largest=0
    for group in union.groups().values():
        largest=max(largest,len(group))
        roles={rows[i]["population"] for i in group}
        reason="historical" if "historical" in roles else ("cross_partition" if len(roles)>1 else "retained")
        for i in group:
            r=rows[i]
            if r["population"]!="historical":counts[r["corpus"]+"/"+r["population"]+"/"+reason]+=1
    return dict(counts=dict(sorted(counts.items())),largest_component=largest)


def run(minimum_context=None):
    if minimum_context not in (None, 8):raise ValueError("unsupported_diagnostic_policy")
    start=time.monotonic()
    reservation=json.loads((ROOT/"source-preparation.json").read_bytes())
    if sha(ROOT/"history-source-metadata.jsonl.gz")!=reservation["history_metadata_sha256"] or sha(FROZEN)!=FROZEN_SHA:
        raise ValueError("history_changed")
    history={}
    with gzip.open(ROOT/"history-source-metadata.jsonl.gz","rb") as stream:
        for line in stream:
            row=json.loads(line);history[row["stable_id"]]=row
    for line in lines(FROZEN):
        row=historical_input_metadata(line);history[row["stable_id"]]=row
    rows=list(history.values()); lengths={}; profiles={}
    for mode in ("wiki","aozora-extract"):
        path=ROOT/mode/"targets.jsonl"; receipt=json.loads((ROOT/mode/"execution.json").read_bytes())
        if sha(path)!=receipt["targets_sha256"]:raise ValueError("targets_changed")
        counts=Counter(); readings=set(); inputs=Counter(); articles=set()
        for raw in lines(path):
            target=json.loads(raw); key=canonical_json_hash([target["left_context"],target["reading"]])
            lengths[key]=len(target["left_context"])
            if minimum_context is None or len(target["left_context"])>=minimum_context:
                rows.append(dict(stable_id=target["stable_id"],source=target["source"],population=target["population"],corpus=target["corpus"],input_hash=key))
            else:
                counts["diagnostic_context_excluded/"+target["population"]]+=1
            readings.add(target["reading"]);inputs[key]+=1;articles.add(target["source_id"])
            counts[target["population"]]+=1
            counts["reading_le_9"]+=len(target["reading"])<=9
            counts["empty_context"]+=not target["left_context"]
            counts["context_lt_8"]+=len(target["left_context"])<8
            counts["surface_gt_32"]+=len(target["target"])>32
        profiles[mode]=dict(counts=dict(counts),unique_readings=len(readings),source_documents=len(articles),
            duplicate_input_rows=sum(n for n in inputs.values() if n>1))
    for row in rows:validate_metadata(row)
    source=_build_leakage_components(rows,near_duplicate_threshold=0.8)
    union=_UnionFind(len(rows))
    _union_groups(union,{str(i):group for i,group in enumerate(source.component_records)})
    steps={"source_relations_only":summarize(union,rows)}
    inputs=defaultdict(list)
    for i,row in enumerate(rows):
        if row.get("input_hash"):inputs[row["input_hash"]].append(i)
    # Long inputs first, empty inputs last: increments depend on this order.
    for name,predicate in (("plus_context_ge_8",lambda n:n>=8),("plus_context_1_to_7",lambda n:0<n<8),("plus_empty_context",lambda n:n==0)):
        selected={key:group for key,group in inputs.items() if key in lengths and predicate(lengths[key])}
        duplicate_groups=_union_groups(union,selected)
        steps[name]=dict(summarize(union,rows),input_duplicate_groups_added=duplicate_groups)
    # Historical-only repeated inputs can also bridge historical source groups.
    _union_groups(union,{key:group for key,group in inputs.items() if key not in lengths})
    final=summarize(union,rows)
    registered=json.loads((ROOT/"isolation/execution.json").read_bytes())
    retained={"/".join(key.split("/")[:2]):value for key,value in final["counts"].items() if key.endswith("/retained")}
    if minimum_context is None and retained!=registered["retained_by_source"]:raise ValueError("diagnostic_final_population_differs")
    result=dict(kind="growth_isolation_diagnostic",status="complete",source_profiles=profiles,incremental_relation_steps=steps,
        full_relation_result=final,registered_population_unchanged=True,diagnostic_order_not_unique_causal_attribution=True,
        counterfactual_minimum_context=minimum_context,
        independent_gold=False,models_trained=0,elapsed_seconds=round(time.monotonic()-start,3))
    name="isolation-diagnostic.json" if minimum_context is None else "isolation-diagnostic-context8.json"
    write_once(ROOT/name,canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-min-context",type=int,choices=(8,))
    print(canonical_json_bytes(run(parser.parse_args().diagnostic_min_context)).decode("utf-8"))
