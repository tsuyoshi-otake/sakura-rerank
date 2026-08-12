# Data boundary tooling

This package defines acquisition, deterministic source-span preprocessing,
provenance, Tier A assembly, and splitting. It never invokes Sakura Input or
trains a model. Tier A assembly consumes immutable external artifacts and does
not infer readings or candidates.

## Fixed snapshot manifest

`manifests/jawiki-snapshot.schema.json` describes a version-2 staged
manifest. The committed 2026-08-01 multistream manifest is currently
`official_metadata_verified`: the official byte size, MD5, and SHA-1 are
recorded while local path, retrieval time, and local SHA-256 remain null
because the full dump has not been downloaded. The exact date, artifact URL,
size, and official digests are pinned in both the schema and validator rather
than accepted as arbitrary well-formed values.

At `local_artifact_verified`, the Python validator requires a regular local
file below the caller-provided allowed root and independently checks byte
size, official MD5, official SHA-1, and local SHA-256. At
`preprocessing_verified`, extractor identity and preprocessing Git SHA also
become mandatory. Mutable `latest` text is rejected as a substring before
and after repeated URL decoding. The validator also requires the snapshot
date, official URL directory, file-name date, and exact
`pages_articles_multistream_xml_bz2` artifact kind to agree.

If upstream metadata cannot be confirmed, use the blocked-report shape shown in
`manifests/jawiki-snapshot.blocked.example.json`. A blocked report is useful
evidence, but it is never accepted as a verified manifest and contains no
invented snapshot values.

## Pinned artifact acquisition

The `jawiki-acquire` command accepts only the already reviewed fixed manifest
and a destination below its allowed root. It resumes exclusively from the
adjacent `.part` file, requires an exact HTTP `Content-Range` when resuming,
rejects redirects outside the pinned Wikimedia HTTPS host, bounds retries, and
honors bounded `Retry-After` values. The downloader reserves 512 MiB beyond the
remaining artifact size before starting.

Downloaded bytes become the final `.bz2` only after the official byte size,
MD5, and SHA-1 match. MD5, SHA-1, and the local SHA-256 are measured together in
one streaming pass. Only then is a `local_artifact_verified` manifest written
atomically. A complete existing artifact is revalidated without network access;
an invalid final artifact is never overwritten automatically. The dump,
resumable partial, and local manifest all remain under ignored local paths.

## JSONL contract

Each line is a version-3 `training_example` with source/page/revision
provenance, same-session Sakura Input committed left context, reading and gold
surface, converter candidate snapshots, split assignment, oracle result,
automatic Tier A verification, and a separately sampled human audit.
Candidate snapshots carry separate `training_top32` and `production_top6`
records. The latter must be the canonical prefix of the former, and each
snapshot has a content hash.

`training_top32.exporter_run` is a separate staged research-exporter contract.
It records an exporter Git SHA and/or binary SHA-256, requested limit, effective
converter bound, returned count, and whether a short search was exhausted or a
result was truncated. The pinned base Sakura Input HEAD is not an exporter
identity: its production converter/UI bound is 18. Commit F pins only the
measured Commit E Git-tree `06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1` with binary
SHA-256 `0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf`.
The validator also requires the exact patch, Cargo.lock, rustc/cargo, target,
profile, flags, environment, dictionary, Sakura Input HEAD, bound, and
user-dictionary state recorded in the verified manifest. Unverified measurement
artifacts remain outside the trusted dataset boundary.

Production records fail closed unless they identify Sakura Input HEAD
`8e966dff456e4e7165e025f97c1f73327ff3f550` and dictionary SHA-256
`6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad`.
They must also identify the pinned 2026-08-01 jawiki source and use
`sakura_converter_full_reading_nbest` provenance. A record marked
`is_fixture` instead has explicit `contract_fixture` provenance, null
production pins, fixture-only source categories, and can never be training
eligible.

Feature contract version 1 preserves converter-derived candidate rank,
surface, signed local cost, candidate fingerprint, optional system entry
index, candidate source category, and segment boundaries/IDs/flags/source
categories. Segment boundaries must be contiguous and cover the reading and
surface in UTF-8 bytes. Production values must come from the pinned converter;
the contract does not infer or fill them.

`tier_a_verification` contains deterministic checks such as normalized gold,
unique dictionary reading, forward-conversion match, and an explicit
converter-derived assertion that one exact dictionary path covers the complete
reading. Tier A and training also cross-check the gold candidate segments:
every segment must be `system_dictionary` or `user_dictionary`. Any reading,
katakana, generated-literal, or mixed-with-fallback gold path fails closed.
`sampled_human_audit` records only independently selected manual review.
They are intentionally separate: an automatic Tier A pass remains a pass when
the record was not sampled, while a sampled rejection fails closed. Training
also requires a gold label and at least two candidates, so fixture provenance,
missing gold, and singleton examples are rejected.

