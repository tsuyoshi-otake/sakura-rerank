# Original-reading reconstruction and candidate evidence — Issue #31

All **335 exact original-ruby contradictions** now have immutable reconstruction
outcomes. The source repair preserves each original example and gives the derived
example a new identity linked to its parent. Of335 parents,318 support a bounded
new reading and17 remain pending because the original reading has one character.
The existing2–32-character preparation contract is unchanged.

The candidate result limits the immediate benefit: only **7 reconstructed rows
meet the existing Top-6 candidate contract**. A further6 have the exact original
surface in Top-32;305 measured rows lack it even in Top-32. The17 pending rows are
unmeasured, not candidate misses. All335 remain in the report denominator.

This is a source-data repair, not an adopted accuracy improvement. The adopted
record remains90.72%; independent Gold, calibration, final Test and release gates
remain open. See the [aggregate JSON](../../reports/issue-31-reading-rebuild-v1.json).

## Scope and invariant

The [previous preparation](../issue-31-reading-consistency/README.md) held these335
contradictions and580 uncertain annotation cases from75,000 previously consumed
research rows. This run selects every exact contradiction before inspecting its
new candidates; it leaves the580 uncertain cases alone.

`source_reading_rebuild.rebuild` recomputes the actual parent's decision from the
authenticated original paragraph. Only a dictionary-origin Aozora example with
an exact, conflicting original ruby extent is accepted. It copies that complete
reading and maps fullwidth Katakana to Hiragana. Historical kana, original surface,
left prefix, source positions and component identity remain unchanged. It does
not infer a pronunciation, modernize spelling or extend an input boundary.

The new stable identity commits to the parent input/source/decision/component,
old and new reading hashes, original annotation hash and frozen repair policy.
Its source receipt links to the derived lineage, which retains the original row
hash. Pending readings also receive terminal lineage records. Neither a new ID
nor matching original annotation grants training, Gold or independent evaluation
status. The original335 parent rows remain pending in the previous immutable pool.

All318 derived rows pass the strict default `source_reading_gate` producer and
authenticated consumer. Missing annotations cannot use its dictionary-only weak
exception in this child pool. The old extractors, labels, splits and models remain
unchanged. No newly inferred reading or original-label overwrite occurred.

## Complete candidate census

The318 derived rows require264 distinct readings. Their exact requests were
committed before native execution. Every request completed and validated; no
request was retried, rejected or left unattempted. The same pinned reference
exporter, dictionary,32-candidate limit and18-segment validator were retained.

| Exact source presence | Rows /all335 parents | Rows /318 measured |
|---|---:|---:|
| Top-1 | 3 /335 | 3 /318 |
| Top-5 | 7 /335 | 7 /318 |
| Top-6 | 7 /335 | 7 /318 |
| Top-10 | 8 /335 | 8 /318 |
| Top-32 | 13 /335 | 13 /318 |

The exclusive terminal partition is7 Top-6-eligible,6 present only beyond Top-6,
305 missing from Top-32,17 held by reading bounds. Top-6 encoding has0 candidate
truncation rows and0 surface-token collision rows. This selected subset is not a
sample from general IME use; it cannot revise the previous dev candidate ceiling
or establish a confidence interval for Japanese conversion accuracy.

The original dictionary-selected examples and reconstructed examples have
different readings. Comparing their candidate rates is not a same-input accuracy
comparison. The result does not prove that305 annotations are wrong or305
converter defects exist: source-specific notation, historical pronunciation and
the relation between ruby extent and actual IME input remain unresolved.

