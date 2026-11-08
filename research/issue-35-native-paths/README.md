# Native path features for fixed models (#35 / parent #1)

The current converter's display segments are not the historical model's path
edges. Bunsetsu fusion combines words, while native evidence groups distinguish
repair/spelling edges from ordinary dictionary paths. The historical v1/r2/#29
feature definitions need the pre-fusion edge count and whether every raw edge
originated in the system dictionary. Neither can be guessed from an evidence tag.

Schema5 now binds observed raw paths and supplies a dedicated research-model
adapter. Native current-Tiny selection, the full768-candidate population, one-use
Test consumption and both0.25% safety references remain unchanged. No real Test,
fit, corpus acquisition, Gold registration or production source edit occurs.
Adoption remains90.72%; input/score parity is not accuracy improvement.

## Producer and provenance

The source is clean Sakura Input HEAD
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`. `probe.py` archives583 tracked files
under a fresh private`~/tmp` directory, uses the unchanged lock/toolchain offline
with one build job, and reuses the bounded native build/process owner. No worktree
or production checkout change is made.

Private instrumentation attaches a research carrier to each constructed candidate.
Inside`make_candidate`, it records each real node's source kind, reading/surface
UTF-8 coordinates, POS IDs and flags before display fusion. The carrier follows
clones. Its equality deliberately ignores research data, so the original derived
candidate equality is preserved; Debug hides the extra raw payload. This changes
private diagnostic allocation/layout and is not a production benchmark.

The seven constructor sites are explicit: ordinary path materialization,
lossless fallback, exact literal, date, numeric, punctuation and appended
single-kanji synthesis. Synthetic constructors record their actual constructed
segments with nonlexical provenance. Rewriting an exact literal refreshes that
carrier. New/unsupported paths cannot acquire a guessed dictionary origin.

`Surface::Dictionary`, including dictionary repair/correction variants, maps to
the old exporter's`system_dictionary` source. User/reading/katakana/literal
origins preserve their distinct categories. New passthrough/generated sources
are explicitly non-system; the old binary system feature remains0 for them.
Native authority and this historical model feature remain separate concepts.

The new capture has`path_version:1`; each candidate adds its recorded path and
actual display-segment count. `native_paths` first removes only this declared
extension and checks the existing native request/session/candidate identities.
It then verifies exact reading/surface correspondence, complete contiguous
UTF-8 ranges, bounded64-edge paths and POS/flag types. A carrier whose text or
reading changed after materialization is refused. This does not establish all
raw-repair/remapping or live-session behavior; unsupported transformations require
their own explicit producer treatment before evaluation.

The plan is native-producer version3 with`pre_fusion_converter_path_v1`, bound
to source/instrumentation/compiler/input/output hashes. The result envelope
remains the shared build owner's version2. Hashes establish byte identity, not
independent producer trust, Gold, or source/intent correctness.

## Consumer, model math and evaluation

Schema5 uses policy version4 and a distinct native-path provenance marker.
The existing hash-only case commitments cover the complete extended capture.
Every case is checked after durable Test consumption and before inference;
missing/tampered paths, changed inputs and session replay fail the whole cohort.
All candidates, including the tail, must bind. Sealed observation version3 adds
the path contract and retains full counts, model-prefix counts and all receipts.

`native_path_inputs` applies the unchanged v1/r2 functions to semantic descriptors
from observed raw edges. It does not create a legacy training/exporter record or
invent system entry IDs. Feature2 uses`min(raw_edges,8)/8`; feature5 is1 iff all
edges are system-dictionary origins. Other mathematical definitions, six/seven
feature widths,32-character hashing/truncation and empty observed context remain.
Long native strings retain these same formulas; their model accuracy outside the
training distribution remains unproved.

`native-path-tiny-gru-v1` is allowed only for historical models under schema5.
It cannot replace the current product baseline. The older generic GRU factory
remains refused for captured-native schemas. Current Tiny keeps its separate
native adapter and protected selection. Gate bindings must use the new frozen
policy; this work does not select, relax or independently calibrate a threshold.

## Observed evidence

- Native31 paired conditions produce62 executions,60 snapshots,1178 candidates
  and2046 raw edges. Both no-conversion events remain explicit. Removing the
  declared path extension reproduces all50 earlier native events exactly.
- The fusion fixture has216 paired candidate occurrences with fewer display
  segments than raw edges. Across this controlled population,434 system-only
  raw paths have a native evidence tag other than exact-system. These are
  provenance/representation counts, not errors, rescues or independent samples.
- Six added conditions cover fusion, mixed system/user paths, correction-flag
  dictionary entries, numeric synthesis, punctuation and fallback. This is not
  exhaustive synthesis, raw-repair, lifecycle or host coverage.
- Thirty predeclared response-arm snapshots supply model inputs; paired controls
  remain in the native audit. Three unchanged FP32 models (v1/r2/#29) match30780
  input scalar values byte-for-byte against their frozen historical encoder. Two feeds per model
  total180 CPU requests and540 equal output scores. No labels are used or scored.
- All1064 tests pass (13 new, failures/errors/skips0). Schema5's synthetic3000-row
  integration retains9874 candidates,5992 model requests, seven variants and3000
  path bindings. Tail tampering, missing provenance, replay and baseline-adapter
  replacement are refused. Synthetic fixtures never enter real Gold trust.

The native build took43.128seconds and its controlled execution0.399seconds;
fixed-model parity took2.618seconds. These are diagnostic wall times, not product
latency or a production CPU benchmark. Native ONNX/live-worker behavior is not
executed by the injected-response probe.

## Reproduction and preservation

Use the existing pinned Python environment,`PYTHONPATH=src;.` and
`PYTHONDONTWRITEBYTECODE=1`. Each attempt needs a fresh owned root under`~/tmp`.

```text
python -B research/issue-35-native-paths/probe.py prepare --source-root <clean-native-source> --work-root <fresh-native-root>
python -B research/issue-35-native-paths/probe.py run --work-root <same-root> --plan-sha256 <prepare-output>
python -B research/issue-35-native-paths/verify.py prepare --capture-root <native-root> --old-capture <retained-native-state-capture> --work-root <fresh-parity-root>
python -B research/issue-35-native-paths/verify.py run --capture-root <native-root> --old-capture <same-old-capture> --work-root <same-parity-root> --plan-sha256 <prepare-output>
```

The verifier pins the recorded native plan/result/capture and fixed model hashes;
a new producer identity requires a separately recorded verification recipe.
Run`python -B -m unittest discover -s tests` under a600-second guarded owner,
`python -B research/issue-33-data-growth/verify_integrity.py`, checkpoint hashes,
syntax/import checks,`git diff --check` and artifact tracking checks. Prove owned
process exit and remove task TEMP after retaining private recovery receipts.

[Aggregate evidence](../../reports/issue-35-native-paths-v1.json) records hashes,
counts, attempts and limits. Raw captures, source archives, compiler logs and
binaries are untracked. Six prior reports,16 original artifacts,25 fit bindings,
10 checkpoints and all three frozen encoder modules remain unchanged.

## Remaining work, cost and IRV

Benefit is a faithful fixed-model input comparison; no numerical accuracy gain
is predicted. Cost is one private engine build,62 controlled executions,180
CPU requests and contract verification. Next verify visible selection/commit
normalization and actual worker/session lifetime, stale responses and resource
limits against the same pinned native baseline. Independent Gold, calibration,
one frozen final Test and release Gates remain necessary; no criterion is waived.

Scope covered historical feature functions/exporter categories, native candidate
construction and display fusion, capture/evaluation binding and two focused test
modules. It expanded beyond public candidate accessors because fusion discards
raw boundaries and coarse repair evidence discards exact origins/counts. Private
construction-time capture supplies that missing information without changing
production ownership. `native_paths` owns the new evidence contract;
`native_path_inputs` owns model projection. Admission, worker containment and
metrics retain their existing owners.

Future work can consume these explicit path bindings without reconstructing
legacy feature semantics or guessing source categories. Unsupported post-path
transformations and live-session behavior still need their own evidence. The
working agent verified directly, without outside models or subagents.
