# Original-source extent diagnosis — Issue #31

Including the original literal kana after a ruby span improves candidate
availability on the fixed335-parent diagnostic: **Top-6 source presence7→31;
Top-32 presence13→39**. The maximal supported run gives23 and26 respectively.
These are changed-input source-reconstruction results, not adopted accuracy.

Input extent explains part of the previous305 Top-32 misses: the literal-suffix
condition finds the expanded source target in23 of them, leaving282 without it;
the maximal-run condition finds18, leaving287. The two predefined extensions do
not explain most missing candidates. This is evidence against simply enlarging
every input or repeating training on automatically repaired readings.

The [aggregate JSON](../../reports/issue-31-source-extents-v1.json) retains every
parent and all1,005 view slots. Adopted accuracy remains90.72%, safety0.25%, and
independent Gold, calibration, final Test and release gates remain unresolved.

## Frozen comparison

All335 original-reading contradictions from the
[previous reconstruction](../issue-31-reading-rebuild/README.md) were selected
before the new source/candidate comparison. The305 old misses are only a reporting
subgroup. No new source example was selected or discarded based on model results.

| View | Exact rule | Expanded parents |
|---|---|---:|
| Original ruby | Preserve the complete original ruby base and reading | 0 |
| Literal suffix | Add all immediately following unannotated literal kana; stop before another annotation | 300 |
| Supported run | Take the maximal adjacent run of complete phonetic ruby spans and literal kana containing the original base | 322 |

Unknown readings, nonphonetic/editorial annotations, unresolved annotation scopes
and punctuation/space stop expansion. A supported neighboring ruby must be a
complete1–32-character phonetic annotation, not an inferred partial reading.
Zero-width unresolved annotations also form barriers. Halfwidth kana is not
normalized; historical kana is not modernized. Only the fixed fullwidth Katakana
to Hiragana projection supplies input readings. No surface is normalized.

The rules do not certify grammatical words or intended IME input boundaries.
Stopping at an unannotated Kanji means its reading is unavailable; it is not a
claim that the neighboring unit is invalid or that all Kanji adjacency is wrong.
Maximal runs are never clipped to make their length fit. Changed ranges on an
orphan-marker paragraph remain pending. Every failure has an explicit terminal
outcome and stays in its comparison denominator.

Each view has a new identity bound to its complete source range, original
reading/target/prefix hashes, source evidence, parent repair and original component.
All source characters between its boundaries are retained. Its left prefix is
recomputed at the new start, capped at the existing64 characters. Source text to
the right is used only when it becomes part of the explicit expanded target; no
host-document/right-context feature or observed Sakura session is fabricated.

## Diagnostic bounds and preparation remain separate

Native diagnostics use the existing1–128-character reading and1–256-character
target bounds. The original preparation conditions remain2–32-character reading,
1–32-character target and8–64-character synthetic left prefix. Passing the latter
conditions still does not authorize training, Gold or independent evaluation.

The17 one-character original readings held by the previous preparation are now
measured only as native diagnostics. All17 still lack the original ruby target in
Top-32, so the previous13 original-ruby matches are unchanged. Their original
preparation records remain pending. No length rule was relaxed for learning.

All335 views per condition fit native diagnostic bounds, so all1,005 were measured.
The unchanged preparation bounds hold for318 original-ruby,335 literal-suffix and
324 supported-run views. Original parents, labels, extractors, splits, models and
the other580 uncertain annotation cases are unchanged.

## Complete native results

| View /335 parents | Top-1 | Top-5 | Top-6 | Top-10 | Top-32 |
|---|---:|---:|---:|---:|---:|
| Original ruby | 3 | 7 | 7 | 8 | 13 |
| Literal suffix | 14 | 30 | 31 | 34 | 39 |
| Supported run | 11 | 22 | 23 | 24 | 26 |

Top-6 candidate eligibility plus unchanged preparation bounds holds for7/31/23
rows respectively. All remain unadmitted research examples. None has reading or
candidate prefix truncation or encoded candidate-surface collision in this run.

At Top-32, literal suffix and original ruby are both present in11 parents; suffix
only28, original only2, neither294. Supported run and original are both present
in5; run only21, original only8, neither301. Thus a larger range can lose source
matches even while gaining others. At Top-6, suffix retains all7 original matches
and has24 additional matches; supported run retains4, loses3 and adds19.

Within the fixed305 previously measured Top-32 misses, literal suffix provides
23 Top-32 matches and20 Top-6 matches; supported run provides18 and17. These are
different input/target hypotheses, not successful ranker corrections of the same
IME input. A best-per-row choice across hypotheses would be an oracle and is not
a deployed selection rule. This selected cohort cannot establish general Japanese
accuracy, dictionary defect rates, Gold quality or a confidence interval for them.

There are830 distinct readings:264 previous requests were fully authenticated and
reused;566 new requests were committed before execution. All566 completed and
validated. Rejections, missing requests and retries are0. The fixed32-candidate
and18-segment contracts were unchanged. The clean current Sakura Input HEAD was
`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`; the reference exporter's source HEAD is
`5eefa2ffe15297e563da281432cece56049a1b09`, so this is not production equivalence.

## Input exposure

| View | Current source-prefix input matches | Current empty-context input matches | Actual historical train /dev matches, empty context |
|---|---:|---:|---:|
| Original ruby | 5 | 161 | 1 /0 |
| Literal suffix | 3 | 26 | 0 /0 |
| Supported run | 1 | 7 | 0 /0 |

