# Data growth experiment (#33, parent #1)

The owner approved the current-model / larger-Wikipedia / mixed-source comparison
on 2026-11-05. The [source plan](plan-v1.json) fixes selection before new text access.
This is source-exact weak-supervision research; independent Gold and release Gates
A/B remain unresolved. Existing data, models, final-Test records and 0.25% safety
criteria remain unchanged.

The [completed model comparison](results-model-v2.md) reports every seed, fixed
gate and ungated results, confidence intervals and source-specific limits.
Mixed-source data helped this conditional population more consistently than the
tested Wikipedia quantity increase; no model was promoted. The final 458-test
suite passed without skips, and a separate direct recount matched all 20 point
reports and 50 paired comparisons. See the tracked completion and verification
reports for test logs, artifact integrity and process-cleanup evidence.

The existing 12,516-row model remains a frozen reference. A nested 12,516-row
subset of the new 50,000-row Wikipedia cohort is an additional necessary control:
otherwise the difference from the historical model would mix data amount,
extraction, source selection and training procedure. The three new-data arms use
the same model procedure and compute budget. Mixed data has 25,000 Wikipedia and
25,000 Aozora examples. The 4,000-row development evaluation is held apart by
article/work and Aozora author before text extraction; it is not final Gold Test.

The initial extra source is public-domain-flagged modern-orthography Japanese
fiction/essays from Aozora, not arbitrary web text. It tests one specific source
mixture, not all modern dialogue/business domains. Metadata is kept with source
files, dates and hashes under ignored generated storage. No corpus or trained
artifact redistribution is authorized by a passing experiment.

## Verification rubric

- Verify: authenticate the fixed dump, dictionary, six historical source-span
  generations and Aozora index; build selections before fetching work texts.
  Expect: exact hashes, immutable source reservations and no evaluation labels
  or candidate content accessed by history isolation.
- Verify: synthetic extraction/selection tests and complete source receipts.
  Expect: bounded prior context, annotation removal without silent word joining,
  metadata rights checks, stable hash order, duplicates and failures accounted for.
- Verify: candidate snapshots against the committed reference binary and dictionary,
  then exact/near-duplicate component audit before any fitting.
  Expect: no cross-population component; all quarantined/missing cases counted;
  no legacy/Gold admission changes.
- Verify: freeze model recipe, all cohort hashes and selection rules before training.
  Expect: matched initialization/loss/features/budget, three seeds, no old-dev tuning.
- Verify: same fixed development population for all models, including unavailable
  targets/failures; report per-source counts, harms/rescues and uncertainty.
  Expect: reproducible research comparison, never self-certified release approval.

Costs are bounded to one local dump pass, at most 750 sequential work downloads,
100-row converter batches and nine new-data fits after data preparation. Measure
throughput before declaring a training duration; 50k rows is approximately four
times the old example count, not a promised fourfold time or quality gain.

## Source and input isolation execution

`prepare_sources.py` authenticates six historical source generations and reserves
the 750 works. `extract.py` requires the separately committed reservation before
any work-text acquisition. A fresh directory is mandatory: an interrupted or
rate-limited run is not automatically retried. Its attempt records remain the
authority for any later explicitly bounded continuation; failed works are never
replaced. Source receipts distinguish attempted, acquired and parsed works.

`isolate.py` reuses the existing exact source-component closure through a separate
weak-supervision boundary. It additionally hashes the bounded input fields from
all 17,880 frozen historical rows without decoding label/candidate objects.
Historical input text is discarded after hashing; no label is learned from it.
This complements the six-generation article/paragraph/near-sentence exclusion.
Every new member of a component touching history or both new partitions is
quarantined. Insufficient yield terminates this registered experiment before
candidate acquisition or fitting; the audit and retained artifact are preserved.

The 2,000 rows per source for development evaluation are fixed before converter
outcomes. Identical readings may share a reference snapshot because the bound
converter accepts only the reading and fixed dictionary, with user dictionaries
disabled. Source targets and model left contexts remain distinct. This reuse
does not assert legacy exporter equivalence or certify the weak labels.

## Responsibility and reading scope (IRV)

A. Scope: source manifests, extraction/context rules, source/input isolation,
reference snapshot admission and the C2 training contract. B. New source and
historical-exposure checks are necessary to avoid measuring memorization as data
growth; model architecture exploration is excluded. C. The new experiment owns
its source reservations, weak labels and artifacts; existing trusted dataset and
Gold admission owners do not change. D. Future growth experiments can reuse the
fixed source and cohort contracts, but must still bind new sources, populations,
rights and training recipes explicitly.

## Measured source outcome and continuation

The [v1 source results](results-source-v1.md) preserve the insufficient-yield
outcome and a complete count reconciliation. [Plan v2](plan-v2.json) was fixed
before converter/model outcomes. It excludes short-context targets before the
same isolation audit and adds a disjoint, fixed Wikipedia page slot. This is a
conditional research population; it cannot establish overall IME accuracy.

The numerical adapter keeps weak labels separate from legacy dataset admission.
It counts missing targets and compares output surfaces, including duplicate
candidate surfaces. Training reads only the training tensor file; all nine fixed
fits must finish before any development inference. `env/uv.lock` and its project
file preserve the already installed Issue-21 environment (including its original
project name); no new package installation or version selection is required.

The subsequent [fundamental accuracy diagnosis](../issue-33-fundamentals/README.md)
uses a separately registered posthoc analysis of these exposed development cases.
It preserves the original experiment and reports all 60 context interventions,
gate/selection ceilings, and the next task/representation/calibration hypotheses.
It does not fit another model or consume an independent final Test.
