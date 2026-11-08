# Source conflicts and reading consistency — Issue #31

The [aggregate result](../../reports/issue-31-conflict-source-v1.json) identifies
**335 dictionary-derived Aozora rows whose reading disagrees with the exact
original ruby span**. This is 1.34% of that fixed 25,000-row cohort. Original
source occurrence and dictionary reading uniqueness do not establish contextual
reading correctness. These are concrete source-reconstruction repair candidates,
not 335 independently judged Japanese errors.

All 75,000 existing rows and labels remain unchanged. Hash-only repair proposals
are saved separately and have not been applied. Adopted accuracy remains
**90.72%**; this work demonstrates no adopted accuracy improvement or release
qualification. Safety remains 0.25%, and Gold requirements remain point estimate
99.5%, Wilson95% lower bound 99.0%, and at least 3,000 final valid examples.

## What causes the 2,114 conflicting input groups?

All 21,459 empty-context numeric inputs were joined to authenticated native
snapshots. Each maps to one literal reading/candidate input. No whole-input
encoding alias, within-snapshot surface encoding collision, reading truncation
or candidate-surface truncation explains these conflicts in this population.
This is a population-specific finding, not a proof that character hashing can
never collide.

| Whole-group mechanical notation result | Groups | Rows | Minimum source mismatches |
|---|---:|---:|---:|
| Distinct after all declared folds | 2,087 | 21,918 | 5,626 |
| Kana fold collapses all target forms | 26 | 156 | 30 |
| Case fold collapses all target forms | 1 | 6 | 2 |
| Total | 2,114 | 22,080 | 5,658 |

The fixed precedence is literal, NFC, NFKC, kana, case, combined kana/case, then
distinct. A group belongs to the first transformation that collapses **all** its
target forms; a matching pair alone does not classify a whole group. No group
required only NFC/NFKC, combined folding, or identical literal targets in different
slots. The 27 mechanically collapsible groups account for only 32 of the 5,658
minimum mismatches. Even these 27 do not authorize normalization: names,
identifiers, quoted forms and intended meaning remain unreviewed. The remaining
2,087 groups are not all proven semantic ambiguity; intended alternatives and
extraction problems still require suitable evidence.

## Source evidence across the complete population

An initial diagnosis recovered all 22,080 conflicting rows and found 101 reading
disagreements. Before examining the remaining source states, revision2 extended
the same mechanical checks to all 75,000 already consumed rows. This avoids
reporting a conflict-selected rate as general data quality. Both runs are kept;
every original conflict aggregate is unchanged. The full census finds another
234 disagreements outside the conflicting groups.

| Reading evidence | Dictionary Aozora | Annotation Aozora | Wikipedia |
|---|---:|---:|---:|
| Exact original ruby reading matches | 567 | 25,000 | — |
| Exact original ruby reading disagrees | 335 | 0 | — |
| No overlapping original ruby | 23,518 | 0 | — |
| Original ruby scope differs | 567 | 0 | — |
| Ruby parse unresolved | 11 | 0 | — |
| Exact ruby nonphonetic/out of bounds | 2 | 0 | — |
| No original reading annotation in this source contract | — | — | 25,000 |
| Total | 25,000 | 25,000 | 25,000 |

All 75,000 target substrings and bounded left prefixes match their authenticated
source spans: 22,034 Wikipedia paragraphs and 545 original Aozora works were
recovered. Thus the 335 discrepancies are not failed substring joins. All labels
remain weak source reconstruction, including the 25,000 annotation matches.
Those matches preserve the source's reading but do not certify meaning, intended
IME boundaries or Gold quality, and do not reverse the prior failed annotation
model experiment.

The audit records adjacent character classes, including the right boundary,
solely as source metadata. They never enter model features, trigger blanket
Kanji-adjacency rejection, or act as linguistic judgments. All 75,000 input-unit
and semantic judgments remain unresolved. Human reviews and AI linguistic
reviews in this task are both zero.

## Context information and source mixture

The suffix lengths below were fixed before the first run. Each row uses only
the existing synthetic source prefix; none is observed Sakura session history.

| Left-source suffix characters | Unique hashed inputs | Conflicting groups | Minimum source mismatches |
|---|---:|---:|---:|
| 0 | 21,459 | 2,114 | 5,658 |
| 1 | 51,920 | 1,298 | 1,835 |
| 2 | 69,128 | 269 | 300 |
| 4 | 73,771 | 30 | 32 |
| 8 | 74,548 | 0 | 0 |
| 16 | 74,592 | 0 | 0 |
| 32 | 74,594 | 0 | 0 |
| 64 | 74,594 | 0 | 0 |

Literal-context unique counts at lengths1/2 are 51,925/69,129; character hashing
merges five/one additional groups there, without changing the mismatch bound.
Literal and hashed mismatch counts agree at all eight lengths. The zero-context
alias result above does not claim zero collisions in every new projection.

