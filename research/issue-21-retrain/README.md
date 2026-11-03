# Issue #21 retraining experiment harness

These scripts produced
[`reports/issue-21-retrain-experiment.json`](../../reports/issue-21-retrain-experiment.json),
the pre-registered comparison of three research recipes on the frozen v5
train/dev split. They are tracked byte-for-byte so the SHA-256 values in that
report (`artifacts.run_py_sha256`, `independent_recomputation.script_sha256`)
can be checked against reviewable source.

| File | Role |
| --- | --- |
| `run.py` | Harness: reproduce the v1 prototype without dev, grouped 5-fold CV, OOF-only selection, final training, the single dev evaluation, and the mechanical decision |
| `devin_recompute.py` | Independent recomputation of every count, McNemar test, and the decision from `predictions.npz` (written separately from `run.py`) |
| `publish.py` | Builds the aggregate tracked report and refuses to publish if the independent recomputation disagrees |
| `v1_latency_same_scope.py` | Re-measures the frozen v1 ONNX exports with the revision-2 timing scope (inputs prebuilt, `InferenceSession.run` only) and repeats v1's published loop on the same machine; writes [`reports/issue-21-v1-latency-same-scope.json`](../../reports/issue-21-v1-latency-same-scope.json) |

## Protocol

- Recipes: **B0** = the v1 recipe; **C1** = B0 + per-candidate
  `-log1p((cost_i - min cost) / 1000)`; **C2** = C1 + scorer dropout 0.1 +
  label smoothing 0.05 over valid candidates. Seeds 20260814, 20261103, and
  20261104.
- Folds group train rows that share `source.article_id`,
  `source.paragraph_hash`, or a non-null `source.template_cluster_id`.
- Epochs (and the reference-only abstention threshold) are frozen from
  out-of-fold train predictions. Dev is evaluated once, bound to the frozen
  selection hash. Final-holdout lines are skipped by their split token before
  JSON parsing and never reach any array.
- Adoption rules (Issue #21): OOF correct above B0 for all three seeds, exact
  McNemar p < 0.025 for at least two seeds, OOF mean harm not above B0; then dev
  mean correct not below B0 and dev mean harm not above B0.

## Running

The scripts resolve paths relative to their own directory and write outputs
next to themselves, so copy them into the ignored
`data/generated/issue-21-retrain/` directory first. Every stage refuses to
overwrite an existing output.

```powershell
$py = "<venv>\Scripts\python.exe"   # Python 3.13, torch 2.12.1+cu130, numpy, onnx, onnxruntime
Set-Location data/generated/issue-21-retrain
& $py -I run.py prepare
& $py -I run.py check-cache
& $py -I run.py reproduce
& $py -I run.py cv B0; & $py -I run.py cv C1; & $py -I run.py cv C2
& $py -I run.py select
& $py -I run.py final
& $py -I run.py eval-dev
& $py -I run.py decide
& $py -I devin_recompute.py predictions.npz selection.json devin-recompute.out.json
& $py -I publish.py devin-recompute.out.json <uv.lock of the venv>
& $py -I v1_latency_same_scope.py ../../../reports/issue-21-v1-latency-same-scope.json
```

The adopted recipe is implemented for reuse in
[`src/sakura_rerank/research_tiny_r2.py`](../../src/sakura_rerank/research_tiny_r2.py),
which reproduces the harness checkpoint for seed 20260814 exactly. All outputs
here are research-only: Gate A remains failed, the final holdout is unused, and
no Sakura Input production change is authorized.
