# Current Tiny snapshot parity (#35 / parent #1)

The current model can now be compared through its actual protocol-v1 tensor
projection and protected candidate choice. This is an offline, pre-display native
candidate snapshot contract. It does not certify Gold, capture a live IME session,
measure asynchronous UI availability or prove the native ORT deployment. Adopted
accuracy remains90.72%, safety remains0.25%, and the Gold trust set remains empty.

## Hypotheses and changes

The previous research adapter supplied reading/context and six/seven research
features. The pinned product uses the same GRU family but empty reading/context,
only feature columns0/1/3, int32-clipped costs and protected evidence groups.
Model weights/signature alone therefore do not identify the unchanged baseline.
`current_tiny.py` owns the separate projection, artifact pins and choice rule.
The shared CPU ONNX session boundary keeps one intra/inter-op thread and the CPU
provider; no package or dependency was installed.

The current product chooses one candidate instead of sorting the entire score
vector. Strongest native evidence wins: user exact, then system exact, then
composite lexical. Generated, repaired and fallback candidates do not participate.
Ties retain native order. No additive local-cost fusion or calibrated margin is
introduced for the shipped baseline. Remaining indices keep their original order
in the evaluation's selected-first representation; this is not a mutation of the
IME's displayed list.

The local fallback may itself select an index other than converter rank0.
Version2 records that index instead of rewriting candidate ranks/cost features.
All models share native eligibility/protection. Ineligible cases are retained as
`not_eligible`, with zero inference attempts and the authenticated local fallback.
An all-ineligible population starts no model and still preserves every row.

## Native source and evidence boundary

