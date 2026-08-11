# Current Sakura Input Reranker Review

Status: **Current HEAD audit and current Tiny baseline reproduced**

Review date: 2026-08-11 (Asia/Tokyo)

This review separates immutable `HEAD` source evidence from a dirty local
working tree. Source conclusions below come from `git show HEAD:<path>` and are
fingerprinted in [`reports/current-state-audit.json`](../reports/current-state-audit.json).
The working tree was not modified by this repository's audit or benchmark.

## Reproduction identity

| Item | Observed value | Evidence |
| --- | --- | --- |
| Sakura Input Git SHA | `8e966dff456e4e7165e025f97c1f73327ff3f550` | `git rev-parse HEAD`; audit JSON |
| Remote | `https://github.com/tsuyoshi-otake/sakura-input.git` | audit JSON |
| Repository state | Dirty: 31 paths (26 modified, 5 untracked at audit time) | audit JSON records every path; no dirty file is treated as HEAD evidence |
| Dictionary SHA-256 | `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad` | released `system.dic` |
| Dictionary size | 38,456,565 bytes | compiled header and file length agree |
| Dictionary entries | 472,825 | compiled header and 14 category TSV counts agree |
| Unique readings | 290,465 | exact set count over the 14 canonical category TSVs |
| Unique surfaces | 368,341 | exact set count over the 14 canonical category TSVs |
| Unique reading/surface pairs | 415,214 | exact set count over the same TSVs |
| Dictionary nodes / connection classes | 703,485 / 2,672 | compiled header |
| Current model | `ku-nlp/deberta-v2-tiny-japanese-char-wwm` at revision `41bcb8a393383a039c7ee18ded6893ca82e668b7` | release manifest |
| Model SHA-256 / size | `59fb798139a2dbb52a093dfb8cb9c59dd0e3633d03089a5802a3f537b302b137` / 42,333,503 bytes | release manifest and local hash |
| Worker SHA-256 / size | `0f22f2529bb2dc0ded652dd3ef2ed68d64944de916338703f5f2074a901f9229` / 412,160 bytes | local hash |
| Runtime SHA-256 / size | `18370c375f07357fa5874344a9d9ac17e6b6fe1eb18b1dd209d79483b4470257` / 15,809,848 bytes | released `onnxruntime.dll` |
| Runtime | ONNX Runtime 1.28.0, FP32 O2 export, opset 18 | release manifest |
| Vocabulary | 22,012 rows; SHA-256 `902cbd7e218aaf23a72955533293ceac12fcc4e010ad98c0c14757b94ce7abb6` | `vocab.txt` and manifest |

All five audit consistency checks pass: category count versus compiled header,
category files versus checked build report, checked dictionary hash, checked
versus release build report, and model files versus manifest.

## Current conversion and reranking path

### Candidate generation and bounds

The existing dictionary, lattice, Viterbi search, and full-path N-best converter
remain the candidate generator. The engine/UI can carry at most 18 candidates:
`sakura_proto::MAX_CANDIDATES` is two pages of nine and
`MAX_CONVERSION_CANDIDATES` aliases it. Neural scheduling truncates that stable
local ordering to the first six candidates. Therefore “current top-K” has two
different, important meanings:

- converter/UI bound: 18;
- neural worker snapshot: top 6.

Evidence: `crates/sakura-proto/src/lib.rs`,
`crates/sakura-core/src/conversion.rs`, and
`crates/sakura-engine/src/long_conversion.rs` at the pinned HEAD.

### Eligibility and privacy boundary

The engine schedules only when all of the following hold:

- the scope is classified and exactly `InputScope::Normal`;
- the request is not `test_only`;
- conversion is not already active and shifted-ASCII input is not active;
- the preedit is non-empty and the cursor is at its end;
- at least two candidates exist; and
- the reading has at least 10 Unicode scalar values, or the local top candidate
  has at least three segments (the segmented case still requires at least three
  reading scalars).

This excludes Password, URL, Email, Digits, unknown, and test-only paths before
neural scheduling. No host document is read. The current worker receives no
left context at all, so it cannot leak host or right context, but it also cannot
perform the requested context-aware ranking.

### Protocol v1 contract

The worker uses a length-prefixed, little-endian protocol with a 32 KiB payload
bound, at most six candidates, and at most 3 KiB of UTF-8 per candidate.

Request payload:

