# Issue #25 confidence-gate experiment harness

These scripts produced
[`reports/issue-25-confidence-gate.json`](../../reports/issue-25-confidence-gate.json),
the pre-registered evaluation of a confidence gate on the revision-2 (C2)
reranker. The plan is the body of
[Issue #25](https://github.com/tsuyoshi-otake/sakura-rerank/issues/25); the
report records its SHA-256 (`plan_body_sha256`, the UTF-8 bytes of the Issue
`body` field as returned by the GitHub REST API). Both scripts are tracked byte
for byte so the hashes in the report can be checked against reviewable source.

| File | Role |
| --- | --- |
| `run.py` | Harness: cross-fitted epoch/score/tau selection on train OOF, final gates, the decision, the single dev evaluation, the INT8 reference, and the tracked report |
| `recompute.py` | Independent recomputation of the cross-fit, final gates, decision, and dev counts, written in a separate context from the Issue body alone |

## Protocol

- Gate: keep the converter's first candidate unless the model's top candidate
  beats it by more than tau. Score **L** is the logit difference (as in Issue
  #21); score **P** is the softmax-probability difference. Logits are converted
  from the stored float32 values to float64 first.
- Tau is the smallest grid value whose harm on the selection rows is at most
  `k_max(N) = max{k : P(Binomial(N, 1/400) <= k) <= 1/20}` (exact integers), N
  being the selection rows whose converter first choice is correct. The score
  with more selection-row rescue wins; ties go to fewer harm, then L.
- Cross-fit: for each seed and outer fold, the epoch, score, and tau come from
  the other four folds only; the outer fold is then counted. The decision uses
  only these cross-fitted train counts and is written, with the cross-fit and
  selection hashes, before dev is read. Adoption requires, for every seed,
  harm <= 0.25% of baseline-correct rows, rescue >= 3 x harm, and relative error
  reduction >= 10%.
- Dev and INT8 are reference measurements only. No model is trained, the
  frozen split JSONL is not read, and the final holdout is never touched.

## Running

Inputs are the hash-pinned Issue #21 artifacts in the ignored
`data/generated/issue-21-retrain/` directory and, for the INT8 reference, the
revision-2 ONNX files and numeric caches. Outputs go to the ignored
`data/generated/issue-25-confidence-gate/`; every stage refuses to overwrite.

```powershell
$py = "<venv>\Scripts\python.exe"   # Python 3.13, numpy, onnxruntime 1.23.2
& $py -I research/issue-25-confidence-gate/run.py crossfit
& $py -I research/issue-25-confidence-gate/run.py select
& $py -I research/issue-25-confidence-gate/run.py decide
& $py -I research/issue-25-confidence-gate/run.py eval-dev
& $py -I research/issue-25-confidence-gate/run.py int8
& $py -I research/issue-25-confidence-gate/recompute.py
& $py -I research/issue-25-confidence-gate/run.py publish
```

All outputs are research-only: Gate A remains failed, and no Sakura Input
production change is authorized.
