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
