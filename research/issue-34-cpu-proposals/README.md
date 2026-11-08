# Fixed CPU proposals and context-removal limits — Issue #34

Both 75,000-row #29 CPU proposal sets are complete and replay exactly. The new
[aggregate report](../../reports/issue-34-cpu-proposals-v1.json) identifies a
material limit: after removing context, 2,114 identical numeric-input groups
have incompatible source labels. At least 5,658 of these 75,000 source targets
cannot be matched by any deterministic selector of those same inputs.

**The 92.456% empirical ceiling applies only to this consumed weak-label pool.**
It is not the ceiling of the old dev set, actual Japanese conversion accuracy,
or a Gold-label quality bound. Additional data cannot resolve a contradiction
that the chosen input representation makes indistinguishable.

## Input identity and dependency results

| Census, all 75,000 rows | Source-prefix context | Empty context |
|---|---:|---:|
| Unique complete numeric inputs | 74,594 | 21,459 |
| Duplicate groups / excess rows | 406 / 406 | 9,639 / 53,541 |
| Incompatible source-label groups | 0 | 2,114 |
| Rows in incompatible groups | 0 | 22,080 |
| Minimum unavoidable source mismatches | 0 | 5,658 |
| Empirical deterministic source-match ceiling | 100% | 92.456% |
| Direct matches to actual old train inputs | 0 | 1,688 |
| Direct matches to actual old dev inputs | 0 | 210 |
| Distinct current rows directly matching either | 0 | 1,888 |
| Rows connected to old history after component closure | 0 | 73,623 |
| Derived components | 10,024 | 1,093 |
| Largest component | 46,961 | 73,608 |
| Union fold sizes | 46,961 / 7,010 / 7,010 / 7,010 / 7,009 | 73,608 / 348 / 348 / 348 / 348 |

The [previous ancestry audit](../issue-34-selector-lineage/README.md) established
zero overlap for the original source-prefix inputs. It does **not** establish
zero overlap for a new projection that removes context. This run compares the
new projection to the authenticated *actual* old numeric inputs. It does not
invent old empty-context fitting exposures. Train/dev match counts overlap by
10 current rows, so they must not be added as distinct cases.

The full original source-component closure is retained. Projected input equality
adds edges before either 50,000-row arm is selected. Both empty-context arms
therefore have folds 48,608 / 348 / 348 / 348 / 348; all 25,000 Aozora rows in
each arm are in the giant component. The remaining folds contain Wikipedia
only. A five-fold count alone does not demonstrate useful cross-validation
coverage. No component is split or dropped to conceal this problem.

The empty-context condition is explicitly ineligible as clean OOF evidence for
the fixed selector. Its 1,377 history-unconnected rows are still previously
consumed weak-label research data, not independent calibration or Gold. The
source-prefix condition retains recorded ancestry eligibility, but its context
is synthetic source text, not observed IME session text. A 100% empirical bound
only says this census has no contradictory identical inputs; it does not imply
that a learned model can achieve 100% or that the labels are correct.

## Fixed-model source reconstruction

All counts below use the same 75,000 rows. The local baseline matches 52,962
source labels (70.616%). `R` is a successful correction, `H` loses a baseline
match, and `W` changes an already wrong result to another wrong result.
Correction failure is `H + W`; changed rows are `R + H + W`.

| Context / rule | Source matches | Baseline delta | R | H | W | Changed | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Source / ungated | 56,091 (74.788%) | +4.172 pp | 4,915 | 1,786 | 2,733 | 9,434 | 52.099% | 22.302% |
| Source / published L > 1.7 | 54,288 (72.384%) | +1.768 pp | 1,568 | 242 | 774 | 2,584 | 60.681% | 7.115% |
| Empty / ungated | 56,071 (74.761%) | +4.145 pp | 4,864 | 1,755 | 2,716 | 9,335 | 52.105% | 22.071% |
| Empty / published L > 1.7 | 54,143 (72.191%) | +1.575 pp | 1,402 | 221 | 687 | 2,310 | 60.693% | 6.362% |

The source-prefix gate prevents 1,544 harms but suppresses 3,347 successful
corrections. The empty-context gate prevents 1,534 harms and suppresses 3,462
successful corrections. No threshold is selected from these results.
The JSON also records correction failure, error application, coverage,
baseline/correct counts, winner ranks, and counts for all three source groups,
both arms and all component folds: 64 metric populations and 32 input-ceiling
populations. These are a training-data census, not inferential confidence
intervals or an independent 0.25% safety assessment.

Source-context versus empty-context net match differences are small for this
fixed model; net totals alone do not prove that the model ignores context.
The input-level contradiction bound does prove that some distinctions are
unavailable after context removal. Actual semantic ambiguity, extraction
problems and possible encoding aliases still require separate diagnosis.
The fixed model's empty-context result is also well below the 92.456% census
bound: 13,271 additional source matches remain between its result and that
bound. Input ambiguity therefore does not explain all ranking failures.

## Verified execution

- Exact #29 FP32 ONNX, CPU provider, GPU disabled, batch one, one intra-op and
  one inter-op thread. There were 150,000 quality calls, 400 warmups and 20,000
  model-only timing calls. No quality failure or unattempted row occurred.
- Model-only p95: 0.5400 ms with source context; 0.5363 ms with empty context.
  These are not production end-to-end latency or Gate B certification.
