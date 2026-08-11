# Data boundary tooling

This package defines the provenance and split boundary for Issue #1. It does
not download jawiki, extract articles, invoke Sakura Input, generate training
examples, or train a model.

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

## JSONL contract

Each line is a version-2 `training_example` with source/page/revision
provenance, same-session Sakura Input committed left context, reading and gold
surface, converter candidate snapshots, split assignment, oracle result,
automatic Tier A verification, and a separately sampled human audit.
Candidate snapshots carry separate `training_top32` and `production_top6`
records. The latter must be the canonical prefix of the former, and each
snapshot has a content hash.

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
unique dictionary reading, and forward-conversion match.
`sampled_human_audit` records only independently selected manual review.
They are intentionally separate: an automatic Tier A pass remains a pass when
the record was not sampled, while a sampled rejection fails closed. Training
also requires a gold label and at least two candidates, so fixture provenance,
missing gold, and singleton examples are rejected.

## Deterministic split

`assign_splits` unions records by article, exact paragraph hash, near-sentence
character-shingle similarity, and non-null template cluster. Identical shingle
signatures are collapsed first and unioned as a star; the implementation never
materializes the quadratic set of record-pair edges. A regression fixture with
10,000 identical signatures therefore performs bounded work.

Existing split assignments are immutable; conflicting assignments fail
closed. New components are assigned by a SHA-256 ordering of the seed and
stable component ID, so the same input and seed produce byte-identical
canonical JSONL. The version-2 leakage report includes zero cross-split counts
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

python -m sakura_rerank.data contract validate `
  tests\fixtures\data-contract.fixture.jsonl

# An input JSONL file has the same contract fields with `split: null`.
python -m sakura_rerank.data split `
  data\generated\examples.jsonl data\splits\examples.jsonl `
  --seed 20260811 --report reports\split-report.json
```

The manifest command returns status 3 for a structured blocker. The split
command rejects any normalized or filesystem-alias collision among input,
output, and report before writing. The split and contract commands write only
bounded metadata and content hashes; downloaded dumps, extracted text,
generated datasets, models, and checkpoints stay under the ignored artifact
paths in `.gitignore`.
