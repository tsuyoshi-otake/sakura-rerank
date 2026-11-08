# Evaluation artifact access contract v1 (#35)

This contract connects artifact authentication to the existing one-use Test
registry. It does not replace the frozen independent-evaluation protocol, certify
Japanese labels, run models, interpret gate configurations, or pass any release
gate. No independent Gold certificate is currently verified. Real Test access is
therefore refused. Synthetic tests patch the trust set only inside temporary test
fixtures; those fixtures are not quality evidence and are never real datasets.

## Responsibility and public boundary

`evaluation_admission.initialize_anchor(registry, anchor)` creates a separately
retained head for an existing, empty registry. It cannot reset an existing anchor
or initialize one for a nonempty registry. `access_test(...)` authenticates an
externally committed plan, reserves consumption, pins the new head, authenticates
Test bytes, and yields `EvaluationAccess`. The caller uses its immutable byte
mapping and calls `complete(result_bytes)` exactly once. The result is a bounded
JSON object saved with exclusive creation and fsync in the registry directory.
Its SHA-256 is then committed in the terminal event. A completed access job is not
necessarily a complete model comparison, valid metric report, or passing Gate B.
Those semantics belong to the [evaluation runner](evaluation-runner-v1.md).

An optional `preflight(non_test_bytes, plan_bytes)` callback runs after non-Test
authentication and before reservation or Test content access. It receives an
immutable byte mapping and the authenticated original plan bytes; it must return
`None` or raise. `EvaluationAccess.plan_bytes` retains those same bytes, so the
caller need not reopen a mutable plan path. Existing callers remain compatible.

The existing registry owns consumption history. The new module owns artifact
identity and access sequencing. `atomic_io` owns atomic single-file replacement;
the statistics module supplies the already-tested Wilson calculation. Existing
dataset splitting, metrics, production code, and legacy artifact formats do not
change. The runtime caller must consume returned bytes rather than reread paths.

## Frozen plan and evidence formats

The caller supplies an exact expected SHA-256 independently of the plan file.
Before Test access the complete experiment registration and this digest must be
durably committed outside the artifact directory. The API authenticates that
digest; it cannot prove when or independently of which observations it was chosen.

The plan has exactly `kind: evaluation_access_plan`, `schema_version: 1`,
`artifacts`, `data`, and `models`:

- `artifacts` maps 1–64 bounded IDs to `{path, role, sha256, bytes}`. Paths are
  relative to the explicitly supplied artifact root, resolve inside it, and have
  no traversal, absolute path or alternate-stream syntax. File identity aliases,
  including hard links, are rejected; intentional sharing uses the same ID.
- `data` binds exactly one ID for each role: `historical`, `train`, `calibration`,
  `test`, `policy`, `partition`, `tokens`, `sampling`, `provenance`, `experiment`,
  and `quality`. Raw population files include frozen candidates and labels.
- `models` includes `v1`, `r2`, `issue29`, `current_tiny` and at most four additional
  names, each binding `weights`, `tokenizer`, `features`, `gate`. Required names
  do not prove binary identity with historical exports; that still needs actual
  provenance/parity evidence. Ungated/gated evaluations, unchanged local baseline,
  and the parent GRU/minGRU/Tiny Transformer work remain protocol requirements.

All catalog entries must be referenced with their declared roles. Non-Test files
are streamed and compared with exact sizes/SHA-256. Model and metadata bytes are
retained so later path edits cannot silently change the accepted snapshot.

The `quality` document has exactly `kind: independent_gold_evidence`,
`schema_version: 1`, `bindings`, `audit_completed`, `audit_valid`,
`valid_test_count`, `oracle6_present`. `bindings` maps every data role except
`quality` to the exact artifact hash. Its entire hash must already be in
`VERIFIED_GOLD_CERTIFICATES`, currently empty. No CLI, plan flag or permission
flag can add an identity. Recognizing future evidence requires actual independent
validation of label truth, acquisition denominator, population representation,
history completeness, source/candidate provenance and the bound report contents.
The method for obtaining that evidence without human reviewers is unresolved.
Changing this trust set is not itself an evidence-production method.

