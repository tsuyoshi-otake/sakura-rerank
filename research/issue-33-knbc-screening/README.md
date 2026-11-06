# One KNBC preparation for the screened-dictionary comparison (#33 / parent #1)

This prepares one research comparison of the original dictionary training arm
(50,000 rows) with the source-screened arm (49,085 rows). It does not train a
model, certify Gold, change a gate, or demonstrate an accuracy improvement.
Adopted accuracy remains 90.72%. The full release objective remains open.

## Result: stop this comparison before fitting

The single preparation is complete and fails its frozen readiness rule:
**eight retained slots in one recorded component**, below 500 slots and 20
components. No fit, model prediction, threshold selection or final Test followed.
This is not a measured rejection of the 915-row filtering hypothesis; the
available evaluation frame cannot test it under the current isolation contract.

| Complete fixed population | Slots |
| --- | ---: |
| Reserved and consumed | 2,786 |
| Structurally parsed source coverage | 2,771 |
| Full-unit input hypotheses before history | 1,158 |
| Direct matches to consumed reading/context inputs | 167 |
| Other inputs in components touched by those matches | 983 |
| Retained for candidate preparation | 8 |

The last three rows partition the 1,158 hypotheses, not all 2,786 slots. The
five new-input component sizes are 1,103 / 28 / 13 / 8 / 6. Four touch known input
aliases. The large component also reaches historical/consumed source evidence;
the other three excluded components contain 47 inputs. **1,150 exclusions do
not mean 1,150 duplicate sentences, mislabeled examples or direct fit leaks.**
They result from the unchanged complete-component policy, including article,
prefix-family, input, exact-text and near-text relations. Actual authorship and
statistical independence have not been certified.

The 1,628 preparation exclusions are non-kana readings 984, no Kanji target 543,
document correction markers 74, unsupported morpheme columns 15, style markers
six and already-exposed documentation matches six. No substitute units or source
members were selected. These selected-slot counts are not corpus error rates.

All 2,786 source/ledger slots replay, including 1,158 literal reading/surface
pairs checked directly from raw token columns. The full forward/reverse history
comparison covers 995,283 nodes, 2,407,061 representative edges, 96,748 known input
aliases and 6,260 explicitly consumed source nodes. It took 203.963 seconds;
source preparation took 7.340 seconds. Counts are diagnostic work, not independent
evaluation samples or accuracy observations.

The existing model-data screening experiment is stopped with **fits=0**. Do not
relax the isolation rule, restore exclusions, switch units or add sources merely
to pass this readiness check. The next decision concerns the evaluation design:
which direct-input and source relations the independence requirement must cover,
and whether an eligible population can exist under that contract. Any changed
contract needs explicit justification before a separately reserved experiment;
this consumed frame cannot become a fresh final Test.

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
python -B research/issue-33-knbc-screening/diagnose.py --commit a0d740e3dd6d7f2091bd496d06d49826e31d46e3
```

Outputs are write-once; these commands do not overwrite an existing attempt.
All 1,077 unit tests pass (13 new, zero failures/errors/skips). Six authored Python
files pass syntax/import checks. The 16 original artifacts, 25 fit bindings, ten
checkpoints and four prior reports retain their bytes. All 17 recorded owner or
child PIDs, descendants and matching task commands are absent. No task-specific
TEMP root or worktree was created; 40 private recovery files (13,099,655 bytes)
remain intentionally retained. The aggregate evidence is
[reports/issue-33-knbc-screening-v1.json](../../reports/issue-33-knbc-screening-v1.json).

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

The exact preparation was frozen at
`a0d740e3dd6d7f2091bd496d06d49826e31d46e3` before new source access.
The later `diagnose.py` only reproduces the direct/transitive aggregate from the
sealed results; it changes no selection, artifact or relation. Private attempts
and consumed-source evidence remain in
`data/generated/issue-33-knbc-screening-v1/`; operational evidence is in
`.codex/goal-loop/issue-33-knbc-screening/`. Neither is a trusted Gold artifact.
