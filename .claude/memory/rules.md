# Claude Code verified project rules

- The frozen v5 train/dev `left_context` is already bounded to at most 64
  characters upstream (max 64, p75 64 in both splits), so `research_tiny`'s
  `text[:64]` head slice drops nothing. Readings and candidate surfaces are all
  at most 32 characters. Do not re-investigate truncation for this split.
- `research_tiny.candidate_features` min-max normalizes local cost per row,
  which hides the absolute rank-1/rank-2 cost gap (train quintile baseline
  accuracy 57% -> 100%). Adding the gap alone (Issue #21 C1) gained OOF rows
  but no seed reached McNemar p < 0.16; only gap + scorer dropout 0.1 + label
  smoothing 0.05 (C2) passed. Verified 2026-11-04 by
  `reports/issue-21-retrain-experiment.json`.
- Dev differences of a few rows are noise: with ~60 discordant rows a paired
  comparison needs net >= 18 rows for exact McNemar p < 0.05. Select epochs and
  thresholds on grouped train out-of-fold predictions, not on dev.
- Compare a new recipe with B0 retrained under the same no-dev protocol, not
  with the published v1 prototype: its epoch was the best of 20 on dev (dev
  top-1 by epoch 1,618-1,640), while B0 seed 20260814 under OOF selection
  reached 1,629. Verified 2026-11-04.
- Harm thresholds: choosing the smallest tau whose selection-set harm is at
  the 0.25% limit overshoots on held-out rows (Issue #21 rule cross-fitted to
  harm 29/29/27 against 27). Budget harm with the exact one-sided binomial test
  instead (k_max 18 on 11,120 baseline-correct rows). Dev's 1,586
  baseline-correct rows can show harm < 0.25% only at zero harm, so judge harm
  limits on cross-fitted train OOF, not dev. Verified 2026-11-04 by
  `reports/issue-25-confidence-gate.json`.
- Ensembles: averaging the three C2 seeds' logits raises gated rescue at the
  same exact-binomial harm budget (cross-fit harm 15 / rescue 200 against the
  single models' 17-19 / 156-185), but model-only latency scales with the
  member count: one FP32 ONNX graph of three r2 models measured p95 2.211 ms
  against 0.704 ms for r2 alone on the same box (INT8 1.971 ms). Do not plan a
  three-member r2-size FP32 ensemble under the 2 ms p95 bar; distil instead.
  Verified 2026-11-04 by `reports/issue-27-ensemble-gate.json`.
- Distillation works here: one C2 student trained with 0.5 x C2 loss + 0.5 x
  T^2 x KL to the 3-seed ensemble (T = 2) passed the gate criteria for all
  three seeds (cross-fit harm 21/19/21, RER 12.97/13.90/12.11%) at r2 latency
  (FP32 p95 0.661 ms), and raised ungated OOF top-1 (11,456-11,470 vs
  11,416-11,432). For cross-fitted distillation, outer fold k's teacher must
  never have trained on k: train one model per fold pair {a, b} on the other
  three folds (10 per seed) and score both a and b. Verified 2026-11-04 by
  `reports/issue-29-distill-gate.json`.
- Import the Issue #21 harness from `data/generated/issue-21-retrain/run.py`
  (byte-identical to the tracked copy, sha d0e24a57...): its `EXP.parents[2]`
  only resolves to the repo from there. A copied training loop proves itself
  by reproducing #21's stored OOF logits bitwise (fold 0, epochs 1-2, ~7 s).
  On this box a 20-epoch C2 fold model takes ~20 s (3/5 rows) to ~25 s (4/5).
  Verified 2026-11-04 (#29 parity.json).
- Pre-registration hashes: `plan_body_sha256` is the SHA-256 of the Issue
  `body` string as the REST API returns it. `gh api ... --jq .body` appends one
  newline, so strip exactly one trailing newline before hashing. Verified
  2026-11-04 on Issue #27 (531393e6...).
- Never index an `np.load` NpzFile inside a timed loop: each access re-reads
  the array. v1 `research_tiny.benchmark_onnx` does this, so its published
  latency is inflated (same machine: 4.07 ms p50 vs 0.51 ms model-only). Build
  feeds before timing and time `InferenceSession.run` only. Verified
  2026-11-04 by `reports/issue-21-v1-latency-same-scope.json`.
- `research_tiny_r2` regeneration on this box (RTX 4060 Ti, torch
  2.12.1+cu130, deterministic algorithms) is byte-for-byte reproducible:
  sidecar, checkpoint, and FP32/INT8 ONNX were identical across three runs,
  and exporting under a temporary file name does not change ONNX bytes. After a
  module change, regenerate and compare bytes instead of arguing equivalence
  (about 1 minute). Verified 2026-11-04.
- Devin in sakura-tmux: `capture-pane` returns empty output, `-p` with
  `--permission-mode auto` exits after rejecting an exec call, and pwsh
  `Tee-Object` stores its UTF-8 output as CP932 mojibake. Embed the source in
  the prompt (a 140 KB prompt worked) and read results from a file: send-keys a
  pwsh line that runs `devin.exe -p --prompt-file <md> --model swe-2-high
  --permission-mode auto --respect-workspace-trust false | Tee-Object <out>`,
  then `Set-Content <done> $LASTEXITCODE`, and wait for the done file.
  Verified 2026-11-04 (sessions devin-r2, devin-r2-fix).
- Scan a GitHub Issue for leaks via `rtk gh issue view <n> --json
  body,comments` (or the REST API). Non-TTY `gh issue view` prints only the
  body and `--comments` prints only the comments, so either plain output
  silently drops half the Issue. Verified 2026-11-04 on Issue #21 (plain view
  24/24 body lines and 0/31 comment lines; `--comments` the reverse).
- Verbatim leak checks over Japanese prose flag generic vocabulary: a 6-char
  train `gold_surface` matched a common katakana term in the Issue #21 plan,
  and single English words occur in jawiki contexts as 12-grams. Scope leak
  checks to task-added content and adjudicate each residual hit by location,
  length, and SHA-256 instead of editing published text. Verified 2026-11-04.
- This shell has no git identity (`~/.gitconfig` holds only safe.directory and
  http.sslBackend). Commit with `git -c user.name=tsuyoshi-otake -c
  user.email=<owner-email>`, the identity of every direct commit here (read
  the address with `git log -1 --format=%ae 1859098`; it is kept out of
  tracked text because the repository is public); GitHub squash merges record
  `Tsuyoshi Otake <owner-email>`. Verified 2026-11-04 (commit 1859098, squash
  a0a3cfe).
- Releases here are source-and-evidence prereleases `v0.1.0-research.N` made
  by `gh release create --target <main sha> --prerelease` (lightweight tag, no
  assets); PRs merge by squash with subject `<PR title> (#PR)`. Verified
  2026-11-04 (v0.1.0-research.1, .2, and .3; PRs #22 and #30). Before each
  one, leak-scan the notes and every Issue comment with a positive probe, and
  cross-check each quoted number against the tracked reports.
- The repository is MIT-licensed since 2026-11-04 (#23, squash 5ba9845; GitHub
  licenseInfo `mit`). It covers source and docs only: model manifests keep
  `license_status=not_selected_no_distribution_authorized`, and checkpoints and
  ONNX files stay undistributed. Verified 2026-11-04.
- Full suite: `PYTHONPATH=src ~/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe
  -m unittest discover -s tests` (1095 tests, ~76 s, torch 2.12.1+cu130). Without
  `PYTHONPATH=src` 112 modules fail to import; under the global Python 3.13
  (numpy, no torch) `test_language_pretraining.TiedLanguageHeadTests` errors 3
  times because its `setUp` imports torch without a skip guard. Verified
  2026-11-08 on b8479e2 and main 4159fd9.
- GitHub closing keywords fire on prose that does not mean completion, from two
  sources when a PR stack lands on main: commit messages ("fixed #41 training
  inputs" in 0f68712 closed #41), and the description of any stacked PR whose
  base is main, which GitHub auto-marks merged — "This PR stays draft and does
  not close #31" in #36 closed #31. The landing PR's `closingIssuesReferences`
  listed only the commit-message hits (#29, #41), not #31. Before landing, grep
  commit messages and every base-main PR body for `(close|fix|resolve)\w* #N`,
  then reopen any open issue that closes with an explanatory comment. Never
  write "does not close #N" in a PR body; write "Refs #N; stays open". Verified
  2026-11-08 (#79, #78).
- Leak scans through the Bash tool: backslashes in regex or bytes patterns
  can be collapsed, so a pattern for JSON-escaped Windows paths silently
  matched nothing and reported zero hits on four reports that each held one
  absolute user path. Always add a backslash-free positive probe (`grep -n -i
  users`, `grep -n -i develo`) and build literal backslashes with `chr(92)`.
  Verified 2026-11-08 (#80).
- Evidence written on Windows can be hash-pinned over CRLF or mixed line
  endings while `* text=auto` stores LF. Compare each pin with the staged blob
  (`git show :<path> | sha256sum`); keep a pinned file byte-exact with a
  per-file `-text whitespace=cr-at-eol` attribute. Verified 2026-11-08 (#80).
- The #36-#77 draft stack (230 commits) landed by one merge-commit PR (#79,
  4159fd9) at the owner's request, an exception to the squash convention so
  that per-commit research history survives. Local `main` lags after a remote
  merge; with a modified tracked file in the tree, run `git branch -f main
  origin/main` (after an ancestor check) before `git switch main`. Verified
  2026-11-08.
