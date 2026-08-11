# Current Sakura Input Reranker Review

Status: **Not yet measured**

This report must be completed from source and executable evidence at an exact
Sakura Input revision. Unknown values remain explicitly unknown; they are never
inferred from issue descriptions alone.

## Reproduction identity

| Item | Observed value | Evidence / command |
| --- | --- | --- |
| Sakura Input Git SHA | Pending | Pending |
| Repository dirty state | Pending | Pending |
| Dictionary SHA-256 | Pending | Pending |
| Dictionary entry count | Pending | Pending |
| Unique reading count | Pending | Pending |
| Unique surface count | Pending | Pending |
| Current model/runtime/tokenizer hashes | Pending | Pending |

## Current conversion and reranking path

The review will record the code entry points and observed contracts for:

- long-conversion eligibility and exclusions;
- N-best generation and current top-K;
- worker request and response schemas;
- reading and left-context availability at the worker boundary;
- current Tiny model and tokenizer contract;
- pseudo-log-likelihood scoring and ORT call count;
- local-cost normalization and neural-cost fusion;
- snapshot/fingerprint ownership and stale-result handling;
- timeout, failure, and local-fallback terminal states;
- displayed candidate order freezing;
- user learning, exact cache, and user-dictionary priority.

## Baseline resource measurements

| Measurement | Cold | Warm | Conditions / evidence |
| --- | ---: | ---: | --- |
| Tokenization latency | Pending | Pending | Pending |
| Model inference latency | Pending | Pending | Pending |
| Score-fusion latency | Pending | Pending | Pending |
| Worker roundtrip latency | Pending | Pending | Pending |
| Worker startup latency | Pending | N/A | Pending |
| Private working set | Pending | Pending | Pending |
| Model file size | Pending | N/A | Pending |
| Request payload size | Pending | Pending | Pending |

## Quality evidence

The review will identify whether current Top-1 evaluation exists and will record
the exact corpus, dictionary, candidate snapshots, denominators, oracle recall,
fallback accounting, and limitations. A connectivity corpus is not treated as a
model-selection holdout.

## Adversarial findings

Pending source inspection and baseline reproduction.

## Decision

No production change is authorized by this placeholder report.