## Tier A assembly

The `tier-a` command joins three external, bounded inputs: jawiki source spans
bound to an allowlisted source-span manifest, an exact system
dictionary surface index bound to the pinned compiled dictionary SHA-256, and
allowlisted research top-32 snapshots. A source span contains no reading. The
reading comes only from an exact surface lookup with exactly one indexed
reading of 3--128 characters, then the forward converter output must contain
exactly one NFKC-equal gold candidate whose full path consists only of
`system_dictionary` segments.

Expected exclusions (missing/ambiguous dictionary evidence, missing snapshots,
reading mismatch, missing/ambiguous gold, fallback paths, and singleton
candidate sets) appear only as aggregate counts. Reports contain hashes and
counts, never raw text or stable IDs. If no row passes, or any prerequisite is
unverified, generation returns a structured blocker and publishes neither
artifact. Successful output and report use the same transactional pair writer
as the splitter.

The source-span manifest binds the local dump SHA-256, dictionary-index hash,
extractor Git SHA, cleaner version, every bound/sampling parameter, aggregate
counts, record count, and canonical JSONL hash. A measured result remains
blocked until the exact identity and all metadata are reproduced and
allowlisted. The trusted identity is extractor commit
`7cdb51f77875caab8be25683fc3bf174c0e91325` with 1,969 source spans and
content SHA-256
`f06b747dfa4ec1b650696cd04f156071acde8bf543b5ba9fe94f6146123275c9`.
No dump, extracted span, dictionary index, exporter JSONL, or generated dataset
is tracked by Git.

## Verified exporter requests

`exporter-requests` validates the allowlisted source-span and dictionary-index
manifests, then joins every source `gold_surface` to exactly one indexed system
dictionary reading. A missing or ambiguous reading rejects the complete batch;
readings outside 3--128 characters are also rejected before publication. The
command never guesses, normalizes, or partially publishes readings. Output
contains exactly `stable_id` and `reading`, sorted by stable ID and bounded to
the research exporter's 4,096-record input limit.

The paired report follows
`manifests/research-exporter-request-report.schema.json`. It binds the builder,
source extractor, dictionary indexer, jawiki artifact, Sakura Input, dictionary,
and request hashes. Its schema is closed and contains no reading, surface, or
stable ID. Output and report use the transactional pair writer. The measured
verified batch and double-export result are pinned in
`manifests/jawiki-research-top32-snapshot-verified.json`; generated JSONL and
reports remain ignored.

For batches larger than 4,096 records, `exporter-request-shards` preserves one
global stable-ID order and publishes a new immutable directory containing
bounded `requests-NNNNN.jsonl` files plus a closed, aggregate-only manifest.
Every shard and the concatenated logical request stream have independent
SHA-256 identities. Existing destinations are rejected, all staged files are
flushed before the directory rename, and a failed rename removes the complete
staging directory. The closed manifest shape is documented in
`manifests/research-exporter-request-shards.schema.json`.

After the isolated exporter has produced matching `output-NNNNN.jsonl` and
`report-NNNNN.json` files, `tier-a-shards` validates every result against the
trusted exporter manifest, requires exact request/output stable-ID equality,
recomputes every per-shard report, and requires global sorted uniqueness before
Tier A assembly. Unexpected files, missing shards, and aggregate mismatches fail
closed.

`scripts/run_research_top32_shards.ps1` invokes the trusted binary once per
canonical request shard with a bounded timeout. It captures no exporter output
in the final directory, kills the owned process on timeout, removes the entire
staging directory on any failure, and renames the directory only after every
shard completes. Invoke it twice with different destinations and compare every
file hash before treating a large export as deterministic evidence.

Exporter `result_status` describes the search terminal, not the returned list
length. `truncated` means the candidate limit or bounded search-state budget was
reached before search exhaustion; path consolidation can therefore leave fewer
than 32 returned candidates. Validation still requires an allowed terminal,
exact `returned_count`, the bound 32, and a trusted exporter identity.

## Provenance-aware audit gate

`human-audit queue` selects every final-holdout record and fills any remaining
minimum sample by deterministic round-robin sampling across reading-length,
candidate-count, and local-correctness strata. The review queue intentionally
contains the bounded text needed by a reviewer; its paired manifest contains
only counts, configuration, and hashes. Review responses use a closed verdict
schema and require a reviewer identity, a `human` or `ai_teacher` reviewer kind,
and a timezone-qualified timestamp. AI teacher evidence can be accepted only by
the explicit owner-policy switch and never sets `gate_a_human_audit_pass`.
The aggregate queue manifest and response record shapes are documented in
`manifests/human-audit-queue-manifest.schema.json` and
`manifests/human-audit-response.schema.json`.

