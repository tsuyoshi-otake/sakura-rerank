# One KNBC preparation for the screened-dictionary comparison (#33 / parent #1)

This prepares one research comparison of the original dictionary training arm
(50,000 rows) with the source-screened arm (49,085 rows). It does not train a
model, certify Gold, change a gate, or demonstrate an accuracy improvement.
Adopted accuracy remains 90.72%. The full release objective remains open.

## Fixed question and stopping rule

The later experiment asks whether removing the 915 conflicting/uncertain source
rows improves held-out source reconstruction without increasing harmful changes.
At most three new fits, 500 updates each, may follow a separate fit binding.
The original three dictionary checkpoints are controls; architecture, loss,
initialization, optimizer, compute and fixed gate are not additional search axes.
The comparison and stopping conditions are recorded in Issue #33.

This preparation uses one slot per previously unconsumed KNBC sentence member.
All 19 prefix families reserved by the old 100-slot pilot remain excluded,
including its empty annotation. Metadata selects all 2,786 remaining members
from 167 articles and 62 prefix families. A prefix family is a conservative
relation, not verified author identity or a proof of statistical independence.

The new slot rule chooses one complete provider `*` bunsetsu by a fixed hash of
source identity and unit position, before checking reading, target, or length.
It never replaces an unusable chosen unit, cuts a token, clips a long reading,
strips punctuation or guesses a pronunciation. Whole documents containing ER,
reading-ambiguity or style markers remain pending. Lemma ambiguity alone is not
a reading error. Literal annotated surface is a source-reconstruction target,
not certified Japanese IME intent. Observed session context is empty.

The rule was checked using the already-consumed pilot: 100 slots, 99 parsed
sentences and 613 complete bunsetsu; 41 chosen slots are input hypotheses, 35 have
non-kana readings, 18 have no Kanji target, five have correction markers, and one
retains the old empty-annotation failure. These are selected-slot diagnostics,
not label-error rates. No new sentence was decoded during this check.

After preparation, complete known source relations and consumed-source exposure
must be checked. Previously consumed raw-input aliases, including the empty
context projection, can only exclude whole connected components. Numeric model
input equality depends on the future candidate projection and remains a separate
required check before fitting. Source preparation alone does not authorize a fit.

Fewer than 500 retained slots or 20 recorded components stops this preparation
without fitting. Meeting those bounds only permits preparation of a candidate
binding. No replacement source, coefficient search or infrastructure expansion
automatically follows failure. Every original slot remains in the census.

## Preservation and verification

The source is the existing quarantined `KNBC_v1.0_090925_utf8` archive, SHA-256
`2df066f321f57413dc94404a60273b84a85c67b55fc5d2c8a34926074c1b83a4`.
Provider documentation and its BSD-style terms remain pinned. No additional GET
or raw-text redistribution is needed. Corpus content, private identities and
checkpoints are not tracked by Git.

Attempt-01 failed before archive access: the new consumer incorrectly assumed
the pilot ledger used a zero genesis and `previous`. The actual producer binds
its decode manifest and uses `previous_sha256`. Attempt-02 follows that exact
contract and checks every event/row/slot identity. The failed receipts remain;
the existing ledger and source data were not edited. New consumption is reserved
durably before decoding and all selected families remain consumed on failure.

The entry points use the existing pinned Python environment with `PYTHONPATH=src;.`
and `PYTHONDONTWRITEBYTECODE=1`:

```text
python -B research/issue-33-knbc-screening/owner.py pilot
python -B research/issue-33-knbc-screening/prepare.py freeze
# Commit the exact plan and implementation before any new sentence access.
python -B research/issue-33-knbc-screening/owner.py prepare --commit <plan-commit>
python -B research/issue-33-knbc-screening/owner.py history --commit <plan-commit>
python -B research/issue-33-knbc-screening/owner.py verify --commit <plan-commit>
python -B research/issue-33-knbc-screening/owner.py tests
```

Outputs are write-once; these commands do not overwrite an existing attempt.
Each owner has a finite timeout, no retry, a terminal receipt and parent/child
cleanup. The working agent verifies directly; no outside reviewer is used.
Safety remains 0.25% on both references. Gold point 99.5%, Wilson 95% lower bound
99.0%, final valid 3,000, independent calibration and one-use final Test remain.

## Scope and ownership

The scope is KNBC metadata/annotation contracts, one source unit rule, historical
graph contracts, a research stage owner and focused tests. It expands into the
previous consumption bindings because row disjointness alone cannot establish
source/input independence. It does not expand into native worker implementation.

`knbc_research` owns the fixed reservation/unit and exposure-classification rules;
the research scripts own immutable bytes, reservations and process terminals.
The existing parser and graph retain ownership of syntax and source relations.
No production API, original data, model weights or legacy admission rule changes.
Future comparison work can consume this explicit frame and its terminal census
without re-deriving source boundaries. It must still validate candidate/numeric
history, freeze evaluation/fit bindings and respect the unproven Gold boundary.
