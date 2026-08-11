# AGENTS.md

## Scope

This repository owns Sakura Rerank research, datasets tooling, model training,
evaluation, export, benchmarking, and design reports. Sakura Input production
integration remains in the separate `tsuyoshi-otake/sakura-input` repository.

## Mandatory sequencing

- Inspect and record the exact Sakura Input HEAD before relying on its behavior.
- Complete the current-state review and reproduce the current Tiny baseline
  before changing Sakura Input production code.
- Do not design or implement production protocol v2 before Gates A and B pass.
- Do not change the production default, installer payload, or settings UI before
  the first Gate A/B report. Default enablement requires separate approval.

## Stable system boundaries

- Preserve Sakura Input's dictionary, lattice, Viterbi, N-best generation,
  nonblocking conversion, isolated worker, fingerprint checks, stale-result
  discard, displayed-order freeze, and local fallback.
- Preserve explicit learning, exact cache, and user-dictionary priorities.
- Never read host-document contents or right/future context. Bounded left context
  may contain only text committed by Sakura Input in the same active session and
  must be cleared on focus/session/deactivation boundaries.
- Never log raw input text.
- Bound frames, context, readings, candidates, features, retries, concurrency,
  and processing time. Every stateful branch must have an explicit observable
  terminal outcome and a clearly owned finalization path.
- Missing, mismatched, late, stale, malformed, timed-out, or failed neural work
  must fail closed to the unchanged local ranking.

## Data and artifacts

- Never commit Wikipedia dumps, extracted article text, generated datasets,
  checkpoints, model binaries, runtime binaries, private corpora, or raw traces.
- Track exact snapshot names, official hashes, local SHA-256 values, licenses,
  tool versions, preprocessing Git SHAs, timestamps, and resulting artifact
  hashes in manifests.
- Never use `latest` as a reproducible Wikipedia input identifier.
- Build labels from actual Sakura converter full-reading N-best paths. Do not
  accept morphology, language-model output, or guessed readings as ground truth
  without forward verification and the documented tier rules.
- Keep train/dev/final-holdout immutable and leakage-safe. Never tune on the
  final holdout.

## Development and dependencies

- Keep Python/CUDA dependencies outside the Sakura Input production Cargo
  workspace.
- Create task-specific Python virtual environments under `~/tmp/`; never install
  packages globally or into the reserved `~/tmp/pdfvenv`.
- Do not hard-code credentials. If environment files become necessary, use
  dotenvx and commit only a non-secret example.
- Pin exact dependencies and artifact hashes once an experiment begins. Verify
  current official installation guidance before selecting a new PyTorch/CUDA
  stack.

## Verification

- Every non-trivial change needs executable `Verify:` steps and observable
  `Expect:` results.
- Use identical immutable candidate snapshots and denominators for model
  comparisons.
- Report failures, timeouts, stale results, and fallbacks in product metrics;
  never remove them from the denominator.
- Benchmark production candidates on Windows CPU with GPU disabled, batch one,
  one ORT intra-op/inter-op thread, warmup, and at least 10,000 measured runs.
- After tests or benchmarks, prove that repository-owned test, training, ORT,
  and worker processes have exited.

