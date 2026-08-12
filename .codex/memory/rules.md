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
