# Sakura Rerank

Sakura Rerank is the reproducible research and tooling repository for a
context-aware, ultra-low-latency reranker for
[Sakura Input](https://github.com/tsuyoshi-otake/sakura-input).

The project reranks bounded N-best full-path candidates produced by Sakura
Input. It does **not** replace the dictionary, lattice, Viterbi search, or
candidate generator.

## Status

The repository has completed the current-HEAD audit, current Tiny baseline
reproduction, deterministic data contracts, and the isolated verified top-32
research exporter tracked by
[Issue #1](https://github.com/tsuyoshi-otake/sakura-rerank/issues/1).
No Gate A/B result has been established, and no production default is approved.

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
JSONL contracts, deterministic Tier A assembly, and leakage-safe splitting. The
standard-library tooling and CLI are documented in
[`src/sakura_rerank/data/README.md`](src/sakura_rerank/data/README.md). It does
not download jawiki, invoke the converter, train a model, or alter Sakura Input.
Real Tier A assembly remains blocked until deterministic jawiki source spans
are reproduced and their exact extractor/output identity is allowlisted.

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