`human-audit report` counts only supplied reviews. Gate A passes only when at
least 1,000 labels are complete, at least 3,000 valid final-holdout labels exist,
point precision is at least 99.5%, and the two-sided 95% Wilson lower bound is at
least 99.0%. `human-audit apply` excludes rejected rows, marks unanswered
selected rows pending and ineligible, and accepts only explicitly valid human
responses. AI teacher responses remain separate quality evidence and cannot be
written into the `sampled_human_audit` field. The command never invents or
relabels responses; output and aggregate report are published as one
transaction. `--allow-ai-teacher` reports a distinct
`gate_a_owner_authorized_audit_pass` while preserving the human-gate result.

`human-audit serve` runs a dependency-free reviewer on `127.0.0.1` only. A
random token in the printed URL protects every API call; the server suppresses
request logs, sends a restrictive content-security policy, and never transmits
queue text outside the loopback connection. Review order is a deterministic
SHA-256 permutation of the queue seed. Each explicit verdict atomically rewrites
the canonical response JSONL, an existing response can never be overwritten,
and restarting with the same response path resumes at the next pending item.

## Deterministic jawiki source spans

`jawiki-preprocess` streams the pinned bzip2 XML with `iterparse`; it never
writes raw XML or an intermediate article corpus. It accepts namespace-zero,
non-redirect pages with numeric page and revision identities. The versioned
conservative cleaner removes balanced templates, tables, references, supported
links and tags, and rejects paragraphs with ambiguous or residual markup.
Cleaner v2 keeps physical source lines separate and rejects dictionary matches
that cut through ASCII/kana tokens or occur inside kana reading annotations.
Cleaner v3 additionally removes colon-prefixed media namespace links, rejects
residual emphasis/media namespace text, and indexes only exact single-reading
surfaces whose reading has 3--128 characters.

The current matcher indexes only system-dictionary surfaces that have exactly
one in-range reading. Manifest schema v2 pins both reading bounds; historical
schema-v1 cleaner-v1/v2 manifests remain verifiable without being normalized to
the current schema. Exporter request and non-fixture training validation repeat
the same bound independently. Two-character prefix buckets and descending surface lengths select the
longest non-overlapping exact match without materializing article-by-dictionary
pairs. Hash sampling and per-page/global record bounds are deterministic. The
canonical JSONL and text-free manifest are staged and committed as one
transaction; a failed second replacement restores the prior pair.

## Exact dictionary index

The `dictionary-index` command rebuilds the complete surface-to-readings index
from the 14 category TSVs recorded by the pinned current-state audit. Before
parsing, it requires the exact audit SHA-256, pinned Sakura Input HEAD, compiled
dictionary SHA-256, successful dictionary audit checks, and each category
file's name, byte size, SHA-256, and entry count. Each verified file is read
once into a bounded byte buffer, so indexing cannot parse bytes different from
the bytes it hashed.

Aggregation is expected O(N) over source entries, followed by deterministic
sorting of surfaces and each surface's unique readings. The canonical index and
its manifest are published as one transaction. The manifest records the audit,
category-source aggregate, indexer Git SHA, 472,825 source entries, 368,341
surfaces, and index content hash. The generated 47 MB JSONL remains outside
Git. A measured manifest does not become trusted Tier A evidence until its
indexer/output identity is reproduced and pinned separately. The trusted
identity is currently indexer commit
`227ffe8a6b0b515c7f3cdf504b3d98b313360e53` with index SHA-256
`4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072`.
Tier A also requires every measured audit hash, category aggregate, and source
count to match that identity; changing only provenance metadata fails closed.

## Deterministic split

`assign_splits` unions records by article, exact paragraph hash, near-sentence
character-shingle similarity, and non-null template cluster. Identical shingle
signatures are collapsed first and unioned as a star; the implementation never
materializes the quadratic set of record-pair edges. A regression fixture with
10,000 identical signatures therefore performs bounded work.

Distinct signatures use an exact set-similarity join: a Jaccard length filter
and prefixes ordered by global shingle rarity produce candidates, then exact
Jaccard decides every union. This PPJoin/AllPairs-style filter has no LSH false
negatives. A 10,000-signature regression sharing only one globally frequent
shingle performs no quadratic candidate expansion. Leakage-report version 3
names the algorithm, reports total unique-signature pairs separately, and
defines `sentence_signature_comparison_count` as the number of exact Jaccard
checks after both filters.

