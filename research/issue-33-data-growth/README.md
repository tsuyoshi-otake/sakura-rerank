# Data growth experiment (#33, parent #1)

The owner approved the current-model / larger-Wikipedia / mixed-source comparison
on 2026-11-05. The [source plan](plan-v1.json) fixes selection before new text access.
This is source-exact weak-supervision research; independent Gold and release Gates
A/B remain unresolved. Existing data, models, final-Test records and 0.25% safety
criteria remain unchanged.

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

## Responsibility and reading scope (IRV)

A. Scope: source manifests, extraction/context rules, source/input isolation,
reference snapshot admission and the C2 training contract. B. New source and
historical-exposure checks are necessary to avoid measuring memorization as data
growth; model architecture exploration is excluded. C. The new experiment owns
its source reservations, weak labels and artifacts; existing trusted dataset and
Gold admission owners do not change. D. Future growth experiments can reuse the
fixed source and cohort contracts, but must still bind new sources, populations,
rights and training recipes explicitly.
