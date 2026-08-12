# Sakura Rerank

Sakura Rerank is the reproducible research and tooling repository for a
context-aware, ultra-low-latency reranker for
[Sakura Input](https://github.com/tsuyoshi-otake/sakura-input).

The project reranks bounded N-best full-path candidates produced by Sakura
Input. It does **not** replace the dictionary, lattice, Viterbi search, or
candidate generator.

## Status

The repository has completed the current-HEAD audit, current Tiny baseline
reproduction, deterministic data contracts, fixed jawiki acquisition, and a
reproducible research-only top-32 exporter. The first expanded Tier A snapshot
retained 33,553 of 40,703 source rows, assigned 5,033 rows to the final holdout
with zero measured cross-split leakage, and measured Oracle Recall@6 at 99.064%.

Gate A is still pending. At the owner's direction, Codex inspected the first 120
queue rows as an explicitly identified `ai_teacher`: 115 were valid and five
were rejected (95.83% point precision, 90.62% Wilson lower bound). This is not
reported as human review and fails the quality thresholds. Cleaner v2 rejects
the observed unsafe source boundaries and has now reproduced 30,003 corrected
source spans twice with byte-identical output and report pairs. Its downstream
candidate snapshot and teacher queue must still be regenerated before model
training. The queue, aggregate
evidence, and remaining quality gate are tracked in
[Issue #15](https://github.com/tsuyoshi-otake/sakura-rerank/issues/15) and
[`reports/issue-15-tier-a-pre-review.json`](reports/issue-15-tier-a-pre-review.json).
The first teacher-audit result is recorded in
[`reports/issue-15-tier-a-teacher-audit-120.json`](reports/issue-15-tier-a-teacher-audit-120.json).
Reviewers can use the loopback-only `human-audit serve` interface documented in
[`src/sakura_rerank/data/README.md`](src/sakura_rerank/data/README.md); every
click is atomically persisted and resumable without sending queue text to an
external service.
No Gate B result or production default is approved, and a trained
Sakura-Rerank-Tiny-v1 model has not yet been selected or exported.

The evidence and decision are recorded in
[`research/current-state-review.md`](research/current-state-review.md) and
[`research/current-tiny-baseline.md`](research/current-tiny-baseline.md).
Production protocol or integration changes must wait until independently
reviewed data satisfies the relevant quality gates.

## Intended production boundary

- Production inference runs on Windows CPU only.
- GPU and Python are training, export, and research dependencies only; they do
  not enter the Sakura Input production Cargo workspace.
- The existing dictionary/lattice/Viterbi/N-best pipeline remains authoritative
  for candidate generation.
- Neural output is a bounded residual over normalized local candidate costs.
- The hot key path never waits for a worker.
- Late, stale, malformed, unavailable, or failed results preserve local order.
- Password, URL, email, digits, unknown, and test-only scopes are excluded.
- Explicit learning, exact cache hits, and user-dictionary priority are kept.
- Only left context committed by Sakura Input in the same session may be used;
  host-document and right/future context are forbidden.
- Raw user input is never logged.

## Planned layout

| Path | Purpose |
| --- | --- |
| `research/` | Current-state review, experiment design, and decision reports |
| `manifests/` | Immutable source, dataset, tokenizer, model, and environment metadata |
| `src/` | Dataset, model, evaluation, export, and benchmark implementation |
| `tests/` | Unit, parity, leakage, safety, and reproducibility tests |
| `reports/` | Reviewable summarized results without raw user text or large artifacts |

Downloaded Wikipedia dumps, extracted text, generated datasets, checkpoints,
ONNX models, and runtime binaries are intentionally excluded from Git. Their
exact hashes and provenance belong in tracked manifests.

## Research sequence

1. Inspect the current Sakura Input HEAD and reproduce the current Tiny system.
2. Freeze dictionary, Wikipedia, tokenizer, candidate snapshot, and split
   manifests.
3. Build and audit high-confidence Tier A examples from actual full-reading
   Sakura converter N-best paths.
4. Compare equal-budget GRU, minGRU, and Tiny Transformer students on identical
   snapshots and CPU benchmark conditions.
5. Consider protocol v2 and opt-in production integration only after the data,
   quality, safety, and resource gates pass.

The target and verification rubric are maintained in Issue #1. Adoption is
based on the measured accuracy/latency Pareto frontier, not architecture novelty.

## Data contract boundary

The current data boundary includes fixed-source manifest validation, versioned
JSONL contracts, deterministic source-span and exporter-request generation,
verified top-32 export, Tier A assembly, and leakage-safe splitting. The
standard-library tooling and CLI are documented in
[`src/sakura_rerank/data/README.md`](src/sakura_rerank/data/README.md). It does
not train a model or alter Sakura Input. The acquisition command may download
only the pinned jawiki artifact, and converter invocation remains isolated in
the separately built research exporter. The next data step is Tier A assembly
and audit from the immutable verified snapshot; the snapshot itself is not Gate
A/B evidence.

## Verified top-32 snapshot

[`manifests/jawiki-research-top32-snapshot-verified.json`](manifests/jawiki-research-top32-snapshot-verified.json)
binds the complete aggregate-only result. The verified 2026-08-01 source batch
contains 1,969 records. Its canonical exporter request SHA-256 is
`aed057119b2ba07b0d028b9e9040192cd132b93f7129ff1809261852b830a9b7`.
Two runs of the trusted exporter produced byte-identical 35,414-candidate
snapshots with SHA-256
`82bbea56bb1305f335799188a39c829a0aff52825d069744912cb9faa7bdee2d`.
The Python contract validator independently accepted both results.

Generate the bounded request batch from verified local artifacts:

```powershell
$env:PYTHONPATH = "src"
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
```

Build and run the exporter only from the exact clean revisions and dictionary
described in
[`research/exporter/README.md`](research/exporter/README.md). Validate its output
before Tier A assembly:

```powershell
$env:PYTHONPATH = "src"
python -m sakura_rerank.data contract exporter-validate `
  data\generated\top32.jsonl `
  --manifest manifests\research-exporter-verified.json
```

The dump, extracted spans, dictionary index, request JSONL, exporter output,
reports, dictionary image, and exporter binary remain ignored local artifacts.
Only text-free identities, counts, and hashes are tracked.

## Current-state audit

The first audit command uses only the Python 3.11 standard library. Run it from
an isolated environment outside this repository and pin the expected Sakura
Input revision:

```powershell
$env:PYTHONPATH = "src"
& "$env:USERPROFILE\tmp\sakura-rerank-audit-venv\Scripts\python.exe" `
  -m sakura_rerank.audit `
  --sakura-input-root ..\sakura-input `
  --expect-head <exact-sakura-input-sha> `
  --output reports\current-state-audit.json
```

The command is read-only with respect to Sakura Input. It records the dirty
state separately, hashes source and release artifacts, validates the compiled
dictionary header and manifests, counts entries/readings/surfaces from the
canonical category exports, and records corpus sizes without copying row text.

The released Tiny worker can then be measured through its exact protocol v1
stdio boundary. The default is the required 10,000 warm requests, split across
fixed 8-, 16-, and 32-character synthetic workloads; no candidate text is
written to the report:

```powershell
$env:PYTHONPATH = "src"
& "$env:USERPROFILE\tmp\sakura-rerank-audit-venv\Scripts\python.exe" `
  -m sakura_rerank.current_tiny_benchmark `
  --worker ..\sakura-input\artifacts\release\sakura_neural_worker.exe `
  --model-dir ..\sakura-input\artifacts\release\neural\deberta-v2-tiny-japanese-char-wwm `
  --expect-worker-sha256 <worker-sha256> `
  --expect-model-sha256 <model-sha256> `
  --output reports\current-tiny-benchmark.json
```

Every launched worker has a response timeout and explicit close/terminate/kill
ownership. The report separates cold process-to-first-response latency, warm
roundtrip percentiles by workload, probe startup, response failures, payload
size, and Windows private working set.

## Licensing

No repository license has been selected yet. Model, corpus, tokenizer, runtime,
and extraction-tool licenses and provenance must be reviewed and recorded before
redistribution.
