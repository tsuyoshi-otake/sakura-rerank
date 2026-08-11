# Current Tiny Baseline

Status: **Reproduced; not accepted for production selection**

This report measures Sakura Input's released DeBERTa V2 Tiny pseudo-PLL worker
before any production change. Machine-readable evidence is in
[`current-tiny-benchmark.json`](../reports/current-tiny-benchmark.json) and
[`current-tiny-quality-summary.json`](../reports/current-tiny-quality-summary.json).

## Pinned inputs

| Input | SHA-256 | Bytes |
| --- | --- | ---: |
| Sakura Input HEAD | `8e966dff456e4e7165e025f97c1f73327ff3f550` | N/A |
| `system.dic` | `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad` | 38,456,565 |
| `sakura_neural_worker.exe` | `0f22f2529bb2dc0ded652dd3ef2ed68d64944de916338703f5f2074a901f9229` | 412,160 |
| `model.onnx` | `59fb798139a2dbb52a093dfb8cb9c59dd0e3633d03089a5802a3f537b302b137` | 42,333,503 |
| `vocab.txt` | `902cbd7e218aaf23a72955533293ceac12fcc4e010ad98c0c14757b94ce7abb6` | 88,151 |
| `onnxruntime.dll` | `18370c375f07357fa5874344a9d9ac17e6b6fe1eb18b1dd209d79483b4470257` | 15,809,848 |
| 600-row authored draft | `5e7ba4822b4272881692dab57bd4d5a6240a9ec71ef15d43f37f7a4766196a5c` | 74,674 |
| Dirty-tree evaluator source | `8c9a253affbedca2c6cf618ea7cc9c7c57a5aab905ceb7a5942d1bc331c0dad9` | 28,855 |
| Built evaluator executable | `fc00eca30ac9c5ce6195bfa8f97ea4d4d93c7bdb8d8f4a51ee2bb87309a1849f` | 348,672 |

The current neural release payload represented by worker, runtime, model,
vocabulary, and manifest totals 58,644,253 bytes (55.93 MiB). The ONNX model
alone is 40.37 MiB.

## CPU benchmark method

- Host: Windows 10.0.26200, AMD Ryzen 7 9700X, x86-64, 8 logical processors.
- Device: CPU only; the child receives `CUDA_VISIBLE_DEVICES=-1` and the release
  runtime is the CPU ONNX Runtime DLL.
- ORT source contract: intra-op 1, inter-op 1, sequential execution.
- Request concurrency: one; worker requests are sent synchronously over framed
  stdio.
- Warmup: 10 requests per bucket.
- Measurement: 10,000 requests total, round-robin over three buckets; nearest-
  rank p50/p95/p99.
- Cold samples: 5 new processes; probe samples: 5 new processes.
- Integrity: every response ID, status, finite score, and exact candidate
  fingerprint set is checked.
- Privacy: fixed synthetic hiragana surfaces only; the JSON records their
  aggregate hash, lengths, and byte counts, not surface text.
- Cleanup: each worker receives EOF, then bounded wait/terminate/kill cleanup;
  no worker or benchmark Python process remained afterward.

The three fixed groups have six candidates each and characterize the current
scorer's serial-work bound:

| Bucket | Surface chars | Differing positions | Source-implied ORT calls | Framed request bytes | Runs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Short | 8 | 1 | 1 | 268 | 3,334 |
| Medium | 16 | 4 | 4 | 412 | 3,333 |
| Long | 32 | 8 | 8 | 700 | 3,333 |

These are system microbenchmarks, not language-quality examples. “ORT calls” is
inferred from the pinned scorer source and character tokenizer; protocol v1 does
not report call count dynamically.

## Latency results

All 10,000 warm requests and all five cold requests returned success on SIMD
tier 2 (`avx2-fma`).

| Path | Count | Mean ms | p50 ms | p95 ms | p99 ms | Max ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Probe startup | 5 | 162.50 | 162.44 | 166.66 | 166.66 | 166.66 |
| Cold process → first response | 5 | 157.50 | 155.25 | 164.82 | 164.82 | 164.82 |
| Warm aggregate | 10,000 | 61.12 | 39.34 | 138.74 | 143.07 | 222.32 |
| Warm short / 1-call-equivalent | 3,334 | 6.59 | 6.53 | 7.21 | 7.57 | 20.70 |
| Warm medium / 4-call-equivalent | 3,333 | 39.47 | 39.34 | 41.00 | 42.93 | 63.21 |
| Warm long / 8-call-equivalent | 3,333 | 137.30 | 136.72 | 140.97 | 154.36 | 222.32 |

