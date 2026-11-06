# Full native candidate evaluation (#35 / parent #1)

Schema4 represents the entire captured native candidate list. It removes the
legacy evaluator's32-candidate restriction without changing training data,
historical schemas1–3 or the six model slots. The source remains clean at
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`. This is an evaluation-file version,
not a production worker protocol change.

## Contract and ownership

`native_snapshot.validate_population_input` owns the new contract:1–768 entries
in original order; reading/surface limits are1536 UTF-8 bytes. Candidates contain
exactly`rank`, `surface`, `local_cost`, `evidence_tag`, `native_fingerprint`.
Cost is signed64-bit, evidence is the pinned native enum, and fingerprint is
recomputed from surface/cost/evidence. Duplicate surfaces/descriptors at different
ranks remain separate. No source category, entry index or segment is invented.

`population_input` projects an inspected capture; `bind_population_input` binds
the entire projection and policy facts to it. Schema4 retains frozen per-case
capture commitments, session replay rejection and validation after durable Test
consumption but before inference. Missing/shortened/reordered/modified tails fail
the whole evaluation. Diagnostic no-conversion events stay explicit and cannot
become invented candidate rows or disappear from the diagnostic denominator.

Policy version3 declares`native_full_population_v1`, capacities and observed
field semantics. Old policy/gate bindings cannot be silently reused. Context
remains empty because the producer observed no same-session committed left text.
Hashes prove byte identity; source trust and independent Gold remain obligations.

Runner owns full rows and sealed bindings. Workers receive only the eligible
direct prefix, at most six candidates, without Gold, case/session IDs, captures
or slice tags. Sealed observation version2 records both`candidate_counts` (model
slots) and`full_candidate_counts`, plus all projection receipts. Local selection
outside model slots is retained by fallback. Admission and worker owners remain.

The separate`current-tiny-native-population-v1` adapter uses the same pinned
model, tokenization, cost clipping, six features and protected choice. It accepts
native text extent: feature3 preserves full scalar length while token encoding
retains32 scalars. The historical adapter keeps its256-character bound and is
refused in schema4; the new adapter is refused outside schema4. Native1536-byte
storage is below protocol3072-byte capacity. Live-worker framing/timing is not
certified by these offline projections.

Generic research GRU factories, including aliases, remain refused: native tags
do not establish their per-edge features. Caller-registered custom adapters are
trusted code and need separate feature/selection parity evidence. This migration
does not certify the real historical-model comparison.

## Metrics

`evaluate_runs(candidate_contract="native_full_population_v1")` explicitly opts
into the new limits; default remains legacy32. Metrics schema2 retains the whole
list in the cohort hash and reports Top1/5/6/10/32 plus`all` observed oracle.
Candidate total/minimum/maximum, full oracle misses, actual model-prefix oracle
and cases present only outside that prefix distinguish generation from model
opportunity. Full native oracle does not mean exhaustive search beyond native
search budgets. Duplicate surfaces do not multiply Gold-correct case counts.

Surface equality, successes/failures/harms, application, precision/recall,
confidence intervals and paired statistics are unchanged. Converter-Top1 and
native-local references use identical cases/outputs and both keep0.25%. Failed,
missing, ineligible and unattempted model rows remain in all denominators.

## Evidence and reproduction

All48 saved native snapshots/924 candidates bind, including both108-candidate
snapshots formerly refused by schema3. Two no-conversion events remain in the50
event accounting. Replay of prior evidence is not new independent sampling.

Initial parity attemptA stopped before inference at the historical diagnostic
wire reader's1024-byte assertion. Its plan/result/terminals are retained. The
new private generated harness changes only that reader bound to1536 with an
exact-one-match check; historical harness/production source stay unchanged.
The included native scorer matches20 accepted projections/6760 scalar values
and rejects three invalid candidate counts. Two CPU executions of the unchanged
model total40 requests; all120 output scores match. This uses a test backend,
not live native ONNX, session behavior or accuracy evidence.

All1051 tests pass (14 new; failures/errors/skips0). Synthetic integration keeps
3000 cases/9874 candidates, including108/768-candidate lists, duplicate surfaces,
1536-byte text and tail local choices. Four adapters/seven variants make5992
requests and seal3000 bindings. Full oracle2999 versus prefix2997 tests arithmetic,
not Japanese accuracy. Failure tests retain1502 ineligible, one failed and1497
unattempted rows per model, still9874 candidates. Schema3 still refuses108.

Use the existing pinned environment,`PYTHONPATH=src;.` and
`PYTHONDONTWRITEBYTECODE=1`. Run`python -B -m unittest discover -s tests` under
a600-second process owner. Targeted modules are`test_native_population` and
`test_native_population_evaluation`, plus native/current regression contracts.
Run`python -B research/issue-33-data-growth/verify_integrity.py`, checkpoint hashes,
`git diff --check`, artifact tracking and actual process-exit checks. No packages
are installed or upgraded. Native parity uses fresh private roots under`~/tmp`:

```text
python -B research/issue-35-native-population/verify.py prepare --source-root <clean-native-source> --capture-root <retained-diagnostic-c> --work-root <fresh-private-root>
python -B research/issue-35-native-population/verify.py run --source-root <clean-native-source> --capture-root <retained-diagnostic-c> --work-root <same-root> --plan-sha256 <prepare-output>
```

The recipe pins source/compiler/harness/runtime/vector/capture hashes before
execution, uses120-second native commands and bounded contained CPU workers,
does not retry an existing attempt, and preserves failed attempts. Add
`research/issue-35-current-tiny-parity` to child`PYTHONPATH` for the captured-feed
reference adapter. [Aggregate evidence](../../reports/issue-35-native-population-v1.json)
records exact identities. Raw captures, logs and binaries stay untracked. Retain
recovery receipts, prove process exit, then remove owned TEMP roots.

## Remaining release work and IRV

The subsequent [schema5 native-path work](../issue-35-native-paths/README.md)
captures pre-fusion edge metadata and connects a separate fixed-model adapter.
Its controlled input/score parity addresses the feature-provenance task below;
unsupported post-path transformations and live-session coverage remain explicit.

Benefit is a complete denominator and faithful tail fallback, not a predicted
accuracy gain. Cost is one prior-capture replay, a small Rust projection build,
40 synthetic-input model requests and contract tests. Adoption stays90.72%.
Gold99.5% point/99.0% Wilson lower bound/3000 valid final holdout, independent
calibration and a frozen one-use Test remain necessary.

Next capture exact path/segment features for historical models from the pinned
converter and prove projection parity. Visible selection/commit normalization,
live worker/session timing and resources/deployment Gates also remain unverified.

Scope: native capture, payload validation, current projection, runner sealing,
shared surface metrics and two focused test modules. Investigation expanded to
native text capacity and the diagnostic reader because count expansion alone
would still reject valid long strings. No production state ownership moved and
no training contract widened. Future work reuses full-population APIs, explicit
prefix counts, tail/failure metrics and bounded parity rather than rediscovering
32 versus768. Per-edge and live-session semantics still need evidence. The
working agent verifies directly, with no external/subagent review.