All three source-prefix conditions have335 distinct numeric inputs. Empty context
has275/323/333 distinct inputs, with39/9/2 duplicate groups covering99/21/4 rows.
All source-prefix historical direct matches are0. The comparison uses the bound
75,000 current inputs and14,304 actually consumed historical inputs, not a
counterfactual projection of old fitting data or newly opened evaluation labels.

Private ledgers preserve every raw duplicate, numeric match and original component
bridge. Zero direct matches does not certify independence: source/component history
is inherited, and full projected exposure closure is still required before a
separately bound experiment. No variant becomes fresh calibration or final Test.

## Verification and reproducibility

Source policy/code were committed at
`41e5a3a510087b12194a6fb9f54a4d68d64e45e5`; exact native requests were committed at
`e0c989f62eda0a266f8c832eef8fc9e11d74dec7`. Both precede their respective execution.

Before real source consumption,23 new contracts passed and a separate
coverage-mask/sorted-atom implementation matched256 seeded synthetic sources
(768 views), including unsupported/zero-width annotations. After execution, the
same independent derivation recovered all335 parents and1,005 complete views,
including extents, literal/ruby parts, readings, prefixes, stable IDs and lineage.
All1,005 raw-overlap records,830 native receipts and2,010 numeric projections were
checked. Literal source presence and20 paired censuses were separately recounted.
The previous318 original measurements reproduce exactly. Forbidden data reads:0.

All890 tests pass in19.780 seconds, with0 failures/errors/skips. Nine Python files
pass syntax/unused-import checks. The original16 artifacts,25 fit bindings and10
checkpoints retain their hashes. Ten recorded owner/child processes exited; all
566 native calls were waited, no matching native process remains, and the dedicated
task TEMP directory was deleted. These are engineering checks by Codex, not human
or independent linguistic review.

Preparation took14.386 seconds, native execution plus census35.833 seconds, and
direct verification17.367 seconds. The566 new native calls took34.814 seconds.
Limits:2 workers,30 seconds/request,900 seconds/native run,128MiB accepted output,
0 retries. Each stage owns one child with a1,800-second deadline and explicit
terminal/termination records. Failed stages cannot produce the verified public
report; any already executed request and rejected snapshot remain traceable.

The recorded stage commands are:

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
$python='C:/Users/developer/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe'
$sourceCommit='41e5a3a510087b12194a6fb9f54a4d68d64e45e5'
$nativeCommit='e0c989f62eda0a266f8c832eef8fc9e11d74dec7'
& $python -B research/issue-31-source-extents/run_owned.py prepare --commit $sourceCommit
# Seal and commit the exact request binding before the native stage.
& $python -B research/issue-31-source-extents/run_owned.py native --commit $nativeCommit
& $python -B research/issue-31-source-extents/run_owned.py verify --commit $nativeCommit
& $python -B research/issue-31-source-extents/run_owned.py tests
& $python -B research/issue-31-source-extents/publish_results.py
```

Executed outputs are write-once; these commands do not overwrite an existing
attempt. A new attempt needs a new explicit request binding. Tests require their
own task TEMP under `~/tmp/`, removed after process exit. Raw source/requests,
individual identities, native bytes and measurements remain ignored under
`data/generated/issue-31-source-extents-v1/attempt-01/`:3,984 files,24,036,576 bytes.
Rubric, synthetic replay, process and cleanup evidence is retained in
`.codex/goal-loop/issue-31-source-extents/`.

## Decision, priority and cost

1. Preserve the executable source-extent contract and all three outcomes as
   evidence. Literal suffix is a useful candidate-generation hypothesis on this
   selected cohort; it is not adopted as a universal extraction or IME-boundary
   rule. Its measured candidate-capacity benefit is24 additional Top-6 matches,
   with no old Top-6 loss here, but two old Top-32 matches are lost.
2. Prioritize the remaining original-reading versus dictionary/candidate mismatch
   over more arbitrary extent expansion. Reconcile exact original readings,
   surfaces and available lexical evidence without rewriting historical/name/
   quotation intent. The source mismatch may involve annotation intent or
   reference coverage; neither is proven by a missing candidate alone. Expected
   effect is a defensible source-admission/repair policy, not a quantified accuracy
   gain. Cost starts with the existing335 source records and pinned dictionary;
   another full corpus download or GPU fit is not required for that diagnosis.
3. Before changing the weak training recipe, test a fixed source-unit policy on a
   separately reserved research cohort with complete ancestry/exposure accounting.
   Do not choose a favorable range per row or reuse this cohort as independent
   evaluation. A bounded candidate run of this scale cost35 seconds here; future
   cohort size and fitting cost must be fixed before that experiment.

No model fit/inference, threshold selection, original-label overwrite, calibration,
final Test, Gold admission or production change occurred. Gold requirements remain
99.5% point quality, Wilson95% lower bound99.0% and at least3,000 final valid rows.
Safety remains0.25%; release Gates A/B remain incomplete.

## Scope, architecture and future reading

Actual scope is one82-line data module,23 contract tests, seven bounded research
orchestration/verification/publication files and frozen bindings. The complete
regression suite ran; model and production architecture are unchanged.

Changing a source extent changes target, reading, prefix and input equality, so
scope necessarily includes paired candidate/exposure accounting. The data module
owns deterministic derivation; immutable view lineage and native receipts own
state. It depends on the existing parent-reading check and fixed kana projection.
The candidate-only research path does not bypass or widen training preparation.

Future fixed extent diagnostics need this API/tests, the original-source gate
contract and pinned native protocol. They need not re-read the earlier full-corpus
audits. They must still understand inherited components, different-input comparison
semantics and the distinction between source presence and intended IME correctness.
