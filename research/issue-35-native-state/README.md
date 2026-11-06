# Native state capture and evaluation binding (#35 / parent #1)

The actual pinned engine dispatcher now produces research snapshots before
display projection. The capture records native candidates, local preference,
selection calls and the request/response identities from the same execution.
Evaluator schema3 checks the frozen capture commitment and rejects snapshot
replay before model execution. This is controlled native contract evidence,
not independent Gold, a measured accuracy improvement or a release approval.

## What the native experiment established

Clean Sakura Input HEAD is `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`.
The probe archives583 tracked source/configuration/fixture files, keeps the
original Cargo.lock and builds the engine's library test with its existing
`dev-fixtures` feature. No worktree, production edit, package update or download
is made. Compiler/linker/library identities reuse the existing pinned profile;
build work is one job, offline, locked and bounded to600 seconds. Native execution
is bounded to120 seconds in a Windows Job Object.

The diagnostic adds two observation hooks and a test module to the private
archive. Actual `Dispatcher`, `Session`, conversion, preference, scheduling,
candidate building and selection run. The test creates an in-memory dictionary
and learning service, and supplies explicit synthetic worker responses. No
native ONNX worker, real model, host document, personal dictionary or external
corpus is used. Built-in tracked test fixtures are compiled, not evaluated as
new corpus data.

There are25 conditions, each with a separate no-response local control:50
executions,48 conversion snapshots and two no-conversion events. All50 remain
in accounting. The native captures contain924 candidate records, with108 in the
largest snapshot. Two separately built versions produced byte-identical final
capture streams; their executable hashes differ and are not claimed identical.
The earlier23-condition probe remains preserved separately.

Three findings change the next implementation work:

1. Native candidate populations exceed the legacy32-row evaluation boundary.
   The pinned engine's transport capacity is768, with1536-byte text storage and
   separate search budgets. The108-row example is preserved completely; neither
   truncation nor excluding the case is an acceptable migration.
2. Scheduling and applying are different events. Eight executions built a model
   request while authoritative local selection prevented application. A cached
   preference at native index13 remains outside the six scored slots. Attempting
   to learn a preference does not itself prove that native learning admitted it.
3. Flushing pending Romaji changes the reading/candidates between the two phases.
   Both paired executions keep local fallback because the original request no
   longer matches. Owner/session/generation/reading and candidate-set/individual
   fingerprints all matter. FNV is the native identity check, not a cryptographic
   substitute for the outer SHA-256 artifact binding.

Five synthetic response applications are expected choices, not correction
successes. The count says nothing about Japanese label accuracy. The scripted
Left-key scenario records the observed native outcome; it does not certify that
every caret movement state was exercised. TSF, visible projection, all session
lifecycle transitions and asynchronous availability/latency remain separate.

## Capture and evaluator contracts

`native_snapshot.py` owns strict capture decoding, native fingerprint checks,
request/response joins, paired controls and binding of observable row fields.
It accepts the full native bound. Captures and baseline controls retain their
original order and terminal outcomes; altered, missing, reordered or repeated
evidence cannot become a successful diagnostic. Errors contain no raw text.

`bind_evaluator_input` compares the exact full candidate order, costs, reading,
empty observed context and native policy facts. It does not invent the legacy
per-edge source categories or segment provenance. The final native diagnostic
binds46 compatible projections, reports two larger populations as unsupported
by the legacy evaluator, and retains two no-conversion events. These are
diagnostic counts, never a filtered evaluation dataset.

Execution/cohort schema3 adds `native_capture` to every row. Its hash-only
`native_evaluation_provenance` metadata binds the pinned source, producer plan,
producer result, full capture hash and each case's canonical capture hash.
Metadata is checked before Test reservation; raw captures are checked only
after the existing one-use reservation and before any inference. Reusing a
native owner/session/generation/reading identity under a new fixture ID fails.
Projection binding receipts are sealed alongside all model outputs.

Schema3 uses a new policy version, preventing reuse of old calibration/gates
without the distinct provenance binding. Both converter-Top1 and native-local
safety references still require0.25%. Schema1/2 historical contracts remain.
The native snapshot domain is a counterfactual offline model opportunity:
matching scheduled candidates and local application permission. Captured
response availability/failures are checked and reported separately; replaying
fresh model scores does not reproduce the original worker's arrival time.