The clean current Sakura Input HEAD was
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`. The research reference exporter uses
source HEAD `5eefa2ffe15297e563da281432cece56049a1b09`. Its pinned binary identity
does **not** establish equivalence to current production. No rebuild, dependency
installation, production edit or worktree was needed.

## Input exposure after repair

New readings change input identity, so the original isolation result cannot be
transferred automatically. Five reconstructed source-prefix/reading inputs match
existing rows exactly, including the target surface. They are retained and marked.

| Numeric condition | Unique /318 | Match current75,000 | Match actual historical train | Match actual historical dev |
|---|---:|---:|---:|---:|
| Original synthetic source prefix | 318 | 5 | 0 | 0 |
| Empty observed-session context | 264 | 161 | 1 | 0 |

Empty-context inputs contain34 duplicate groups covering88 reconstructed rows.
The historical comparison uses14,304 bound, actually consumed numeric inputs
(12,516 train /1,788 dev), not a counterfactual projection of those old examples.
It reads input-hash metadata, not historical evaluation labels or model scores.

Private ledgers retain current row matches, original component bridges and
historical match identities. These are direct matches, **not** a completed
transitive exposure closure or permission to use any row as fresh evaluation.
Recompute full component closure before a separately bound fit. All318 examples
and all335 parent outcomes remain consumed research; changing their IDs does not
erase that history.

## Verification and reproduction

The source plan and code were committed at
`a04998f814809342837816a1c003dc808b8de7de`; exact requests were committed at
`c047ea6eab7671403e0e99fd810665254b4fa7bb` before native execution.

Direct verification recovered all335 original paragraphs and separately derived
the reading projection, new IDs and full lineage without calling the repair
function. Every strict child input and all318 duplicate records matched. All264
native receipts, identity files and snapshots revalidated without another native
call. Literal Top-k presence was independently recounted; all636 numeric inputs
and their direct exposure matches were recomputed using a separate hash/context
calculation. Forbidden source/evaluation reads:0.

All867 tests pass in19.764 seconds:18 new repair contracts,0 failures/errors/skips.
Nine Python files pass syntax and unused-import checks. The original16 artifacts,
25 fit bindings and10 checkpoints retain their hashes. Ten recorded owner/child
processes exited, all264 native calls were waited, and no matching native process
remains. The task-specific TEMP directory was removed. These are engineering
checks by Codex, not human or independent linguistic judgments.

Measured stage costs were13.524 seconds for preparation,15.679 seconds for native
execution plus census, and14.318 seconds for direct verification. The264 native
requests took14.820 seconds of bounded execution; concurrency2,30seconds/request,
900seconds total,128MiB accepted-output cap,0 retries. Each outer stage owns one
child with a1,800-second deadline and explicit terminal/termination records.

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
$python='C:/Users/developer/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe'
$sourceCommit='a04998f814809342837816a1c003dc808b8de7de'
$nativeCommit='c047ea6eab7671403e0e99fd810665254b4fa7bb'
& $python -B research/issue-31-reading-rebuild/run_owned.py prepare --commit $sourceCommit
# Exact prepared request hashes must be committed by the seal stage before native.
& $python -B research/issue-31-reading-rebuild/run_owned.py native --commit $nativeCommit
& $python -B research/issue-31-reading-rebuild/run_owned.py verify --commit $nativeCommit
& $python -B research/issue-31-reading-rebuild/run_owned.py tests
& $python -B research/issue-31-reading-rebuild/publish_results.py
```

These are the recorded stage commands. Executed artifacts are write-once; they
do not overwrite an existing attempt. The initial verification consumed sealed
native bytes without re-execution. Test runs require a fresh task-specific TEMP
under `~/tmp/`, removed after its processes exit, as required by repository policy.
A new attempt needs a new explicit binding; the old native binding names its
original attempt and cannot authorize a different directory. No automatic retry
or hidden replacement of a rejected reading is available.

Private evidence is retained at
`data/generated/issue-31-reading-rebuild-v1/attempt-01/`:1,873 files,6,804,852 bytes.
It includes complete parent/child lineage, strict pool, requests, native receipts,
measurements and verification. Raw readings/surfaces/candidates and individual
identities remain ignored and uncommitted. Local rubric, process and cleanup
evidence is at `.codex/goal-loop/issue-31-reading-rebuild/`.

## Priority and expected effect

1. Keep the enforced source-reading guard and this append-only repair contract
   in future preparation. Demonstrated effect:335 contradictions cannot silently
   remain as accepted original-reading examples; only7 derived rows satisfy the
   current candidate contract. This is data integrity, not a measured accuracy gain.
2. Diagnose the305 missing candidates using original continuous reading/surface
   extents and explicit input-unit hypotheses. Freeze those hypotheses before
   another bounded native comparison; do not infer missing readings or normalize
   historical/name/quotation intent to improve the count. Expected effect is to
   distinguish input-unit mismatch from reference candidate coverage; magnitude
   is unknown. Cost: existing-source recovery and a bounded native run comparable
   to this264-request run, not GPU training or a larger corpus download.
3. Before any model comparison, bind the revised weak-source recipe and complete
   projected-input exposure closure. Preserve the original comparator and a
   separately reserved evaluation source. Seven candidate-ready repairs cannot
   justify another unstructured dev tuning round. Expected accuracy effect and
   fitting cost remain unmeasured until that recipe and comparison are fixed.

Independent Gold must still meet99.5% point quality, Wilson95% lower bound99.0%
and at least3,000 final valid examples. Safety remains0.25%. No new fit, model
inference, threshold choice, calibration, final Test, human/AI linguistic review,
Gold admission, production change or release qualification occurred.

## Scope, architecture and future reading

Actual scope: one45-line data repair module, its18 contract tests, seven research
orchestration/verification/publication files, frozen source/native bindings and
aggregate documentation. The complete regression suite ran. No model or
production architecture changed.

Scope expanded to native candidate and input-exposure verification because a
reading change creates a different converter request and different model input.
The repair module owns derivation; the existing source gate owns preparation
admission; the immutable lineage/pool/native receipts own derived state. Research
orchestration depends on those contracts and the existing native validator,
without changing their bounds or coupling repair logic to model predictions.

For the next exact-reading repair, readers need the small repair API/tests,
source-gate contract and bound candidate protocol. They need not reconstruct the
earlier75,000-row diagnostic. Future experiments must still understand inherited
source components, changed numeric identity and the distinction between source
reconstruction, weak training authorization and independent IME correctness.
