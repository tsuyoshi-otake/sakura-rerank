# Verified project learnings

- On Windows, publish independently reproduced immutable queue directories
  sequentially. A 2026-08-13 run that published sibling directories in
  parallel hit `Access denied` at the atomic rename boundary; the same two
  publications succeeded sequentially and produced byte-identical trees. The
  failed atomic publication left no partial target.
- When validating many independently written verdict batches, include the
  three-digit batch index in every fail-closed validation error. This made an
  exact stable-ID-order defect immediately attributable without exposing any
  queue text or reviewer note.
- On Windows, use `core.autocrlf=false` in external reproducible worktrees that
  hold canonical JSONL artifacts. LF-to-CRLF checkout conversion changes the
  bytes and therefore invalidates hash-bound canonical JSONL evidence.
- Keep schema-version constants separate for nested contract domains. The Gate-A
  teacher envelope/verdict contract is version 1 while its adapted audit queue
  rows are version 2; an exact-binding test caught the otherwise plausible
  mistake of reusing the envelope version for embedded rows.
- On Windows, an outer command timeout is not proof that descendant workers were
  terminated. A one-hour shell timeout around two Jawiki preprocess runs returned
  while both Python workers continued to completion and held their temporary
  outputs open. Before restarting or deleting anything, inspect the exact process
  ancestry and command lines, assign cleanup ownership, and prove the descendants
  have exited.
- For long explicit-review queues, durable progress means one published and
  mechanically validated verdict batch, not judgments retained in an agent's
  working context. A confirmation pass had reviewed 400 rows while its resumable
  scanner still reported zero files; pausing further review and publishing one
  batch at a time restored the intended crash-safe boundary.
- When a generic scanner or finalizer is reused across versioned evidence
  contracts, make the expected record type an explicit bounded parameter with a
  backward-compatible legacy default. Test both mismatch directions so a newer
  artifact cannot silently enter the legacy path and a legacy artifact cannot
  enter the newer path.

- Repository commit identity may be unset in this environment. The 2026-11-04
  Gold pilot commit initially failed for that reason; a command-scoped Codex
  noreply identity succeeded without changing repository/global configuration.
  Check each Git mutation exit code before a dependent push; otherwise an
  empty branch can be published after a failed commit. Verified commit:
  `92a3252448465e9759f8eef958b04ac442d96830` (#31/#32).

- Gold pilot triage (#31): dictionary-unique reading and forward conversion
  verify a candidate path, not contextual pronunciation or a realistic user
  input boundary. The v5 frozen extractor and current extractor have identical
  ASTs; synthetic cases show kanji and mixed-script lexical fragments passing
  its character-class boundary filter. See
  `reports/issue-31-policy-triage.md` and its verification JSON. Keep source
  fidelity, reading, input unit, context integrity, meaning, spelling intent,
  and reviewer provenance separate; AI routing is neither Gold certification
  nor permission to normalize names/quotes or remove hard cases.

- Six-axis human pilot (#31): source gold is not independent source evidence.
  Without that evidence, record source fidelity as unverifiable and keep its
  informative-agreement denominator at zero. Preserve first A/B judgments for
  agreement even after pre-seal corrections; seal all 1000 pairs before exposing
  disagreements to C. Human identity and independence require coordinator
  confirmation, not merely distinct IDs. Verified by the contract tests and
  `reports/issue-31-human-six-axis-verification-v1.json`.
