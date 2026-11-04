"""Bind the nested training cohorts and unchanged development denominator."""
from collections import Counter
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.growth_numeric import eligible_target,encode
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import authenticate_identity,validate_probe_records
from candidates import BINARY,DICTIONARY,IDENTITY,IDENTITY_SHA
from extend_wiki import ROOT,bound_plan
from prepare_sources import sha

PLAN_COMMIT="1ca3fb4ff9670d1cd12f21e4d87f6bb975248415"


def run():
    import numpy as np
    plan,plan_sha=bound_plan(PLAN_COMMIT)
    selection=json.loads((ROOT/"isolation/execution.json").read_bytes())
    acquired=json.loads((ROOT/"candidates/execution.json").read_bytes())
    if selection["status"]!="complete" or acquired["status"]!="complete":raise ValueError("complete_input_stages_required")
    if sha(ROOT/"isolation/selected.jsonl")!=selection["selected_sha256"]:raise ValueError("selected_population_changed")
    identity=authenticate_identity(IDENTITY,IDENTITY_SHA,BINARY,DICTIONARY)
    requests=[json.loads(line) for line in (ROOT/"isolation/requests.jsonl").read_bytes().splitlines()]
    if sha(ROOT/"isolation/requests.jsonl")!=selection["requests_sha256"]:raise ValueError("requests_changed")
    snapshots={}; failures=0
    for offset in range(0,len(requests),100):
        directory=ROOT/"candidates"/f"batch-{offset//100:05d}"
        commitment=acquired["batches"][offset//100]
        if commitment["index"]!=offset//100 or sha(directory/"execution.json")!=commitment["execution_sha256"]:
            raise ValueError("candidate_batch_receipt_changed")
        receipt=json.loads((directory/"execution.json").read_bytes())
        batch=requests[offset:offset+100]
        if receipt["status"]!="complete":failures+=len(batch);continue
        raw=(directory/"output.jsonl").read_bytes()
        if sha(directory/"output.jsonl")!=receipt["output_sha256"]:raise ValueError("candidate_snapshot_changed")
        for row in validate_probe_records(raw,batch,identity):snapshots[row["stable_id"]]=row
    if len(snapshots)+failures!=len(requests):raise ValueError("unaccounted_candidate_requests")
    targets=[json.loads(line) for line in (ROOT/"isolation/selected.jsonl").read_bytes().splitlines()]
    if len(targets)!=selection["selected_rows"]:raise ValueError("selected_count_changed")
    train={"jawiki":[],"aozora":[]};evaluation=[];counts=Counter()
    for row in targets:
        snapshot=snapshots.get(row["candidate_request_id"])
        candidates=[] if snapshot is None else snapshot["candidate_snapshots"]["production_top6"]["candidates"]
        eligible,reason=eligible_target(row["target"],candidates)
        counts[row["corpus"]+"/"+row["population"]+"/"+reason]+=1
        if row["population"]=="evaluation":evaluation.append(row)
        elif eligible:train[row["corpus"]].append(row)
    for corpus in train:train[corpus].sort(key=lambda r:r["stable_id"])
    evaluation.sort(key=lambda r:r["stable_id"])
    output=ROOT/"cache";output.mkdir(exist_ok=False)
    receipt=dict(kind="growth_numeric_cache",status="insufficient_fixed_cohort_yield",plan_commit=PLAN_COMMIT,plan_sha256=plan_sha,
        selected_sha256=selection["selected_sha256"],candidate_execution_sha256=sha(ROOT/"candidates/execution.json"),
        available_eligible_training={k:len(v) for k,v in train.items()},source_outcomes=dict(counts),
        independent_gold=False,new_final_test_used=False,models_trained=0)
    if len(train["jawiki"])<50000 or len(train["aozora"])<25000:
        write_once(output/"manifest.json",canonical_json_bytes(receipt)+b"\n");return receipt
    if Counter(r["corpus"] for r in evaluation)!={"jawiki":2000,"aozora":2000}:raise ValueError("fixed_evaluation_population_differs")
    pool=train["jawiki"][:50000]+train["aozora"][:25000]
    artifacts={}
    for name,rows in (("train",pool),("evaluation",evaluation)):
        arrays,metadata=encode(rows,snapshots)
        if name=="train" and (np.any(arrays["gold"]<0) or not np.all(arrays["correct_mask"].sum(axis=1)==1)):
            raise ValueError("ineligible_numeric_train_target")
        with (output/(name+".npz")).open("xb") as stream:np.savez_compressed(stream,**arrays)
        write_once(output/(name+"-metadata.jsonl"),b"".join(canonical_json_bytes(r)+b"\n" for r in metadata))
        artifacts[name]=dict(rows=len(rows),sha256=sha(output/(name+".npz")),metadata_sha256=sha(output/(name+"-metadata.jsonl")))
        del arrays
    cohorts=dict(wiki_small=list(range(12516)),wiki_large=list(range(50000)),mixed=list(range(25000))+list(range(50000,75000)))
    write_once(output/"cohorts.json",canonical_json_bytes(cohorts)+b"\n")
    receipt.update(status="complete",artifacts=artifacts,cohorts_sha256=sha(output/"cohorts.json"),training_pool_rows=75000,evaluation_rows=4000,
        comparison_scope="All source/quantity comparisons conditional on left context of at least eight characters")
    write_once(output/"manifest.json",canonical_json_bytes(receipt)+b"\n")
    return receipt


if __name__=="__main__":print(canonical_json_bytes(run()).decode("utf-8"))
