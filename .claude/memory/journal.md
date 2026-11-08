# Claude Code journal (append-only)

## 2026-11-03 — Issue #20 follow-up: where the research prototype can still improve

- Context: Issue #20 closed the no-retraining weight-edit lane (best: +1 dev row,
  noise). Owner asked whether the model can still be improved. HEAD `b4b21b0`.
  Inputs verified by SHA-256: FP32 ONNX `b3fe1e0a…`, numeric cache `41eb7f59…`,
  frozen v5 split `0651bfaa…`. Final holdout rows were skipped unread.
- Symptom: dev 1,640/1,788 correct (local order 1,586), harm 23, rescue 77;
  dev harm rises 23 -> ~50 after epoch 3 while train loss keeps falling.
- Findings (aggregate only, reproduced with the existing FP32 ONNX):
  - Dev error budget 148 = 8 no-gold + 23 harm + 117 not rescued; in 106 of
    the 117 the model kept the local first candidate, and 67 had gold ranked 2.
    Train rescues only 644 of 1,346 rescuable rows even in-sample.
  - Margin abstention (override only if score gap > tau): dev tau 1.4 gives
    harm 3 (meets 0.25%) but 1,612 correct; train-selected tau 0.8 gives dev
    1,627 / harm 9. Harm gate is reachable only by giving up ~60% of rescues.
  - Absolute local-cost gap (rank 2 minus rank 1) is strongly predictive:
    train quintile baseline accuracy 57% / 90% / 97.5% / 99.6% / 100%. The
    model's per-row min-max cost normalization removes this magnitude. All dev
    net gain (+56) sits in the smallest-gap quintile; quintiles 2-5 are net -2
    on dev (harm 10, rescue 8) but +72 in-sample on train.
  - Refuted: left-context head truncation (`text[:64]`) drops nothing because
    contexts are already <= 64 chars; no reading/surface exceeds 32 chars;
    source_category is system_dictionary for 99.8% of candidates and 100% of
    gold. Character hashing shares IDs for 17.8% of character tokens, but no
    train/dev row has two candidates with identical model inputs.
  - Label ceiling: v5 AI-teacher audit found 174/3,576 final-holdout rows
    invalid (166 ambiguous), at similar rates for local-correct (154/3,176)
    and local-wrong (20/400) strata.
  - Noise threshold: with ~60 discordant dev rows, a paired change needs net
    >= 18 rows (exact McNemar, p < 0.05).
- Devin (SWE-2 High, read-only, source embedded in prompt) ran in sakura-tmux
  session `devin-rerank`; 9 findings, of which the cost-normalization finding
  was the only one confirmed by data. Session closed and process exit verified.
- Tooling learnings: sakura-tmux `capture-pane` returned empty output, so route
  agent output through files; Devin `-p` with `--permission-mode auto` rejected
  an exec tool call and exited with only a warning, so embed sources in the
  prompt; pwsh `Tee-Object` stored Devin's UTF-8 output as CP932 mojibake,
  repaired with `text.encode('cp932', errors='replace').decode('utf-8', errors='replace')`.
- Evidence and scripts: `~/tmp/rerank-improve-20261103/` (diagnostics JSON,
  feature-signal JSON, Devin review). No repository code changed.
- Status: awaiting owner decision on research-only retraining (grouped
  train CV for selection, absolute cost-gap feature, OOF-selected abstention).

## 2026-11-04 — Issue #21: pre-registered retraining, C2 adopted, revision 2 exported

- Plan (owner approved): B0 = v1 recipe, C1 = B0 + absolute cost-gap feature
  `-log1p((cost_i - min cost)/1000)`, C2 = C1 + scorer dropout 0.1 + label
  smoothing 0.05 over valid candidates; seeds 20260814/20261103/20261104;
  epochs and tau frozen from grouped 5-fold OOF on train; one dev evaluation;
  mechanical adoption. Base HEAD `b4b21b0`. Final holdout never read.
- Result: OOF mean correct / harm B0 11,371.3 / 328.7, C1 11,396.0 / 300.0,
  C2 11,424.0 / 265.7; dev mean B0 1,624.3 / 50.7, C1 1,632.3 / 42.7,
  C2 1,637.3 / 39.3. C1 rejected (McNemar p >= 0.16 every seed); C2 adopted
  (p = 0.0028 / 0.064 / 0.0075). Independent recomputation matched everything.
