# Source/input partition feasibility (#35, #32)

**The prospective rule leaves 615 inputs in 47 source components in a fixed
metadata-only counterfactual, above the original 500/20 research prerequisite.**
The old full-closure result remains eight inputs/one component with 1,150
exclusions. The actual independently usable Test capacity of this consumed frame
is **zero**. Adopted accuracy remains 90.72%; no accuracy gain has been measured.

The [immutable specification](specification-v1.md) and [plan](plan-v1.json) were
committed at `edf348b0148b07ffece630ecbd62a5f8ae0f9217` before measurement.
The proposal is not adopted by the existing splitter or evaluation admission.
It preserves source article/template/paragraph/near components and quarantines
shared input units without allowing their equality to combine entire articles.
This is a prospective specification change, not a correction of old outcomes.

## Fixed result and meaning

The study uses the same 995,283 nodes and 2,407,061 edges. It exactly reproduces
all 1,158 old component identities and 1,150 old exclusions before the proposal.
The source-only relation graph has 48 components containing new inputs; 47 have
metadata-unblocked inputs. These are recorded source groups, not certified
independent authors or statistical effective sample sizes.

| Exclusive proposed input terminal | Count | Meaning |
|---|---:|---|
| Historical source component | 323 | Keep entire article/template/content component quarantined |
| Historical exact input | 139 | New input matches supplied historical reading/context, after source exclusions |
| Repeated new input | 81 | Quarantine every repeated occurrence still remaining; select no representative |
| Metadata only unblocked | 615 | Topology permits further preparation, all admission still pending |
| Total input hypotheses | 1,158 | Every supplied input has a terminal |

Reasons can overlap. Across all input hypotheses, 181 match historical inputs or
aliases and 175 have repeated new hashes; those are not additional rows to add to
the exclusive table. Exact-string comparisons retain the old conservative
reading/context rule; a different candidate tensor cannot erase a match.

All 2,786 acquisition slots remain in the census. The 1,628 slots without an input
remain 984 non-kana readings, 543 no-Kanji targets, 74 document correction flags,
15 unsupported morpheme columns, 6 style flags and 6 exposed-documentation matches.
There is no replacement, label edit or new source access. The counterfactual uses
the old pre-access history snapshot for comparison; current history separately
records every slot as consumed. Neither the 615 nor the other 543 input hypotheses
are relabeled as fresh independent Test.

All 615 metadata-unblocked rows still lack complete authenticated channel/span
footprints, complete numeric candidate input identity and certified IME Gold.
Author mapping, statistical independence and inventory completeness also remain
uncertified. A whole source bunsetsu does not establish intended IME boundaries.
No training, calibration, Gold or final-Test admission is emitted.

## Implemented boundary and verification

`partition.py` owns a research diagnostic only. Source connectivity excludes the
input edge type but preserves every other original relation, including the
sentence-Jaccard 0.8 rule. A source component touching history/consumed source or
multiple future populations quarantines all its inputs. Exact history/alias
inputs, cross-population inputs and all repeated new inputs quarantine their
own records. Remaining inputs must be unique and their source groups must be
disjoint from supplied history and conflicting populations.

`check_spans` detects entry of quarantined half-open annotation-scalar intervals
through input, left context, teacher and body-pretraining channels. It merges
intervals and uses binary search, O((Q+U)logQ), with 100,000-row bounds. Changed
preprocessing on the same raw source is incomparable/pending, never evidence of
disjointness. This checks supplied span relations only; a zero-overlap or empty
result explicitly cannot certify channel/offset completeness. Complete producer
coverage and raw offset/projection binding still need independent evidence.

The 13 new tests include an independent all-pair source oracle on 35 randomized
populations and an independent quadratic interval oracle on 40 randomized cases.
They cover all source relation types, known aliases, train/calibration/Test
conflicts, duplicates, order invariance, malformed/missing provenance, all four
channels and half-open boundaries. The real study reverses all node, edge and
assignment order and reproduces every proposed row/reason/component and summary.

