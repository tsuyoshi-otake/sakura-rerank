# Data boundary tooling

This package defines the provenance and split boundary for Issue #1. It does
not download jawiki, extract articles, invoke Sakura Input, generate training
examples, or train a model.

## Fixed snapshot manifest

`manifests/jawiki-snapshot.schema.json` describes a verified manifest. The
Python validator additionally checks that the local file exists below the
caller-provided allowed root and that its byte size and SHA-256 match both
recorded digests. Mutable `latest` aliases, non-official URLs, missing
provenance, placeholders, and unsafe paths are rejected.

If upstream metadata cannot be confirmed, use the blocked-report shape shown in
`manifests/jawiki-snapshot.blocked.example.json`. A blocked report is useful
evidence, but it is never accepted as a verified manifest and contains no
invented snapshot values.

## JSONL contract

Each line is a version-1 `training_example` with source/page/revision
provenance, same-session Sakura Input committed left context, reading and gold
surface, a converter candidate snapshot, split assignment, oracle result, and
human-audit flags. Candidate snapshots carry separate `training_top32` and
`production_top6` records. The latter must be the canonical prefix of the
former, and each snapshot has a content hash.

Production records must identify the fixed Sakura Input HEAD and dictionary,
use `sakura_converter_full_reading_nbest` provenance, and preserve every
candidate source category. A record marked `is_fixture` must instead use the
explicit fixture provenance and can never be training eligible. This keeps
contract fixtures from masquerading as converter output.

Tier A requires an accepted human audit, a unique dictionary reading, a
forward-conversion match, and a noise-free label. The validator never infers
readings, surfaces, costs, or labels.

## Deterministic split

`assign_splits` unions records by article, exact paragraph hash, near-sentence
character-shingle similarity, and non-null template cluster. Existing split
assignments are immutable; conflicting assignments fail closed. New components
are assigned by a SHA-256 ordering of the seed and stable component ID, so the
same input and seed produce byte-identical canonical JSONL and a leakage report
with zero cross-split counts.

The splitter consumes only sentence shingle hashes after preprocessing. It
does not copy raw sentence text into its report.

## CLI examples

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m sakura_rerank.data manifest validate `
  tests\fixtures\jawiki-manifest.blocked.json --allowed-root tests\fixtures

python -m sakura_rerank.data contract validate `
  tests\fixtures\data-contract.fixture.jsonl

# An input JSONL file has the same contract fields with `split: null`.
python -m sakura_rerank.data split `
  data\generated\examples.jsonl data\splits\examples.jsonl `
  --seed 20260811 --report reports\split-report.json
```

The manifest command returns status 3 for a structured blocker. The split and
contract commands write only bounded metadata and content hashes; downloaded
dumps, extracted text, generated datasets, models, and checkpoints stay under
the ignored artifact paths in `.gitignore`.