- Integration: v1 `research_tiny.py` is hash-bound by its manifest, so the
  recipe went into new `research_tiny_r2.py` (deviation from the plan's
  "edit research_tiny.py"). Seed 20260814 / 9 epochs reproduces the harness
  checkpoint tensor for tensor; dev 1,639 correct / 38 harm / 91 rescue.
  FP32 ONNX top-1 equals PyTorch on all 1,788 dev rows; INT8 changes 3 top-1
  choices with identical counts. CPU batch-one p95 0.67 ms (FP32).
- Caveat: vs the published v1 prototype (1,640 / 23, epoch picked on dev) r2 is
  -1 correct / +15 harm; vs same-protocol B0 seed 20260814 (1,629 / 50) it is
  +10 / -12. Unmet: harm rate 2.40% (0.25%), rescue/harm 2.39 (3). Gates A/B/C
  false; no production change.
- Review: Devin (sakura-tmux, sessions devin-r2 and devin-r2-fix) found 1 major
  (report subtrees copied into published outputs unvalidated) + 9 minor, then
  4 minor on the fix (untyped leaves let `false` pass as 0, unlink masking,
  identical export paths, experiment flag). Fixed with exact typed shapes,
  canonical-JSON comparison, pair-atomic ONNX publish, recursive forbidden-key
  check on every written document; `training_eligible` kept (v1 uses the same
  predicate, research_tiny.py:212).
- Root cause found on the way: v1 `benchmark_onnx` starts its timer before
  `feed()` indexes the lazily loaded NpzFile (8 arrays per run). Same machine:
  v1 loop p50/p95 4.07/4.50 ms vs model-only 0.51/0.67 ms. v1's p95 miss is an
  artifact; README tables now carry a note; three-model comparison reuses the
  inflated value (follow-up, not changed here).
- Verification: full unittest 255 OK (train-env Python); git diff --check 0;
  prepare/train/export regenerated twice after the review fixes with
  byte-identical sidecar, checkpoint, and ONNX; publish-evidence wrote
  `manifests/sakura-rerank-tiny-v1-research-r2.json` (module sha256 `c2ede357…`)
  and `reports/sakura-rerank-tiny-v1-research-r2.json`; Issue #21 comment
  6607872676. Not committed (owner has not asked); commit SHA: none yet.

## 2026-11-04 — Issue #21 goal-loop iteration 1: verifier failed C6

- fail: rubric-verifier passed C1-C5, C7, C8 and failed C6: gold_surface hits 0,
  but left_context 12-gram hits 3 (README.md 2, untracked
  `.claude/goal-loop/issue-21-retrain/rubric.md` 1). Verifier noted the README
  hits lie before this task's inserted section and the rubric hit is a common
  English word.
- investigate (own scan; counts, line numbers, and booleans only):
  - README.md: both hits (lines 99 and 106) are already in `git show
    HEAD:README.md`. The 111 lines this task added to README.md, the added lines
    of `reports/README.md` and `tests/test_generated_reports.py`, and every new
    file have 0 gold and 0 12-gram hits. Line 99 is one ASCII English word; line
    106 is a multi-word ASCII English heading, both pre-existing.
  - rubric.md line 11: one pure-ASCII English word, present in 1 train/dev row.
  - New finding the verifier missed: the Issue #21 body (the pre-registered
    plan written by this task), line 15, column 57, contains one 6-character
    katakana generic technical term that equals the `gold_surface` of 1 train
    row. It completes the phrase for the deterministic-algorithms training
    setting; it was not copied from a row, and no train/dev context 12-gram
    occurs in the Issue body.
  - Root cause of the miss: non-TTY `gh issue view 21` prints only the body and
    `gh issue view 21 --comments` prints only the comments. The verifier scanned
    the `--comments` output (4,207 bytes), so the body was never checked.
- verify: the plain view holds 24/24 nonblank body lines and 0/31 comment lines;
  `--comments` holds 0/24 and 31/31; `--json body` equals the REST API body
  (1,681 characters). The 7 prompt files sent to Devin and the 7 Devin outputs
  have 0 gold and 0 12-gram hits and never mention the split file.
