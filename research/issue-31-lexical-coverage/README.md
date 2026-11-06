# Exact lexical coverage diagnosis — Issue #31

Of the 335 source-reading contradictions, **320 original-ruby pairs have no
complete cover in the pinned dictionary index**. Fifteen can be composed from
two indexed entries; 13 already appear in the reference converter's Top-32 and
two do not. This separates an exact lexical correspondence problem from the
smaller set that is composable but absent from the observed candidates.

This cohort was selected because dictionary and original-ruby readings disagree.
It does not estimate dictionary coverage on general Japanese or the existing dev
set. A missing indexed cover does not identify a dictionary defect, an annotation
error, historical spelling, or the user's intended conversion. Those explanations
require separate evidence. No labels or dictionary entries were corrected.

The [aggregate report](../../reports/issue-31-lexical-coverage-v1.json) preserves
all 335 parents, all 1,005 source views and 335 dictionary-reading controls.
Adopted accuracy remains 90.72%; no accuracy improvement is demonstrated here.

## Frozen comparison and results

The [previous source-extent diagnostic](../issue-31-source-extents/README.md)
supplies authenticated source inputs and native observations. The new comparison
was committed at `f9eee3f6d6ecf87816c9405be2d6a620446c055e` before analysis.
Its plan pins 13 inputs and 15 code files, including the exact 368,341-row
surface/reading index and its verified manifest/compiled-dictionary identity.
No candidate miss or uncertain lexical outcome was selectively dropped.

| Source view / 335 parents | Complete index cover | Present in Top-32 | Index cover but absent from Top-32 | No index cover and absent from Top-32 |
|---|---:|---:|---:|---:|
| Original ruby | 15 | 13 | 2 | 320 |
| Following literal kana | 45 | 39 | 6 | 290 |
| Maximal supported run | 41 | 26 | 15 | 294 |

These columns describe overlapping properties: the first equals the second plus
the third in this run. The last three columns partition each 335-row condition.
All 78 native-positive view slots have an indexed cover; exceptions outside the
index model are zero. There are 23 composable-but-missing view slots, not 23
independent examples. The three conditions share parents and change the input
and target, so they cannot be pooled into an accuracy estimate.

Exact whole-surface reading entries occur in 0 / 1 / 1 source views respectively.
All 335 original-ruby surfaces exist in the index with a different unique reading;
absence of the desired pair is not absence of the surface. All 335 original
dictionary-reading controls have their exact single-entry cover. This control
checks provenance and lookup, not correctness of those dictionary-derived labels.

The graph was run separately with exact dictionary pairs only and with literal
kana copying allowed. Both modes give the same coverage on this complete cohort.
There are no work-bound outcomes. Original-ruby covers need two lexical entries;
the suffix and maximal-run conditions need between one and seven/eight entries.
Lexical entry counts are not native segmentation counts.

## Contract and limits

`src/sakura_rerank/data/lexical_cover.py` owns exact target/reading composition.
Both strings must be consumed completely. The optional literal rule copies only
Hiragana or projects fullwidth Katakana to Hiragana; it never infers Kanji readings,
normalizes surfaces, modernizes historical readings, or accepts a semantic label.
Witness offsets count Unicode characters, unlike native UTF-8 byte offsets.

A suffix automaton selects relevant dictionary surfaces in a single dictionary
scan without comparing every entry with every target. The selected 1,195 records
feed a trie and bounded acyclic state search. Limits remain 256 target characters,
128 reading characters, 33,153 states and 1,000,000 examined edges per pair.
Exhausting a bound produces an explicit `work_bound`, never a claim of absence.

The model omits POS connections, costs, pruning and other native generators.
Composition is therefore weaker than converter reachability; conversely, no
composition is only absence from this simplified index model. Previously verified
native observations are reused by exact committed/private artifact hashes. There
are no new native calls, model calls, fitting, threshold choices or Test accesses.
Original components and exposure history remain attached; new identities and
zero direct matches do not certify independent training/calibration/Test data.

## Verification and reproduction

All **911 tests pass**, with zero failures, errors or skips (18.679 seconds).
The 21 new tests include 2,400 seeded substring checks and 2,340 small graph cases
against a breadth-first reference. The first targeted run exposed one incorrect
expected character offset in a synthetic fixture (5 instead of 4); only that
expectation was corrected. The failed log and successful rerun are retained.

