# Sakura Rerank

Sakura Rerank is the reproducible research and tooling repository for a
context-aware, ultra-low-latency reranker for
[Sakura Input](https://github.com/tsuyoshi-otake/sakura-input).

The project reranks bounded N-best full-path candidates produced by Sakura
Input. It does **not** replace the dictionary, lattice, Viterbi search, or
candidate generator.

## Status

The repository is in the baseline-reproduction phase tracked by
[Issue #1](https://github.com/tsuyoshi-otake/sakura-rerank/issues/1).
No Gate A/B result has been established, and no production default is approved.

The first required result is an adversarial review of the current Sakura Input
reranker at an exact Git revision, followed by reproduction of the current Tiny
baseline. Production protocol or integration changes must wait until that work
is complete and the relevant quality gates pass.

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

## Licensing

No repository license has been selected yet. Model, corpus, tokenizer, runtime,
and extraction-tool licenses and provenance must be reviewed and recorded before
redistribution.

