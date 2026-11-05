# Data growth: source acquisition and isolation results

The first registered experiment stopped before converter acquisition or model
fitting: its fixed 50,000-row cohorts could not survive complete source/input
isolation. All source files, failures and the original plan are preserved.

| Stage | Wikipedia | Aozora |
|---|---:|---:|
| Extracted source targets | 94,965 | 87,001 |
| Initial training partition | 75,949 | 69,528 |
| Training targets after full isolation | 38,377 | 2,015 |
| Evaluation targets after full isolation | 9,428 | 256 |
| Reading length at most nine characters | 93,347 (98.30%) | 86,953 (99.94%) |

Wikipedia processing excluded all 95,061 historical articles before extraction
and selected a fixed 1% page-hash slot from the pinned 2026-08-01 snapshot.
Aozora metadata fixed 750 works before text access. Acquisition retained 735
archives and recorded 15 validation failures without replacement requests.
Of these 735 archives, 20 failed the conservative header parser; 715 parsed,
and 708 yielded targets. These failures remain in the source-acquisition
denominator. The 15 acquisition receipts record `ValueError` but not its precise
branch; their rejected bodies were not retained, so archive-format causes cannot
be reconstructed from those receipts alone. This limitation is not a label error.

The source/input closure included 115,251 unique historical source metadata rows
plus bounded-input hashes for every one of the 17,880 frozen historical rows.
Labels and candidate objects in the frozen container were not decoded. Every
new member of a component touching history or both new partitions was excluded.
The largest resulting component contained 131,277 historical and new records.
That number is a transitive component size, not a count of identical sentences.

## What caused the attrition

The read-only relation diagnostic reconstructed the registered counts exactly.
With source relations and exact inputs having at least eight context characters,
52,288 Aozora training targets survived. After also connecting one-to-seven
context characters, 11,359 survived; including empty-context inputs left 2,015.
The increments depend on this stated order and are not unique additive causal
contributions. Short shared inputs bridge works and author groups, amplifying a
small direct overlap into large component exclusions.

A separate counterfactual removed short-context targets *before* applying all
the same source/input relations. It retained 52,523 Wikipedia and 60,520 Aozora
training targets, with 13,046 and 15,394 evaluation targets. The largest component
was 970 records. This counterfactual changes the population, not the leakage
rules; it is not a measurement of model improvement and does not certify Gold.

Two findings guide the next experiment: source quantity is available, but short
context harms isolation; source diversity alone does not remove the extractor's
strong preference for short dictionary surfaces. Dictionary-unique readings
remain weak supervision rather than independent contextual truth.

## Separately registered continuation

[Plan v2](plan-v2.json), committed at `1ca3fb4`, restricts both training and
evaluation to 8–64 characters of synthetic left context. It preserves the
original article/author partitions and every isolation relation. A second,
disjoint 1% Wikipedia page slot is reserved before converter outcomes to provide
capacity for candidate-eligibility losses. Aozora files are reused without new
requests. Results will describe this conditional population, not overall IME
accuracy. The fixed source counts, three seeds, common Issue-29 initialization,
500 updates of 256 examples, and unchanged gate threshold are preregistered.

Verify: run `python research/issue-33-data-growth/publish_source_report.py` with
`PYTHONPATH=src`. Expect: exact reconstruction of the aggregate JSON, reconciled
181,966 source targets, and no new data/model writes. The tracked evidence is
[reports/issue-33-data-growth-source-v1.json](../../reports/issue-33-data-growth-source-v1.json).
Local corpora and execution receipts remain under ignored
`data/generated/issue-33-data-growth-v1/`; no source texts are committed.
