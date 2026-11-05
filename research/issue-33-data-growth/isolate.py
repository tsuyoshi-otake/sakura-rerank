"""Freeze source-isolated development inputs before any converter/model outcome."""
from collections import Counter
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.growth_isolation import historical_input_metadata, isolate
from sakura_rerank.data.kwdlc_probe import write_once
from extract import authenticate
from prepare_sources import ROOT, sha
from extend_wiki import ROOT as V2_ROOT, bound_plan

RESERVATION_COMMIT = "d2bff3bcbef7e7104fc081e6ee195c1427cd7f4f"
FROZEN = Path("data/generated/issue15-v5-slot120/frozen-split.jsonl")
FROZEN_SHA = "0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82"


def lines(path):
    with path.open("rb") as stream:
        while raw := stream.readline(256*1024+1):
            if len(raw) > 256*1024:raise ValueError("source_line_bound")
            yield raw


def run(version="v1", plan_commit=None):
    authenticate(RESERVATION_COMMIT)
    if version not in ("v1","v2"):raise ValueError("unregistered_version")
    sources={mode:ROOT/mode for mode in ("wiki","aozora-extract")}
    minimum_context=0
    plan_sha=None
    if version=="v2":
        plan,plan_sha=bound_plan(plan_commit)
        minimum_context=plan["minimum_left_context_chars"]
        if minimum_context!=8:raise ValueError("unregistered_context_policy")
        sources["wiki-extra"]=V2_ROOT/"wiki-extra"
    output=(ROOT if version=="v1" else V2_ROOT)/"isolation"
    output.mkdir(exist_ok=False)
    start=time.monotonic()
    receipt=dict(kind="growth_input_reservation",status="failed",gold_certified=False,
        new_final_test_used=False,source_reservation_commit=RESERVATION_COMMIT,
        historical_labels_candidates_decoded=False,models_trained=0)
    if version=="v2":receipt.update(v2_plan_commit=plan_commit,v2_plan_sha256=plan_sha,minimum_context_chars=minimum_context)
    try:
        history={}
        with gzip.open(ROOT/"history-source-metadata.jsonl.gz","rb") as stream:
            for raw in stream:
                row=json.loads(raw)
                if row["stable_id"] in history and row!=history[row["stable_id"]]:
                    raise ValueError("historical_identity_conflict")
                history[row["stable_id"]]=row
        digest=hashlib.sha256()
        frozen_rows=0
        for raw in lines(FROZEN):
            digest.update(raw)
            row=historical_input_metadata(raw)
            if row["stable_id"] in history:raise ValueError("frozen_identity_conflict")
            history[row["stable_id"]]=row
            frozen_rows+=1
        if digest.hexdigest()!=FROZEN_SHA or frozen_rows!=17880:
            raise ValueError("frozen_history_changed")
        receipt.update(historical_source_unique_rows=len(history)-frozen_rows,
            frozen_input_rows=frozen_rows,frozen_input_file_sha256=FROZEN_SHA,
            historical_bounded_inputs_hashed_and_discarded=True)
        targets=[]
        input_artifacts={}
        context_excluded=Counter()
        for mode,directory in sources.items():
            path=directory/"targets.jsonl"
            execution=json.loads((directory/"execution.json").read_bytes())
            if execution["status"]!="complete" or sha(path)!=execution["targets_sha256"]:
                raise ValueError("source_extraction_incomplete_or_changed")
            if mode=="wiki-extra" and execution["plan_sha256"]!=plan_sha:raise ValueError("extension_plan_differs")
            part=[json.loads(raw) for raw in lines(path)]
            if len(part)!=execution["target_count"]:raise ValueError("source_population_changed")
            for row in part:
                if len(row["left_context"])<minimum_context:context_excluded[row["corpus"]+"/"+row["population"]]+=1
                else:targets.append(row)
            input_artifacts[mode]=dict(sha256=execution["targets_sha256"],rows=len(part),execution_sha256=sha(directory/"execution.json"))
        receipt["source_artifacts"]=input_artifacts
        receipt["context_excluded_before_relation_closure"]=dict(context_excluded)
        metadata=list(history.values())+[dict(stable_id=row["stable_id"],source=row["source"],
            population=row["population"],input_hash=canonical_json_hash([row["left_context"],row["reading"]])) for row in targets]
        print(json.dumps({"stage":"isolation","historical":len(history),"new":len(targets)}),flush=True)
        excluded,components,audit=isolate(metadata)
        receipt["audit"]=audit
        retained=[dict(row,component_id=components[row["stable_id"]]) for row in targets if row["stable_id"] not in excluded]
        counts=Counter(row["corpus"]+"/"+row["population"] for row in retained)
        receipt["retained_by_source"]=dict(counts)
        # Save the complete audit and retained populations even if fixed yield fails.
        write_once(output/"excluded.json",canonical_json_bytes(excluded)+b"\n")
        destination=output/"retained.jsonl"
        with destination.open("xb") as stream:
            for row in sorted(retained,key=lambda row:row["stable_id"]):stream.write(canonical_json_bytes(row)+b"\n")
        receipt["retained_sha256"]=sha(destination)
        minimum={"jawiki/train":50000,"aozora/train":25000,"jawiki/evaluation":2000,"aozora/evaluation":2000}
        if any(counts[key]<n for key,n in minimum.items()):
            receipt["status"]="insufficient_fixed_cohort_yield"
            receipt["minimum_before_candidate_eligibility"]=minimum
            return receipt
        evaluation=[]
        for corpus in ("jawiki","aozora"):
            evaluation.extend(sorted((r for r in retained if r["corpus"]==corpus and r["population"]=="evaluation"),key=lambda r:r["stable_id"])[:2000])
        selected=sorted([r for r in retained if r["population"]=="train"]+evaluation,key=lambda r:r["stable_id"])
        requests={}
        with (output/"selected.jsonl").open("xb") as stream:
            for row in selected:
                key="growth-reading-"+canonical_json_hash(row["reading"])
                row["candidate_request_id"]=key
                requests[key]=dict(stable_id=key,reading=row["reading"])
                stream.write(canonical_json_bytes(row)+b"\n")
        with (output/"requests.jsonl").open("xb") as stream:
            for key in sorted(requests):stream.write(canonical_json_bytes(requests[key])+b"\n")
        receipt.update(status="complete",selected_sha256=sha(output/"selected.jsonl"),
            requests_sha256=sha(output/"requests.jsonl"),selected_rows=len(selected),unique_readings=len(requests),
            development_evaluation_rows=len(evaluation),converter_outcomes_seen=False)
        return receipt
    except Exception as error:
        receipt["error_type"]=type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(output/"execution.json",canonical_json_bytes(receipt)+b"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",choices=("v1","v2"),default="v1")
    parser.add_argument("--plan-commit")
    args=parser.parse_args()
    print(canonical_json_bytes(run(args.version,args.plan_commit)).decode("utf-8"))
