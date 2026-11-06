# Independent evaluation protocol v1 (#35)

Parent: #1. Dependencies: #31 Gold evidence, #32 input/source audit, #34 calibration.
Frozen workflow version: 2026-11-04. This is not a completed experiment registration:
the actual source population, Gold evidence, artifact hashes, primary selected
student and power calculation must be committed before any Test access.
The existing pilot, dev and previously audited holdout are historical exposure.
None is an independent Test. There is no certified new Gold Test at this date.

## Ownership and admission

The data boundary owns immutable source/candidate/label provenance and partition
audits. The evaluator owns frozen model/gate/feature identities, denominators,
statistics and outcome records. `test_use_registry` owns consumption state only.
It does not certify Gold, validate model binaries, execute a model, or grant
release approval. A passing partition receipt alone never admits an evaluation.

Before running the final evaluator, all of the following must be independently
evidenced, bound by hashes and recorded in one immutable experiment manifest:

1. The complete historical exposure inventory: every training/dev/old holdout,
   pilot, AI/human inspection, manual edit, calibration, previous Test and source
   component. Inventory file hashes, counts, versions and coverage are required.
   The supplied-record audit cannot establish that omitted history never existed.
2. A new, representative full-reading population with labels fixed independently
   of model outputs. Preserve oracle misses, unresolved labels and exclusion
   counts in the acquisition denominator. Gold validation must meet point
   precision >=99.5%, Wilson two-sided 95% lower >=99.0%, valid final holdout
   >=3,000, Oracle@6 >=97%, complete immutable provenance and zero leakage.
   AI agreement, dictionary uniqueness, source equality and the 1,000-case
   operations pilot are not substitutes. The available independent-quality
   evidence method remains unresolved; there is no self-asserted pass flag.
3. Exact train/calibration/Test membership before model selection. Article,
   paragraph, template and sentence Jaccard>=0.8 components, plus exact bounded
   left-context/reading groups, cannot cross populations. Canonical input equality
   uses exact strings; no global NFKC or name/spelling normalization. All labels
   and candidate snapshots stay immutable. A failed audit stops the run; it does
   not silently delete rows to repair the denominator.
4. Model, tokenizer, features, candidate order/snapshots, label policy, software,
   environment, dictionary/exporter and gate hashes; selected primary student;
   frozen hypothesis family, seeds, sample size, statistics and terminal rules.
   v1, r2 and #29 FP32 are required comparisons, each ungated and with a gate
   already fixed on separate calibration. Include unchanged local and current
   Tiny baselines. Parent #1's equal-budget GRU/minGRU/Tiny Transformer comparison
   remains required; this protocol does not remove it from release scope.
5. An intact shared Test registry and its latest head pinned outside that
   directory. Reserve the population durably before any Test input, prediction,
   label, metric or model-dependent slice is opened by the evaluator.

Model-independent curation may access source/labels under the fixed Gold process;
its exposure must be documented and isolated from model/gate selection. Complete
candidate generation remains the actual Sakura full-reading converter, not an AI
or morphology oracle. No host-document or right/future context is permitted.

## Population and selection

The initial planning target is 12,000 representative Test rows and 3,000 separate
calibration rows. These are planning values, not an implemented sample or a
post-result stopping rule. Commit the final fixed size and sampling design after
source availability and clustering are measured, before Test predictions.
Do not keep collecting until a favorable harm bound or 10,000 baseline-correct
rows happens to be reached. An insufficient denominator yields inconclusive
safety. There is no repeated peeking or threshold adjustment on Test.

Report short/multi-segment reading, empty/1–63/64-character left context,
protected names and spelling-policy slices. Do not choose slices after seeing
results. Oversampled challenge cases form a separate cohort and are not mixed
into representative accuracy. Keep unresolved/source-invalid counts and retention
relative to the acquisition population visible; report valid-label metrics with
their explicit denominator, never as unconditional accuracy on rejected cases.

## Metric contract

The primary label metric is exact surface match to the frozen unique Gold label.
Any separately adjudicated accepted-surface set is a preregistered secondary
metric; it cannot be created from model predictions. A changed candidate index
with the same output surface is not an effective correction.

For the fixed valid-label evaluation cohort: N=all rows; C=baseline-correct;
E=N-C; R=wrong→correct; H=correct→wrong; W=wrong→different-wrong;
A=effective changed output surfaces. Primary unique-Gold scoring has A=R+H+W.
Identical wrong output is an unchanged baseline error, not W.

| Reported quantity | Definition / denominator |
|---|---|
| Baseline / final Accuracy | C/N; (C-H+R)/N |
| Correction success / failure | R; H+W, with H and W separate |
| Harm rate | H/C, never H/A or H/N |
| Overwrite coverage | A/N |
| Application to correction targets | (R+W)/E |
| Correction Precision / Recall | R/A; R/E |
| Baseline gain / relative error reduction | (R-H)/N; (R-H)/E |
| Rescue/harm ratio | R/H; infinity only if R>0,H=0; undefined at 0/0 |
| Candidate ceiling | exact Gold existence at 1/5/6/10/32 with declared bounds |
| Ranking | Top-1, MRR, NDCG@6 on identical frozen candidates and rows |

