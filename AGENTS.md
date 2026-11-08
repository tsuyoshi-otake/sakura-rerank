# AGENTS.md

Research/tooling only; production integration belongs in `tsuyoshi-otake/sakura-input`.

- Record the exact clean Sakura Input HEAD in a manifest before relying on it.
  Complete current-state review and Tiny baseline before production edits.
  Protocol v2 design/implementation requires Gates A/B to pass; defaults/installer/
  settings require the first A/B report. Default enablement needs separate approval.
- Preserve local conversion, learning/cache/user-dictionary priorities, nonblocking
  isolated workers, fingerprint/stale checks, displayed-order freeze and local fallback.
  Bound inputs/work/retries/concurrency/time; failures keep local order, and every
  branch owns an observable terminal outcome.
- Context: bounded, same-session Sakura-committed left text only; clear on
  focus/session/deactivation. No host-document/right context or raw-text logging.
  No readings/surfaces/candidates in progress/errors; reports/manifests are aggregate-only.
- Never commit dumps, extracted text, datasets, dictionary images, private corpora,
  traces, checkpoints or binaries. Manifests pin snapshot names (no `latest`), official
  hashes, local SHA-256, licenses, tool versions, preprocessing SHAs, times and artifact hashes.
- Before data/review work, follow [data contracts](src/sakura_rerank/data/README.md):
  verified readings/full-reading N-best labels, tier rules, immutable leakage-safe splits,
  audit thresholds, pending/rejected handling and loopback/token/no-log review UI.
  Never guess labels, invent human verdicts or automate human-review clicks.
  Authorized AI reviews use `ai_teacher`, never human/`sampled_human_audit`; record
  owner overrides. Failed inputs publish no partial trusted artifact.
- Keep Python/CUDA outside production Cargo; pin dependencies/artifacts and verify
  official installation guidance. No final-holdout or public-eval training/tuning.
  Compare identical immutable snapshots/denominators, including failures and fallbacks.
- Production benchmarks: Windows CPU, GPU off, batch one, one ORT intra/inter-op
  thread, warmup, >=10,000 runs. Before push: full unit suite, `git diff --check`,
  artifact tracking check. Prove owned test/training/exporter/ORT/worker processes exited.

Read relevant sections only: [status/commands/boundaries](README.md),
[exporter contract](research/exporter/README.md). Keep changing results in existing
reports/manifests and README, not agent instructions.
