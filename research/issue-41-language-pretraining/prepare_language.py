"""Recheck all evaluation history before generating causal train-only windows."""
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import canonical_json_hash,text_sha256,canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.language_windows import fragment_windows
from sakura_rerank.research_tiny import character_ids
from language_common import ROOT,TRAIN_ROOT,PLAN,bound_plan,rows,read_json,save,sha
from acquire_sources import PLAN_COMMIT
from cohort import source_history


def admitted_fragments():
    plan=bound_plan(PLAN_COMMIT);recipe=plan["pretraining"]
    if sha(recipe["source_path"])!=recipe["source_sha256"]:raise ValueError("language_train_source_changed")
    original=read_json(TRAIN_ROOT/"isolation/execution.json")
    if original["status"]!="complete" or original["selected_sha256"]!=recipe["source_sha256"]:raise ValueError("original_train_isolation_missing")
    if read_json(ROOT/"cohort-verification.json")["cohort_sha256"]!=sha(ROOT/"cohort.json"):raise ValueError("new_source_cohort_not_verified")
    historical,proof=source_history()
    approved_train=set()
    for part in ("issue-33-data-growth-v1/wiki","issue-33-data-growth-v1/aozora-extract","issue-33-data-growth-v2/wiki-extra"):
        for row in rows(Path("data/generated")/part/"targets.jsonl"):
            if row["population"]=="train":approved_train.add(row["stable_id"])
    # Growth train rows are allowed training, not evaluation. The original six
    # generations/frozen inputs use independent historical IDs and remain here.
    historical=[r for r in historical if r["stable_id"] not in approved_train]
    for row in rows(ROOT/"source-coverage.jsonl"):historical.append(dict(row,population="historical"))
    for row in rows(ROOT/"pool.jsonl"):
        historical.append(dict(stable_id="language-eval-history-"+row["stable_id"],population="historical",source=row["source"],
                               input_hash=canonical_json_hash([row["left_context"],row["reading"]])))
    train=[r for r in rows(recipe["source_path"]) if r["population"]=="train"]
    if any(r["stable_id"] not in approved_train or r["corpus"] not in ("jawiki","aozora") for r in train):raise ValueError("unapproved_lm_source")
    metadata=[dict(stable_id=r["stable_id"],population="train",source=r["source"],
                   input_hash=canonical_json_hash([r["left_context"],r["reading"]])) for r in train]
    print(json.dumps(dict(stage="language_train_history_closure",historical=len(historical),train_fragments=len(train))),flush=True)
    excluded,components,audit=isolate_with_source_coverage(historical+metadata)
    selected=[r for r in train if r["stable_id"] not in excluded]
    return selected,excluded,components,dict(original_train_fragments=len(train),admitted_fragments=len(selected),
        removed_fragments=len(excluded),historical_records=len(historical),approved_growth_train_ids=len(approved_train),
        history=proof,audit=audit,original_isolation_sha256=sha(TRAIN_ROOT/"isolation/execution.json"))


def generate_windows(selected):
    fragments={}
    for row in sorted(selected,key=lambda r:r["stable_id"]):
        text=row["left_context"]+row["target"]
        if not 9<=len(text)<=128:raise ValueError("source_fragment_bound_differs")
        identity=text_sha256(text)
        if identity not in fragments:fragments[identity]=(text,row)
        elif fragments[identity][0]!=text:raise ValueError("fragment_hash_collision")
    windows={}
    for text,row in fragments.values():
        for window in fragment_windows(text):
            key=window["window_id"]
            if key not in windows:windows[key]=dict(window,stable_id=row["stable_id"],corpus=row["corpus"])
            elif (windows[key]["context"],windows[key]["next_character"])!=(window["context"],window["next_character"]):raise ValueError("window_hash_collision")
    available=Counter(r["corpus"] for r in windows.values());chosen=[]
    for corpus in ("jawiki","aozora"):
        chosen.extend(sorted((r for r in windows.values() if r["corpus"]==corpus),key=lambda r:r["window_id"])[:500000])
    chosen.sort(key=lambda r:r["window_id"])
    return chosen,dict(unique_fragments=len(fragments),unique_windows_before_cap=len(windows),available_per_corpus=dict(available),
        selected_per_corpus=dict(Counter(r["corpus"] for r in chosen)),selected_windows=len(chosen))


