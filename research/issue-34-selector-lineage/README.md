# Fixed #29 selector ancestry — Issue #34

The fixed #29 selector can generate **ancestry-compatible research training
proposals for all 75,000 rows** without retraining the ranker. The previous OOF
audit left this root unknown; this audit authenticates its recorded ancestry.
This does not make those already consumed rows independent evaluation data,
certify their labels, or authorize a gate fit. No inference or model fit ran.

The aggregate [JSON report](../../reports/issue-34-selector-lineage-v1.json)
contains the full counts, evidence hashes, limitations and verification.

## Findings

| Check | Observed result |
|---|---:|
| Historical frozen identities covered | 17,880: train 12,516; dev 1,788; reserved holdout 3,576 |
| Conservative historical source nodes | 218,189, including unknown-role and prior selection exposure |
| Rebuilt active source graph | 813,852 nodes; 1,806,331 edges; 115,681 components |
| Selected research rows / source components | 75,000 / 10,024 |
| Selected rows connected to historical source components | 0 |
| Exact old train/dev numeric-input matches | 0 / 14,304 inputs checked |
| Final teacher independently reproduced | all 75,096 float64 elements, exactly |
| Expanded artifact ancestry | 22 nodes; zero missing or incomplete parents |
| Full regression suite | 788 passed; zero failures, errors or skips |
| Existing artifacts preserved | 16 original artifacts, 25 fit bindings, 10 checkpoints |

#29 constructs a new C2 student. Its three final teachers come from the old
train OOF files at epochs 9, 8 and 10; their exact float64 mean equals the stored
teacher. The student, nested teacher, OOF student, cross-fit, selection, decision,
checkpoint and ONNX links are authenticated. Character hashing and cost-gap
features are fixed transformations, not a fitted vocabulary or pretrained
encoder. The old cache and source manifest identify the same frozen dataset.

The ancestry projection conservatively includes *all* historical source nodes,
not only the 12,516 fitted rows. Frozen dev and reserved holdout identities are
checked through the existing metadata-only adapter; their labels are not
decoded. Old train/dev cache reads name only the eight input arrays. The audit
does not reopen old labels or evaluate the final holdout.

The consumed-source closure is rebuilt with the original quarantine decisions,
all retained bridge nodes, and the original relation policy. Every selected
row's identity, source metadata, original input and component digest matches
its existing receipt. A separate depth-first traversal verifies the saved
graph against the original union-find result. It also independently verifies
all 75,000 receipt-chain entries and the old numeric inputs.

## Consequence for the next experiment

The [nested OOF design](../issue-34-oof-design/README.md) remains correct for a
ranker learned on this same pool: 16 fits with identical symmetric-pair reuse,
or 26 without it. A **fixed external #29 ranker needs zero new ranker fits**.
Only the gate needs component cross-fitting: five outer fits and one final fit,
conditional on a separately frozen recipe and appropriate evaluation readiness.
The giant Aozora component and resulting fold imbalance remain unchanged.

The next concrete step is to bind CPU-only proposal generation for #29 on the
existing training cache, with separate original-source and empty-context
conditions. Source-prefix context is not observed IME session context. Saved
GPU scores from the previous audit failed some CPU numeric-parity checks and
are not certified by this metadata audit. New CPU scores require their own
input, model, output and replay binding.

This removes an unnecessary ranker-training cost and one known ancestry blocker.
It does **not** demonstrate an accuracy improvement: the adopted record remains
90.72%. Source reconstruction still does not identify every intended Japanese
conversion. Human judgment is not invented, and the 1,000-row pilot is not final
Gold certification. Safety remains 0.25%; Gold remains point estimate 99.5%,
Wilson 95% lower bound 99.0%, and at least 3,000 final valid examples. Independent
calibration and the one-use final Test are outstanding; the consumed pool is
neither. Existing old-train gate OOF dependence is not repaired retroactively.
Gate A/B, production integration, default enablement and release remain open.

## Reproduction and retained evidence

The immutable plan and audit code were committed at
`9c726e20427f5a63df66581caf45d586dda7a3ff`; the separate verifier at
`3035b0493c44fcdb2d4f0bc13dadd1e5f9262561`. Both commands completed within their
1,200-second deadlines. Measured audit time was 140.232 seconds; verifier owner
wall time was 11.667 seconds. No packages, downloads or native probes were added.

```powershell
$env:PYTHONPATH='src'
$python="$HOME/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe"
& $python research/issue-34-selector-lineage/audit_lineage.py plan
# Commit the plan and audit code before execution.
& $python research/issue-34-selector-lineage/run_stage.py audit audit_lineage.py 1200 execute --commit 9c726e20427f5a63df66581caf45d586dda7a3ff
& $python research/issue-34-selector-lineage/run_stage.py verification verify_lineage.py 1200 --commit 3035b0493c44fcdb2d4f0bc13dadd1e5f9262561
& $python research/issue-34-selector-lineage/run_stage.py full-tests check_lineage.py 1200
& $python research/issue-34-selector-lineage/publish_lineage.py
```

Commands are write-once. The existing result cannot be overwritten; a new run
needs its own output binding. Private identities, graph witnesses, source/input
digests, execution logs and process receipts stay in the ignored recovery path
`data/generated/issue-34-selector-lineage-v1/`. No dataset or binary is committed.
The rubric, iteration record and cleanup evidence are local under
`.codex/goal-loop/issue-34-selector-lineage/`. Codex performed direct verification;
no independent agent or external review was requested.

## Scope and architecture

- **Actual scope:** #21/#25/#29 fitting, teacher and selection contracts; #32/#33
  historical metadata and consumed-source closure; #34's existing receipt,
  component and ancestry APIs; the full existing regression suite. Six new
  research scripts own this audit's input binding, execution, verification and
  aggregate publication. Runtime model and admission code is unchanged.
- **Expansion:** proving ancestry required tracing the historical adapters and
  original source manifests, exceeding the usual three-guide/450-line review
  trigger. A checkpoint filename alone did not prove which teachers or selected
  data could reach the gate. The plan pins 54 imported repository modules and
  60 artifact inputs; this transitive scope is recorded rather than hidden.
- **Ownership and contracts:** original files retain their existing owners and
  admission states. Only this research run owns its write-once artifacts. The
  public `gate_oof.score_exposure` contract receives a verified projection; an
  empty projected set is justified by closure evidence, not missing ancestry.
  No new runtime dependency, production state owner or semantic interface was
  introduced.
- **Future reading:** the next gate-proposal experiment can start with this
  report, the fixed checkpoint/ONNX hashes and the existing cache/fold contracts.
  It need not rediscover the 22-node historical parent chain. It must still
  understand weak labels, prior research consumption, CPU output binding,
  component imbalance, and the independent-calibration/Test boundary.
