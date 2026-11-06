# Verified project learnings

- [consumed source exposure] Neutral source coverage is not semantic consumption. Bind all actually consumed source-only IDs, including invalid readings, and propagate exposure through existing relations without inventing input hashes. Five synthetic contracts and the 991255-node forward/reverse audit found one additional real historical connection (#32/#35).

- [source input extent] A whole ruby base can still be a word stem. Preserve literal kana and exact source positions in separately named whole-source/literal-run hypotheses; all-components presence is not a joint N-best rank or model accuracy. Verified by the fixed 100-sentence source-unit diagnostic and okurigana contracts (#31/#35).

- [native terminal accounting] Process exit 0 can precede a snapshot-contract rejection. Keep the entire rejected snapshot unmeasured, preserve the original report, and continue only hash-bound unattempted requests. Verify requested/attempted/measured/rejected totals separately from runner completion; the 426-request source-unit audit preserved 18 segments and retried 0 inputs (#35).

- Tatoeba source evidence: join transcription IDs to the licensed sentence export before selection; its SQL lacks the sentence-license filter. A named editor, exact ruby alignment and whole ruby base do not certify contextual reading or an IME input boundary. Source owner is management provenance, not proven authorship; report direct input matches separately from propagated component exclusions. Verified by the #35 external-source pilot and 25 synthetic contracts.

- Frozen research entrypoints can collide through generic sibling module names (`cohort`, `acquire_sources`), even when their parent was loaded by explicit path. Use unique new module names or the existing contract API; preserve executed historical code hashes. The #33 loss-balance preparation failures and successful direct-API candidate/numeric verification establish this boundary.

- Source-layout research stage owners must set the child `PYTHONPATH` explicitly to repository `src` and the repository root; a subprocess working directory alone is insufficient. The #33 train-change audit reproduced 77 import errors without it and passed all 664 tests with the explicit child environment.

- Python audit hooks on Windows must derive the access-mode mask from `os.O_WRONLY | os.O_RDWR`; `os.O_ACCMODE` is unavailable. Check both string-mode and `mode=None` open events. Verified by `tests/test_annotation_fit_boundary.py` and six guarded fits in #33.

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

- Machine pilot evidence (#31): the separate frozen source-spans artifact can
  verify source-to-candidate correspondence without rereading holdout examples.
  Match only selected train IDs before JSON parsing, authenticate all bytes,
  and keep exact matches separate from NFKC-only matches. All 1000 pilot rows
  matched exactly on 2026-11-04, but the common extractor means this is not an
  independent check of contextual reading, intended spelling, or Gold quality.
  See `reports/issue-31-machine-evidence-verification-v1.json`.

- Six-axis AI reread (#31): linguistic plausibility is weaker than unique
  intended output. The same 1000-case pilot has 609 all-ordinary/supportive
  combinations, but none are independently certified by that classification.
  Recheck the entire cohort, including old "unique" cases; compare axis counts
  conditionally without treating changed definitions as improved accuracy.
  Source-exact checks, single-AI judgments and human evidence remain separate.
  See `reports/issue-31-ai-six-axis-review.md` and its verification JSON.

- Follow-up evidence (#31): all 50 flagged targets matched dictionary-unique
  readings, while two primary-source contextual readings conflicted with the
  assigned readings. Keep whole-word pronunciation, arbitrary partial IME input
  and intended output separate. Synthetic math tags and template-only titles
  reproduce residual TeX and empty quotes in the frozen cleaner; they establish
  a mechanism, not the original source's causal history. Preserve the old cleaner
  contract when introducing a corrected version. See the doubt-evidence addendum
  in `reports/issue-31-ai-six-axis-review.md`.
- Task helper filenames must not shadow Python standard-library modules. A local
  `inspect.py` shadowed `inspect` during a `dataclasses` import in the #31 audit;
  renaming it to `audit_cases.py` resolved the import and the full audit passed.

- Versioned source quarantine (#31): apply quality flags to the exact bounded
  left context plus target after v4 coordinates/sampling and stable-ID exclusions.
  This preserves historical IDs and avoids future-context selection. Count a
  candidate stopped at the output-byte limit separately from retained records;
  v5 manifest reconciliation tests exercise that terminal branch. On the frozen
  12,516-row train cohort, the fixed TeX/empty-title rules flagged nine rows, but
  eight still had locally understandable targets: routing flags are not label
  errors or independent Gold evidence. See the source-quality addendum in
  `reports/issue-31-ai-six-axis-review.md`.
- Spelling policy mapping (#31): protection and uncertainty are separate axes.
  Among 330 style/protection cases, three old style cases needed name/title
  protection; 64 protected cases still had unresolved reading, meaning, input
  unit or context. Derive exclusive workflow routes separately from overlapping
  rule memberships. Conditional pair review is not an accepted-surface set, and
  exact-form protection does not certify the source label. Verified by the
  spelling mode of `pilot_policy_triage` and its contract tests.

- Independent Test consumption (#35): source isolation also needs exact bounded
  left-context/reading equality, including transitive source/input chains. A local
  reservation must survive inference failure and even an fsync exception that
  leaves bytes written. Keep an external ledger-head commitment to detect tail
  truncation; a hash chain alone cannot. Equality tokens do not replace complete
  near-duplicate history or Gold admission. Verified by the 16 contracts in
  `tests/test_evaluation_protocol.py`; no real Test was opened.

- Historical metric checks (#35): bind the gate selection source as well as the
  model/score artifact. Issue-21 C2 L>2.7 produced 34 rescues and four harms; the
  later Issue-25 L>2.9 produced 29 and three on the same dev cohort. A verifier
  initially compared the former against the latter. Correcting its reference,
  without changing thresholds or metric code, matched the published records.
  Saved offline scores do not establish exported-binary parity or runtime failure
  telemetry. See `reports/issue-35-metrics-v1.md`.

- Evaluation access (#35): reserve and externally pin Test consumption before
  authenticating Test content. Retain authenticated runtime bytes to close path
  replacement gaps. An fsync exception can leave a reservation written; a terminal
  anchor failure can leave a completed ledger with a stale head. Neither permits
  retry or a second terminal event. The admission trust set remains empty until
  independent Gold evidence exists. Verified by 28 synthetic admission contracts;
  see research/evaluation-admission-v1.md and its verification report.

- External annotation evidence (#31): third-party human-corrected morphology can
  supply readings independently of Sakura's dictionary, but a corpus-level
  morphology accuracy claim is not an IME label-quality confidence bound. Ruby
  markup can also encode editorial notes rather than pronunciations. Preserve
  source/task scope and inspect actual annotation fields before Gold admission.
- Large evidence reports can contain thousands of component hashes on one JSON
  line. Select metric fields before printing; locate stage artifacts with bounded
  directory depth rather than listing all review batches.

- External annotation probe (#31): KWDLC's three logical source sentences may
  have multiple ordered KNP S-ID parts. Preserve initial parser failures, then
  support contiguous split parts without replacing sampled documents. Keep
  target indices tied to annotation-unit order and reset left context at every
  unit. All 46 first-pass targets remained unchanged when all 50 parsed.
  Dictionary-index absence is not an N-best oracle miss; only authenticated
  converter execution can measure that. See reports/issue-31-kwdlc-probe-v1.md.

- [relation certificates] Full-graph parity does not prove a relation-removal diagnostic: one near edge between signature representatives depends on exact-signature stars. Preserve per-near-pair bipartite spanning evidence (or prove each view independently). Verified by the failing-then-passing omission fixture and full edge/path checks in research/issue-32-source-relations/README.md.

- [node-removal diagnostics] Deleting nodes from a graph requires rebuilding relation groups on the retained nodes; filtering saved representative-star edges can lose surviving member relations. Keep the original inventory/exclusions and distinguish the new consumption scope from data admission. Verified by tests/test_consumed_source.py and research/issue-32-consumed-source/README.md.

- [canonical artifact bytes] On Windows, write hash-bound JSON/manifests with write_bytes or explicit LF; Path.write_text default newline translation can differ from Git-committed bytes even when the policy is identical. Preserve the failed attempt and restore exact committed bytes rather than weakening authentication. Evidence: research/issue-49-consumed-contrast/README.md.

- [fixed source-model inputs] Six candidate slots are padded capacity, not an exact count. Preserve one-to-six active candidates with zero padding and a mask; source reconstruction requires a label-free feed and empty context when no session text was observed. The initial connector failed on three valid short snapshots before inference; corrected feeds matched all 420,024 scalar elements and all three CPU replays (#35, research/issue-35-source-models/README.md).

- [nested gate provenance] A gate outer fold must be absent from every model generating its inner training scores, including initialization, teacher and selection ancestors. Row disjointness or one-layer OOF is insufficient; missing lineage stays unknown. The #34 audit reproduced all75000 metadata rows, cross-recipe component overlap25000/24830, and the5-fold nested16-versus26 ranker-fit schedule;19 synthetic contracts cover the boundary.

- [fixed external selectors] Nested ranker retraining is unnecessary when the selector stays fixed and its recorded fit/teacher/selection/preprocessing ancestry is disjoint from the gate-training pool. Prove the projection before treating empty ancestry exposure as valid; consumed weak-label data remains research, never fresh calibration or Test. Evidence: #34 selector-lineage audit,22 ancestor nodes,813852-node closure,75000 selected identities and14304 old numeric inputs independently checked with zero overlap.

- [input projection exposure] Recompute input equality and historical exposure after removing context or changing a representation; original disjointness does not transfer automatically. Keep original component bridges and join derived equality before folds. The #34 CPU proposal replay verified 150,000 outputs: 1,888 empty-context rows matched historical inputs and 73,623 rows became connected; 2,114 conflicting groups impose a 92.456% empirical source-match ceiling on that pool, not on Japanese IME accuracy.

- [source-check selection bias] Do not estimate reading consistency from conflicting-input rows alone. Authenticate the declared complete population or report the conditional denominator explicitly. The #31 source audit replayed75,000 original spans:335/25,000 dictionary-Aozora readings contradicted exact original ruby, including234 outside the initially selected conflicts; no label or Gold admission followed automatically. Evidence: research/issue-31-conflict-source/README.md.

- [missing versus contradictory readings] Keep missing original annotations separate from observed reading conflicts and uncertain annotation scopes. An explicit dictionary-only weak-source allowance may cover missing evidence, never override a conflict or uncertainty; enforce the same rule in the producer and bound consumer. Verified by 28 source-reading-gate contracts and the 75,000-row application: 335 conflicts and 580 uncertain cases remain pending, with no training/Gold admission. Evidence: research/issue-31-reading-consistency/README.md.

- [reading repair changes the task] Rebuilding an exact original ruby reading requires a new request, candidate proof and input-exposure check; source agreement is not recoverable training capacity. The335-parent repair produced318 bounded inputs but only7 Top-6-eligible rows;17 remained pending and305 measured targets were absent from Top-32. Empty-context projection also matched161 current inputs and one actual historical train input. Preserve parent/component lineage and record the entire denominator; never modernize readings or claim independence to rescue the count (#31, research/issue-31-reading-rebuild/README.md).

- [source extent is a hypothesis] Preserve full original annotations and literal kana, with unknown readings as barriers, when comparing source extents. Native diagnostic bounds and training preparation bounds are different contracts. On335 fixed parents, original/suffix/maximal-run Top32 presence was13/39/26; suffix added23 of305 previous misses but lost2 previous matches. Larger ranges are not inherently better, and changed-input source matches are neither ranker rescues nor certified IME boundaries. All1005 views and830 requests were directly replayed (#31, research/issue-31-source-extents/README.md).

- [lexical cover is not native reachability] Require complete target and reading consumption when checking indexed token composition; preserve resource-bound and native-positive exceptions explicitly. Character-offset witnesses and lexical unit counts are not native byte offsets or segment counts, and POS/cost/search/intent remain separate. Verified by 21 contracts and an independent 1,340-pair/2,680-condition replay (#31, research/issue-31-lexical-coverage/README.md).

- [source-to-training joins] Authenticate the actual producer vocabularies and bind per-arm presentation order separately from source order and numeric row order. Equal membership is not equal training order; preserve the original order when filtering and retain excluded history. Real-contract fixtures and all75,000 joins verified the exact origin-enum correspondence and34,158 dictionary order differences;30 contracts and full replay pass (#31, research/issue-31-source-recipe/README.md).

- [provider correction fields] Human-annotated corpora may preserve erroneous source spelling; keep surface, reading, lemma and correction notes separate. Interpret markers at their declared scope: KNBC had5 ER notes on structural lines (zero on token notes) and47 lemma-ambiguity units, neither a token replacement rule nor a measured reading/IME-label error rate. Verified by the pinned manual and fixed100-slot/1479-token pilot,18 contracts and972 tests (#35, research/issue-35-knbc-format-pilot/README.md).

- [current baseline semantics] Pin the current product HEAD; model signature alone does not identify projection/selection. Compiled native parity verifies the protocol-v1 encoder and protected choice. Keep native eligibility/evidence and the local preferred index explicit, then retain both raw-converter and native-local safety references so existing local behavior cannot masquerade as neural improvement. Neither legacy source categories nor this parity certify live-session facts. Evidence:67 projection conditions,1756 choices and the dual-reference fallback regression (#35, research/issue-35-current-tiny-parity/README.md).

- [native snapshot identity] Preserve the full native population and join queued and conversion-time owner/session/generation/reading/candidate identities. A pending-Romaji flush can change the input, and a valid cached choice can be outside the model prefix. Evidence tags do not establish legacy per-edge source features. Verified by25 paired native conditions,48 snapshots,924 candidate records and schema3 binding/refusal tests (#35, research/issue-35-native-state/README.md).
- [Windows test entrypoints] Guard custom test-runner execution with if __name__ == '__main__' when tests spawn multiprocessing workers. Otherwise child bootstrap recursively executes the suite before the intended worker. The native-state targeted runner failed while direct metrics worked, then passed19 tests after adding only the guard (#35).

- [native population extent] Version candidate count and UTF-8 text bounds together; retain full native order and tail local choice separately from the model prefix. Duplicate surfaces remain positions, and source categories/segments cannot be inferred from evidence tags. The legacy diagnostic reader also needs its own explicit bound. Verified by48 native snapshots/924 candidates,768-candidate synthetic integration and1536-byte native tensor/CPU parity (#35, research/issue-35-native-population/README.md).

- [pre-fusion feature provenance] Historical Tiny feature2 counts raw converter path edges, not fused display segments; feature5 reflects raw system-dictionary origin, including dictionary correction edges, not the native authority group. Capture at construction, preserve through clones, and bind final reading/surface before projection. Verified by216 fused candidate occurrences,434 system paths with non-exact evidence,30780 matching scalar values and540 matching fixed-model scores (#35, research/issue-35-native-paths/README.md).