def run():
    start=time.monotonic();selected,excluded,components,history=admitted_fragments()
    plan=read_json(PLAN);windows,counts=generate_windows(selected)
    write_once(ROOT/"lm-admitted-fragments.jsonl",b"".join(canonical_json_bytes(r)+b"\n" for r in selected))
    save(ROOT/"lm-source-relations.json",dict(excluded=excluded,components=components))
    count=len(windows);numeric=dict(context_ids=np.zeros((count,64),dtype=np.uint16),context_lengths=np.zeros(count,dtype=np.uint8),next_ids=np.zeros(count,dtype=np.uint16))
    with (ROOT/"lm-window-provenance.jsonl").open("xb") as stream:
        for i,row in enumerate(windows):
            numeric["context_ids"][i],numeric["context_lengths"][i]=character_ids(row["context"],64)
            numeric["next_ids"][i]=character_ids(row["next_character"],1)[0][0]
            metadata={k:row[k] for k in ("window_id","stable_id","corpus","position","fragment_sha256")}
            stream.write(canonical_json_bytes(metadata)+b"\n")
    np.savez_compressed(ROOT/"language-windows.npz",**numeric)
    ready=plan["pretraining"]["minimum_windows"]<=count<=plan["pretraining"]["maximum_windows"]
    result=dict(kind="train_only_language_windows",status="ready" if ready else "insufficient_do_not_train",**counts,
        source_isolation=history,plan_sha256=sha(PLAN),source_sha256=plan["pretraining"]["source_sha256"],
        scripts={p:sha(p) for p in ("research/issue-41-language-pretraining/prepare_language.py","src/sakura_rerank/data/language_windows.py")},
        artifacts={name:sha(ROOT/name) for name in ("lm-admitted-fragments.jsonl","lm-source-relations.json","lm-window-provenance.jsonl","language-windows.npz")},
        elapsed_seconds=round(time.monotonic()-start,3),reading_labels_used=False,kwdlc_training_rows=0,
        gold_certified=False,final_test_used=False)
    save(ROOT/"language-preparation.json",result);save("manifests/language-pretraining-data-v1.json",result)
    return {k:result[k] for k in ("status","unique_fragments","selected_windows","selected_per_corpus","elapsed_seconds")}


def verify():
    start=time.monotonic();receipt=read_json(ROOT/"language-preparation.json")
    for name,expected in receipt["artifacts"].items():
        if sha(ROOT/name)!=expected:raise ValueError("language_artifact_changed")
    selected,excluded,components,history=admitted_fragments()
    if history!=receipt["source_isolation"] or dict(excluded=excluded,components=components)!=read_json(ROOT/"lm-source-relations.json"):
        raise ValueError("language_history_closure_replay_differs")
    by_id={r["stable_id"]:r for r in selected}
    with np.load(ROOT/"language-windows.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k]) for k in saved.files}
    ids=set();checked=0;counts=Counter()
    for i,meta in enumerate(rows(ROOT/"lm-window-provenance.jsonl")):
        row=by_id[meta["stable_id"]];text=row["left_context"]+row["target"];position=meta["position"]
        context=text[max(0,position-64):position];next_char=text[position]
        if (not 8<=position<len(text) or meta["fragment_sha256"]!=text_sha256(text)
                or meta["window_id"]!=canonical_json_hash([context,next_char]) or meta["window_id"] in ids):raise ValueError("language_causal_provenance_differs")
        # Independent scalar implementation of the frozen character hash.
        encoded=[(ord(c)*2654435761)%13311+1 for c in context]+[0]*(64-len(context))
        if (arrays["context_lengths"][i]!=len(context) or arrays["next_ids"][i]!=(ord(next_char)*2654435761)%13311+1
                or arrays["context_ids"][i].tolist()!=encoded):raise ValueError("language_numeric_recount_differs")
        ids.add(meta["window_id"]);counts[meta["corpus"]]+=1;checked+=1
    if checked!=receipt["selected_windows"] or checked!=len(arrays["next_ids"]) or dict(counts)!=receipt["selected_per_corpus"]:
        raise ValueError("language_window_denominator_differs")
    # Deterministic selection replay also checks the six-position and per-corpus caps.
    regenerated,_=generate_windows(selected)
    if [r["window_id"] for r in regenerated]!=[r["window_id"] for r in rows(ROOT/"lm-window-provenance.jsonl")]:raise ValueError("language_window_selection_replay_differs")
    result=dict(kind="language_window_verification",status="passed",windows=checked,all_causal_hashes_recounted=True,
        full_history_closure_replayed=True,selection_replayed=True,data_manifest_sha256=sha(ROOT/"language-preparation.json"),
        elapsed_seconds=round(time.monotonic()-start,3),script_sha256=sha(__file__))
    save(ROOT/"language-verification.json",result);save("reports/issue-41-language-data-verification-v1.json",result)
    return result


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("prepare","verify"));args=parser.parse_args()
    print(json.dumps(run() if args.stage=="prepare" else verify()))
