# Issue #27 seed-ensemble confidence-gate experiment harness

These scripts produced
[`reports/issue-27-ensemble-gate.json`](../../reports/issue-27-ensemble-gate.json),
the pre-registered evaluation of a confidence gate on the mean of the three
Issue #21 C2 models' logits. The plan is the body of
[Issue #27](https://github.com/tsuyoshi-otake/sakura-rerank/issues/27); the
report records its SHA-256 (`plan_body_sha256`, the UTF-8 bytes of the Issue
`body` field as returned by the GitHub REST API). Both scripts are tracked byte
for byte so the hashes in the report can be checked against reviewable source.

| File | Role |
| --- | --- |
| `run.py` | Harness: cross-fit, final gate, criteria 1-3 written before dev, ensemble ONNX export and parity, latency benchmark, final decision, the single dev evaluation, and the tracked report |
| `recompute.py` | Independent recomputation of the cross-fit, final gate, criteria 1-3, and dev counts, written in a separate context from the Issue bodies alone |

## Protocol

- Model: the element-wise mean of the three seeds' float32 logits, converted to
  float64. No model is trained.
- Gate and counting: Issue #25's rules, imported from its hash-pinned `run.py`
  so they cannot drift. Each seed's epoch is chosen per outer fold on the other
  four folds; the ensemble's score (L or P) and tau then come from the same
  four folds with the exact-binomial harm budget, and the outer fold is
  counted. The final gate uses the Issue #21 epochs (9 / 8 / 10) on the full
  train OOF.
- Adoption requires all five criteria: cross-fitted harm <= 0.25% of
  baseline-correct rows, rescue >= 3 x harm, relative error reduction >= 10%,
  FP32 ensemble ONNX p95 <= 2 ms under `research_tiny_r2.benchmark_onnx`
  (batch 1, one intra-op and one inter-op thread, 100 warmup runs, 10,000
  measured runs, inputs prebuilt), and FP32 ONNX gated decisions equal to the
  stored-logit decisions on all 1,788 dev rows.
- Order: criteria 1-3 are written with the cross-fit and selection hashes
  before dev is read; the ONNX parity and the benchmark (which also computes
  ungated dev ranking metrics) run after that; the final decision is written
  before the single dev evaluation. Dev, INT8, the reference rules, and the
  single-model latency are reference measurements only. The frozen split JSONL
  is not read and the final holdout is never touched.

## Running

Inputs are the hash-pinned Issue #21 artifacts in the ignored
`data/generated/issue-21-retrain/` directory, the revision-2 ONNX and numeric
caches, and `src/sakura_rerank/research_tiny_r2.py` (hash-pinned). Outputs,
including the ensemble ONNX files, go to the ignored
`data/generated/issue-27-ensemble-gate/` and are not distributed; every stage
refuses to overwrite.

```powershell
$py = "<venv>\Scripts\python.exe"   # Python 3.13, numpy, torch, onnx, onnxruntime 1.23.2
& $py -I research/issue-27-ensemble-gate/run.py crossfit
& $py -I research/issue-27-ensemble-gate/run.py select
& $py -I research/issue-27-ensemble-gate/run.py decide-accuracy
& $py -I research/issue-27-ensemble-gate/run.py export
& $py -I research/issue-27-ensemble-gate/run.py benchmark
& $py -I research/issue-27-ensemble-gate/run.py decide
& $py -I research/issue-27-ensemble-gate/run.py eval-dev
& $py -I research/issue-27-ensemble-gate/recompute.py
& $py -I research/issue-27-ensemble-gate/run.py publish
```

All outputs are research-only: Gate A remains failed, and no Sakura Input
production change is authorized.