Zero denominators are null with counts, never silently zero or one. Timeouts,
malformed outputs, stale results, missing scores and gate abstentions remain in N.
The operational output is unchanged local ranking on failure. Report each
terminal status and both attempted and effective application counts. A whole-run
failure is a consumed Test with incomplete results, not a successful evaluation
on the rows that happened to finish.

## Calibration and statistics

Calibrate on the separate calibration set only. Plot correction Precision/Recall
and risk versus coverage there, recording the threshold grid, model family and
selection objective before tuning. Preserve the 48 dev rescues suppressed by the
old gate as a hypothesis about discrimination, not 48 independently verified
future successes. The Test table uses only precommitted thresholds.

Report two-sided 95% intervals on Accuracy, proportions and paired improvements.
Use the same component resamples across models: 10,000 paired component bootstrap
replicates, seed 20261104, percentile interval with a declared quantile convention.
Freeze component membership and hypothesis family in the experiment manifest.
Report exact two-sided McNemar and Holm adjustment over the frozen confirmatory
comparisons. Parent Gate B requires a positive paired lower bound, RER>=10%,
rescue/harm>=3, improvement over current Tiny, and no unseen-dictionary regression.

Report harm's two-sided 95% Clopper–Pearson interval and one-sided 95% upper bound.
The safety threshold stays 0.0025. Also report component-cluster sensitivity for
harm and paired gain. Binomial coverage assumes independent Bernoulli trials;
cluster bootstrap and row-binomial intervals do not by themselves prove that
assumption for correlated language examples. The final sampling/power plan must
state the independent unit and dependence treatment before exposure. Degenerate
bootstrap distributions (including zero observed harm) are not proof of zero
risk. If dependence or effective sample size makes safety unestablished, record
inconclusive and do not pass Gate B. Do not relax the threshold or select whichever
interval is favorable.

Primary method references (consulted 2026-11-04; no new package installed):
[SciPy binomial test and exact interval](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html),
[statsmodels exact McNemar](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html),
[SciPy paired bootstrap and degenerate distributions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html).
These references describe methods; they do not validate this corpus's sampling.

## Consumption state and recovery

`initialize_registry` explicitly creates a fresh directory. The release workflow
must use the same registry for all experiments, retain it, and pin its current
head outside the directory. Creating a different registry is not a fresh Test.
`audit_evaluation_partitions` returns aggregates plus private reuse tokens.
Its aggregate binds the tokens; tokens ignore model, labels, candidate costs,
revision and split names. Source/input/record overlap prevents claiming subsets
or relabeled populations again. Near-duplicate reuse additionally requires the
complete historical source audit; equality tokens alone cannot establish it.

States are unused → reserved/consumed → completed or failed. `reserve_test`
checks the full history under an exclusive writer lock and appends/fsyncs before
returning. One reservation may be active. `finish_test` appends exactly one
terminal result; failed never means reusable. Persist the returned head externally
before the next operation. A changed plan cannot reopen consumed data.

Writer contention fails immediately; there is no retry loop. A crash may leave a
lock or a reserved run. Inspect the actual process/job handle before recovery;
never infer that a lock file means a live process or that elapsed time means it
died. Only after proving the owner terminal may a coordinator preserve the
evidence, remove that stale lock and append a failed result. This is not an
automatic retry. Partial/torn writes and head mismatches stop all further writes;
preserve the original bytes and investigate without rewriting history. A failed
fsync may leave a consumed claim whose durability is uncertain; no Test access
is allowed on that exception.

Hash chains detect edits and externally pinned heads detect truncation. They do
not prevent an operator from deleting all evidence, lying about supplied history,
reading Test outside the evaluator or creating another registry. Filesystem
permissions, off-machine commitments and the final evaluator integration remain
required operational controls. The registry itself runs no models and certifies
no Gold. The artifact access boundary is now implemented in
`evaluation_admission.py`, and supplied-observation metrics/statistics are in
`evaluation_metrics.py` and `evaluation_statistics.py`. Their presence does not
establish a final model runner: no non-test caller connects `access_test` to model
execution. The Gold trust set remains empty. See the
[unit and sample-size reconciliation](issue-35-knbc-format-pilot/README.md#evaluation-feasibility)
for the implementation status checked on 2026-11-06.

## Verify / Expect and remaining work

- Verify: `python -m unittest tests.test_evaluation_protocol -v`.
  Expect: exact-input leakage and transitive source/input closure detected;
  input order does not matter; all input rows preserved; no Gold certification.
- Verify: the same test module's Test consumption tests.
  Expect: one concurrent reservation winner; failures retain consumption;
  relabel/subset/revision changes cannot refresh identity; tampered/truncated
  history and fsync errors fail closed; stale locks are not auto-removed.
- Verify: `python -m unittest discover -s tests`, bounded to 300 seconds, followed
  by runner-process inspection and `git diff --check`.
  Expect: no regressions, original artifacts unchanged, no task-owned runners.

Remaining before final evaluation: independently supportable Gold evidence;
complete historical inventory; representative new corpus and frozen partitions;
final model runner integrated with the existing artifact-authenticating admission
and metric/statistic computation; calibration; preregistered power/dependence
design; sealed experiment manifest. The access and metric libraries have synthetic
contracts and historical research replays, not a completed independent evaluation.
Then run Test once. Gate C CPU measurements and Gate D integration/rollout remain
separate release requirements. Default enablement still needs separate approval.
