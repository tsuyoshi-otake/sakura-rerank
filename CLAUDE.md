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
- Expanded jawiki source spans:
  `manifests/jawiki-tier-a-source-spans-expanded-v2-verified.json`
- Research exporter identity: `manifests/research-exporter-verified.json`
- Verified candidate snapshot:
  `manifests/jawiki-research-top32-snapshot-verified.json`
- Expanded pre-review evidence: `reports/issue-15-tier-a-pre-review.json`

The old expanded-v1 chain produced 33,553 automatic Tier A records and a
5,033-row final holdout with zero measured article, exact-paragraph,
near-sentence, or template leakage. An owner-authorized Codex teacher audit
rejected five of its first 120 rows. Cleaner v2 repairs those source-boundary
classes and its 30,003 corrected source spans reproduced twice byte-identically;
Issue #15 owns regeneration and review of the downstream v2 chain.
The teacher result is explicitly not human review. Automatic verification is
prerequisite evidence, not a Gate A/B result and not approval for production
integration. No Sakura-Rerank-Tiny-v1 model has been selected or exported yet.

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
- Never fabricate or infer a human-review response. An owner-authorized AI
  teacher must use `reviewer_kind=ai_teacher`; it must never claim the human
  gate, and its policy override must remain explicit in the aggregate report.
  AI teacher responses are quality evidence only and must not be applied to the
  `sampled_human_audit` field. Selected unanswered rows
  remain pending and training-ineligible; rejected rows are excluded. Gate A
  requires at least 1,000 completed labels, 3,000 valid final-holdout labels,
  99.5% point precision, and a 99.0% 95% Wilson lower bound.
- Use `human-audit serve` for local review. Keep it bound to loopback and
  preserve its token requirement and no-log behavior. Never automate clicks or
  populate verdicts on behalf of a named human reviewer; AI teacher work must
  identify itself as such.

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