- fix: C6 rewritten. Scope = task-added content only (new files, `git diff -U0
  HEAD` added lines, Issue #21 body and comments via `--json`, Devin prompts).
  `.claude/goal-loop/` is excluded as local verifier instructions with machine
  paths that are never committed or sent. A pure-ASCII single-word 12-gram match
  is a common English word; every other match must be listed in an adjudication
  table by location, length, and SHA-256, and the verifier confirms its context.
  The pre-registered Issue body is not edited.
- verify (iteration 2): a fresh rubric-verifier passed all 8 criteria (C1-C8).
  C6 scanned 407 scope items against 596 gold surfaces and 392,657 context
  12-grams; the only non-word hit was adjudication entry 1, confirmed by
  location, length, SHA-256, and context.
- cleanup: removed both verifier scratch directories (13 + 7 files), the 9 early
  diagnostic files in `~/tmp/rerank-improve-20261103/`, and all 36 scratchpad
  files (Devin prompts and outputs, diffs, logs). Kept
  `~/tmp/rerank-improve-20261103/train-env` (3.0 GB; recovery handle and test
  env) and the ignored evidence directories `data/generated/issue-21-retrain/`
  (121 MB) and `data/generated/sakura-rerank-tiny-r2-research/` (17 MB) that the
  tracked reports bind by SHA-256. `~/tmp/rerank-improve-20261103/venv` (12 MB)
  remains because its deletion was denied earlier. Process audit: no
  task-owned process or tmux session alive. Commit SHA: none (not committed).

## 2026-11-04 — Issue #21: commit, squash merge, and prerelease v0.1.0-research.2

- request: 「OKリリースまで頼むよ」 (merge and release authorized by the
  personal-repository rule).
- pre-release safety checks, run in parallel: 129 tracked + new files had no
  email, local path, UUID, or token; all 64 historical commits use the owner
  identity `<owner-email>` (57 direct, 7 GitHub squash merges); the repo is
  PUBLIC with one prior prerelease `v0.1.0-research.1` (lightweight tag at
  b4b21b0, no assets); there is no LICENSE file, as at the prior release whose
  notes state that no distribution license has been selected, so none was
  added and no artifact was attached.
- finding: this shell has no git identity (`~/.gitconfig` holds only
  safe.directory and http.sslBackend; no system, local, or GIT_* identity), so
  a plain `git commit` would fail or auto-detect a machine identity. Committed
  with `-c user.name=tsuyoshi-otake -c user.email=<owner-email>`, matching
  the repository history.
- result: commit 1859098 (14 paths, 3,718 insertions) on branch
  issue-21-retrain -> PR #22 -> squash merge a0a3cfe on main (parent b4b21b0,
  tree equal to 1859098; author Tsuyoshi Otake <<owner-email>>, committer
  GitHub) -> Issue #21 closed by the PR -> prerelease v0.1.0-research.2
  (lightweight tag at a0a3cfe, 0 assets) -> completion comment on Issue #21.
- verification: 255 unit tests OK before the commit and again on main at
  a0a3cfe; staged set equal to the 14 expected paths, 0 binaries, no data/
  paths, cached diff-check clean, generated artifacts ignored; no python
  survivors.
- cleanup: local and remote issue-21-retrain branches deleted after the tree
  equality check; local main fast-forwarded (it was 34 commits behind).
- verify (release rubric `.claude/goal-loop/issue-21-release/rubric.md`, 1
  iteration): a fresh rubric-verifier passed R1-R6: main a0a3cfe has parent
  b4b21b0 and the PR head tree with exactly 14 paths; 255 tests OK at the tag;
  no data/ or binary path, 0 release assets, tags v0.1.0-research.1 -> b4b21b0
  and v0.1.0-research.2 -> a0a3cfe; no email except the Co-Authored-By
  noreply, no local path, UUID, or token; every release-note number matches the
  reports; Issue #21 closed with the completion comment, PR #22 merged, no
  issue-21-retrain branch, and only pre-existing entries in git status.
- cleanup: deleted the release verifier's scratch directory (263 files of
  exported public tree and fetched JSON) and the 8 release temp files.
  Commit SHAs: branch 1859098, main a0a3cfe; release v0.1.0-research.2.

## 2026-11-04 — Issue #23: MIT license

- request: 「LICENSEはMITでいいよ」.
- decision: MIT covers the repository's source and documentation. Model
  artifacts (trained on Japanese Wikipedia text, generally CC BY-SA 4.0/GFDL,
  and Sakura Input dictionary and converter output) are not covered; the
  hash-bound model manifests keep
  `license_status=not_selected_no_distribution_authorized`. No new release was
  cut, so the v0.1.0-research.1/.2 tags predate the LICENSE.
- result: LICENSE copied byte for byte from the owner's activity-monitor repo
  ("Copyright (c) 2026 Tsuyoshi Otake", the holder form in 17 of the owner's 20
  self-held MIT licenses); README licensing text updated in 3 places; commit
  26072b1 -> PR #24 -> squash 5ba9845 (parent a0a3cfe, tree equal); Issue #23
  closed; GitHub licenseInfo = mit.
- verification: 255 tests OK; diff-check clean; the LICENSE blob is LF-only and
  equals its source; local and remote branches deleted; no test survivors.

