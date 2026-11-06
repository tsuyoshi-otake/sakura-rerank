# Source-screened research recipe — Issue #31

The new bound recipe excludes **915 source-conflicting or uncertain rows** from
the dictionary training arm, retaining **49,085 / 50,000**. The annotation arm
retains **all 50,000**. Source preparation now connects to exact numeric-cache
positions while preserving the separately stored training presentation order.

This is an enforceable input-selection improvement, not measured model accuracy
or Gold certification. Adopted accuracy remains 90.72%. Repeating the annotation
fit with only this source screen would not change its data; such a fit is not
justified by this result. No new training or model evaluation occurred.

The [aggregate report](../../reports/issue-31-source-recipe-v1.json) retains the
complete original denominators and both failed attempts. The successful recipe
is private, immutable and explicitly restricted to preparing a separate fit binding.

## Measured selection

| Existing arm | Original rows | Selected rows | Excluded rows | Selected original-annotation / dictionary-only weak rows |
|---|---:|---:|---:|---:|
| Dictionary | 50,000 | 49,085 | 915 | 567 / 48,518 |
| Annotation | 50,000 | 50,000 | 0 | 25,000 / 25,000 |

The arms share 25,000 Wikipedia rows. Their union contains 75,000 original row
identities and 74,085 selected identities; the sum of selected arm positions is
99,085. These are not independent statistical observations. Original source
components, numeric-input hashes and all excluded history remain attached.

Exclusions are 335 exact reading conflicts, 567 annotation-scope uncertainties,
11 parse uncertainties and two nonphonetic/out-of-bound annotation cases. No
reading, surface, source extent, label, candidate, feature or original split was
rewritten. The [source gate](../issue-31-reading-consistency/README.md) remains the
owner of those evidence states; the recipe does not reassess them by model score.

Extraction arm and evidence tier are different properties. A dictionary-extracted
row can have an exact original-annotation match; 567 such rows remain in that arm.
Conversely, half of the annotation arm is still dictionary-only Wikipedia weak
supervision. Neither an arm name nor original-source agreement certifies intended
Japanese conversion.

The consumed cache already requires a literal Top-6 label, valid active candidates
and full numeric verification. It is not an unfiltered corpus: candidate absence
cannot be estimated from this selected cache. The new recipe does not repair the
335 readings or admit the previously diagnosed source-extent alternatives.

| Training composition only | Original source Top-1 matches | Selected source Top-1 matches | Excluded source Top-1 matches |
|---|---:|---:|---:|
| Dictionary | 40,132 / 50,000 | 39,655 / 49,085 | 477 / 915 |
| Annotation | 34,186 / 50,000 | 34,186 / 50,000 | 0 / 0 |

These counts describe which training examples remain, not an accuracy improvement.
Filtering changes the dictionary arm's source and baseline-correctness composition.
A later comparison must report that change and retain a fixed evaluation denominator.

## Three ordering contracts and one limited consumer

`source_research_recipe.build_recipe` requires the authenticated source pool,
complete original cohort, numeric receipts/manifest and **original per-arm indices**.
It joins source decisions by the complete encoder-input hash and verifies original
source, component, cohort and receipt-chain identities. No positional source join
or guessed pronunciation is used.

Source preparation order, global numeric row order and per-arm presentation order
are separate contracts. All 75,000 diagnostic rows remain in numeric order. Each
arm retains its own old presentation order with ineligible indices removed; it is
not sorted or reconstructed from global row positions. The reader externally pins
the canonical arm-order hash alongside the source and numeric artifact identities.

The default policy excludes dictionary-only weak evidence. This recorded recipe
explicitly allows the existing weak tier, while every conflict/uncertainty stays
excluded. That allowance does not bypass a source conflict or upgrade a label.

`load_recipe` accepts only `fit_binding_preparation` and the exact externally pinned
recipe hash/bindings. It recomputes membership, order, tier selection and census.
Training, Gold, calibration and Test purposes are rejected. The original cache and
pool retain their existing unadmitted flags. A fresh isolated research evaluation
reservation and separate committed fit binding remain necessary before any fit.

## Preserved failures and verification

The first frozen application at `62de972858d53dd61478eb5f710a2614bec440ce` stopped
before publication: the cohort uses `original_ruby_annotation`, while the source
pool uses `original_ruby`. All 75,000 original-row hashes and admission flags
agreed; only the documented enum names differed in 25,000 rows. The correction
adds that exact correspondence and rejects undocumented aliases. The fixture now
uses the real producer vocabulary; no normalization or weakened hash check was added.