```text
u32 request magic (SKNR)
u16 version = 1
u16 reserved = 0
u64 request ID
u32 context byte count
u32 candidate count
u8[context byte count] context
repeat candidate count:
  u64 candidate fingerprint
  u32 local cost
  u32 candidate UTF-8 byte count
  u8[...] candidate surface
```

Response payload contains response magic, version, status, request ID, SIMD
tier, score count, and `(fingerprint, f32 score)` rows.

The engine encoder always writes a zero context length. Reading has no field in
protocol v1. The worker skips any context bytes and discards each local cost,
retaining only candidate fingerprint and surface. Thus the current model scores
candidate surfaces alone; local cost affects only the later engine-side fusion.
The response does not carry model/runtime/hash/shape metadata.

Evidence: `crates/sakura-engine/src/long_conversion.rs` and
`crates/sakura-neural-worker/src/protocol.rs` at the pinned HEAD.

### Model, tokenizer, and scorer

The release model is a DeBERTa V2 Tiny masked-language-model export, not a
listwise residual ranker. Its tokenizer is `BertJapaneseTokenizer` with basic
word tokenization followed by character tokenization, case preserved. Any
candidate containing a token that resolves to the single `[UNK]` ID causes the
whole request to fail closed; there is no UTF-8 byte fallback.

Scoring is conditional pseudo-log-likelihood over candidate body-token
positions that differ across the six surfaces. Every differing candidate token
becomes one masked row. ORT admits at most six rows per call, with total work
bounded to 48 rows, so a request performs between one and eight serial ORT calls.
The worker's own deadline is 400 ms. It therefore does not meet the proposed
one-ORT-call-per-request contract.

The dominant serial work is proportional to the number of differing positions:
with six candidates, `6D` mask rows are chunked by six, producing approximately
`D` ORT calls until the eight-call cap. The baseline's 1/4/8-position workload
means of 6.59/39.47/137.30 ms confirm that this repeated inference, not framing,
is the scaling bottleneck.

Evidence: `crates/sakura-neural-worker/src/tokenizer.rs`, `scorer.rs`, and
`runtime.rs` at the pinned HEAD.

### Local-cost fusion

The engine does preserve local cost. For each candidate it computes the gap
from the maximum neural score, multiplies by `240.0`, rounds, clamps the penalty
to `[0, 1200]`, and adds it to the existing local candidate cost. The best
combined cost wins. In equivalent notation:

```text
neural_penalty_i = clamp(round((max_score - score_i) * 240), 0, 1200)
combined_cost_i  = local_cost_i + neural_penalty_i
```

This is bounded residual evidence, but its scale and clamp are fixed source
constants rather than values selected on a documented dev set.

### Scheduling, stale results, and terminal states

Scheduling is asynchronous and the key path never waits for the worker. A
single latest-wins mailbox replaces pending work. At conversion time the engine
only polls for an already-ready result. The request key contains owner, session,
generation, reading hash, and reading byte length; the result additionally
checks the exact candidate-set fingerprint. A mismatch or unavailable result
preserves local order. The candidate UI is populated from the one synchronous
selection made at conversion start and is not reordered afterward.

The worker response timeout is 500 ms, separate from its 400 ms scoring
deadline. Restart backoff begins at 250 ms, doubles to an 8 s cap, and adds
deterministic jitter.

`RerankState` declares `NotEligible`, `Queued`, `Ready`, `Applied`,
`LocalFallback`, `TimedOut`, `Stale`, `Failed`, and `Cancelled`. Exact key and
fingerprint checks safely prevent stale application, but `Stale` and `Cancelled`
are never constructed at the pinned HEAD. Terminal outcomes are mainly internal
and are not exposed as the production effectiveness counters required by the
new design. Safety is present; observability and explicit state finalization are
incomplete.

### Learning, cache, and user dictionary

An explicit requested index, exact learned preference, exact cache match, or
general learned preference is authoritative and suppresses neural selection.
That preserves explicit learning and cache precedence.

User-dictionary precedence is **not proven and has a plausible violation path**:

1. user entries enter the ordinary lattice with `EntryFlags::NONE`;
2. `ConversionCandidate` does not retain a general user/system source identity;
3. the authoritative-preference guard checks explicit choice, learning, and
   cache, but not candidate origin; and
4. a neural penalty of up to 1,200 cost units can therefore reorder a locally
   top-ranked user entry when the local gap is within that bound.