Even recognized evidence is numerically checked: completed audit >=1,000,
valid/completed >=99.5%, Wilson two-sided 95% lower >=99.0%, valid Test >=3,000,
Oracle@6 >=97%. A 1,000-case operational pilot alone does not certify the final
population. The audit sample design/independence must justify these calculations.
Counts are integers bounded by 100,000, and the partition Test count must match.
The certificate binds exact bytes; its truth cannot be derived from hashes.

Gate documents have exactly `kind: frozen_gate`, `schema_version: 1`, `bindings`,
`safety_threshold: 0.0025`, and an object `configuration`. Bindings are exact hashes
of that model's weights/tokenizer/features and the shared calibration/policy.
The gate threshold value is not a claim that observed safety already passes.
The later runtime adapter must interpret the configuration without changing it.

The existing partition receipt/token validation enforces zero supplied-population
leakage and matching reuse tokens before any reservation is appended. It cannot
establish that unlisted historical exposures never existed. Full inventory
verification and near-duplicate coverage remain requirements of the recognized
evidence. Duplicate JSON keys, non-finite values and excessive nesting are refused.

## Ordering, terminal outcomes and recovery

1. Acquire the separate access lock, authenticate the anchor/ledger head, validate
   the pinned plan/catalog, and recognize/authenticate quality evidence. Catalog
   checks may stat Test but never open its content. Unknown evidence stops before
   opening dataset or model payloads.
2. Authenticate all non-Test artifacts and bindings. Validate the partition receipt
   and tokens. Run the optional metadata-only preflight. Append/fsync the consumption reservation and atomically publish its
   head outside the registry. A failed anchor publication never opens Test.
3. Authenticate Test content and return immutable bytes. Hash mismatch consumes
   the population and produces a failed terminal event. File replacement between
   catalog inspection and authentication is rejected before its bytes are read.
4. Require explicit completion. Persist result bytes before appending/fsyncing a
   completed event and publishing its head. Body exceptions, missing completion,
   duplicate completion, result write failure and Test mismatch produce failure;
   consumed tokens are never released. Calling completion after closure fails.

Any uncertain ledger/anchor write raises an explicit reconciliation error. Do not
retry automatically, erase evidence, invent a result, or reset the registry. A
reservation fsync exception may leave complete bytes even though the call failed;
it remains unavailable for reuse. A terminal-anchor failure may leave a completed
ledger with a stale external head; no second terminal is appended. Partial result
files remain evidence, not successful results. Reconcile against retained heads
and durable event/result bytes after confirming the original process is stopped.
An abruptly killed process leaves a lock/reservation requiring that same explicit
reconciliation. This API performs no automatic stale-lock recovery.

The access lock serializes this API's complete job. Other code must use the same
entrypoint and registry. This is an accidental-reuse control, not an OS sandbox or
tamper-proof remote ledger. An operator can bypass it by reading raw files, changing
trust code, or deleting both registry and anchor. Keep externally backed-up head
commitments and exposure inventory; local hashes cannot detect coordinated erasure.
Filesystem durability still depends on the host's fsync/atomic-replace guarantees.

## Bounds and verification

Plan <=512 KiB; metadata/result <=8 MiB each; individual artifact <=512 MiB;
all catalog bytes <=4 GiB; retained artifact bytes including Test <=768 MiB.
Streaming uses 1 MiB chunks; assembly can temporarily retain another payload copy.
These are offline research limits, not Gate C production memory/latency claims.
There are no retries, network access, package installation, or model execution.

Verify: `PYTHONPATH=src python -m unittest tests.test_evaluation_admission -v`
(PowerShell: set `$env:PYTHONPATH='src'` first). Expect: all synthetic access,
tampering, binding, budget, concurrency, write-failure and terminal tests pass;
the unmodified empty trust set refuses real admission. Verify: full repository
unittest discovery with a 300-second subprocess timeout. Expect: existing behavior
unchanged, existing optional skips explained, and no remaining owned runners.