- All 150,000 rows replayed bit-for-bit in a fresh process using independently
  constructed eight-field feeds. All 51,600,000 projected tensor elements and
  75,000 source receipts were checked. DFS/heap recomputation verified all six
  union/arm fold populations and the new historical-exposure counts.
- All 805 tests passed (17 new contracts), no failures/errors/skips. Direct
  scalar recounts verified all 64 outcome and 32 ceiling populations. The old
  16 artifacts, 25 fit bindings and 10 checkpoints retain their hashes.
- Preparation, inference and label analysis had zero forbidden data-read
  attempts. Only eight input array bodies were decoded before the CPU outputs
  were sealed; labels were subsequently read only from the bound training cache.

The plan/code commit is `b5f69fe2be4290dc283b05f31db694b3d3cbce9c`; the separate
input/output inference binding is `404518a179d5c9e1bdfe2e0b7ce4907e43b3da12`.
The verifier was committed at `936c24e5a526dd1b463e3722f5dbfa62079f9bf1`.
Preparation took 10.530 s, inference 83.889 s, and the verifier owner 91.005 s.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
$python="$HOME/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe"
& $python -B research/issue-34-cpu-proposals/prepare_proposals.py plan
# Commit the plan before preparation; commit the inference binding before scoring.
& $python -B research/issue-34-cpu-proposals/run_stage.py preparation prepare_proposals.py 1800 execute --commit b5f69fe2be4290dc283b05f31db694b3d3cbce9c
& $python -B research/issue-34-cpu-proposals/run_cpu.py seal
& $python -B research/issue-34-cpu-proposals/run_stage.py inference run_cpu.py 1800 execute --commit 404518a179d5c9e1bdfe2e0b7ce4907e43b3da12
& $python -B research/issue-34-cpu-proposals/run_stage.py analysis analyze_proposals.py 1800 --commit 936c24e5a526dd1b463e3722f5dbfa62079f9bf1
& $python -B research/issue-34-cpu-proposals/run_stage.py verification verify_proposals.py 1800 --commit 936c24e5a526dd1b463e3722f5dbfa62079f9bf1
& $python -B research/issue-34-cpu-proposals/run_stage.py full-tests check_proposals.py 1200
& $python -B research/issue-34-cpu-proposals/publish_proposals.py
```

Artifacts are write-once; replaying the orchestration needs a new run binding,
not overwriting these files. Private inputs, scores, projected folds, bundle,
timings and terminal receipts remain in the ignored recovery directory
`data/generated/issue-34-cpu-proposals-v1/`. Only aggregate reports, source and
tests are committed. The local rubric and cleanup evidence are under
`.codex/goal-loop/issue-34-cpu-proposals/`. Verification was performed directly
by Codex, not a delegated reviewer.

## Priority and remaining release work

1. **#31: explain the incompatible input groups.** Join the 2,114 training-only
   groups to authenticated source/reading/boundary evidence. Distinguish intended
   alternatives from extraction/label errors and encoding aliases. Preserve all
   labels and histories; majority voting or accepting every alternative would
   not establish Japanese correctness. Cost: bounded metadata/source diagnosis,
   no new fit. Benefit: choose the right repair for the demonstrated information
   loss instead of adding contradictory training examples.
2. **#32/#35: reserve evaluation under the actual input projection.** Include
   projected equality and complete model ancestry before any new split. Retain
   source failures, source diversity and independent calibration/Test boundaries.
   Cost: linear hash/group joins plus separately scoped source/quality work.
3. **#34: bind the gate recipe after those data contracts are valid.** The CPU
   bundle is ready for inspection, not fit permission. Six gate fits are a
   conditional budget for a fixed selector; source imbalance, empty-context
   exposure and independent evaluation readiness must be addressed first.

Adopted accuracy remains 90.72%; this run demonstrates no adopted improvement.
Safety remains 0.25%. Gold requirements remain point estimate 99.5%, Wilson95%
lower bound 99.0%, and at least 3,000 final valid examples. No new ranker or gate
fit, threshold selection, Gold admission, calibration, final Test or production
change occurred. Gate A/B, production integration, default enablement and release
remain open.

## Scope and architecture

Actual scope: the fixed source-cache input contract, #29 lineage projection,
component fold contract, CPU feed/output contract and training-census arithmetic;
one new reusable projection module, its tests, and nine research scripts own this
work. Existing training, model, label-admission and production modules are
unchanged. The complete regression suite ran.

Scope expanded from CPU scoring to projected-input dependence because removing
context changed equality and invalidated the earlier ancestry conclusion for
that condition. This is a required data-integrity boundary, not an optional
refactor. Existing source components remain authoritative; the projection only
adds equality relations and exposure evidence.

`gate_proposal_inputs.py` owns validated read-only numerical views and the fold
projection. The research stage owners own immutable run artifacts and terminal
states; labels stay outside inference and enter only the sealed-output census.
Dependency is one-way toward the existing cache schema and `gate_oof` contracts;
no runtime or production ownership changes were introduced.

Future gate work can begin with the proposal-bundle hashes, condition-specific
exposure counts and the projection tests, without re-reading historical teacher
code. It must understand that context ablation changes input identity and that
an empirical source-label ceiling is not a Japanese accuracy or safety claim.