At eight characters, 74,548 distinct inputs remain among 75,000 rows. Removing
empirical contradictions by nearly identifying individual examples is not a
held-out generalization result. These values select no production context
length, imply no 100% achievable accuracy, and do not authorize host-document or
right-context access. The fixed #29 model still falls 13,271 source matches
below the empty-input census ceiling, so ambiguity alone cannot explain its
ranking failures.

Separately, minimum empty-input mismatches are 1,003 for Wikipedia, 1,240 for
dictionary Aozora, and 1,584 for annotation Aozora: 3,827 total. The union requires
5,658, adding **1,831** because one common input-to-choice mapping must serve
the different source distributions. This arithmetic is not a causal accuracy
effect; source identity is not proposed as an available production feature.
No hard source, giant component or failed source state is dropped.

## Repair priority and cost

1. **#31: fix source-reading consistency before adding more data.** Rebuild new
   source-reconstruction examples from authenticated whole original annotations,
   or quarantine contradictions with an append-only reason. The private335-row
   proposal points back to immutable source/cache receipts; it changes no labels
   and promises no accuracy lift. Cost: bounded source joins and separately bound
   native candidate regeneration, without GPU training for this integrity fix.
2. **#33: test useful local context and ambiguity handling.** Bind real available
   session context, then compare a small fixed recipe on an unused research
   evaluation source. The information diagnostic justifies this hypothesis but
   does not justify adopting an eight-character length or a larger model. Cost:
   a bounded representation/ranking experiment after source isolation; no fit
   starts in this task.
3. **#32/#34: preserve source mix and actual input equality.** Keep source-stratum
   reporting and the projection/ancestry constraints from #65. Empty-context
   training inputs remain historically exposed; no giant component is split to
   obtain convenient folds. Cost: existing linear hash/group checks, followed by
   separately valid calibration before any gate threshold selection.
4. **#35: independently certify labels before claiming safety or final gain.**
   Source agreement and AI cannot supply the missing independent Gold guarantee.
   Calibration and one-use final Test remain separate. This dependency is still
   unresolved; the 1,000-case pilot and consumed research data cannot replace it.

## Verification and reproduction

The original plan/code commit is
`02ac7f1fd9c39411e7b148bcb16463c61d82349f`. Full-population extension and removal
of one unused import were committed before execution at
`247c8a791fb68e3375880c4d66449b62e08dd35f`. The first static check exposed that
unused import; it was removed rather than suppressed. The second iteration
replayed all original conflict results exactly.

The verifier uses independent sorted run-length counts for 16 literal/numeric
context populations and four union/stratum populations, plus separate explicit
tensor-hash serialization. It rechecks every raw/numeric row, source span and
hash-only group/row artifact. Original source parsing is reused and replayed;
this is direct engineering verification by Codex, not independent linguistic
review. Full regression: 821 tests (16 added), no failures, errors or skips.
Seven Python files pass syntax/unused-import checks. The original16 artifacts,
25 fit bindings and ten checkpoints retain their hashes.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:SAKURA_CONFLICT_ATTEMPT='attempt-02'
$python='C:/Users/developer/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe'
$commit='247c8a791fb68e3375880c4d66449b62e08dd35f'
& $python -B research/issue-31-conflict-source/run_owned.py audit --commit $commit
& $python -B research/issue-31-conflict-source/run_owned.py verify --commit $commit
& $python -B research/issue-31-conflict-source/run_owned.py tests
& $python -B research/issue-31-conflict-source/publish_conflicts.py
```

These are the executed commands, not permission to overwrite artifacts. A replay
needs a fresh bounded attempt reservation. The runner permits at most one child,
no retry and a1,800-second deadline with explicit completion/failure/timeout.
Private hash-only rows, groups, source receipts and proposed repairs are retained
under `data/generated/issue-31-conflict-source-v1/`; no corpus, dataset, model or
individual source identifiers are committed. Rubric, iteration history and
cleanup evidence are in `.codex/goal-loop/issue-31-conflict-source/`.

## Scope and architecture

Actual scope: source/cache provenance, fixed native-input encoding, original
paragraph/ruby recovery, descriptive conflict arithmetic and their tests. Five
analysis/ownership scripts plus one publisher and one contract-test file own the
new work. Production, model architecture, training and old source extractors are
unchanged. The full regression suite ran.

Scope expanded from conflict-selected source checks to all existing75,000 source
spans because the initial conditional count could otherwise be mistaken for a
quality rate. Relevant source contracts required reading more than the normal
small-Issue guide budget; following existing authenticated receipts avoided
loading the764MB original dictionary pool or re-scanning the Wikipedia dump.

The research audit owns all derived state. `conflict_metrics.py` owns empirical
counts and explicitly non-admitting notation observations; `source_evidence.py`
owns original-source authentication and extent checks. Existing input/source
APIs remain unchanged, and no production dependency is added. Future related
Issues can start with this report and the335-row repair ledger instead of
reconstructing the source joins. They must still understand that source reading,
semantic correctness, genuine session context and independent Gold are different
contracts. No reduction in required safety/evaluation evidence is claimed.