No reranker/user-dictionary priority test was found. This is an adversarial
finding, not proof that every user entry is currently displaced. Protocol v2 or
any wider rollout must first retain candidate provenance or enforce user-entry
authority before neural fusion, with a regression test.

## Current corpus and quality evidence

The checked-in frozen `held-out.tsv` has only 60 rows (30 general, 30 IT), and
only two readings are at least ten characters. Its SHA-256 is
`42d0a88158288d60c8beed93f8bee517e3b09a87e234a9fb15d177656fc01d66`.
It is a smoke/connectivity corpus, not a model-selection holdout. The 20-row
`tuning.tsv` has no reading at least ten characters.

A dirty-working-tree evaluator and authored 600-row communication draft were
also inspected and executed. Their text-free aggregate is in
[`reports/current-tiny-quality-summary.json`](../reports/current-tiny-quality-summary.json).
Both `long` and `all-normal` runs reproduce local 545/600 and Tiny 545/600,
with 192 applied, 408 worker failures/fallbacks, and 0 wins / 0 losses / 600
ties. This is exploratory regression evidence only: the corpus is templated,
not independently reviewed, not provenance-complete, and not the frozen final
holdout. It establishes neither Gate A nor Gate B.

Issues [sakura-input#24](https://github.com/tsuyoshi-otake/sakura-input/issues/24)
and [sakura-input#32](https://github.com/tsuyoshi-otake/sakura-input/issues/32)
remain the relevant implementation/evaluation history. Their reported draft
numbers were reproduced, but issue comments are not substituted for executable
evidence or an independent holdout.

## Baseline resource measurements

The complete method and tables are in
[`current-tiny-baseline.md`](current-tiny-baseline.md). On the specified AMD
Ryzen 7 9700X, Windows CPU-only, sequential request workload:

| Measurement | Observed result |
| --- | ---: |
| Probe startup p50 / p95 | 162.44 / 166.66 ms |
| Cold process-to-first-response p50 / p95 | 155.25 / 164.82 ms |
| Warm roundtrip, all 10,000, p50 / p95 / p99 / max | 39.34 / 138.74 / 143.07 / 222.32 ms |
| Warm 1-call-equivalent p95 / p99 | 7.21 / 7.57 ms |
| Warm 4-call-equivalent p95 / p99 | 41.00 / 42.93 ms |
| Warm 8-call-equivalent p95 / p99 | 140.97 / 154.36 ms |
| Maximum observed private working set | 125,452,288 bytes (119.64 MiB) |
| Model file | 42,333,503 bytes (40.37 MiB) |

Protocol v1 does not expose internal timestamps, so tokenization, model
inference, score fusion, and IPC cannot be separated from the released binary.
They remain explicitly unmeasured rather than inferred. The engine-side fusion
is not part of the black-box worker roundtrip.

## Adversarial findings

1. **Not context-aware:** reading and left context do not reach the scorer;
   protocol context is zero and discarded.
2. **Serial inference amplification:** one request can invoke ORT eight times,
   and measured latency scales with differing token positions.
3. **Opaque high fallback:** 408/600 draft rows return only generic status 2;
   protocol v1 cannot distinguish unknown token, no differing positions,
   deadline, bound, backend, or output failure.
4. **User-dictionary priority unproven:** source identity is lost before the
   authority guard and no targeted test exists.
5. **Terminal observability gap:** stale results are safely rejected, but
   `Stale`/`Cancelled` are not explicit observable outcomes.
6. **Single-UNK fail-closed behavior:** one unknown token rejects the entire
   candidate list instead of using deterministic byte fallback.
7. **Fixed fusion constants:** the 240-per-nat scale and 1,200 clamp have no
   recorded dev-set selection evidence.
8. **Insufficient evaluation:** the checked-in holdout is 60 rows; the 600-row
   draft is authored/templated and gives no independent Gate A/B conclusion.

## Decision

The required current-state investigation and current Tiny reproduction are
complete. No Sakura Input production code, protocol, installer payload, default,
or settings UI was changed.

The evidence rejects the current pseudo-PLL worker as the target v1 architecture:
it is candidate-only, multi-call, too slow for the proposed roundtrip gate, above
the working-set target, and shows no Top-1 gain on the available draft. It does
not yet authorize the proposed GRU either. Work may proceed in this separate
research repository to freeze provenance, build and independently audit Tier A
data, export exact N-best snapshots, and compare equal-budget challengers.
Production protocol v2 and Sakura Input integration remain blocked until Gate A
and Gate B are satisfied with a frozen independent holdout.