Existing split assignments are immutable; conflicting assignments fail
closed. New components are assigned by a SHA-256 ordering of the seed and
stable component ID, so the same input and seed produce byte-identical
canonical JSONL. The version-3 leakage report includes zero cross-split counts
and separate canonical SHA-256 values for `train`, `dev`, and
`final-holdout`.

The splitter consumes only sentence shingle hashes after preprocessing. It
does not copy raw sentence text into its report.

## CLI examples

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m sakura_rerank.data manifest validate `
  manifests\jawiki-20260801-pages-articles-multistream.json --allowed-root .

python -m sakura_rerank.data jawiki-acquire `
  manifests\jawiki-20260801-pages-articles-multistream.json `
  --allowed-root . `
  --output data\downloads\jawiki-20260801-pages-articles-multistream.xml.bz2 `
  --local-manifest data\generated\jawiki-20260801-local-manifest.json

python -m sakura_rerank.data contract validate `
  tests\fixtures\data-contract.fixture.jsonl

python -m sakura_rerank.data dictionary-index `
  <audited-category-directory> data\generated\system-dictionary-index.jsonl `
  --audit-report reports\current-state-audit.json `
  --manifest data\generated\system-dictionary-index-manifest.json `
  --indexer-git-sha <exact-sakura-rerank-git-sha>

python -m sakura_rerank.data jawiki-preprocess `
  data\downloads\jawiki-20260801-pages-articles-multistream.xml.bz2 `
  data\generated\source-spans.jsonl `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --allowed-root . `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest manifests\system-dictionary-index-verified.json `
  --report data\generated\source-spans-measured.json `
  --extractor-git-sha <exact-sakura-rerank-git-sha> `
  --min-reading-chars 3 --max-reading-chars 128

python -m sakura_rerank.data exporter-requests `
  data\generated\source-spans.jsonl `
  data\generated\top32-requests.jsonl `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest manifests\system-dictionary-index-verified.json `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --source-span-manifest manifests\jawiki-tier-a-source-spans-verified.json `
  --allowed-root . `
  --report data\generated\top32-requests.report.json `
  --builder-git-sha a39d9e460ae6f28b73b4dee16fafcbb69e83ed45

python -m sakura_rerank.data exporter-request-shards `
  data\generated\source-spans-expanded-v3.jsonl `
  data\generated\top32-request-shards `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest manifests\system-dictionary-index-verified.json `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --source-span-manifest manifests\jawiki-tier-a-source-spans-expanded-v3-verified.json `
  --allowed-root . --builder-git-sha <exact-sakura-rerank-git-sha>

pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\run_research_top32_shards.ps1 `
  -ExporterBinary <trusted-exporter.exe> `
  -DictionaryPath <pinned-system.dic> `
  -IdentityManifest <generated-verified-identity.json> `
  -RequestDirectory data\generated\top32-request-shards `
  -OutputDirectory data\generated\top32-output-shards

python -m sakura_rerank.data tier-a `
  data\generated\source-spans.jsonl data\generated\top32.jsonl `
  data\generated\tier-a.jsonl `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest data\generated\system-dictionary-index-manifest.json `
  --exporter-manifest manifests\research-exporter-verified.json `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --source-span-manifest manifests\jawiki-tier-a-source-spans-verified.json `
  --allowed-root data --report reports\tier-a-generation.json

python -m sakura_rerank.data tier-a-shards `
  data\generated\source-spans-expanded-v3.jsonl `
  data\generated\top32-request-shards `
  data\generated\top32-output-shards `
  data\generated\tier-a-expanded.jsonl `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest manifests\system-dictionary-index-verified.json `
  --exporter-manifest manifests\research-exporter-verified.json `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --source-span-manifest manifests\jawiki-tier-a-source-spans-expanded-v3-verified.json `
  --allowed-root . --report data\generated\tier-a-expanded.report.json

# An input JSONL file has the same contract fields with `split: null`.
python -m sakura_rerank.data split `
  data\generated\examples.jsonl data\splits\examples.jsonl `
  --seed 20260811 --report reports\split-report.json `
  --train-ratio 0.75 --dev-ratio 0.10 --final-holdout-ratio 0.15

python -m sakura_rerank.data human-audit queue `
  data\splits\examples.jsonl data\generated\human-audit-queue.jsonl `
  --manifest data\generated\human-audit-queue.manifest.json `
  --seed 20260812 --minimum-sample-size 1000

