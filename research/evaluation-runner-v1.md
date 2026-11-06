# Authenticated evaluation runner v1 (#35 / parent #1)

This is a research execution contract, not independent Gold evidence or a release
gate. The existing empty Gold trust set remains authoritative. Real Test access
stays refused until genuine evidence is available; synthetic fixtures are never
registered as real certificates. No final experiment population is chosen here.

The [schema3 native capture binding](issue-35-native-state/README.md) adds per-case
source capture commitments, native identity/replay checks and sealed projection
bindings before scoring. It keeps prior schemas and both0.25% references. Missing
legacy per-edge provenance and native populations above32 remain explicit whole-
evaluation refusals; the diagnostic does not supply independent Gold or a full
current-product evaluation population.

## Ownership and scope

Admission authenticates bytes, owns the shared consumption registry/anchor and
durably completes or fails its access transaction. Runner preflight validates the
frozen execution metadata before reservation. The runner receives the retained
plan bytes and payloads, never reopens mutable model/Test paths. The bounded
executor owns child processes and shared memory; a model adapter owns scoring
semantics; existing surface metrics own all quantitative results.

Adapter identity includes its importable factory, source hash and the runner's
runtime fingerprint. A frozen experiment names the adapter for every model.
Unsupported factories or configurations fail preflight. The built-in GRU adapter
supports the research eight-input ONNX family with six/seven features. Current
Sakura Input also uses a GRU; it must not be confused with the historical DeBERTa
baseline. However, its protocol-v1 worker zeros reading/context and features
2/4/5, and its engine preserves candidate-evidence priorities. Research scores
with unrestricted ranking do not reproduce that policy. The known incompatible
research factory is rejected for `current_tiny`, including registry aliases.
The [version2 snapshot adapter](issue-35-current-tiny-parity/README.md) now supplies
the pinned current-model projection and protected choice. It requires a distinct
native policy/provenance binding, explicit local selection and native evidence
facts; version1 does not silently adopt it. A real native-state producer, Gold
admission and native deployment/session evidence remain unresolved.

