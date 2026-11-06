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

## Exclusion trace 2026-11-07

**The evaluation frame collapses through equal inputs and prefix grouping,
without needing any paragraph or sentence similarity edge.** More source prose
alone is therefore not a demonstrated remedy. The proposed 915-row screening
comparison remains stopped, its effect unmeasured, and adopted accuracy remains
90.72%. This diagnosis changes neither exclusions nor the 0.25% safety criterion.

The fixed eight-view trace rebuilds the same 995,283 nodes and 2,407,061 typed
witness edges. It reproduces all 1,158 component identities and 1,150 exclusions.
Its seeds are 503,339 historical input records, 6,260 explicitly consumed source
records, and 167 new inputs matching the separately recorded 96,748 input aliases.
Historical includes prior evaluation and other exposure; it does not mean all
503,339 records trained a model. The 167 aliases alone are not an exhaustive count
of every direct historical match: input edges also find 59 historical matches,
45 overlapping the aliases. Their union is **181**, not 167.

| Fixed relation view | Inputs connected to any seed | Inputs unconnected | New-input components |
|---|---:|---:|---:|
| Input equality only | 181 | 977 | 1,057 |
| Article + input | 995 | 163 | 68 |
| Prefix/template + input | 1,150 | 8 | 5 |
| Article + prefix/template + input | 1,150 | 8 | 5 |
| Paragraph + exact/near sentence only | 167 | 991 | 1,158 |
| Identity + exact content, without near | 1,150 | 8 | 5 |
| All relations except prefix/template | 1,008 | 150 | 60 |
| Full unchanged contract | 1,150 | 8 | 5 |

These are sensitivity counts, **not alternative admissible dataset sizes**.
The content-only view's 167 are its own alias seeds; zero new inputs connect to
historical inputs or consumed source through content edges alone. Every excluded
input has a zero-content-edge path after article/prefix/input components are
contracted. Those paths can contain many identity edges; zero does not mean a
direct raw match. The path validator checks all 119,789 identity roots for each
of the three seed sets, including unreachable terminals and acyclic parents.
Distances are for the representative graph, not unique causal explanations or
raw-pair graph distances.

The largest component contains 1,103 new inputs from 158 articles and 58 prefix
families, including 159 direct alias matches. The other components contain
28/13/8/6 inputs. The schema's `author` edge compares `template_cluster_id`;
KNBC uses filename prefixes there, without certification that they identify
authors. Nevertheless, dropping that relation alone would leave only 150 inputs,
still below the frozen minimum of 500. Article grouping plus input equality alone
also fails the minimum (163). A prefix-only fix or a relaxed near-duplicate
threshold would not make this reserved comparison ready.

### Next decision, expected value and bounded cost

1. **P0, #32/#35: specify the separation unit before another collection or fit.**
   Distinguish source/author groups, consumed reading/context inputs, and complete
   numeric candidate inputs. A shared reading is a real recorded match, but is
   not by itself proof that every other input in both articles was consumed by
   the model. Keep the old full closure and failed frame intact. Compare a
   prospective policy that fixes source groups first and quarantines shared
   consumed units, with explicit bans on re-entry through context, teachers or
   pretraining. This is a specification change, not a refactor or permission to
   restore rows. Expected value: determine whether future independent evaluation
   is feasible; accuracy gain is unknown. Cost: one contract, boundary fixtures,
   and one hash-only dry run on existing metadata; this trace took 144.893 seconds
   and gives the scale of graph verification, not a promised total design time.
2. **P1, #31: establish label and input-unit evidence on that contract.** A whole
   annotated bunsetsu and its source spelling still do not certify IME intention.
   Human absence cannot be replaced with invented human verdicts. Existing AI
   evidence stays `ai_teacher`; independent Gold qualification remains unmet.
   Cost and attainable Gold volume must be established before full collection.
3. **P2, #33: reconsider the fixed-budget screen only after a separately reserved
   frame qualifies.** The 915-row hypothesis is neither proven nor disproven.
   The previous cap remains three 500-update fits with fixed controls, no threshold
   or seed search. This already-consumed frame cannot become fresh Test after
   seeing these results. No substitute source search starts automatically.

Gold point 99.5%, Wilson95 lower bound 99.0%, final valid 3,000, independent
calibration, one frozen final Test, and both 0.25% safety references remain fixed.
No new performance sample exists, so accuracy confidence intervals or improvement
claims are not manufactured from these deterministic graph counts.

### Trace reproduction and verification

`trace-plan-v1.json` and commit `f8961af` preserve the first failed execution.
It authenticated inputs but failed before graph construction: a generic `history`
import occupied the module name expected by an older cohort. The corrected
adapter loads under a unique name. `trace-plan-v2.json`, frozen at `982d56f`, keeps
the same eight views and data hashes. Original frozen code/data are unchanged.

```text
# Existing pinned Python environment; PYTHONPATH=src;.; no dependency install.
python -B research/issue-33-knbc-screening/trace.py --output <new-private-output-directory>
python -B -m unittest discover -s tests
python -B research/issue-33-data-growth/verify_integrity.py
git diff --check
```

The owner refuses an existing output directory, runs once with a 900-second bound,
and records its terminal. Trace-02 completed in 146.650 seconds including ownership.
All 2,407,061 edges satisfy the corresponding metadata relation; full components,
exclusions, seed reachability, parent edges and shortest content distances verify.
All 1,082 tests pass (five new contracts, zero failure/error/skip); two files pass
syntax/import checks. No separate type checker was run. Original 16 artifacts,
25 fit bindings, ten checkpoints and five prior reports remain byte-identical.
All six recorded owner/child PIDs and their descendants/task commands are absent.
The throwaway test runner was removed; no dedicated TEMP directory was created.

The [aggregate result](../../reports/issue-32-knbc-trace-v1.json) contains all views
and checks. Eight private recovery files (223,998 bytes) remain in `trace-01/` and
`trace-02/` under `data/generated/issue-33-knbc-screening-v1/`; the original 40
recovery files remain separate and unchanged. Operational evidence and rubric are
in `.codex/goal-loop/issue-32-knbc-trace/`. The diagnostic passed in two iterations;
the screening experiment and overall release are not complete.

### Trace scope and ownership

A. Scope: one research trace, its two frozen plans, one focused test file, the
existing frame/history/witness contracts and result documentation. Full regression
remains required; no model, original splitter or production code changed.

B. Expansion: exact reproduction requires the historical import chain. The
module-name collision exposed that dependency; the local adapter was isolated
without refactoring prior experiments. Repeated historical-script loading is
architectural debt, not a reason to expand this diagnostic into another framework.

C. The trace owns diagnostic views and process receipts. The existing graph owns
relation semantics; the original frame continues to own exclusions/admission.
No semantic dependency, public production API or state owner was changed.

D. The next isolation design can start from these eight views and verified paths
without rereading the learning code or rerunning source extraction. It must still
define source versus actual-consumption boundaries and validate them prospectively;
this report is not an independence certificate.
