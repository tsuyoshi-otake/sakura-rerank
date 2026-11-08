# Prospective consumption partition (#35, #32)

Status: research specification and metadata feasibility study, **not adopted
evaluation policy**. Parent #1. The existing protocol v1, full historical closure,
all consumption ledgers and failed KNBC frame remain authoritative. This study
cannot admit training, calibration, Gold or final Test, restore old exclusions,
or make a consumed source unused. Accuracy remains 90.72%, improvement unproved.

## Reason for the specification change

The [KNBC trace](../issue-33-knbc-screening/README.md#exclusion-trace-2026-11-07)
proved that input equality and prefix grouping alone join 1,150 of 1,158 inputs
to exposure. Only 181 inputs directly match supplied history/aliases. A shared
input currently combines two source groups, so all other inputs in those groups
inherit exposure. Merely dropping prefix grouping still leaves only 150 inputs.

The proposed question is narrower than whether an input was seen: **which source
groups were used, and which complete input units were used?** Source provenance
and exact input equality both remain exclusion rules. They need not share a
single transitive relation. This changes the specification and must be evaluated
prospectively; it is not a refactor of v1 or evidence that old exclusions were wrong.

## Prospective contract

1. Before input/label/model access, freeze source membership, sampling, history,
   grouping, role assignment and all processing identities. Preserve article,
   non-null template/author surrogate, paragraph and sentence-Jaccard >=0.8
   components. A source component touching historical input or an explicitly
   consumed source is quarantined. A source component assigned to multiple
   train/calibration/Test populations is quarantined in every population. Unknown
   authors remain unknown; filename prefixes are conservative surrogates.
2. Hash bounded exact left-context/reading strings without spelling or Unicode
   normalization. Quarantine every new input matching any historical input or
   consumed projection, and every occurrence shared across populations. A shared
   input does not merge otherwise separate source components. For the fixed
   feasibility experiment, quarantine all repeated new input hashes, including
   within a population; do not select a favorable label/representative. All input
   records retain an explicit terminal and their original source component.
3. A source span consumption sidecar must cover the actual source position,
   decoder/preprocessing identity and owner population for each input, left
   context, teacher request/response and body-pretraining window. Quarantined
   units cannot re-enter any of those channels. Unknown offsets, missing channel
   coverage, changes to extents or unbound provenance remain pending. Hash-only
   topology cannot prove this. In particular, an already decoded/inspected source
   cannot be made unused by removing an input record.
4. Bind complete model input identity separately: reading/context, full immutable
   candidates/order, model-prefix projection and numeric feature tensors for each
   frozen encoder. Missing numeric identity never rescues a reading/context match.
   Different candidate tensors cannot override the conservative exact-string rule.
   Candidate/label/intent correctness still requires its own evidence. No model or
   numeric candidate generation is part of this metadata study.
5. Historical exclusion occurs at acquisition/preparation, before sample-size
   choice or model predictions. Record raw slots, parse/reading/label failures,
   exposure, duplicates and unresolved footprint counts. Do not delete rows from
   a frozen evaluator to improve readiness. Once reserved Test begins, any audit
   failure consumes the run and stops it. Calibration and Test remain disjoint;
   final Test is used once after labels, models, features and gates are fixed.

The following must still pass before any independent evaluation: certified Gold
point >=99.5%, Wilson two-sided95% lower >=99.0%, final valid >=3,000, Oracle@6
>=97%, representative sampling/power and complete history. Both raw-converter and
native-local harm references keep the <=0.25% criterion with 95% confidence.
No human evidence is invented; AI remains `ai_teacher`. Parent #1's complete
model comparison, native worker/session/resource requirements and release Gates
remain in scope. This proposal changes no production default or release approval.

## Fixed feasibility experiment

Hypothesis: on a graph with source relations preserved, quarantining direct
historical/repeated input units can leave enough source components for a future
research frame without the input edges joining all articles together.

Use only the already-consumed 2,786-slot KNBC reservation and complete 995,283-node
pre-access history snapshot from the prior study. This is a counterfactual on that
snapshot, not current unused capacity: the current ledger consumes all 2,786 slots,
so the actual independent-Test capacity of this frame is zero regardless of the
diagnostic result. All 1,158 input hypotheses are assigned to the same
`research_evaluation` role; this is not a real train/calibration/Test allocation.
Keep the old 1,150 exclusions and eight retained slots unchanged. Build the same
typed graph, remove only input edges from source-component construction, then
apply the fixed quarantine rules above. Preserve every old pending/source slot.

Readiness is the original research minimum of 500 metadata-unblocked inputs in
20 source components, decided once. This measures topology capacity only, not
Gold volume or an admissible evaluation. Report exclusive terminal counts and
overlapping reasons separately. Verify no remaining source component touches
history/multiple populations and no remaining input hash is historical or repeated.
Run reversal/fixture checks, exact old hash checks and full regression. If the
metadata prerequisite fails, stop; do not try extra policies or another source.

Expected value: resolve whether source/input propagation is a tractable obstacle
to a future evaluation. Accuracy gain remains unknown. Cost: one fixed graph
construction and audit on existing metadata; prior full trace took144.893 seconds.
No new provider access, source replacement, model call, fit or final Test occurs.

Results, executable reproduction, missing provenance and actual next release
prerequisite are recorded in the companion README after the frozen execution,
including a negative result. This specification remains immutable.
