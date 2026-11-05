"""Recount saved predictions against original target/candidate surfaces, without inference."""
from collections import Counter
import json
import math
from pathlib import Path
import re

import numpy as np

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from extend_wiki import ROOT
from prepare_sources import sha
from train import authenticate_fit

FIT_COMMIT="ad976a7f4515a80ff2602e8153b3decb35e37f6f"


def run():
    authenticate_fit(FIT_COMMIT)
    report_path=Path("reports/issue-33-data-growth-model-v2.json")
    report=json.loads(report_path.read_bytes())
    metadata=[json.loads(line) for line in (ROOT/"cache/evaluation-metadata.jsonl").read_bytes().splitlines()]
    targets={}
    with (ROOT/"isolation/selected.jsonl").open("rb") as stream:
        for line in stream:
            row=json.loads(line)
            if row["population"]=="evaluation":targets[row["stable_id"]]=row
    if set(targets)!={row["stable_id"] for row in metadata} or len(targets)!=4000:raise ValueError("raw_evaluation_population_differs")
    requests={row["candidate_request_id"] for row in targets.values()}
    snapshots={};identity=re.compile(rb'(?<!\\)"stable_id":"([^"\\]+)"')
    acquisition=json.loads((ROOT/"candidates/execution.json").read_bytes())
    for batch in acquisition["batches"]:
        directory=ROOT/"candidates"/f"batch-{batch['index']:05d}"
        if sha(directory/"execution.json")!=batch["execution_sha256"]:raise ValueError("batch_receipt_changed")
        terminal=json.loads((directory/"execution.json").read_bytes())
        if terminal["status"]!="complete":continue
        path=directory/"output.jsonl"
        if sha(path)!=terminal["output_sha256"]:raise ValueError("raw_candidates_changed")
        with path.open("rb") as stream:
            for line in stream:
                match=identity.search(line)
                if match and match[1].decode("ascii") in requests:
                    row=json.loads(line);snapshots[row["stable_id"]]=row
    if len(snapshots)!=len(requests):raise ValueError("unexpected_missing_candidate_execution")
    with np.load(ROOT/"evaluation/scores.npz",allow_pickle=False) as archive:scores={name:np.array(archive[name]) for name in archive.files}
    if sha(ROOT/"evaluation/scores.npz")!=report["scores_sha256"]:raise ValueError("scores_changed")
    base=[];cases=[];oracle=Counter()
    for item in metadata:
        target=targets[item["stable_id"]]
        all_surfaces=[c["surface"] for c in snapshots[target["candidate_request_id"]]["candidate_snapshots"]["training_top32"]["candidates"]]
        for k in (1,5,6,10,32):oracle[str(k)]+=target["target"] in all_surfaces[:k]
        if not all_surfaces:raise ValueError("unexpected_empty_candidate_snapshot")
        cases.append((target["target"],all_surfaces[:6]));base.append(all_surfaces[0]==target["target"])
    if dict(oracle)!=report["source_exact_presence"]:raise ValueError("source_presence_recount_differs")
    correct_by_run={}
    for mode in ("ungated","gated"):
        for name,values in scores.items():
            counts=Counter();rights=[]
            for i,(target,surfaces) in enumerate(cases):
                if not all(math.isfinite(float(v)) for v in values[i]):raise ValueError("unexpected_nonfinite_score")
                winner=max(range(len(surfaces)),key=lambda j:float(values[i,j]))
                if mode=="gated" and not float(values[i,winner]-values[i,0])>1.7:winner=0
                actual=surfaces[winner];right=actual==target;changed=actual!=surfaces[0];rights.append(right)
                counts.update(rows=1,correct=int(right),baseline_correct=int(base[i]),changed=int(changed),
                    rescue=int(not base[i] and right),harm=int(base[i] and not right),
                    wrong_to_wrong=int(not base[i] and not right and changed))
            key=mode+"/"+name;expected=report["models"][key]
            if any(expected[k]!=v for k,v in counts.items()):raise ValueError("surface_point_count_differs")
            if expected["correction_failure"]!=counts["harm"]+counts["wrong_to_wrong"]:raise ValueError("failure_recount_differs")
            correct_by_run[key]=rights
    for name,contrast in report["contrasts"].items():
        left,right=name.split(" minus ")
        a=correct_by_run[left];b=base if right=="baseline" else correct_by_run[right]
        left_only=sum(x and not y for x,y in zip(a,b));right_only=sum(y and not x for x,y in zip(a,b))
        if (left_only!=contrast["left_only_correct"] or right_only!=contrast["right_only_correct"]
                or not math.isclose(contrast["gain"],(left_only-right_only)/4000,abs_tol=1e-15)):
            raise ValueError("paired_contrast_recount_differs")
    result=dict(kind="growth_result_verification",status="passed",rows=4000,
        point_reports_verified=len(correct_by_run),paired_contrasts_verified=len(report["contrasts"]),
        source_presence_verified=dict(oracle),method="Original source targets plus authenticated raw candidate surfaces and immutable saved logits; no metric helper or repeat inference",
        report_sha256=sha(report_path),scores_sha256=report["scores_sha256"],new_inference_runs=0,new_model_fits=0,
        independent_human_gold=False,new_final_test_used=False)
    write_once(ROOT/"evaluation/verification.json",canonical_json_bytes(result)+b"\n")
    write_once(Path("reports/issue-33-data-growth-verification-v2.json"),canonical_json_bytes(result)+b"\n")
    print(canonical_json_bytes(result).decode("utf-8"))


if __name__=="__main__":run()