The second application at `fded441fc311c235d53e92440f4f839352d132eb` also stopped
before publication. Both arm membership sets were correct, but deriving the
dictionary arm from global numeric order changed 34,158 positions. The structural
fix makes per-arm order an explicit API input and consumer binding, with
nonascending fixtures and tampering tests. Both failed plans, logs and terminal
receipts remain intact. No trusted recipe was published by either failure.

Plan v3 and code were committed at `4ec11bfe5990b67e5b7b6fa57621937b4e53e089`
before attempt-03. The plan pins 15 input artifacts and 65 loaded/relevant code
files, including prior failure evidence. Source eligibility, thresholds and the
75,000-row population did not change between attempts.

All **941 tests pass**, including 30 recipe contracts, with zero failures/errors/
skips (19.095 seconds). Six authored Python files pass syntax/unused-import checks.
Direct verification independently derives tiers from original reading-evidence
states and filters the original arm-order artifacts. It matches all 75,000 recipe
rows, rechecks 75,000 numeric tensor rows, all 100,000 original arm positions and
99,085 selected positions, and independently recounts source/baseline distributions.
Forbidden data reads are zero. This is Codex engineering verification, not human
or independent linguistic review.

The original 16 artifacts, 25 fit bindings and ten checkpoints retain their hashes.
The clean Sakura Input HEAD remains `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`.
No production code or current-runtime equivalence claim is introduced. Eighteen
recorded stage/diagnostic PIDs exited, no matching repository runner remains, and
the dedicated task TEMP was deleted.

Preparation took 13.832 seconds and verification 11.750 seconds (14.399 / 12.299
including their owners). Each stage owns one child with a 1,800-second limit and
an explicit terminal/termination record. Executed stages are write-once. Failed
attempts are retained and are never resumed or overwritten as if they had succeeded.

Recorded commands use the existing verified research venv and owned TEMP under
`~/tmp/`; no package installation is needed:

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:SAKURA_RECIPE_ATTEMPT='attempt-03'
$commit='4ec11bfe5990b67e5b7b6fa57621937b4e53e089'
python -B research/issue-31-source-recipe/run_owned.py prepare --commit $commit
python -B research/issue-31-source-recipe/run_owned.py verify --commit $commit
python -B research/issue-31-source-recipe/run_owned.py tests
python -B research/issue-31-source-recipe/publish_results.py
```

These commands do not overwrite an existing attempt or report. Another execution
needs a fresh explicit attempt and separately versioned publication. Recovery
evidence remains under `data/generated/issue-31-source-recipe-v1/` (31 files,
52,834,960 bytes, including all three attempts). Rubric, diagnoses, process and
cleanup evidence is in `.codex/goal-loop/issue-31-source-recipe/`.

## Next decision, expected benefit and cost

1. Preserve this recipe as the source-screened dictionary-arm candidate. Its
   measured effect is exclusion of 915 unsupported/uncertain source rows, not a
   quantified accuracy gain. The existing annotation arm is an unchanged control.
2. Secure a fresh research evaluation source before fitting. The previously fixed
   KWDLC public-train reservation is exhausted; old research evaluations and public
   dev/test are not substitutes for an unused cohort. Verify reading provenance,
   usage conditions and full source/input/history isolation before freezing any
   new comparison. This is also the next critical step toward independent Gold;
   a new source alone does not certify the Gold quality requirements.
3. After that prerequisite, bind one dictionary-data-screening comparison with
   fixed initialization, structure, loss, seeds and compute budget. Preserve all
   failures and the evaluation denominator. Recipe replay costs approximately
   14 seconds per source/cache pass here; the fit/evaluation budget must be fixed
   before that experiment, not inferred from these preparation timings.

No model fit/inference, new native request, original-label overwrite, threshold
selection, human/AI linguistic review, Gold admission, calibration, final Test or
production change occurred. Safety remains 0.25%. Gold still requires point quality
99.5%, Wilson 95% lower bound 99.0% and at least 3,000 valid final rows. Gates A/B,
independent Gold and release remain incomplete.

## Scope, ownership and future reading

Actual scope is one 193-line recipe module, its 183-line contract tests, four
research scripts, frozen plans and aggregate/documentation updates. Scope expanded
to the two producer vocabularies and numeric arm-order contract because string
equality and membership alone did not preserve the actual source/training contract.

The existing source gate owns source evidence; the existing numeric artifacts own
global row identity and per-arm order. The new recipe owns source-tier selection
and its complete immutable decision ledger. The recipe module depends on canonical
hashing, not model internals; the research adapter reuses authenticated source and
numeric readers. Production/model architecture and original data remain unchanged.

Future fits can consume the bounded recipe API and index/binding contract without
reopening source parsing or native generation. They must still understand the
three orders, inherited exposure history, synthetic source context, weak-label
scope and the separate fit/evaluation authorization. One verified memory rule
records the producer-vocabulary and presentation-order boundary.
