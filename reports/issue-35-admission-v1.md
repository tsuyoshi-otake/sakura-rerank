# Evaluation artifact admission and Test consumption (#35)

2026-11-04. Base commit: `b0693578593fb343e3b199a72414f8c5dabaedfe`.
Parent #1; depends on #31/#32 and eventual #34 calibration evidence.

## Completed and still unavailable

The new `evaluation_admission` access API authenticates a frozen plan, exact
artifact bytes, quality evidence identity, and model/gate/calibration bindings.
It connects these checks to the existing one-use Test registry. A durable
reservation and separately retained head precede every Test content read.
Changed Test bytes or failed execution remain consumed. Successful access saves
the result bytes before committing their hash; missing completion is a failure.

**No independent Gold certificate is verified.** The production trust set is
empty and real admission is refused. There is no new Test dataset/plan, no final
model comparison, no training, no label edit, no production change, and no Gate
A/B or release pass. Positive tests use explicitly synthetic attestations with
a test-local patched trust set. Their fabricated population counts are fixtures,
not observations of 3,000 real Gold examples. No human judgments are claimed.

The user has no human reviewers. This work avoids asking for people while keeping
that unresolved quality-evidence requirement visible. It does not turn AI voting,
dictionary uniqueness or source equality into independent truth. The recognition
mechanism is only an access boundary; it does not solve how to obtain the evidence.

## Observable safeguards

- Exact plan SHA, bounded relative paths, size/hash/file identity checks, no
  catalog aliases, role-consistent bindings, and required v1/r2/#29/current Tiny
  identities. Later model execution still needs to prove it uses these bytes.
- Quality evidence binds the exact data, labels, provenance, history, sampling,
  experiment specification and partition receipt. Numerical checks preserve
  >=99.5% point precision, Wilson lower >=99.0%, valid Test >=3,000 and Oracle@6
  >=97%. The operational pilot is not final certification.
- Gates bind exact weights/features/tokenizer/calibration/policy and retain
  safety 0.25%. Receipt leakage/token mismatches stop before reservation. Model
  and Test snapshots cannot silently drift with later file edits.
- The access lock covers the job. Reservation, result and terminal write failures
  never release Test tokens; uncertain writes require explicit reconciliation.
  A failed terminal anchor cannot trigger a second terminal event. Closed jobs
  reject completion. See the [access contract](../research/evaluation-admission-v1.md).

## Verification rubric and results

| Criterion | Verify | Expect / observed |
|---|---|---|
| Fail closed without genuine evidence | Admission contracts, unpatched trust store | Refused before dataset/model/Test content; 0 recognized certificates |
| Preserve access order and terminal state | Synthetic success, changed files, stale/foreign anchors, concurrency, missing/duplicate completion and injected fsync/write failures | 28 new tests passed; failed Test remains consumed |
| Preserve existing behavior | Unittest discovery under a 300-second subprocess timeout | 410 tests: 405 passed, 5 existing optional PyTorch skips, 0 failures; 18.202 seconds |
| Preserve old evidence | Recompute all 33 hashes from prior metrics verification | All 33 match; no holdout parsing or model execution |
| Finish cleanly | Compile/AST checks, git diff check, owned-process audit | Passed; owned runners 0; existing installed worker preserved |

The executable commands are in the access contract. Machine-readable results,
source hashes and prior artifact pins are in
[issue-35-admission-verification-v1.json](issue-35-admission-verification-v1.json).
No dependencies were installed. Verification used Python 3.13.13. Sakura Input
HEAD was `d586fae572d32aa76512994dca616dadef2899b1`; its source was unchanged.
This repository has no configured standalone lint/type-check command; syntax
compilation and behavioral contracts were run rather than claiming such checks.

## Limits and remaining work

Hashes authenticate bytes, not Japanese meaning, full historical coverage or
sampling independence. The caller's external plan commitment still needs actual
preregistration. A locally stored head is not tamper-proof against deleting both
copies, modifying trust code or reading raw Test files outside this API. Abrupt
termination and uncertain fsync require retained evidence and reconciliation.
Offline memory bounds are not production Gate C benchmarks.

The next substantive decision is how independent label-quality evidence can be
established without reviewers, and which ambiguities remain unresolved by available
sources. Runtime integration, calibration, final one-use evaluation and Gates C/D
also remain. A completed access job alone cannot mark any of these complete.

## Investigation scope and architecture (IRV)

A. Scope: frozen evaluation protocol, registry operations/failure behavior,
atomic single-file publication, Wilson helper, partition fixtures, new admission
module/tests and data index. Existing pins were hashed; training and production
internals were not changed.

B. Expansion: hashing alone leaves a time-of-use gap. The scope therefore included
retained bytes, external-head persistence and failure finalization, all required
for the access-order contract. No unrelated refactor was needed.

C. Ownership: admission owns artifact identity and access lifecycle; registry owns
append-only consumption; atomic I/O owns publication; data owns partition receipts;
statistics owns Wilson math. Dependencies use these existing boundaries. Runtime
model/gate policy was not moved into the data layer.

D. Future IRV: the data README now locates the access boundary, trust limitation,
recovery rules and tests without reconstructing ordering from registry internals.
A runtime adapter must still understand model/gate formats and prove it evaluates
authenticated bytes. Independent label verification remains necessary.