The approximately monotonic 6.59 → 39.47 → 137.30 ms means show that repeated
serial ORT inference is the dominant scaling cost. Protocol v1 exposes no
component timestamps, so tokenization, inference, IPC, and worker-internal score
aggregation cannot be split honestly. Engine-side local-cost fusion is outside
this worker benchmark.

## Memory

Windows private working set is counted from `QueryWorkingSet` resident pages
whose shared bit is clear. Other counters are included to avoid conflating
resident private memory with commit.

| Phase | Private working set max | Working set max | Private commit max | Peak working set counter max |
| --- | ---: | ---: | ---: | ---: |
| Cold first response | 75,644,928 B (72.14 MiB) | 92,356,608 B | 85,557,248 B | 97,640,448 B |
| Warm run | 125,452,288 B (119.64 MiB) | 142,299,136 B | 207,233,024 B | 160,264,192 B |

The warm private working set exceeds the proposed 100 MiB target.

## Exploratory Top-1 reproduction

The raw evaluator reports are kept outside Git because every row contains corpus
text. The tracked summarizer independently recomputes every aggregate from those
rows and emits only counts and file hashes.

| Mode | Local Top-1 | Tiny Top-1 | Applied | Worker fallback | Wins | Losses | Ties |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `long` | 545/600 (90.83%) | 545/600 (90.83%) | 192 | 408 | 0 | 0 | 600 |
| `all-normal` | 545/600 (90.83%) | 545/600 (90.83%) | 192 | 408 | 0 | 0 | 600 |

Per-slice results are also identical between modes:

| Slice | Cases | Local/Tiny correct | Applied | Fallback |
| --- | ---: | ---: | ---: | ---: |
| Chat | 200 | 185 (92.5%) | 37 | 163 |
| Email | 200 | 170 (85.0%) | 57 | 143 |
| General | 200 | 190 (95.0%) | 98 | 102 |

All 600 rows were eligible in both runs. Of them, 408 returned generic worker
status 2 and safely retained local Top-1. Protocol v1 does not reveal whether a
specific failure was unknown token, no differing position, work bound, deadline,
backend, or output-contract failure. The 192 applied rows still produced no
Top-1 change.

This corpus is explicitly an authored, templated regression draft. Its
evaluator's `acceptance_eligible=true` only checks row and chat/email counts; it
does not establish independent review, label precision, provenance, leakage
safety, oracle recall, confidence intervals, or a frozen final holdout. These
results are not Gate A/B evidence.

## Gate comparison

| Proposed initial Gate C item | Current Tiny result | Status |
| --- | --- | --- |
| One ORT call per request | 1–8 calls from source contract | Fail |
| Model warm p95 ≤ 2 ms | Internal model time unavailable in protocol v1 | Unmeasured |
| Worker roundtrip p95 ≤ 5 ms | 7.21 ms even for short; 138.74 ms aggregate | Fail |
| Worker roundtrip p99 ≤ 10 ms | 7.57 ms short, 143.07 ms aggregate | Fail overall |
| Model/payload ≤ 8 MiB | 40.37 MiB model; 55.93 MiB represented neural payload | Fail |
| Worker private working set ≤ 100 MiB | 119.64 MiB observed maximum | Fail |
| Ready-before-convert ≥ 95% | No replay counter exists | Unmeasured |
| Hot key path wait = 0 | Source inspection confirms poll-only selection | Pass |

Gate C targets describe the future student and are not grounds to retrofit the
baseline result. They show why the current masked-LM pseudo-PLL approach is not
the production v1 target.

## Conclusion

The current Tiny baseline is now reproducible and content-addressed. It provides
safe fallback and nonblocking scheduling, but it is candidate-only, multi-call,
opaque on failures, above latency/memory/size targets, and produces no Top-1
change on the available draft. This evidence supports moving research toward a
single-call, approximately 2M-parameter listwise residual student, but no model
or production default is selected until independent Gate A/B data exists.