This finding is bound to clean Sakura Input HEAD
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`, recorded before source inspection.
The model bytes match the manifest SHA-256
`b3fe1e0aa7229edfd0760162d648f10328b0d75224a9cd49f2ba986b7db2ccbd`.
At that HEAD, `sakura_scorer.rs::prepare_inputs` owns input projection and
`conversion/evidence.rs::neural_listwise_choice` owns strongest-group selection
(user exact > system exact > composite; generated/repair/fallback excluded).
Local cost is a model feature, not an additive selection score. Engine scope,
learning/cache precedence, int32 cost clipping, candidate fingerprints and
terminal behavior also need parity evidence. Legacy candidate source-category
fields alone do not establish all of these product states. No production file,
binary, model or setting was changed or executed here.

Custom adapters are trusted code, registered by the caller, never imported from
dataset strings. Their complete dependency identities, projection and selection
parity require review and separate evidence before registration. A source hash
or a model name alone cannot certify those semantics. The runtime fingerprint
binds selected local modules and package versions, not every transitive dependency.

## Frozen payloads

The outer access plan/quality/gate contracts are unchanged. Its `experiment`
artifact is `evaluation_execution_plan`, version1, with exact fields:
`runtime`, `models`, `primary`, `comparisons`, `slices`, `limits`. `runtime` is the
exact execution fingerprint. `models` preserves explicit model execution order;
each item has `model`, `adapter`, `adapter_identity`, `feature_width` and `runs`.
The complete outer model set must appear once. Runs name ungated/gated variants
and use the model's already frozen `score_margin` gate with a strict `>` operator.
The runner does not tune gates. Every model supplies both variants. Current Tiny
needs a verified adapter and score/selection contract preserving its unchanged
behavior; the synthetic adapter in tests establishes no such parity.

`comparisons` freezes the complete hypothesis family, including every run against
local baseline and primary against the current-Tiny gated run. Up to16 runs and
36 comparisons are supported, subject to the existing64-column/64-ratio bounded
bootstrap budget. Oversized families fail before Test. All variants share10000
component bootstrap draws and seed20261104. `slices` is a bounded list of named
predeclared tags; empty slices have zero count and no invented statistics.

The `sampling` artifact is `evaluation_sampling`, version1, with `test_count`,
`component_count`, `independent_unit`, `dependence_evidence_sha256`. Counts must
match the actual cohort and recognized quality evidence. These declarations do
not prove independence; their evidence still needs external validation before
admission. This executable schema does not select a sampling unit or final size.

The Test artifact is `evaluation_cohort`, version1, with `cases`. Each case has
`case_key`, `component_key`, `input`, `gold`, `tags`. Input contains exactly
`reading`, `left_context`, `context_policy`, `candidates`. The context policy is
`sakura_input_committed_same_session`; context is bounded to64 characters. The
source/provenance certificate must establish its truth, not this string alone.
Candidates are the full1–32 native order with surface, integer local cost,
source-category and full contiguous UTF-8 segment/fingerprint fields. Production
input is the first six. Gold may be outside all candidates: misses remain in N.
Case/component IDs are hash commitments; labels and tags never enter workers.

## Execution and terminal states

Execution is currently Windows-only. The executor passes only the frozen model's weights/tokenizer/features/gate bytes
and label-free requests to its spawned worker. Shared memory holds bounded bytes
and fixed numeric outputs, avoiding blocking bulk pipe transfers. GPU is disabled
in that child. Only one model process runs at a time. Startup, each active request,
each model, the job, and metrics have fixed positive deadlines. Windows Job Objects
contain each worker and its native descendants before adapter execution, with
kill-on-close, no breakaway and an active-process limit of four. Cleanup proves
the Job has zero active processes, including when the direct worker exits first.
No retries, worker restart or hidden warmup on Test inputs occurs. The job budget
limits model/metric scheduling; bounded synchronous authentication, parsing,
serialization and filesystem durability calls are not individually interruptible
wall-clock deadlines. This is not a sandbox for hostile adapter code.

The first timeout, crash, exception, stale or malformed result terminates that
model's worker. Completed rows retain their outputs; the failing attempted row
falls back to local order, and unattempted rows are explicitly unavailable. Other
models may continue within the fixed overall budget. All outputs are sealed
before labels are scored. An exclusive, fsynced private observations artifact
retains numeric proposals, terminal states, case-order hash IDs, candidate counts,
applied decisions and process receipts. Its hash enters the aggregate result.
It contains no text or Gold, but remains private because case keys link records;
it supports decision reproduction without another model/Test run. An incomplete model comparison is reported incomplete;
neither successful fallback nor an access transaction marked `completed` means
the model comparison or Gate B passed. No raw text/IDs/exception messages enter
aggregate results. Full cohort and fixed slice counts include every fallback.

Metrics execute in a separately bounded process. A metadata/cohort/metric or
durability failure leaves the access transaction failed and the Test consumed.
The admission layer owns finalization; no retry, registry reset or second terminal
event follows. The runner returns only after terminal persistence succeeds.

## Verification and limits

Run targeted admission/runner/worker/metric contracts and the full unit suite in
a task-owned temporary directory with an outer timeout. Verify real process
termination and shared-memory cleanup as well as result values. Use synthetic
ONNX graphs for the built-in CPU adapter, never existing evaluation payloads.
Independent label evidence, current-Tiny native-state provenance/deployment parity, independent calibration,
final population/experiment registration and Gates A/B/C/D remain separate work.

Primary API references: [Python shared memory lifecycle](https://docs.python.org/3.13/library/multiprocessing.shared_memory.html)
and [ONNX Runtime CPU API](https://onnxruntime.ai/docs/api/python/api_summary.html).
Process containment follows [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[job limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
and [tree termination](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject).
No package installation or upgrade is part of this change.

## Observed validation and next boundary

[Aggregate verification](../reports/issue-35-evaluation-runner-v1.json) records
997 passing tests (zero failures/errors/skips), including25 added contracts.
The synthetic integration preserves3000 rows, one oracle miss and12000 model
requests across four adapters/eight variants. Its contrived ungated/gated
rescue counts are both750; harms are750/0 and wrong-to-different-wrong changes
750/0. These numbers validate arithmetic and execution, not model accuracy.
All12000 gated decisions are reconstructed from sealed numeric proposals.
CPU ONNX tests use generated toy graphs with feature widths6/7, not actual
production or research checkpoints. No real Test or new corpus was consumed.

Reproduce with the pinned environment in the JSON report, `PYTHONPATH=src;.` and
`PYTHONDONTWRITEBYTECODE=1`, running `python -B -m unittest discover -s tests`
under a600-second outer owner. The targeted modules are
`tests.test_evaluation_admission`, `tests.test_evaluation_runner`,
`tests.test_evaluation_cpu_adapter`, `tests.test_evaluation_metrics`.
Afterward inspect the actual runner PID ancestry and prove no survivors; then run
`python -B research/issue-33-data-growth/verify_integrity.py` and `git diff --check`.
The ten older checkpoint hashes remain bound by
`research/issue-33-loss-balance/evaluation-binding-v1.json`. Syntax/unused imports
were checked directly on ten changed Python files; no formal type checker was
installed or run. Verification was performed by the working agent.

Before exposing Test, next implement and verify the current product adapter on
synthetic inputs against that pinned native contract. This requires the true
candidate-evidence, scope and precedence metadata, not a guessed mapping from
legacy source categories. Its expected benefit is a valid unchanged baseline
comparison, not an asserted accuracy gain; cost is a separate contract/parity
task with bounded synthetic native execution. Independently supportable Gold and
representative isolated data remain higher-level prerequisites; this work does
not substitute AI agreement or source morphology for them.

## Reading scope and architecture (IRV)

The required scope spans admission, frozen evaluation payloads, worker lifetime,
surface metrics and the existing native-candidate validator: six changed source
files and four test files, with corresponding contracts. Existing source encoder,
statistics, registry and old integrity bindings were read through their contracts.
Investigation expanded to the clean current Sakura Input scorer/runtime/manifest,
candidate-evidence rule and engine selection boundary because the historical
DeBERTa document no longer identified the current baseline. It was read-only.

Admission remains the sole owner of consumption/finalization; runner owns the
frozen orchestration and sealed outputs; worker owns subprocess/shared-memory
lifetime; adapter owns model input/scoring; metrics own statistical definitions.
The new preflight/retained-plan contract removes mutable-path rereads. The public
candidate validator reuses existing rules without granting label admission.
Metrics accept16 run variants within the unchanged64-column bootstrap budget.
No production, dataset, training or safety policy ownership moved.

The next adapter task can start from this contract, the three new modules and
four targeted test modules without reconstructing registry durability or
bootstrap formulas. It still must understand current native evidence/scope/
precedence and prove exact input/selection parity. Those semantics are deliberately
not hidden behind a model name; their remaining reading cost is necessary.