All 1,095 tests pass, zero failure/error/skip (71.060 seconds, owner 73.496).
Three authored files pass AST/compile/unused-import checks; no separate type
checker was run. Original 16 artifacts, 25 fit bindings, 10 checkpoints and 6 prior
reports remain byte-identical. `git diff --check` and aggregate-only artifact
tracking checks pass. All 4 recorded owner/child PIDs, descendants and task
commands are absent. The study took 137.838 seconds (owner 139.595), with a single
execution, no retries and a 900-second bound. The working agent verifies directly;
no outside review or extra dependency install occurs.

## Decision and next release prerequisite

Retain this as a feasible prospective design candidate: source/input propagation
need not make every new research frame too small. **Do not infer Gold or an
accuracy improvement from 615/47.** New sample sizes cannot be chosen from favorable
model results, and this already-consumed frame cannot be reopened.

The next highest-priority release prerequisite is #31's independent Gold-quality
evidence method. Audit the reading, intended-surface, input-unit and quality
assurance evidence of the already-qualified sources before another body collection
or fit. Require evidence for the actual IME-label property, not a provider's POS
accuracy, AI agreement or source equality. If the quality method remains unsupported,
record that as a release blocker rather than generating more experiments. Complete
consumption footprints and numeric bindings are also required before adopting a
new partition for an untouched population.

Expected value is now measured only for metadata feasibility: 615/47 passes the
old 500/20 rule on this counterfactual. Expected accuracy gain and final Gold yield
remain unknown. The measured audit cost is 137.838 seconds; future quality-evidence
work requires a separate bounded scope. No automatic source search or fit follows.

Gold point 99.5%, Wilson two-sided 95% lower 99.0%, final valid 3,000, Oracle@6>=97%,
both 0.25% harm references with 95% confidence, independent calibration and one
frozen final Test remain unchanged. Parent #1's full model/native/release scope
remains incomplete.

## Reproduction and retained evidence

Use the existing pinned Python environment and `PYTHONPATH=src;.`; no install.
Commands require unused private output directories and refuse overwrite.

```text
python -B research/issue-35-consumption-partition/run.py study --output <new-private-study-root>
python -B research/issue-35-consumption-partition/run.py tests --output <new-private-test-root>
python -B research/issue-33-data-growth/verify_integrity.py
git diff --check
```

[Aggregate result](../../reports/issue-35-consumption-partition-v1.json) pins the
study report, plan and private census hashes. Nine ignored recovery files total
867,813 bytes in `data/generated/issue-35-consumption-partition-v1/study-01/` and
`tests-01/`. Operational verification/rubric lives in
`.codex/goal-loop/issue-35-consumption-partition/`. No dedicated TEMP directory,
throwaway runner, branch or worktree was created; existing unmerged PR77's branch
is reused. Original recovery files/user edits remain untouched.

## Scope, ownership and future reading

A. Necessary scope: the v1 evaluation contract, original KNBC/source graph
contracts, a new immutable proposal, one pure quarantine/span audit, one bounded
research runner and one test file. Full regression still covers the repository.

B. Expansion: actual-consumption semantics require context/teacher/pretraining
span contracts beyond input hashes. Those channels are tested on explicit
fixtures and remain missing for real admission. The historical import chain is
used unchanged to authenticate the old population, not refactored.

C. The research audit owns proposed reasons/rows; the runner owns bound bytes,
processes and write-once outputs. Existing source graph, v1 splitter, data/Gold
admission and Test registry retain state and contracts. No production dependency
or behavior changes. New research-only dependencies point to the existing stable
graph/hash contracts; nothing in production depends on this proposal.

D. Future isolation work can read this specification, focused tests and aggregate
result without re-deriving propagation from all learning experiments. It must
still prove footprint completeness, numeric input identity, authentic author/
population provenance and independent Gold quality before actual adoption.
