# Fixed-cohort metric contract v1 (#35)

This implements the metric definitions in the frozen
[independent evaluation workflow](independent-evaluation-protocol-v1.md).
It scores supplied observations; it does not open Test, train a model, calibrate
thresholds, certify Gold or authorize a release. The unchanged workflow file
remains a historical version. This contract adds exact terminal and ranking
conventions for the future experiment manifest.

## Public inputs and ownership

`evaluation_metrics.evaluate_runs(cases, runs, comparisons=...)` owns the shared
denominator and surface-based outcomes. All runs use the same sorted cases.
An `EvaluationCase` contains a private SHA-256 case key, component key, 1–32
frozen local-order surfaces and one unique Gold surface. Text is bounded to 256
characters per surface. Candidate generation/provenance and Gold validity belong
to the data boundary. At most 100,000 cases and eight models are accepted.

The component membership must come from the frozen full source population via
`data.splitter.evaluation_component_keys`, which shares exactly the source/input
closure used by `audit_evaluation_partitions`. A dev-only component calculation
is explicitly a sensitivity analysis on that supplied subset, not proof of full
historical independence. No component membership is inferred from model errors.

Each run supplies `completed` and case-keyed `Observation` records:

| Status | Operational output and attempt information |
|---|---|
| applied | A permutation of every available production candidate, at most six; attempt required |
| abstained | Unchanged local order; a scoring attempt occurred |
| timeout / stale / malformed | Unchanged local order; a scoring attempt occurred |
| missing | Unchanged local order; attempt may be true, false or unknown |
| error | Unchanged local order; attempt may be false for pre-scoring failure |
| unavailable | Unchanged local order; no scoring attempt |

Missing observation entries become explicit `missing` fallbacks and make the
run incomplete. Their attempt status is unknown, not invented as false. Extra
keys, invalid permutations, unsupported statuses or contradictory observations
raise an error before a report is returned. A failed whole run remains incomplete
even if metrics can be computed for its known outcomes. Input/label mutation,
threshold selection, and silently dropping failed cases are not available APIs.

## Exact counts and ranking

Correctness and effective changes compare exact output surfaces, not candidate
indices. Duplicate paths with the same surface cannot manufacture a correction.
No NFKC, case folding, variant-character conversion or protected-name normalization
is applied. The primary unique Gold convention does not infer accepted variants.

The report records N, baseline-correct C, baseline-errors E, rescue R, harm H,
wrong-to-different-wrong W and changes A. It checks A=R+H+W and final-correct=C-H+R.
Each ratio retains numerator and denominator: Accuracy=(C-H+R)/N; harm=H/C;
coverage=A/N; error-target application=(R+W)/E; Precision=R/A; Recall=R/E.
Gain=(R-H)/N and relative error reduction=(R-H)/E may be negative.
Zero denominators are null. Rescue/harm distinguishes finite, positive infinity
and undefined, while JSON numeric fields never contain infinity or NaN.

MRR@6 and NDCG@6 use the first exact-Gold surface in the operational order.
For the single intended surface, gain occurs once: reciprocal rank is 1/r and
discounted gain is 1/log2(r+1). Repeated identical surfaces do not accumulate
relevance. Gold outside the available production prefix contributes zero.
Observed Oracle@1/5/6/10/32 uses each captured candidate prefix; it is not an
assertion that a short snapshot exhausts the entire converter search space.

## Statistics and bounds

`evaluation_statistics` owns calculations independently of labels/models:

- Wilson two-sided 95% intervals accompany proportions, explicitly labeled as
  row-Bernoulli intervals. Harm additionally has Clopper–Pearson two-sided 95%
  and one-sided 95% upper bounds. The implementation uses bounded log-scaled
  binomial probabilities and 64 bisection steps; endpoint closed forms avoid
  cancellation. It is checked against exact rational small cases and an
  independent SciPy numerical implementation.
- A supplied comparison family defines left-minus-right accuracy differences,
  discordant counts, exact two-sided McNemar p-values and Holm adjustment.
  Duplicate/reversed pairs are rejected. Supplying a family cannot prove it was
  registered before exposure; historical dev results remain exploratory.
  Every model must include its model-minus-baseline pair, ensuring that each
  reported baseline gain also has its paired interval and hypothesis accounting.
- All model accuracy, harm and paired-difference intervals share the same
  component bootstrap draws. Default: 10,000 replicates, PCG64 seed 20261104,
  percentile interval with NumPy `method="linear"`. Tests may explicitly request
  100–10,000 replicates; the report preserves the actual setting.
- Draws are batched at 32. Components are aggregated once; floating-point matrix
  multiplication uses integer-valued totals within exact float64 range. Memory
  is O(N×D + 32×components + replicates×ratios), without a full replicate×N array.
  A resample with zero denominator is counted. If any such draws occur, that
  ratio's interval is null rather than conditioned on the surviving draws.
- Degenerate bootstrap distributions are flagged. Zero observed harm gives a
  positive binomial upper bound, not certified zero risk. Sampling independence,
  label quality, preregistration and all release gates remain unproven by this
  module; `release_eligible` is always false. The harm limit stays 0.0025.

Methods are described in the primary
[SciPy binomial documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html),
[statsmodels exact McNemar documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html)
and [NumPy quantile documentation](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html).
These references do not establish independence for the supplied corpus.

## Historical numerical verification

`research/issue-35-evaluation/recompute_dev.py --output <new-file>` authenticates
the old source, cache, score arrays and selection reports by pinned SHA-256.
It discards train and holdout before JSON parsing, validates all 1,788 dev records
and proves cache-row alignment against context, reading, candidate, feature,
mask, length, padding and Gold tensors. It never fits or selects a threshold.

The four reconstructed runs are Issue-21 C2 seed 20260814, with and without its
already selected L>2.7 gate, and Issue-29's stored final scores, with and without
its already selected L>1.7 gate. These are saved research score decisions, not
runtime reliability telemetry. C2 is not represented as a fresh execution or
per-row parity proof of the separately exported r2 binary. v1 is not reexecuted
by this script. The eventual v1/r2/#29 independent comparison is still required.

The report contains aggregates and content hashes only. It is write-once and
reproducible. Recomputing these historical metrics is a software check, not an
independent quality result or permission to use the old dev as calibration.
No new runtime dependencies are installed; the existing research NumPy is used,
and its version is recorded. SciPy is only a separate verification oracle.

## Verify / Expect

- Verify: `python -m unittest tests.test_evaluation_metrics tests.test_evaluation_protocol -v`.
  Expect: all outcomes reconcile; failed/missing cases remain in N; duplicate and
  protected surfaces are handled exactly; zero denominators are explicit;
  binomial safety boundaries and paired component resampling match their contracts.
- Verify: run the historical script to two different new output paths.
  Expect: identical report bytes and historical counts; train/holdout JSON unused.
- Verify: full suite with a 300-second timeout, compile/diff checks and process audit.
  Expect: no regressions, no source/model/label edits and no surviving task runners.
