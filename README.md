# Sakura Rerank

Sakura Rerank is the reproducible research and tooling repository for a
context-aware, ultra-low-latency reranker for
[Sakura Input](https://github.com/tsuyoshi-otake/sakura-input).

The project reranks bounded N-best full-path candidates produced by Sakura
Input. It does **not** replace the dictionary, lattice, Viterbi search, or
candidate generator.

## Status

The [source-unit diagnostic](research/issue-35-source-units/README.md) preserves
all 100 exposed pilot sentences. Punctuation-delimited runs contain every
source-exact part in Top-32 for 89 sentences versus 38 for individual ruby
fragments (52 paired gains, one reverse case); these are component-presence
counts, not model accuracy. All 426 native requests have one terminal result:
401 validated, six rejected by the unchanged 18-segment contract, and 19 by
the converter's candidate-count check. Omitting only Tatoeba administrative-owner
relations reduces historical connections from 84 to 12 sentences while retaining
all 528,894 legacy author edges. No original exclusions are restored. All 732
tests pass; no model, Gold/calibration, final Test or production changes are made.

The [external-source pilot](research/issue-35-source-pilot/README.md) reserved
100 Tatoeba sentences before reading their text. Exact source/ruby alignment
passed for 98; two had empty readings. Complete history isolation retained
14 sentences / 44 provisional annotations. Twelve direct bounded-input matches
propagated to 84 sentences through source/owner relations; text-only relations
did not connect this pilot to history. Source ownership is not proven authorship,
and ruby spans are not certified IME input units. All 701 tests passed; existing
data and ten checkpoints remain unchanged. This advances source/evaluation design,
with no new fits, Gold admission, calibration, final Test or production change.

The latest [fixed loss-balance experiment](research/issue-33-loss-balance/README.md)
improved the annotation recipe by a mean 1.349 percentage points on 593 previously
unused research examples (paired component 95% CI 0.112 to 2.586). All three seeds
reduced harmful changes, satisfying the frozen research rule. However, it did
not beat the dictionary anchors and fixed-gate accuracy decreased. No model is
adopted: 90.72%, the 0.25% safety requirement, Gold requirements and Gates A/B remain
unchanged. All 676 tests and independent metric/weight/exposure checks passed.
The KWDLC public-train reservation is exhausted; new source-isolated evaluation
and independent calibration must precede another comparison.

The preceding [train-only change audit](research/issue-33-train-change-audit/README.md)
found 357–419 additional harmful changes on the same 25,000 Wikipedia training
rows after the annotation-recipe fits, despite identical per-update Wikipedia
exposure. The Aozora target-rank distribution changed substantially. This narrows
the loss-contribution hypothesis tested above; the audit itself used no new fits
and claimed no independent accuracy gain. All 420
metric groups and 78 paired comparisons were recounted. GPU/CPU numerical
parity did not pass every sampled condition, so this remains a GPU training
diagnostic, not a CPU-equivalence or safety claim.

The earlier [paired extraction experiment](research/issue-33-annotation-experiment/README.md)
completed six fixed fits and all evaluations on 985 isolated research examples.
The original-annotation recipe failed the prespecified primary comparison:
mean accuracy difference versus dictionary extraction was -3.45 percentage points
(paired component 95% CI -5.10 to -1.89). It is not adopted. Both fixed-seed CPU
exports passed parity and 10,000-run latency checks; 658 unit tests passed.
These source-reconstruction results are not independent IME Gold accuracy.
The recorded adopted result remains 90.72%; the 0.25% safety criterion,
independent Gold requirements, and Gates A/B are unchanged. The subsequent audit
and one-change comparison are linked above.

The repository has completed the current-HEAD audit, current Tiny baseline
reproduction, deterministic data contracts, fixed jawiki acquisition, and a
reproducible research-only top-32 exporter. The first expanded Tier A snapshot
retained 33,553 of 40,703 source rows, assigned 5,033 rows to the final holdout
with zero measured cross-split leakage, and measured Oracle Recall@6 at 99.064%.

Gate A remains fail-closed. Cleaner v5 reproduced 24,064 source spans twice
byte-identically, regenerated the complete Tier A chain, and subjected all
21,425 historically eligible rows to two distinct full blind AI-teacher passes.
Only the 17,880 unanimous-valid rows were admitted. The frozen 70/10/20 split
contains 12,516 train, 1,788 dev, and 3,576 final-holdout rows with zero measured
article, exact-paragraph, sentence-near-duplicate, or template-cluster leakage.

At the owner's direction, a fresh and separately identified AI teacher reviewed
all 3,576 final-holdout rows: 3,402 were valid and 174 were non-valid. Point
precision was 95.134% and the Wilson 95% lower bound was 94.379%, below the
required 99.5% and 99.0% thresholds. This is owner-authorized AI evidence, not
human review; both the human Gate A and owner-authorized AI Gate A remain false.
Gate B, protocol changes, and production enablement therefore remain blocked.
At the owner's direction, a research-only Sakura-Rerank-Tiny-v1 challenge was
nevertheless trained and exported locally for dev-only evaluation. It reaches
91.72% Top-1 accuracy on the immutable Sakura IME dev split versus 88.70% for
the unchanged local order, with 3.29 ms mean latency per complete 2--6-candidate
request on Windows CPU. This is practical prototype performance, but it is not
production authorization and the undistributed model artifacts remain bound by
their tracked hashes. The aggregate-only evidence is tracked in
[Issue #15](https://github.com/tsuyoshi-otake/sakura-rerank/issues/15),
[`reports/issue-15-v5-admissibility-gate-a-evidence.json`](reports/issue-15-v5-admissibility-gate-a-evidence.json),
and
[`reports/issue-15-tier-a-owner-authorized-audit-v5.json`](reports/issue-15-tier-a-owner-authorized-audit-v5.json).
Reviewers can use the loopback-only `human-audit serve` interface documented in
[`src/sakura_rerank/data/README.md`](src/sakura_rerank/data/README.md); every
click is atomically persisted and resumable without sending queue text to an
external service.
No Gate B result or production default is approved.

The evidence and decision are recorded in
[`research/current-state-review.md`](research/current-state-review.md) and
[`research/current-tiny-baseline.md`](research/current-tiny-baseline.md).
Production protocol or integration changes must wait until reviewed data
satisfies the relevant quality gates.

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
   snapshots, then run the pinned public AJIMEE Eval as a held-out comparison;
   never train or tune on its labels.
5. Consider protocol v2 and opt-in production integration only after the data,
   quality, safety, and resource gates pass.

The target and verification rubric are maintained in Issue #1. Adoption is
based on the measured accuracy/latency Pareto frontier, not architecture novelty.
Public-eval provenance and the cross-model comparison contract are tracked in
[Issue #18](https://github.com/tsuyoshi-otake/sakura-rerank/issues/18). Final
production candidates are also benchmarked on Windows CPU with GPU disabled,
batch one, one ORT intra/inter-op thread, warmup, and at least 10,000 measured
runs.

## Local Japanese reranker comparison

The following research-only comparison uses the public JMTEB-lite reranking
tasks through MTEB 2.4.2. Quality is NDCG@10. Latency is standalone scoring of
one query-document pair on the same Windows CPU, with GPU disabled, ONNX Runtime
1.23.2, batch size one, one intra-op thread, one inter-op thread, 100 warmups,
and 10,000 measured requests. Both runs had zero inference failures.

| Model | Parameters | INT8 ONNX | JQaRA-lite | JaCWIR-lite | p50 / p95 / p99 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Japanese Reranker Tiny v2](https://huggingface.co/hotchpotch/japanese-reranker-tiny-v2) | 29.4M | 29.6 MB | 0.64372 | 0.93423 | 0.7005 / 1.0006 / 1.3109 |
| [Japanese Reranker XSmall v2](https://huggingface.co/hotchpotch/japanese-reranker-xsmall-v2) | 36.8M | 37.4 MB | **0.73347** | not completed[^xsmall-jacwir] | 2.0740 / 3.2321 / 5.2856 |

On the common completed task, XSmall improves JQaRA-lite NDCG@10 by 0.08975,
but its p50 latency is 2.96x Tiny's and its p99 is 4.03x Tiny's. Tiny's JaCWIR
result is shown as supplemental evidence only; it is not included in a
cross-model average because XSmall did not complete the same task.

[^xsmall-jacwir]: The XSmall two-task run reached the 3,600-second execution
    limit while evaluating JaCWIR-lite. The unfinished task was explicitly
    skipped; no score was estimated or reported.

Exact model commits, ONNX hashes, dataset revisions, input-report hashes,
software versions, CPU environment, and the fail-closed decision are recorded
in
[`reports/issue-19-local-reranker-benchmark.json`](reports/issue-19-local-reranker-benchmark.json)
and tracked by [Issue #19](https://github.com/tsuyoshi-otake/sakura-rerank/issues/19).
This is a general information-retrieval benchmark, not an IME conversion
benchmark. It does not prove an improvement in Sakura Input, does not satisfy
Gate B, and does not authorize a production or default-setting change.

## Sakura-Rerank-Tiny-v1 research export

We also trained a Sakura-specific, research-only listwise reranker over the
frozen v5 train/dev split. It is a 1,861,377-parameter shared character
embedding + unidirectional GRU model with six candidates per example. Training
used an RTX 4060 Ti; the frozen final holdout was neither cached nor evaluated.

| Model | Dev top-1 | MRR | NDCG@6 | Rescue / harm | ONNX size | CPU p50 / p95 / p99 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unchanged local rank | 0.88702 | — | — | — | — | — |
| Sakura-Rerank-Tiny-v1 FP32 | **0.91723** | 0.95105 | 0.96241 | 77 / 23 | 7.47 MB | 3.1965 / 3.8472 / 4.5116 |
| Sakura-Rerank-Tiny-v1 INT8 | 0.91499 | 0.94991 | 0.96156 | 77 / 27 | 2.19 MB | 3.2020 / 3.9188 / 4.5872 |

Latency uses Windows CPU only, ONNX Runtime 1.23.2, batch one, one intra-op and
one inter-op thread, 100 warmups, and 10,000 measured runs with zero failures.
FP32 reduces dev errors by 26.7%, but harms 1.45% of baseline-correct rows. INT8
loses 0.224 percentage points of top-1 accuracy. Gate A was already failed, the
final holdout remains unused, and the harm, p95 latency, and INT8-loss checks
miss their thresholds; therefore Gates A, B, and C all remain false. No Sakura
Input production code, installer payload, settings UI, or default was changed.

The binary checkpoint and ONNX files remain ignored generated artifacts. Exact
architecture, training environment, artifact hashes, ONNX parity, benchmark
contract, aggregate results, and fail-closed decision are bound by
[`manifests/sakura-rerank-tiny-v1-research-prototype.json`](manifests/sakura-rerank-tiny-v1-research-prototype.json)
and
[`reports/sakura-rerank-tiny-v1-research-prototype.json`](reports/sakura-rerank-tiny-v1-research-prototype.json).
This IME-specific dev result is not directly comparable with the public JMTEB
information-retrieval table above.
No model license has been selected, so artifact distribution is not authorized
by this result.

### Out-of-domain JQaRA diagnostic

For completeness, the FP32 Sakura model was also run on the identical pinned
JQaRARerankingLite test revision with MTEB 2.4.2. Because the model accepts up
to six IME candidates rather than arbitrary query-document pairs, every pair
was scored independently as one real candidate plus five masked candidates.
The query was mapped to both bounded left-context and reading encoders, the
document to the 32-character candidate encoder, and rank/local-cost features
were zeroed.

| Model | JQaRA-lite NDCG@10 | Evaluation contract |
| --- | ---: | --- |
| Japanese Reranker Tiny v2 | 0.64372 | Native general-IR cross-encoder |
| Japanese Reranker XSmall v2 | **0.73347** | Native general-IR cross-encoder |
| Sakura-Rerank-Tiny-v1 FP32 | 0.18492 | Out-of-domain pointwise adapter |

The Sakura result is intentionally not treated as directly comparable model
quality: 97,795 of 98,941 documents were truncated by the production model's
32-character candidate bound, JQaRA has no kana-reading input, and the model
received no general-IR training. It demonstrates that this IME-specialized
export should not be substituted for a general reranker. The aggregate-only
evidence is in
[`reports/sakura-rerank-tiny-v1-jqara-ood.json`](reports/sakura-rerank-tiny-v1-jqara-ood.json).
It is not Gate B evidence and authorizes no production change.

### Three-model comparison on the Sakura IME dev benchmark

The comparison direction was also reversed: all three models were evaluated on
the immutable 1,788-row Sakura dev split with the same production top-6
candidate snapshots, gold labels, and denominator. Sakura uses its native
bounded IME features. The two general rerankers use one predeclared adapter,
pairing `left context + "\n読み:" + reading` with each candidate surface. No
adapter variant was tried after observing results.

| Model | Parameters | Top-1 | MRR | NDCG@6 | Rescue / harm | CPU p50 / p95 / p99 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sakura-Rerank-Tiny-v1 FP32 | 1.86M | **0.91723** | **0.95105** | **0.96241** | 77 / 23 | **3.1965 / 3.8472 / 4.5116** |
| Japanese Reranker Tiny v2 INT8 | 29.4M | 0.20582 | 0.45131 | 0.58332 | 43 / 1,261 | 3.9580 / 6.0459 / 7.0596 |
| Japanese Reranker XSmall v2 INT8 | 36.8M | 0.20861 | 0.46164 | 0.59174 | 38 / 1,251 | 11.9433 / 18.5500 / 22.6632 |

The unchanged local candidate order scores 0.88702 Top-1. Both general-IR
models severely damage that strong IME baseline, whereas the Sakura-specific
model improves it. Latency is measured per complete 2--6-candidate conversion
request, not per query-document pair: Windows CPU, GPU disabled, batch-one
request, ORT intra/inter-op threads 1, 100 warmups, 10,000 measured requests,
and zero failures for every model. Exact identities, hashes, aggregate metrics,
and input-report bindings are recorded in
[`reports/sakura-ime-three-model-comparison.json`](reports/sakura-ime-three-model-comparison.json).
This remains dev-only evidence; the failed Gate A and untouched final holdout
keep Gate B and production authorization false.

The Sakura latency in this table and in the v1 table above timed more than the
model: the v1 benchmark started its clock before re-reading eight dev arrays
from the lazily loaded `.npz` on every run. See the revision-2 section below for
a re-measurement with model-only timing.

## Sakura-Rerank-Tiny-v1 research revision 2 (Issue #21)

Issue #20 rejected direct weight editing of the v1 prototype, so
[Issue #21](https://github.com/tsuyoshi-otake/sakura-rerank/issues/21) retrained
it under a pre-registered protocol. Three recipes were trained with seeds
20260814, 20261103, and 20261104 on the frozen v5 train split:

- **B0**: the v1 recipe.
- **C1**: B0 plus a seventh candidate feature, the absolute local-cost gap
  `-log1p((cost_i - min cost) / 1000)`. v1 normalizes local cost per row, which
  hides how large the gap to the cheapest candidate is.
- **C2**: C1 plus scorer dropout 0.1 and label smoothing 0.05 spread over the
  valid candidates.

Epochs were frozen from grouped 5-fold out-of-fold (OOF) train predictions;
folds keep rows that share an article, paragraph, or template cluster together.
Dev was evaluated once, after selection, and the final holdout was never read.
The pre-registered rule adopts a candidate only if its OOF top-1 count beats B0
for every seed, its exact McNemar test against B0 has p < 0.025 for at least two
seeds, its mean OOF harm is not above B0, and then its mean dev top-1 is not
below B0 and its mean dev harm not above B0.

| Recipe | OOF top-1 (mean of 12,516) | OOF harm | Dev top-1 (mean of 1,788) | Dev harm | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| B0 | 11,371.3 | 328.7 | 1,624.3 | 50.7 | baseline |
| C1 | 11,396.0 | 300.0 | 1,632.3 | 42.7 | rejected: McNemar p ≥ 0.16 for every seed |
| C2 | **11,424.0** | **265.7** | **1,637.3** | **39.3** | **adopted**: p = 0.0028 / 0.064 / 0.0075 |

An independent recomputation from the numeric predictions matched every count,
test, and the decision. The aggregate evidence is
[`reports/issue-21-retrain-experiment.json`](reports/issue-21-retrain-experiment.json);
the harness that produced it is tracked byte for byte in
[`research/issue-21-retrain/`](research/issue-21-retrain/README.md).

C2 is implemented in
[`src/sakura_rerank/research_tiny_r2.py`](src/sakura_rerank/research_tiny_r2.py);
`research_tiny.py` stays unchanged because the v1 manifest binds its hash.
Training seed 20260814 for the frozen nine epochs reproduces the experiment's
checkpoint tensor for tensor.

| Model (dev, 1,788 rows) | Top-1 | MRR | NDCG@6 | Rescue / harm | ONNX size | CPU p50 / p95 / p99 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unchanged local rank | 0.88702 | — | — | — | — | — |
| v1 prototype FP32 (epoch chosen on dev) | 0.91723 | 0.95105 | 0.96241 | 77 / 23 | 7.47 MB | 0.5086 / 0.6652 / 0.7772 |
| v1 prototype INT8 | 0.91499 | 0.94991 | 0.96156 | 77 / 27 | 2.19 MB | 0.6471 / 0.6791 / 0.8635 |
| Revision 2 FP32 | 0.91667 | 0.95131 | 0.96261 | 91 / 38 | 7.47 MB | 0.5266 / 0.6696 / 0.7839 |
| Revision 2 INT8 | 0.91667 | 0.95130 | 0.96261 | 91 / 38 | 2.19 MB | 0.5311 / 0.6821 / 0.8151 |

Read the comparison with care:

- Against B0 trained the same way (seed 20260814: 1,629 top-1, 50 harm),
  revision 2 gains 10 top-1 rows and removes 12 harms.
- Against the published v1 prototype it is one top-1 row lower and harms 15
  more baseline-correct rows. The prototype's epoch was picked on dev itself
  (its dev top-1 ranged from 1,618 to 1,640 over 20 epochs, and the maximum was
  kept), so its dev numbers are optimistic; revision 2's epoch was fixed before
  dev was seen.
- INT8 keeps the FP32 counts: it changes the top-1 choice on 3 dev rows with no
  net change in top-1, rescue, or harm.
- Harm is 2.40% of baseline-correct rows (threshold 0.25%) and rescue/harm is
  2.39 (threshold 3), and production round-trip and memory are unmeasured.
  Gate A was already failed and dev is not the final holdout, so Gates A, B,
  and C all remain false and no Sakura Input change is authorized.

All latencies in this table time `InferenceSession.run` only, with every input
prebuilt (Windows CPU, ONNX Runtime 1.23.2, batch one, one intra-op and one
inter-op thread, 100 warmups, 10,000 measured runs, zero failures). Measured
this way on the same machine, v1 and revision 2 are equal within run-to-run
noise. The published v1 numbers (FP32 p50 / p95 3.20 / 3.85 ms, Windows build
26200) also timed the per-run `.npz` reads. Re-running v1's own loop on this
machine (build 26300) gives 4.07 / 4.50 ms, against 0.51 / 0.67 ms for the same
FP32 file with model-only timing, so the scope, not the model, explains the
gap. The v1 prototype's missed p95 check is therefore a measurement artifact;
its harm and INT8-loss misses stand. All three measurements are in
[`reports/issue-21-v1-latency-same-scope.json`](reports/issue-21-v1-latency-same-scope.json).

Artifact hashes, the training environment, ONNX parity (FP32 top-1 equals
PyTorch on every dev row), the benchmark contract, and the fail-closed decision
are bound by
[`manifests/sakura-rerank-tiny-v1-research-r2.json`](manifests/sakura-rerank-tiny-v1-research-r2.json)
and
[`reports/sakura-rerank-tiny-v1-research-r2.json`](reports/sakura-rerank-tiny-v1-research-r2.json).
The checkpoint and ONNX files remain ignored generated artifacts, and no model
license has been selected, so their distribution is not authorized.

```powershell
$env:PYTHONPATH = "src"
$o = "data/generated/sakura-rerank-tiny-r2-research"
$v = "data/generated/sakura-rerank-tiny-v1-research"
$inputs = @("--cache", "$v/train-dev-cache.npz", "--cache-manifest", "$v/train-dev-cache.manifest.json",
            "--cost-gap", "$o/cost-gap.npz", "--cost-gap-manifest", "$o/cost-gap.manifest.json")
python -m sakura_rerank.research_tiny_r2 prepare-cost-gap data/generated/issue15-v5-slot120/frozen-split.jsonl `
  --cache "$v/train-dev-cache.npz" --cache-manifest "$v/train-dev-cache.manifest.json" `
  --output "$o/cost-gap.npz" --manifest "$o/cost-gap.manifest.json"
python -m sakura_rerank.research_tiny_r2 train "$o/sakura-rerank-tiny-v1-research-r2.pt" @inputs --report "$o/training.report.json"
python -m sakura_rerank.research_tiny_r2 export "$o/sakura-rerank-tiny-v1-research-r2.pt" `
  "$o/sakura-rerank-tiny-v1-research-r2-fp32.onnx" "$o/sakura-rerank-tiny-v1-research-r2-int8.onnx" `
  @inputs --report "$o/export.report.json"
python -m sakura_rerank.research_tiny_r2 benchmark "$o/sakura-rerank-tiny-v1-research-r2-fp32.onnx" @inputs `
  --report "$o/fp32-benchmark.report.json"
```

Training requires CUDA and the v1 numeric cache. `benchmark` takes the INT8
file the same way, and `publish-evidence` writes the manifest/report pair only
when every input report is consistent.

### Confidence gate on revision 2 (Issue #25)

Revision 2 harms too many baseline-correct rows (2.40%, threshold 0.25%).
[Issue #25](https://github.com/tsuyoshi-otake/sakura-rerank/issues/25)
pre-registered a gate that keeps the converter's first candidate unless the
model's top candidate beats it by more than a threshold tau. Issue #21's
reference gate, tuned so its selection harm sat just under the limit, gave dev
harm 4 / 4 / 1 against a 3-row budget, and dev cannot confirm the limit anyway:
with 1,586 baseline-correct rows only zero harm would show a rate below 0.25% at
one-sided 95% confidence. The decision therefore used cross-fitted train
out-of-fold counts (12,516 rows): for each outer fold, the epoch, the score
(logit difference **L** or probability difference **P**), and tau came from the
other four folds, with tau chosen so the exact one-sided binomial test rejects a
harm rate of 0.25% or more. The decision was written before dev was read.

| Seed | Rule | Harm (rate) | Rescue | RER | Result |
| --- | --- | ---: | ---: | ---: | --- |
| 20260814 | pre-registered (L or P) | 19 (0.171%) | 156 | 9.81% | **fails RER ≥ 10%** |
| 20261103 | pre-registered (L or P) | 17 (0.153%) | 170 | 10.96% | passes |
| 20261104 | pre-registered (L or P) | 18 (0.162%) | 185 | 11.96% | passes |
| all three | Issue #21 reference (L, harm at the limit) | 29 / 29 / 27 (0.261% / 0.261% / 0.243%) | 201 / 211 / 212 | 12.32% / 13.04% / 13.25% | over the harm limit for two seeds |
| all three | P only (reference) | 21 / 15 / 17 | 161 / 167 / 185 | 10.03% / 10.89% / 12.03% | passes all three (not pre-registered as the decision) |

The gate is **not adopted**: the rule required every seed to pass, and seed
20260814 (the revision-2 artifact) misses RER by three rows of net gain
(137 against 140). Choosing tau at the harm limit on the selection rows, as
Issue #21 did, overshoots the limit on held-out rows. On dev (reference only)
the final gates give harm 3 / 2 / 1, rescue 29 / 32 / 30, and RER 12.87% /
14.85% / 14.36%; INT8 reproduces every FP32 gated decision. The P-only result
is a hypothesis for a new pre-registration, not evidence for adoption, because
it was observed on the same rows. Gates A, B, and C remain false. The evidence
is [`reports/issue-25-confidence-gate.json`](reports/issue-25-confidence-gate.json),
produced by [`research/issue-25-confidence-gate/`](research/issue-25-confidence-gate/README.md).

### Seed ensemble with the confidence gate (Issue #27)

[Issue #27](https://github.com/tsuyoshi-otake/sakura-rerank/issues/27)
pre-registered Issue #25's gate on the mean of the three C2 models' logits. The
gate, threshold, and counting rules were imported from Issue #25's hash-pinned
harness. Because the ensemble runs three models, two criteria were added: FP32
ensemble ONNX p95 at most 2 ms under the repository latency contract, and FP32
ONNX gated decisions equal to the stored-logit decisions on all 1,788 dev rows.
Criteria 1-3 used cross-fitted train out-of-fold counts (12,516 rows) and were
written before dev was read.

| Criterion | Result | Pass |
| --- | --- | --- |
| Harm at most 0.25% of 11,120 baseline-correct rows | 15 (0.135%, 95% CI 0.076-0.222%) | yes |
| Rescue at least 3 x harm | 200 against 45 | yes |
| Relative error reduction at least 10% | 13.25% | yes |
| FP32 ensemble ONNX p95 at most 2 ms | 2.211 ms | **no** |
| FP32 ONNX decisions equal stored-logit decisions on 1,788 dev rows | 0 mismatches | yes |

The ensemble is **not adopted**, on latency alone. Its accuracy clears every
criterion that the single revision-2 model missed in Issue #25 (harm 19 / 17 /
18, rescue 156 / 170 / 185 there), but one graph holding three models measures
2.211 ms p95 against 0.704 ms for revision 2 alone on the same machine. The
INT8 ensemble's 1.971 ms p95 is a reference only: it was not the pre-registered
form, and it changes one dev decision relative to FP32. The final gate is score
P with tau 0.78. On dev (reference only) it gives harm 2, rescue 31, and RER
14.36%, against ungated harm 36 and rescue 88. The plan names the next
candidate for a speed-only failure: distil the ensemble into one model. Gates
A, B, and C remain false. The evidence is
[`reports/issue-27-ensemble-gate.json`](reports/issue-27-ensemble-gate.json),
produced by [`research/issue-27-ensemble-gate/`](research/issue-27-ensemble-gate/README.md).

### Distilled single model with the confidence gate (Issue #29)

[Issue #29](https://github.com/tsuyoshi-otake/sakura-rerank/issues/29)
pre-registered the speed-only follow-up named by Issue #27: train one
C2-architecture student on the ensemble's averaged logits and apply Issue
#25's gate. The loss is 0.5 x the C2 loss + 0.5 x T^2 x KL(teacher || student)
with T = 2, fixed in advance. For the cross-fit, the student scored on each
outer fold learned from nested teachers that never trained on that fold
(3 seeds x 10 fold pairs). Before any distillation, the training loop with KL
weight 0 reproduced Issue #21's stored OOF logits bitwise. Criteria 1-3 were
written for every student seed before dev was read.

| Student seed | Harm (rate, 95% CI) | Rescue | RER | Issue #25 single model (harm / rescue / RER) |
| --- | ---: | ---: | ---: | --- |
| 20260814 | 21 (0.189%, 0.117-0.289%) | 202 | 12.97% | 19 / 156 / 9.81% |
| 20261103 | 19 (0.171%, 0.103-0.267%) | 213 | 13.90% | 17 / 170 / 10.96% |
| 20261104 | 21 (0.189%, 0.117-0.289%) | 190 | 12.11% | 18 / 185 / 11.96% |

The distilled model plus gate is **adopted as a research candidate**: every
seed passes harm <= 27, rescue >= 3 x harm, and RER >= 10%; the seed-20260814
final student (epoch 15, gate score L with tau 1.7) runs at FP32 p95 0.661 ms
(revision 2 alone: 0.697 ms in the same session); and its FP32 ONNX gated
decisions equal its stored dev-logit decisions on all 1,788 dev rows. Without
the gate, the students' OOF top-1 is also higher than the single C2 models'
(11,456 / 11,457 / 11,470 against 11,416 / 11,424 / 11,432 correct of 12,516).
Two limits remain. The harm criterion is a point estimate, and every seed's
95% upper bound is above 0.25%. On dev (reference only) the gate gives harm 3,
rescue 39, and RER 17.82% (ungated: harm 30, rescue 87), but 1,586
baseline-correct rows cannot confirm the harm limit. INT8 reproduces every
FP32 gated decision at p95 0.710 ms. The revision-2 manifest and artifacts are
unchanged, the student checkpoint and ONNX files stay undistributed, and Gates
A, B, and C remain false. The evidence is
[`reports/issue-29-distill-gate.json`](reports/issue-29-distill-gate.json),
produced by [`research/issue-29-distill-gate/`](research/issue-29-distill-gate/README.md).

## Data contract boundary

The current data boundary includes fixed-source manifest validation, versioned
JSONL contracts, deterministic source-span and exporter-request generation,
verified top-32 export, Tier A assembly, and leakage-safe splitting. The
standard-library tooling and CLI are documented in
[`src/sakura_rerank/data/README.md`](src/sakura_rerank/data/README.md). It does
not train a model or alter Sakura Input. The acquisition command may download
only the pinned jawiki artifact, and converter invocation remains isolated in
the separately built research exporter. The active data step is a v3 source-span
regeneration and teacher audit that enforces readings of 3--128 characters at
matching, exporter-request, and non-fixture training-contract boundaries. A
snapshot by itself is not Gate A/B evidence.

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

The source code and documentation in this repository are released under the
[MIT License](LICENSE). The license does not cover generated corpora,
checkpoints, or model exports, which stay outside Git. They are derived from
Japanese Wikipedia text (generally CC BY-SA 4.0 and GFDL) and from Sakura Input
dictionary and converter output; no model license has been selected, and their
distribution is not authorized. Model, corpus, tokenizer, runtime, and
extraction-tool licenses and provenance must be reviewed and recorded before
redistribution.