## 2026-11-04 — Issue #25: pre-registered confidence gate on r2 (not adopted)

- request: 「確信度ゲートの事前登録計画を作って」「devinは使わないで」「精度向上を目指してすすめてね」.
- plan: Issue #25 (created 2026-11-03T17:40:32Z, body SHA-256 461190b3…3b99), verified 6/6 by a fresh rubric verifier before publication (gap fixed: argmax tie-break and float64 spelled out; reference rule pinned to score L). Leak scan over 14,304 train/dev rows: 0 hits.
- design: cross-fit on the existing Issue #21 per-epoch OOF logits (no training, no dev in the decision); score L (logit diff) or P (softmax diff) chosen in the inner folds by rescue; tau = smallest grid value with harm <= k_max(N), the exact one-sided binomial budget (18 on 11,120 baseline-correct rows, 14 on the ~8,900 inner rows, 0 on dev's 1,586).
- result: main rule harm 19/17/18, rescue 156/170/185, RER 9.81%/10.96%/11.96% -> seed 20260814 fails RER by 3 rows of net gain (137 vs 140) -> not adopted. Issue #21's boundary rule cross-fitted to harm 29/29/27 (two seeds over 27), confirming that choosing tau at the selection limit overshoots. P-only (reference) passed all seeds (RER 10.03/10.89/12.03%) but is only a hypothesis. Dev reference: harm 3/2/1, RER 12.87/14.85/14.36%; INT8 gated decisions identical to FP32 on all 1,788 dev rows.
- verification: synthetic checks (k_max, Clopper-Pearson tails exactly 0.025, gate semantics); independent recomputation written by a separate agent from the Issue body only matched every fold/tau/total/final gate/dev count (publish refuses otherwise); new report test fails on 3 mutations (adopted flag, rescue total, harm budget); 256 tests OK; diff-check clean.
- learning: my remembered CP(5,100) bounds were wrong in the 6th digit; validate interval code against exact tail probabilities, not memory.

## 2026-11-04 — Issue #27: pre-registered seed ensemble + confidence gate (not adopted, latency only)