Source is clean Sakura Input HEAD
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`, recorded before source reliance.
The7,466,707-byte model is SHA-256
`b3fe1e0aa7229edfd0760162d648f10328b0d75224a9cd49f2ba986b7db2ccbd`.
The adapter refuses different model/tokenizer/feature bytes before Test access.
Its request budget cannot exceed the native400ms request deadline. This does not
claim identical IPC/UI scheduling or end-to-end latency.

Each version2 row adds exactly `product_state`:

- `source_head`, `baseline_index`, `direct_count`;
- `evidence_tags`, one native fingerprint evidence tag per captured candidate;
- `schedule_eligible`, `selection_allowed`, both explicit booleans.

`schedule_eligible` must come from native scope/host/preedit/cursor/segment-count
admission; `selection_allowed` must come from native learning/cache/literal/bridge
protection. The source boundaries are `dispatch.rs::schedule_long_conversion`,
`begin_conversion`, `long_conversion.rs::build_candidates`/`selection`, and
`conversion/evidence.rs::neural_listwise_choice`. The adapter validates structure;
it does not invent or certify those facts. Legacy source-category strings cannot
be translated into this evidence. A real native-state producer and provenance
verification remain prerequisites. Labels, case/component IDs, tags and these
policy facts never enter model tensors.

The candidate descriptor's existing fingerprint check is a legacy structural
contract; it is not proof of the current engine's full candidate-set/session
identity. An authenticated native producer must preserve that distinction.
Inference-attempt counts describe this offline evaluator. Skipping protected
snapshots avoids unnecessary work here; it does not reproduce background work
that the asynchronous product may already have scheduled before selection.

## Version2 execution contract

Outer one-use admission/quality requirements are unchanged. Execution plan and
cohort use version2. This is evaluator serialization, not a production protocol-v2
change: the model wire contract remains protocol-v1. The `policy` artifact must equal
`current_tiny.snapshot_policy(provenance_sha256)`, including the current source
HEAD, pre-display population, native-local baseline, protected selection and
provenance-artifact hash. All frozen gates bind that policy. Legacy policy/gate
metadata cannot be silently reused; calibration must use this same application
contract, with separate frozen membership.

The current model has one `runs: {shipped: <name>}` entry and frozen configuration
`{kind: current_product_snapshot_v1, source_head: <pinned HEAD>}`. It has no invented
ungated/gated margin pair. Other models retain their ungated/gated variants, with
protected choice and strict frozen margin against the authenticated local index.
If that index is outside the scored prefix, the margin variant abstains. Required
comparisons include each run against local baseline and primary against shipped
current Tiny. Version1 remains the historical research execution contract.

Metrics accept optional `EvaluationCase.baseline_index` and `production_count`.
Defaults preserve the original converter-Top1 behavior. Explicit values enter the
cohort hash. Candidate Oracle@1/5/6/10/32 still describes original captured prefixes;
it must not be confused with local-selection accuracy or policy-selectable oracle.
MRR/NDCG use the selected-first operational prefix, including local fallback.
No statistical formula, denominator exclusion or safety threshold changed.

Both reference baselines are mandatory for version2. `overall` uses native local
selection; `converter_reference` retains the original converter-Top1 reference.
Both use identical sealed outputs, cases and component resamples, including
unchanged native-local fallbacks. Nonempty slices carry both reports; empty
slices retain nulls. Safety must satisfy the unchanged0.25% condition for both
references; a more favorable denominator cannot replace the original one.
Changes relative to raw converter rank0 can include existing local preference,
so they must not be attributed entirely to the neural model. The local-reference
report separates the neural contribution from that shared local behavior.

## Reproduction and measured scope

`parity.py prepare` freezes implementation/runtime/source/compiler/library hashes
and synthetic inputs before `run`. It builds a small standalone Rust harness with
the original scorer source and verbatim native evidence/choice functions. A capture
backend exposes the actual scorer's input tensors. Native ORT is deliberately a
nonexecuting stub in that harness; subsequent model inference uses Python CPU ORT
on each of the two independently produced feeds.

Run with the existing pinned Python environment, `PYTHONPATH=src;.` and bytecode
disabled, using a fresh task-owned directory below `~/tmp/`:

```powershell
python -B research/issue-35-current-tiny-parity/parity.py prepare --source-root <clean-pinned-sakura-input> --work-root <fresh-task-directory>
python -B research/issue-35-current-tiny-parity/parity.py run --source-root <clean-pinned-sakura-input> --work-root <same-task-directory> --plan-sha256 <printed-hash>
python -B -m unittest discover -s tests
python -B research/issue-33-data-growth/verify_integrity.py
git diff --check
```

The test suite needs an outer600-second owner followed by process inspection.
Native compiler/harness commands and model workers are bounded and their process
trees are inspected. Preserve failed attempts; no command overwrites a plan or
result. `native_harness.rs.in` uses explicit LF attributes for reproducible bytes.
The existing compiler/linker profile is reused with no Cargo download or build
tree in the production checkout. See [rustc arguments](https://doc.rust-lang.org/rustc/command-line-arguments.html)
and [CPU ONNX session API](https://onnxruntime.ai/docs/api/python/api_summary.html).

[Aggregate verification](../../reports/issue-35-current-tiny-parity-v1.json)
records exact counts, attempts and hashes. Synthetic results are contract evidence,
never an accuracy experiment or independent label-quality evidence.

The final run passes67 projection conditions (64 accepted, three invalid candidate
counts rejected),21,632 tensor scalar values with byte equality,1,756 protected
choices and384 numerically equal output scores from128 actual-model CPU requests.
Three frozen runs preserve implementation, provenance-policy and dual-safety
binding changes separately:384 actual-model requests in total, all synthetic and
without Gold. The full suite passes1,017 tests, zero failures/errors/skips.

The3,000-row synthetic evaluator test retains7 variants and6,000 model requests;
1,500 rows per model are ineligible. Native-local baseline correctness is2,249,
while raw-converter correctness is1,499. The shipped synthetic output is correct
on2,249 rows: zero gain over native local selection despite an apparent750-case
gain over raw converter order. This verifies why both references are necessary;
it is a constructed arithmetic case, not a measured model-accuracy result.

## Remaining work, expected benefit and cost

The immediate benefit is a faithful model/protected-choice reference for the
frozen snapshot domain, with explicit local fallback. No accuracy gain is claimed.
The next necessary task is a separately bound native-state producer: capture the
actual evidence tags, eligibility and preferred index without host/right context
or raw-text logs, then verify its provenance/identity. Cost is a native snapshot
contract and integration test task; it must precede real final-evaluation admission.
Independent label-quality evidence, representative isolated data, calibration,
one-use Test and production resource/integration gates remain required.

## Reading scope and architecture (IRV)

This change owns one product adapter plus evaluator payload/orchestration/metrics
integration, two focused test modules and the native diagnostic. The existing
worker keeps process/shared-memory ownership; admission keeps consumption and
durability ownership. Reusable CPU session construction preserves prior behavior.

Scope expanded to the native dispatch/selection boundary because a converter's
rank0 is not always the local preferred output. A model-only adapter could have
passed tensor tests while comparing the wrong baseline. The optional index/count
contract and explicit producer facts address that gap without duplicating session
state inside Python. No production code or settings were edited.

Future native-state work starts from this contract and the pinned dispatch source
boundaries; it need not rediscover tensor encoding, group choice, model pins or
worker cleanup. It still must establish native fact provenance and actual session
timing/display behavior. Those requirements were not hidden behind a passing
synthetic parity result.
