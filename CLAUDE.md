# Claude Code guidance

Read and follow `AGENTS.md` before changing this repository. It is the
authoritative project policy; this file is a compact handoff for the current
research boundary.

## Repository boundary

- This is the independent `tsuyoshi-otake/sakura-rerank` research repository.
  Sakura Input production code belongs to `tsuyoshi-otake/sakura-input`.
- Do not modify Sakura Input production behavior, protocol, defaults, installer,
  or settings here. Gates A and B must pass before production protocol work.
- Never use a dirty or moving Sakura Input checkout as verified build input.
  Use the exact clean HEAD recorded in the relevant manifest.

## Current verified chain

- Sakura Input HEAD: `8e966dff456e4e7165e025f97c1f73327ff3f550`
- System dictionary SHA-256:
  `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad`
- Dictionary index: `manifests/system-dictionary-index-verified.json`
- Jawiki source spans: `manifests/jawiki-tier-a-source-spans-verified.json`
- Research exporter identity: `manifests/research-exporter-verified.json`
- Verified candidate snapshot:
  `manifests/jawiki-research-top32-snapshot-verified.json`

The next research step is deterministic Tier A assembly and audit from these
immutable inputs. The verified top-32 snapshot is prerequisite evidence, not a
Gate A/B result and not approval for production integration.

## Data and privacy

- Never commit dumps, extracted text, request/candidate JSONL, dictionary images,
  binaries, checkpoints, models, raw traces, or raw user text.
- Reports and tracked manifests must contain only aggregate counts, hashes, and
  reproducibility metadata. Never print readings, surfaces, or candidate text in
  progress/error summaries.
- Readings come only from an exact single-reading lookup in the verified system
  dictionary index. Candidates come only from the verified full-reading Sakura
  converter exporter. Do not infer or guess either value.
- Missing, ambiguous, stale, mismatched, malformed, late, or failed inputs must
  terminate explicitly and publish no partial trusted artifact.

## Working method

- Ensure a tracking GitHub Issue exists before non-trivial implementation.
- Use `rtk` for shell commands and `rtk gh` for every GitHub operation.
- Use a task-specific Python environment under `~/tmp/`; do not install globally.
- Keep generated work and reproducible clean checkouts under `~/tmp/` or ignored
  `data/` paths, never directly under the home directory.
- Write English commit messages with the Issue number.
- Run the complete unit suite, `git diff --check`, artifact tracking checks, and
  a repository-owned process audit before push. Confirm tests/build/exporter/ORT/
  worker processes have exited.

See `README.md`, `src/sakura_rerank/data/README.md`, and
`research/exporter/README.md` for executable commands and contract details.