The generic research GRU factory is refused for schema3 because its system-
dictionary feature and per-edge segment data are not established by the native
evidence enum. Alias registration cannot bypass that refusal. The existing
32-row/legacy feature contract is not silently widened: an unrepresentable row
fails the whole evaluation, preserves Test consumption and starts no model.

Expected hashes establish byte identity, not trustworthy authorship or Gold.
The diagnostic provenance is not enrolled as independent evidence. Gold trust
remains empty; a real native producer, population design and independent quality
evidence must still be established before any final evaluation.

## Verification and reproduction

Use the existing pinned Python environment with `PYTHONPATH=src;.` and bytecode
disabled. Each build requires a fresh directory below `~/tmp/` and a clean
source checkout. Never overwrite a plan, start marker, capture or result.

```powershell
python -B research/issue-35-native-state/probe.py prepare --source-root <pinned-clean-sakura-input> --work-root <fresh-private-directory>
python -B research/issue-35-native-state/probe.py run --work-root <same-directory> --plan-sha256 <printed-plan-hash>
python -B research/issue-35-native-state/audit.py --work-root <same-directory> --plan-sha256 <pinned-plan-hash> --result-sha256 <pinned-result-hash> --output <new-aggregate-json>
python -B -m unittest discover -s tests
python -B research/issue-33-data-growth/verify_integrity.py
git diff --check
```

The test owner uses a600-second outer deadline and checks child processes after
termination. A custom Python test entrypoint must guard execution with
`if __name__ == '__main__'`: the initial unguarded temporary wrapper recursively
started tests when Windows spawned a worker. Direct metric computation worked;
adding the guard made all19 then-current targeted tests pass. That failed run
is retained as environment feedback, not hidden or fixed by changing metrics.

Final verification passes1,037 tests, including20 new contracts, zero failures,
errors or skips. Schema3's synthetic3,000-row test retains all rows, four adapters,
seven variants,6,000 model requests and3,000 sealed projection bindings. It tests
capture tampering, missing records, session replay, unsupported native populations
and rejection of unproven research features. It is not model-accuracy evidence.

[Aggregate evidence](../../reports/issue-35-native-state-v1.json) records exact
artifact identities, attempts and preservation checks. Cargo invocation follows
the [official Cargo test contract](https://doc.rust-lang.org/cargo/commands/cargo-test.html).
Private captures, binaries and compiler/test logs are not committed.

## Remaining work and expected benefit

The next required task is an explicit current-candidate contract and provenance
for the old models' per-edge features. It must represent the full native
population and local fallback without deriving source categories from native
evidence tags. Verification costs one source-instrumentation/feature-parity task
plus evaluator/metric boundary tests. Its benefit is a comparable denominator
and faithful features; no numerical accuracy gain is predicted from this work.

Visible selection/commit normalization, actual worker/session timing and resource
gates remain unverified. Independent labels, calibration and a single frozen
final Test remain necessary. Adoption stays90.72%, and no safety or Gold threshold
is changed. New corpus acquisition, fitting and production changes remain zero.

## Reading scope and architecture (IRV)

Semantic review covered the native dispatch/schedule/selection boundary, session
cache behavior, native candidate evidence/capacity, and the existing evaluator
payload/runner/worker contracts. Two focused test modules cover the consumer;
the private engine build compiles583 source/configuration/fixture files without
requiring unrelated production modules to be redesigned.

Scope expanded when actual execution produced108 candidates and a post-flush
identity mismatch. The declared booleans in schema2 alone could not prove those
facts. The native capture component now owns that evidence; payload validation
owns row binding, admission retains Test consumption ownership, and workers
retain process/shared-memory ownership. No production state is copied into an
independent Python session implementation.

Future work reuses the capture protocol, identity checks, fallback controls and
cleanup recipe. It still needs the full-population and per-edge feature mapping,
visible projection and real worker/session evidence. Those new obligations are
explicit rather than inferred from a passing synthetic run.