- request: 「コミットとマージして、アンサンブルの事前登録に進んで」→「うん、続けて」 (no Devin).
- plan: Issue #27, body SHA-256 531393e6…a8f3 (the REST `body`; `gh api --jq .body` adds one newline that must be stripped before hashing). Model = float64 mean of the three C2 seeds' logits; gate/tau/epoch/counting imported from the hash-pinned #25 `run.py`; five criteria: harm <= 27, rescue >= 3 x harm, RER >= 10% (cross-fitted train OOF, written before dev), FP32 ensemble ONNX p95 <= 2 ms, FP32 ONNX decisions equal stored on all 1,788 dev rows.
- result: cross-fit main harm 15 (0.135%, CI 0.076-0.222%), rescue 200, RER 13.25% (all accuracy criteria pass; single models in #25: harm 19/17/18, rescue 156/170/185). Final gate P 0.78. FP32 parity 0 mismatches. FP32 ensemble p95 2.211 ms vs r2 single 0.704 ms (3.1x) -> criterion 4 fails -> not adopted. References: INT8 p95 1.971 ms with 1 dev decision mismatch vs FP32; fixed_L 18/192, fixed_P 19/200, #21 rule 28/245 (over 27); dev harm 2, rescue 31, RER 14.36% (one-sided p 0.243, so dev cannot confirm the limit).
- verification: independent sonnet agent wrote recompute.py from the Issue #25/#27 bodies only (its single-seed run reproduced the #25 report) and matched every fold epoch/score/tau/total, the final gate, criteria 1-3, and dev counts; publish refuses otherwise. New report test killed 12/12 mutations; k_max moved to one module-level helper shared by the #25 and #27 tests. 257 tests OK; diff-check clean; leak scan 0 on all added content and on the Issue comment. Fresh rubric-verifier (`.claude/goal-loop/issue-27-ensemble-gate/rubric.md`) passed E1-E8 in 1 iteration, including its own numpy recount of the final-gate train (18/191) and dev (2/31) outcomes.
- next (per the plan, speed-only failure): pre-register distilling the ensemble into one model.
- not yet committed (branch issue-27-ensemble-gate); results comment posted on Issue #27.

## 2026-11-04 — Issue #27 merged; Issue #29: distilled ensemble + gate (adopted as research candidate)

- request: 「うむ」 to 「マージして蒸留の事前登録へ」.
- #27 merge: commit f71a38d -> PR #28 -> squash 41cc9d4 (parent 0ac46d1, tree equal); Issue #27 auto-closed; local and remote branches deleted.
- plan: Issue #29, body SHA-256 93f0ccc4…a22d, verified P1-P6 by a fresh rubric verifier (`.claude/goal-loop/distill-gate-plan/rubric.md`) before posting. Student = Issue #21 C2 recipe with loss 0.5 x C2 + 0.5 x T^2 x KL(teacher || student), T = 2; teacher = 3-seed mean; cross-fit teachers nested so outer fold k's teacher never trained on k (one C2 per fold pair, 10 per seed, seed + 1,000,003 x (6 + pair)); final teacher = #21 OOF at 9/8/10; five #27-style criteria, all three student seeds must pass 1-3.
- verifier gap closed before registration: its weight-0 check short-circuited, so I re-ran the real `distillation_loss` at weight 0 on synthetic tensors (CPU and CUDA): loss and gradient bitwise equal to the #21 C2 loss.
- result: parity bitwise (fold 0, epochs 1-2, diff 0). Cross-fit main harm 21/19/21, rescue 202/213/190, RER 12.97/13.90/12.11% (all pass; #25 single 9.81/10.96/11.96%). Final student epoch 15, gate L 1.7; FP32 p95 0.661 ms (r2 0.697 ms), parity 0 mismatches, INT8 p95 0.710 ms with 0 mismatches -> adopted as a research candidate (r2 manifest unchanged; Gates A/B/C false). Ungated OOF top-1 11,456/11,457/11,470 vs C2 11,416/11,424/11,432. Dev reference harm 3, rescue 39, RER 17.82% (p 0.440). Residual risk: harm 95% upper bounds 0.289/0.267/0.289% exceed 0.25%; the criterion is a point estimate.
- timing: teachers 30 runs in ~10.4 min, students 15 runs in ~6.3 min, final + export + benchmarks ~1 min.
- verification: independent sonnet recompute (Issue bodies + arrays only; its #25 self-check reproduced all 12 seed x rule cross-fits) matched teacher epochs, every seed/rule cross-fit, final epoch/gate, criteria, dev counts; report test kills 15/15 mutations; `criteria_1_to_3` moved to a shared module helper; 258 tests OK; leak scan 0 unadjudicated (my re-created scan regex first failed to compile and then silently missed backslash paths — fixed and proven with a positive probe); fresh rubric verifier E1-E8 pass. After execution only `stage_publish` changed in run.py (parity passthrough; teacher `rows` -> `row_count` because `rows` is a forbidden report key).
- learning: a forbidden-key collision should be fixed by renaming the report key, not by loosening the test's forbidden set.
- not yet committed (branch issue-29-distill-gate); results comment posted on Issue #29.

## 2026-11-04 — Issue #29 merged and released as v0.1.0-research.3

- request: 「うん、リリースまで頼むよ。Issueも更新しといて」.
- merge: PR #30 squash -> main 20fcf527 (tree equals reviewed head 7472f3d); Issue #29 closed; branches deleted; 258 tests OK on main.
- pre-release checks (run in parallel, all clean): tracked files have no emails/local paths/UUIDs/tokens; history identities only <owner-email>, GitHub noreply, Claude noreply; repo PUBLIC + MIT; earlier tags research.1 b4b21b0 and research.2 a0a3cfe.
- release: `gh release create v0.1.0-research.3 --target 20fcf527 --prerelease` (no assets). Notes and both Issue comments leak-scanned (0 dataset hits, 0 PII; positive path probe detected) and every quoted number cross-checked against the #25/#27/#29 reports and README.
- Issues: final comment on #29 (merge SHA + release link); progress comment on #1 (#21/#23/#25/#27/#29 table, dev top-1 baseline 0.88702 / gated 0.90716 / ungated 0.91890, Gate A still failed). #1 stays open.
- verification: fresh rubric verifier on `.claude/goal-loop/release-research-3/rubric.md` (R1-R7).
- verifier result: R1-R7 pass in 1 iteration (tag -> 20fcf527, 0 assets, three prereleases; every quoted number traced to a report; 0 PII matches; 258 tests OK; 0 process survivors).

## 2026-11-07 — #29 product-swap feasibility under Sakura Input protocol v1 (investigation, no product change)

- request: 「蒸留モデルは research candidate として採用済みだから、残るは製品に載せるかの判断と統合の手間、頑張れない?」.
- finding (product state): Sakura Input HEAD bcf42d3 (2.0.27) already ships Tiny-v1 research prototype (model SHA b3fe1e0a…) via protocol v1, owner-approved MIT distribution + installer bundling on 2026-08-14 (`docs/decisions/issue-32-reranker.md`), default scope `LongTextOnly`. Its scorer feeds empty reading/context and only features 0/1/3. #29 student needs 7 features (adds cost gap 6) and was evaluated with reading + left context + features 2/4/5, which protocol v1 cannot carry.
- experiment (inference only, dev reference, fixed gate L tau 1.7, no fit/selection): parity first — #29 full inputs reproduce 1622/harm 3/rescue 39/overrides 45 and v1 full reproduces 1640. Under the protocol-v1 projection (no reading/context, features {0,1,3,6}): #29 gated 1611 (90.10%), harm 3, rescue 28. Shipped v1 under its product projection (ungated argmax; the product's protected evidence-group selection NOT reproduced because dev lacks native evidence tags): 1630 (91.16%), harm 14, rescue 58. Paired: v1-only correct 36 vs #29-only 17, exact McNemar p 0.0127. Reading/context are worth only 11 dev rows to #29 (1611 -> 1622).
- conclusion: swapping v1 -> #29 is a safety trade (harm 14 -> 3, the only one meeting the 0.25% point rule) that loses ~19 dev top-1 rows, not an accuracy upgrade. Protocol v2 (reading/context) would not recover v1's top-1. Product swap needs a fresh owner approval (distribution + installer + default scope); approval for v1 does not extend.
- evidence: ignored `data/generated/product-swap-ablation-20261107/` (script, McNemar helper, ablation.json). Venv `~/tmp/rerank-improve-20261103/venv` (numpy 2.3.5, ORT 1.23.2). No python survivors (tasklist). Commit SHA: none.
- learning: "research candidate adopted" was measured against the unchanged local order, never against the shipped product model in its product input projection; check the shipped baseline before calling a candidate a product upgrade.

## 2026-11-08 — Uncommitted-file triage and main-merge readiness of the #36-#77 stack (investigation, no repo change)

- request: 「あら未コミットあるの?」「mainにマージできないの?」.
- finding (uncommitted, none from this session): (a) AGENTS.md/CLAUDE.md shortened (-181 lines, verified-chain hashes removed; author unknown); (b) 2026-11-03 weight-edit study (rules.md +35, 2 manifests, 4 reports) intentionally left uncommitted per committed `research/accuracy-reassessment-20261104.md:13`; (c) `.claude/` memory + 9 goal-loop rubrics, not ignored (unlike `.codex/goal-loop/`); (d) root `jawiki_300_audit_reviewed.jsonl` (300 rows, Aug 13) carries Wikipedia `left_context` text, so it must not be committed.
- finding (merge): current branch = PR #77, top of 36 stacked draft PRs (#36 base main ... #77). origin/main 20fcf52 is an ancestor of HEAD b8479e2 (230 commits ahead), all PRs MERGEABLE/CLEAN, no CI checks. PR bodies say each "stays draft and does not close" its issue.
- verification: `PYTHONPATH=src <train-env python> -m unittest discover -s tests` -> 1095 OK in 76 s; tasklist shows no python survivors. Global Python 3.13 (no torch) gives 3 errors in `test_language_pretraining.TiedLanguageHeadTests` because `setUp` imports torch without a skip guard.
- learning: full-suite verification here needs `PYTHONPATH=src` and `~/tmp/rerank-improve-20261103/train-env/.venv/Scripts/python.exe` (torch 2.12.1+cu130, numpy 2.3.5); without `PYTHONPATH=src`, 112 modules fail to import.
- Commit SHA: none.

## 2026-11-08 — Landed the #36-#77 research draft stack on main (#78, PR #79)

- request: 「mainにマージできないの?」; owner chose one merge-commit PR and committing the condensed AGENTS.md/CLAUDE.md.
- action: committed 45ada90 (AGENTS.md/CLAUDE.md only, identity tsuyoshi-otake <<owner-email>>); opened #79 main <- issue-33-knbc-screening-v1; merged with a merge commit -> main 4159fd9 (230 stack commits + 45ada90 + merge). Closed 35 superseded drafts (#37-#77) with a pointer to #79; #36 auto-marked merged.
- symptom: the merge closed open research issues #41 and #31.
- root cause: GitHub closing keywords in prose. "fixed #41 training inputs" (commit 0f68712) was listed in #79 closingIssuesReferences ([29, 41]); "does not close #31" in the #36 body fired when #36 was auto-marked merged and was NOT listed in #79 closingIssuesReferences. #29 was already closed.
- fix: reopened #31 and #41 with explanatory comments.
- verification: unittest 1095 OK on b8479e2 and again on main 4159fd9 (train-env python, PYTHONPATH=src); main tree == 45ada90 tree (2d25774); fresh rubric-verifier (sonnet) R1-R6 all pass; no python survivors.
- learning: promoted to `.claude/memory/rules.md` (suite command; closing keywords in commit messages and base-main PR bodies; merge-commit exception; `git branch -f main origin/main` before switching).
- not done: 36 stack head branches (remote + local) from earlier sessions remain; deletion awaits owner OK. Local-only files (weight-edit study, jawiki_300 jsonl, .claude/, .codex rules diff) left untouched.
- Commit SHA: 45ada90, merge 4159fd9.

## 2026-11-08 — Triage of leftover uncommitted files (#20, #80)

- request: 「この未コミットどうすんの」; owner approved the recommended split.
- action: committed the 2026-11-03 weight-edit evidence (4 reports, 2 manifests, `.codex/memory/rules.md` learnings) for #20; started tracking `.claude/memory/` with the owner email redacted to `<owner-email>`; ignored `.claude/goal-loop/` (rubrics carry local user paths) and root `/jawiki_*.jsonl`; moved `jawiki_300_audit_reviewed.jsonl` (Wikipedia text, sha256 1b249651...) unchanged to ignored `data/generated/legacy-audit/`.
- symptom: Git normalized the reports to LF on add, but `manifests/sakura-rerank-tiny-v1-conditional-edit-20261103.json` pins `report_sha256` 146ac16d... over the report's original mixed CRLF/LF bytes.
- root cause: `* text=auto` normalizes JSON; the pin was computed on the Windows working copy. Existing reports pin either CRLF or LF hashes, with no single convention.
- fix: `.gitattributes` marks only that report `-text whitespace=cr-at-eol`, so the blob is byte-exact and `git diff --check` stays clean.
- symptom 2: the first leak scan reported zero local paths, yet the four reports each held one JSON-escaped absolute user path (scratch-directory cleanup field). A later grep for the bare word `Users` found them before push.
- root cause 2: backslashes in regex patterns passed through the Bash tool were collapsed, so patterns for JSON-escaped Windows paths silently matched nothing (a bytes replace failed the same way until built with `chr(92)`).
- fix 2: replaced the four values with `~/tmp/<dir>` (only bytes changed) and moved the conditional report pin from 146ac16d... to bf61d93f...; committed blob sha256 == pin.
- learning: before committing evidence produced on Windows, compare each file's working-copy SHA-256 with any in-repo pin and with the normalized blob hash. For leak scans, add a backslash-free probe (`grep -n -i users`, `grep -n -i develo`) and treat a zero-hit regex scan as unproven until a positive probe hits.
- Commit SHA: lands as one squash commit; see the #80 closing comment.

## 2026-11-08 — Public-path cleanup on main and merged-branch pruning (#82, PR #83)

- request: owner approved fixing the local user paths on main and deleting merged branches.
- finding: a backslash-free probe for the local account name and `users/<name>` path forms found 7 hits on main 17bffe2: six research READMEs (an absolute user-profile path in the `$python` line) and `research/issue-35-knbc-qualification/render_manual.py` (`TEMP`).
- decision: `render_manual.py` stays unchanged; its SHA-256 is the frozen `reports/issue-35-knbc-qualification-v1.json` `static_checks[4].sha256` record of the checked script, so editing either side breaks provenance. Residual: one generic account-name path remains public.
- fix: the READMEs now use `$python="$HOME/tmp/..."`; running the snippet in PowerShell resolved to the same train-env interpreter (torch 2.12.1+cu130). Squash a77f759 (#83); 1095 tests OK; no python survivors.
- branches: posted a name -> SHA recovery table (39 names) to #82, then deleted 38 merged remote and 38 merged local branches plus the task branch. Remaining: main, 7 unmerged local and 6 unmerged remote branches (issues #1/#5/#7/#9/#11/#13/#17 era, out of scope).
- learning: before redacting a tracked research file, look up its SHA-256 and git blob ID in reports/manifests; a pinned script is evidence and must not be edited to tidy text.
- Commit SHA: a77f759 (README fix); this entry lands in the follow-up journal PR.

## 2026-11-08 — Codex review findings on #79 and #81 (#85; PRs #86, #87, memory PR)

- request: the owner asked whether the pasted Codex findings held, then said to handle them.
- verification of findings: all six held. Two were still public on main: (1) `primary_references` in `reports/weight-edit-conditional-20261103.json` tied cases R10/R12 to a real company, artist and wrestler; (2) one repository-path cleanup target in `reports/weight-space-programming-20261103.json`. My #81 scan had searched only user-path forms and no case-level identities.
- fix 1 (#86, 51f3802): moved the three references to ignored `data/generated/weight-edit-conditional-20261103/primary-references.json` (sha256 b02287bd...), leaving count/location/hash. Recorded `reviewer_kind ai_teacher`, `reviewer_model not_recorded`, `owner_policy_acceptance not_recorded`, `admissible_as_gold false`, without inventing an acceptance. Made the path repository-relative. Re-pinned the CRLF byte-exact report: bf61d93f... -> 3ba02cac... History was not rewritten (public account name and public pages only).
- fix 2 (#87, 47886d8): `evaluation_payload.scored_candidate_count(row)` is now the one Oracle@6 / runner prefix definition (`min(6, direct_count)` for product rows). `validate_policy_facts` requires `baseline_index < direct_count`, the native-capture contract, and no tighter. Three fail-before tests failed before the fix (correct certificate 2996 rejected; inflated 2997 accepted and the model started; baseline in a non-direct tail accepted) and pass after. The runner refactor is a separate commit.
- fix 3 (this PR): `.claude/memory/rules.md` keeps durable procedures plus links to the reports holding results; the five 2026-11-03 entries in `.codex/memory/rules.md` keep the lesson and evidence link without dated figures.
- learning: AGENTS.md routes results to reports/manifests/README. Memory rules hold procedures and links, and the journal holds dated figures. Public leak scans must cover case-level identities (URLs, names) as well as paths.
- Commit SHA: 51f3802, 47886d8; the memory PR's squash SHA is in the #85 closing comment.

## 2026-11-08 — Publish Oracle@6 with the certified scored-prefix definition (#90)

- request: owner approved fixing the Codex P1 on #87 with the recommended approach (keep the positional view, publish a separate scored-prefix Oracle@6, check it against the evidence).
- symptom: after #87, `read_cohort` certified `oracle6_present` over `min(6, direct_count)`, but the metrics report still published only `observed_candidate_oracle["6"]` over a positional first six. On a product row with a non-direct tail inside the first six, the published Oracle@6 (2997 in the fixture) disagreed with the certificate it was checked against (2996).
- root cause: one rule (the scored prefix) had two consumers but the metrics owner published only the positional variant; `model_prefix_oracle` held the right value only for full-population schemas.
- fix: `evaluate_runs` computes the scored-prefix count once and publishes it as `scored_prefix_oracle6` for every schema (full-population `model_prefix_oracle` reuses the same count). `observed_candidate_oracle` is unchanged. `run_evaluation` requires the overall and converter-reference `scored_prefix_oracle6` numerators to equal `prepared["quality"]["oracle6_present"]` before `access.complete`; a mismatch raises `RunnerError` and the reservation ends `failed`.
- verification: two fail-before tests (`scored_prefix_oracle6` 2996 beside positional 2997; tampered metrics output fails closed with terminal `failed`) errored with KeyError before the fix and pass after; full suite 1099 tests OK; no python survivors.
- learning: when a certificate check is narrowed to a new definition, the published metric must carry that same definition and be checked against it; otherwise the report and its certificate silently diverge.
- Commit SHA: see the #90 closing comment.

## 2026-11-08 — Tidy-up after #90: torch skip guard and stale branches (#92)

- request: after 「リリースは不要なの?」 the owner said 「なんでもいいよキレイにしといて」, leaving the remaining cleanup and the release decision to me.
- symptom: under a Python without torch, `tests.test_language_pretraining` failed with 3 errors because `TiedLanguageHeadTests.setUp` imports torch, while every other torch class carries a skip guard.
- fix: added the same `@unittest.skipUnless(importlib.util.find_spec("torch"), ...)` guard. Global Python 3.13 (no torch): before 3 errors, after `OK (skipped=3)`; train-env: 6 OK; full suite 1099 OK; no python survivors.
- branches: the six remaining `issue-1/5/7/9/11/13-*` branches each had a tip tree identical to its PR's squash commit (#2/#6/#8/#10/#12/#14, 0 differing files). Posted the name -> tip -> squash table to #92, then deleted them locally and on the remote. Remote now holds only `main`.
- kept: local-only `issue-17-public-ime-benchmarks` (930a1f6) holds 2,465 added lines of unpublished work for open #17 (public IME / AJIMEE benchmark pipelines and baseline reports) absent from main. It is neither deleted nor pushed; pushing would first need a leak review.
- learning: `git cherry` reports squash-merged branches as unmerged. Compare the branch tip tree with the PR's squash commit (`git diff --name-only <branch> <squash>`) before calling a branch stale or unique.
- Commit SHA: see the #92 closing comment.