python -m sakura_rerank.data human-audit serve `
  data\generated\human-audit-queue.jsonl `
  data\generated\human-audit-responses.jsonl `
  --queue-manifest data\generated\human-audit-queue.manifest.json `
  --reviewer-id <reviewer-id> --reviewer-kind <human-or-ai_teacher> --port 8765

python -m sakura_rerank.data human-audit report `
  data\generated\human-audit-queue.jsonl <review-responses.jsonl> `
  reports\human-audit-quality.json `
  --queue-manifest data\generated\human-audit-queue.manifest.json
```

## Corpus v4 teacher cascade

`corpus-v4` is the fail-closed, resumable Stage 0--3 boundary for Issue #15.
It binds Stage 1 to `gpt-5.6-sol-screen-20260812` and Stage 2 to
`gpt-5.6-sol-adjudicate-20260812`, both with `reviewer_kind=ai_teacher`.
Teacher batches contain review text and therefore stay under ignored `data/`;
manifests, status output, partition reports, and issue evidence are aggregate
only.

Validate all immutable v3 inputs before publishing a queue:

```powershell
python -m sakura_rerank.data corpus-v4 preflight `
  data\splits\tier-a-expanded-v3-a.jsonl `
  --source-spans data\generated\source-spans-expanded-v3-a.jsonl `
  --source-span-manifest manifests\jawiki-tier-a-source-spans-expanded-v3-verified.json `
  --jawiki-manifest data\generated\jawiki-20260801-local-manifest.json `
  --dictionary-index data\generated\system-dictionary-index.jsonl `
  --dictionary-manifest manifests\system-dictionary-index-verified.json `
  --exporter-manifest manifests\research-exporter-verified.json `
  --v3-audit-queue data\generated\tier-a-expanded-v3-a-audit-queue.jsonl `
  --v3-audit-manifest data\generated\tier-a-expanded-v3-a-audit-queue.manifest.json `
  --v3-audit-responses data\generated\tier-a-expanded-v3-a-audit-responses.jsonl `
  --handoff-directory data\generated\v4-handoff --allowed-root .

python -m sakura_rerank.data corpus-v4 stage0-analyze `
  data\splits\tier-a-expanded-v3-a.jsonl `
  data\generated\v4-stage0-analysis.json `
  --dev-batches data\generated\v4-handoff\dev-batches `
  --sol-verdicts data\generated\v4-handoff\dev-verdicts-sol

python -m sakura_rerank.data corpus-v4 stage1-queue `
  data\splits\tier-a-expanded-v3-a.jsonl `
  data\generated\v4-screening

python -m sakura_rerank.data corpus-v4 verdict-status `
  data\generated\v4-screening data\generated\v4-screening-verdicts

python -m sakura_rerank.data corpus-v4 stage2-queue `
  data\generated\v4-screening data\generated\v4-screening-verdicts `
  data\generated\v4-adjudication
```

Each queue directory is published by one same-parent rename and becomes
immutable. A verdict directory may be absent or incomplete for resume, but
every present file must match the exact batch order, six-value enum, 200-character
note limit, stage, reviewer kind, and reviewer ID. Malformed or foreign files
stop the cascade instead of being skipped.

After both passes are complete, `corpus-v4 partition` applies the owner-approved
precision-first policy. Two-pass non-valid rows and independent hard exclusions
are excluded; ambiguous rows and Stage-1-nonvalid/Stage-2-valid recoveries are
quarantined; only the remaining rows are retained. It publishes disjoint bucket
files plus the canonical Stage 4 exclusion union. `corpus-v4 calibration-queue`
then publishes every
handoff teacher disagreement plus exactly 100 fixed-seed one-pass-only rows in
the standard `human-audit serve` queue format. It never creates owner responses
or writes `sampled_human_audit`.

Stage 4 remains owner-gated. After the owner completes calibration and fixes the
policy, pass the partition's canonical `stage4-stable-id-exclusion.jsonl` to
`jawiki-preprocess --stable-id-exclusion`. A schema-v3/v4 source-span manifest
is measured only until an A/B reproduction identity is explicitly allowlisted.
This cascade does not run a new final-holdout Gate A audit.

The manifest command returns status 3 for a structured blocker. The split
command rejects any normalized or filesystem-alias collision among input,
output, and report before writing. Output and report payloads are fully staged
in same-directory temporary files before either is committed. A pre-commit
failure changes neither target; a failed second replacement restores the prior
pair from backups, and every path removes temporary/backup residue. The CLI and
`split_jsonl` use this same transactional publisher. The split and contract
commands write only
bounded metadata and content hashes; downloaded dumps, extracted text,
generated datasets, models, and checkpoints stay under the ignored artifact
paths in `.gitignore`.
