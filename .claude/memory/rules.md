# Claude Code verified project rules

Durable procedures and tooling facts only. Experiment results, split-specific
measurements and machine timings live in `reports/`, `manifests/` and the
README (AGENTS.md); `journal.md` keeps the dated log. Re-read the linked report
before relying on any result it holds.

## Where past results live (read, do not copy here)

- Feature normalization, cost gap and the C1/C2 recipes:
  `reports/issue-21-retrain-experiment.json`.
- Confidence-gate harm budgeting: `reports/issue-25-confidence-gate.json`.
- Seed-ensemble gating and its latency: `reports/issue-27-ensemble-gate.json`.
- Distilled gated student: `reports/issue-29-distill-gate.json`.
- v1 latency under the same timing scope:
  `reports/issue-21-v1-latency-same-scope.json`.
- Frozen v5 context/reading/surface bounds (why `text[:64]` truncation was
  ruled out): `journal.md`, 2026-11-04 entry.

## Experiment method

- A few dev rows of difference are noise. Before calling a paired difference
  real, compute the exact McNemar threshold for the actual discordant count.
  Select epochs and thresholds on grouped train out-of-fold predictions, never
  on dev.
- Compare a new recipe with B0 retrained under the same no-dev protocol, not
  with a published prototype whose epoch was chosen on dev.
- Budget harm with the exact one-sided binomial test on cross-fitted train OOF.
  Choosing the smallest threshold whose selection-set harm sits at the limit
  overshoots on held-out rows, and dev is too small to resolve the harm limit
  except at zero harm (figures: `reports/issue-25-confidence-gate.json`).
- Cross-fitted distillation: outer fold k's teacher must never have trained on
  k. Train one model per fold pair {a, b} on the other folds and score both.
- Latency: never index an `np.load` NpzFile inside a timed loop, because each
  access re-reads the array. Build feeds first and time `InferenceSession.run`
  only. State the timing scope whenever comparing with older benchmarks.
- After a module change, regenerate the artifact and compare bytes instead of
  arguing equivalence. First confirm the current toolchain reproduces the
  previous bytes.
- Import the Issue #21 harness from `data/generated/issue-21-retrain/run.py`,
  because its `EXP.parents[2]` resolves to the repository only from there. A
  copied training loop must first reproduce the stored OOF logits bitwise.
- Pre-registration hashes: `plan_body_sha256` is the SHA-256 of the Issue
  `body` string as the REST API returns it. `gh api ... --jq .body` appends
  one newline, so strip exactly one before hashing.

## Verification and tooling

- Full suite: `PYTHONPATH=src ~/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe
  -m unittest discover -s tests`. Without `PYTHONPATH=src` most modules fail
  to import. Test classes that need torch carry
  `@unittest.skipUnless(importlib.util.find_spec("torch"), ...)`; a new one
  without that guard errors under a Python without torch (#92).
- This shell has no git identity. Commit with `git -c user.name=tsuyoshi-otake
  -c user.email=<owner-email>`, the identity of every direct commit here. Read
  the address with `git log -1 --format=%ae 1859098`. It is kept out of tracked
  text because the repository is public.
- PRs merge by squash with subject `<PR title> (#PR)`. A merge commit is used
  only when the owner asks for one, as for the #36-#77 stack (#79).
- Releases are source-and-evidence prereleases `v0.1.0-research.N` made by
  `gh release create --target <main sha> --prerelease` (lightweight tag, no
  assets). Before each one, leak-scan the notes and every Issue comment with a
  positive probe, and cross-check each quoted number against tracked reports.
- The repository is MIT-licensed (#23). This covers source and docs only:
  model manifests keep `license_status=not_selected_no_distribution_authorized`,
  and checkpoints and ONNX files stay undistributed.
- Devin in sakura-tmux: `capture-pane` returns empty output, `-p` with
  `--permission-mode auto` exits after rejecting an exec call, and pwsh
  `Tee-Object` stores UTF-8 output as CP932 mojibake. Embed the source in the
  prompt and read results from a file. Send-keys a pwsh line that runs
  `devin.exe -p --prompt-file <md> --model swe-2-high --permission-mode auto
  --respect-workspace-trust false | Tee-Object <out>`, then `Set-Content <done>
  $LASTEXITCODE`, and wait for the done file.
- Local `main` lags after a remote merge. When a tracked file is modified in
  the tree, run `git branch -f main origin/main` (after an ancestor check)
  before `git switch main`.

## Public-repository hygiene

- Leak-scan an Issue with `gh issue view <n> --json body,comments` (or the
  REST API). Non-TTY plain output prints only the body, and `--comments` prints
  only the comments.
- Leak scans through the Bash tool can lose backslashes, so patterns for
  JSON-escaped Windows paths silently match nothing. Always add backslash-free
  probes for user paths, the repository path and the account name. Run a
  positive control that must hit, and build literal backslashes with
  `chr(92)`. Scan for case-level identities as well: URLs and names that reveal
  which rows were audited belong under ignored `data/generated/`, not in
  reports (#85).
- Verbatim leak checks over Japanese prose flag generic vocabulary. Scope them
  to task-added content, and adjudicate each residual hit by location, length
  and SHA-256 instead of editing published text.
- Evidence written on Windows can be hash-pinned over CRLF or mixed line
  endings while `* text=auto` stores LF. Compare each pin with the staged blob
  (`git show :<path> | sha256sum`). Keep a pinned file byte-exact with a
  per-file `-text whitespace=cr-at-eol` attribute, and edit it at the byte
  level in its own line-ending style.
- Before redacting a tracked research file, look up its SHA-256 and git blob
  ID in reports and manifests. A pinned script is evidence and is not edited
  just to tidy its text.
- GitHub closing keywords fire on prose that does not mean completion. Commit
  messages ("fixed #41 training inputs") close issues, and so does the body of
  a stacked PR whose base is main, because GitHub auto-marks it merged ("does
  not close #31" closed #31). The landing PR's `closingIssuesReferences` lists
  only the commit-message hits. Before landing, grep commit messages and every
  base-main PR body for `(close|fix|resolve)\w* #N`, and reopen any open issue
  that closes, with an explanatory comment. In PR bodies write "Refs #N; stays
  open", never "does not close #N".
