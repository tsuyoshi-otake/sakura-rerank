"""Recount all context diagnostics using scalar candidate selection, no inference."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("data/generated/issue-33-fundamentals-v1")
GROWTH = Path("data/generated/issue-33-data-growth-v2")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = json.loads((ROOT/"report.json").read_bytes())
    if report["status"] != "passed" or sha(ROOT/"scores.npz") != report["diagnostic_scores_sha256"]:
        raise ValueError("diagnostic_receipt_mismatch")
    with np.load(GROWTH/"cache/evaluation.npz",allow_pickle=False) as z:
        mask=z["candidate_mask"].tolist(); gold=z["correct_mask"].tolist(); same=z["baseline_equivalent"].tolist()
    if sha(GROWTH/"evaluation/scores.npz") != report["input_scores_sha256"]:
        raise ValueError("original_scores_changed")
    with np.load(GROWTH/"evaluation/scores.npz",allow_pickle=False) as z:
        old={k:z[k].tolist() for k in z.files}
    with np.load(ROOT/"scores.npz",allow_pickle=False) as z:
        runs={k:z[k].tolist() for k in z.files}
    verified=0
    for entry in report["context_runs"]:
        values=runs[entry["model"]+"/"+entry["variant"]]
        for mode in ("ungated","gated"):
            counts=dict(rows=0,correct=0,changed=0,rescue=0,harm=0,wrong_to_wrong=0,
                        changed_winners=0,intact_only_correct=0,diagnostic_only_correct=0)
            for i,scores in enumerate(values):
                valid=[j for j,v in enumerate(mask[i]) if v]
                winner=max(valid,key=lambda j:scores[j])
                original=max(valid,key=lambda j:old[entry["model"]][i][j])
                if mode=="gated":
                    if scores[winner]-scores[0]<=1.7: winner=0
                    before=old[entry["model"]][i]
                    if before[original]-before[0]<=1.7: original=0
                right=gold[i][winner]; base=gold[i][0]; changed=not same[i][winner]; before_right=gold[i][original]
                counts["rows"]+=1; counts["correct"]+=right; counts["changed"]+=changed
                counts["rescue"]+=not base and right
                counts["harm"]+=base and not right
                counts["wrong_to_wrong"]+=not base and not right and changed
                counts["changed_winners"]+=winner!=original
                counts["intact_only_correct"]+=before_right and not right
                counts["diagnostic_only_correct"]+=right and not before_right
            if counts != entry["modes"][mode]:
                raise ValueError("scalar_recount_differs")
            verified+=1
    result=dict(status="passed",point_reports_recounted=verified,rows_per_report=4000,
                new_inference_runs=0,new_fits=0,report_sha256=sha(ROOT/"report.json"),
                diagnostic_scores_sha256=report["diagnostic_scores_sha256"],
                method="Scalar candidate/surface-equivalence selection; no diagnostic outcome helper")
    with (ROOT/"verification.json").open("x",encoding="utf-8") as stream:
        json.dump(result,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps(result))


if __name__=="__main__": main()
