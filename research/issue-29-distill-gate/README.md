# Issue #29 distillation + confidence-gate experiment harness

These scripts produced
[`reports/issue-29-distill-gate.json`](../../reports/issue-29-distill-gate.json),
the pre-registered evaluation of a single C2-architecture student distilled
from the Issue #27 seed ensemble, with Issue #25's confidence gate. The plan is
the body of [Issue #29](https://github.com/tsuyoshi-otake/sakura-rerank/issues/29);
the report records its SHA-256 (`plan_body_sha256`, the UTF-8 bytes of the
Issue `body` field as returned by the GitHub REST API). Both scripts are
tracked byte for byte so the hashes in the report can be checked against
reviewable source.

| File | Role |
| --- | --- |
| `run.py` | Harness: parity check, nested teachers, distilled students, cross-fitted gate, criteria 1-3 written before dev, final student, ONNX export and parity, latency benchmark, final decision, the single dev evaluation, and the tracked report |
| `recompute.py` | Independent recomputation of the teacher epochs, cross-fit, final epoch and gate, criteria 1-3, and dev counts from the saved arrays, written in a separate context from the Issue bodies alone |

## Protocol

- Teacher: the element-wise mean of the three C2 seeds' float64 logits (the
  Issue #27 ensemble). Every row's teacher logits come from models that never
  trained on that row.
- Nested teachers for the cross-fit: for each seed and each of the ten fold
  pairs {a, b}, a C2 model is trained on the other three folds for 20 epochs
  (seed + 1,000,003 x (6 + pair index)) and scores folds a and b every epoch.
  The student evaluated on outer fold k therefore learns from teachers that
  never trained on fold k. Teacher epochs follow Issue #25's epoch rule on the
  rows outside fold k.
- Final teacher: the Issue #21 OOF logits at epochs 9 / 8 / 10, averaged.
- Student: Issue #21's C2 model, features, hyperparameters, rows, and batch
  order; only the loss changes to 0.5 x the C2 loss + 0.5 x T^2 x
  KL(teacher || student) with T = 2. Training imports Issue #21's hash-pinned
  harness. Before any distillation, the same loop with KL weight 0 must
  reproduce Issue #21's stored OOF logits bitwise (seed 20260814, fold 0,
  epochs 1-2).
- Gate and decision: Issue #25's rules, imported by hash. Adoption requires,
  for every student seed, cross-fitted harm <= 0.25% of baseline-correct rows,
  rescue >= 3 x harm, and RER >= 10%; the seed-20260814 final student's FP32
  ONNX p95 <= 2 ms under `research_tiny_r2.benchmark_onnx`; and its FP32 ONNX
  gated decisions equal to its stored torch dev-logit decisions on all 1,788
  dev rows. Criteria 1-3 are written with hashes before dev is read. Dev,
  INT8, the reference rules, and the single-model latency are reference only.
  The frozen split JSONL is not read and the final holdout is never touched.

## Running

Inputs are the hash-pinned Issue #21 artifacts in the ignored
`data/generated/issue-21-retrain/` directory (its `run.py` is imported from
there because its paths assume that location; it is byte-identical to
`research/issue-21-retrain/run.py`), the v1 numeric cache, and the revision-2
cost-gap cache and ONNX file. Outputs, including checkpoints and ONNX files, go
to the ignored `data/generated/issue-29-distill-gate/` and are not distributed;
every stage refuses to overwrite. Training needs CUDA (deterministic
algorithms).

```powershell
$py = "<venv>\Scripts\python.exe"   # Python 3.13, numpy, torch (CUDA), onnx, onnxruntime 1.23.2
& $py -I research/issue-29-distill-gate/run.py parity
& $py -I research/issue-29-distill-gate/run.py teachers
& $py -I research/issue-29-distill-gate/run.py teacher-select
& $py -I research/issue-29-distill-gate/run.py students
& $py -I research/issue-29-distill-gate/run.py crossfit
& $py -I research/issue-29-distill-gate/run.py select
& $py -I research/issue-29-distill-gate/run.py decide-accuracy
& $py -I research/issue-29-distill-gate/run.py final
& $py -I research/issue-29-distill-gate/run.py export
& $py -I research/issue-29-distill-gate/run.py benchmark
& $py -I research/issue-29-distill-gate/run.py decide
& $py -I research/issue-29-distill-gate/run.py eval-dev
& $py -I research/issue-29-distill-gate/recompute.py
& $py -I research/issue-29-distill-gate/run.py publish
```

All outputs are research-only: Gate A remains failed, and no Sakura Input
production change is authorized.
