# Original-reading consistency in new source preparation — Issue #31

New reconstruction preparation now **holds contradictory or uncertain original
annotation evidence before any row reaches candidate/numeric preparation**.
The [source-reading gate](../../src/sakura_rerank/data/source_reading_gate.py)
is exercised by the real75,000-row pipeline, not just an audit-only classifier.
The [aggregate report](../../reports/issue-31-reading-consistency-v1.json) records
the complete application and direct source/consumer verification.

The previous [source audit](../issue-31-conflict-source/README.md) found335
dictionary-reading contradictions. All335 are now held in the new preparation,
along with580 cases where original annotation scope/parse/reading evidence is
uncertain. Original rows, labels, models and evaluation sets remain unchanged.
This implementation does not demonstrate an adopted accuracy improvement:
90.72% is still the adopted result, and safety remains0.25%.

## Implemented boundary

`assess` accepts the original encoder input, authenticated source extent and
original paragraph, then recomputes reading evidence. Aozora paragraphs must
retain their original ruby structure; callers cannot silently replace them
with unannotated plain text. Exact target and bounded left-prefix correspondence
are mandatory. The check does not infer readings from context, accept spelling
equivalence, or reject input units solely for Kanji adjacency.

`prepare` creates a new immutable pool. Every input receives a hash-chained
terminal decision. Only preparable rows enter its separate payload. The default
holds missing original annotation evidence; dictionary-only weak supervision
requires an explicit policy flag. That flag never overrides observed conflicts,
scope differences, unresolved parses or nonphonetic/out-of-bound annotations.
An annotation-origin claim cannot silently downgrade itself to dictionary-only
when its annotation is missing.

`load_prepared` requires the exact externally pinned manifest hash and one of
two purposes: `candidate_generation` or `numeric_verification`. It checks every
artifact, decision chain, policy/state relationship, original input hash, row
order and count before returning a row. Training, calibration, Gold and final
Test purposes are rejected. Source preparation readiness never implies those
permissions.

The producer validates staging through this consumer before atomically naming
the completed directory. A failed source, duplicate/missing input, all-pending
batch, invalid output or failed rename publishes no completed pool. Existing
destinations are never overwritten; cleanup owns only newly created staging.
The outer runner provides one child, no retry, a1,800-second deadline and an
explicit terminal record, including process-tree termination on timeout.

## Complete consumed-population result

This application explicitly retains dictionary-only weak examples from the
existing research recipe. It is a new source-consistency screen, not a new
training authorization or a change to the default policy.

| Terminal state | Rows | Candidate/numeric preparation |
|---|---:|---|
| Original annotation matches | 25,567 | Available as source reconstruction only |
| Dictionary-only weak evidence, explicitly enabled | 48,518 | Available with weakness retained |
| Original reading conflicts | 335 | Pending |
| Annotation scope differs | 567 | Pending |
| Annotation parse unresolved | 11 | Pending |
| Annotation nonphonetic/out of bounds | 2 | Pending |
| Total | 75,000 | 74,085 preparable /915 pending |

The335 contradictions are1.34% of the original25,000 dictionary-Aozora rows.
The580 other pending cases are uncertainty, not580 certified linguistic errors.
The25,567 matching cases are not Gold; the48,518 weak cases are not promoted.
With the default missing-evidence policy, these48,518 cases would also be pending.
Every training/independent-Gold flag stays false.

All25,000 Wikipedia and25,000 annotation-Aozora rows remain preparable in this
explicit weak-source run; dictionary Aozora contributes24,085 rather than25,000.
This changes source composition. It cannot be reported as an accuracy gain or
silently compared to the old50,000-row arms as an identical-denominator experiment.
The915 pending rows stay in the full75,000-row denominator and consumed-source
history. Removing them from prepared payload does not erase historical exposure,
split component bridges, or make them new calibration/Test candidates.

The new output order groups source access for bounded work: Wikipedia paragraph
stream order, then sorted Aozora work ID, with old cohort order within each source.
All original identities and component IDs remain. Consumers join by authenticated
identity, never by assuming old and new row positions correspond.

## Verification and execution

Plan/code were committed before the application at
`4f7cca7109549a16b7d326504f17dd73794b78a6`. Preparation took20.179 seconds and
direct verification15.855 seconds. No source download, converter request, model
inference, fit, threshold search, calibration or final Test occurred.

The verifier recomputed original reading states with a separate implementation
for all75,000 rows, reconciled them to the previous immutable audit, checked all
335 prior repair identities, and compared every returned input to its original.
All74,085 consumer rows and915 pending rows matched. Forbidden data reads:0.
The original parser is reused; this is direct engineering verification by Codex,
not independent linguistic or human review.

All849 regression tests passed in18.661 seconds, with28 new contracts and no
failures/errors/skips. Tests cover source conflicts and missing evidence, default
versus explicit weak policy, annotation provenance, exact source extents,
non-normalization, adjacency, pending-row injection, payload/manifest tampering,
false admission flags, unsupported purposes, atomic failure and preservation of
existing destinations. Six Python files pass syntax/unused-import checks; the
original16 artifacts,25 fit bindings and ten checkpoints retain their hashes.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
$python="$HOME/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe"
$commit='4f7cca7109549a16b7d326504f17dd73794b78a6'
& $python -B research/issue-31-reading-consistency/run_owned.py prepare --commit $commit
& $python -B research/issue-31-reading-consistency/run_owned.py verify --commit $commit
& $python -B research/issue-31-reading-consistency/run_owned.py tests
& $python -B research/issue-31-reading-consistency/publish_results.py
```

These executed outputs are write-once. Re-execution requires a fresh bounded
attempt via `SAKURA_READING_ATTEMPT`, never overwriting a completed pool.
Private rows, full decision history, manifest and terminal receipts remain under
`data/generated/issue-31-reading-consistency-v1/`. Only code, tests and aggregates
are committed. Rubric/process/cleanup evidence is retained in
`.codex/goal-loop/issue-31-reading-consistency/`.

## Next repair and release dependencies

The source-integrity fix is implemented. Next, separately rebuild the335
contradictory source examples from exact original full readings under new
identities, with original-parent hashes and fresh candidate evidence. Do not
overwrite old readings or guess the580 uncertain cases. Cost: bounded source
reconstruction and native candidate verification; no GPU training is needed to
verify that repair. Its accuracy effect is unknown until a separately bound
experiment has a valid independent evaluation source.

Independent Gold quality, calibration and one-use final Test are still open.
The requirements remain99.5% point quality, Wilson95% lower bound99.0%, at least
3,000 final valid examples and0.25% safety. Source annotation agreement cannot
replace that evidence. Production Gates A/B, integration, default enablement
and release remain incomplete; this pool is not release qualification.

## Scope, ownership and future reading

Actual scope: one source-consistency module, its contract tests, and four bounded
research orchestration/publication scripts. Existing source parsers/extractors
remain unchanged so prior bound experiments can replay. The full regression
suite ran; no production or model-architecture behavior changed.

Scope expanded from a row check to transactional publication and an authenticated
consumer because a detection-only helper would allow pending rows to pass into
later generation. The data module owns this single preparation responsibility;
the immutable pool manifest and complete decisions own derived state. Its
dependencies point to existing source parsing and canonical-hash contracts.
Source metadata and right-boundary text never become model features.

Future consumers need the small `prepare`/`load_prepared` contract, tests and
externally pinned manifest/source binding. They no longer need to reconstruct
the335-row audit or understand parser internals to enforce pending states. They
must still preserve original identities/component history and distinguish weak
source readiness from fitting, Gold and independent evaluation permission.