Direct verification selected the dictionary records by a separate prefix-bucket
method and replayed all 1,340 pairs / 2,680 graph conditions with a separate BFS.
It checked all 1,362 witness units, complete consumption and four terminal censuses.
All checks pass; forbidden data reads are zero. These are engineering checks by
Codex, not independent linguistic or human review.

Seven Python files pass syntax/unused-import checks. The original 16 artifacts,
25 fit bindings and 10 checkpoints retain their hashes. The clean Sakura Input
HEAD remains `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`; the reference runtime is
the separately pinned prior exporter, not a claim of current production parity.
All ten recorded owner/child PIDs exited, no matching repository runner remains,
and the dedicated task TEMP directory was deleted.

Analysis took 4.995 seconds including its owner; independent replay took 4.511
seconds. Each stage owns one child with a 1,800-second timeout, zero retries and
an explicit terminal/termination receipt. Source data stays in ignored storage:
`data/generated/issue-31-lexical-coverage-v1/attempt-01/` (15 files, 2,148,611 bytes).
Rubric, initial failure, rerun, process and cleanup evidence is retained in
`.codex/goal-loop/issue-31-lexical-coverage/`.

Recorded commands use the existing task venv, `PYTHONPATH=src;.` and `-B`:

```powershell
$commit='f9eee3f6d6ecf87816c9405be2d6a620446c055e'
python -B research/issue-31-lexical-coverage/run_owned.py analyze --commit $commit
python -B research/issue-31-lexical-coverage/run_owned.py verify --commit $commit
python -B research/issue-31-lexical-coverage/run_owned.py tests
python -B research/issue-31-lexical-coverage/publish_results.py
```

Use an owned TEMP under `~/tmp/` and remove it after process exit. Executed outputs
are write-once; the commands do not overwrite this attempt or the public report.
Another replay needs a fresh `SAKURA_LEXICAL_ATTEMPT` and separately versioned
publication destination. No package installation was needed.

## Decision, expected effect and cost

1. Finish a fixed weak-data admission recipe before another fit. Keep verified
   source annotations, explicitly weak dictionary-only evidence, conflicts and
   uncertainty distinct. This prevents repaired readings from silently becoming
   impossible or misleading supervision; its accuracy effect remains unmeasured.
   Reuse the existing 74,085-row prepared pool and reserve research evaluation
   before selecting recipes, with full ancestry/exposure closure. No new corpus
   download or GPU run is needed to specify and validate these contracts.
2. Treat the 2 / 6 / 15 composable-but-missing view slots as a separate candidate
   diagnosis. POS connectivity, costs and search are hypotheses, not established
   causes. Existing lexical witnesses and native snapshots are sufficient to
   scope that inspection; any additional native instrumentation must be bound
   before execution. A candidate improvement here would still need measurement
   on fixed inputs and cannot be counted as a ranker improvement in advance.
3. Do not add the 320 original-ruby pairs to a dictionary or normalize their
   readings automatically. Preserve source/name/quotation intent until evidence
   supports a policy. Repeating the full lexical check costs under five seconds
   per pass on this machine; certifying intended Japanese correctness remains a
   separate, unresolved task and has no measured cost or promised accuracy gain.

Safety remains 0.25%. Gold still requires 99.5% point quality, Wilson 95% lower
bound 99.0% and at least 3,000 valid final rows. Human/AI linguistic reviews,
original-label changes, training/Gold admission, calibration, final Test and
production changes are all zero. Gates A/B and release remain incomplete.

## Scope, architecture and future reading

Actual scope is one 100-line lexical data module, its 120-line contract tests,
five research scripts, one frozen plan, aggregate report and linked documentation.
Full-string lookup alone cannot distinguish missing lexical pairs from composed
paths, so the scope necessarily included bounded composition and a native-result
join. It did not require reopening native orchestration or model internals.

The data module owns composition semantics. Immutable pair/artifact hashes and
witnesses own diagnostic state; the research boundary authenticates source and
native inputs. The only runtime semantic dependency added is the existing literal
kana projection. Production and model architecture are unchanged. Future lexical
diagnostics need this API/tests and the sealed artifact contract; they must still
understand the difference between exact cover, native reachability and intended
conversion, and retain original source/exposure lineage.
