# Continuous-source consumption v1 — prospective research only

Parent #1, Issues #31/#32/#35. Freeze this contract and implementation before selecting the next cohort. This does not admit labels, change existing splits, or authorize a release.

## Population and exposure

Use the pinned `tatoeba-jpn-weekly-20261031` licensed sentence/transcription exports from PR60. Their bytes and metadata were previously accessed; the next cohort is prospective source research, not an unseen independent Test. Exclude all100 previously decoded sentence IDs. Before decoding any new text, commit1000 unique slots selected by the smallest canonical SHA256 of `[policy_version, seed, sentence_id]` over the licensed Hrkt join. No editor quota, reading/content/model filter or replacement. Parse failures remain consumed slots. Duplicate/missing IDs, capacity shortages and metadata failures stop the stage.

## Input and evidence

Use the unchanged `tatoeba_input_units.build_source_units` literal-run view. Preserve every source codepoint, original position, ruby base and following literal kana. Unicode P/S characters outside ruby stay literal and delimit conversion runs. Ruby internals are never split. Only the fixed1:1 fullwidth katakana-to-hiragana mapping is permitted on input; retain source spelling, long vowels and original annotations. No NFKC, guessed readings, morphological repair, trimming or length-based subdivision.

Maximum reading128, target256, conversion parts32, source10000 characters, source-only signature1024 and real-input signature512 remain explicit bounds. Unsupported characters, markup, source mismatch, missing fields and bounds have terminal outcomes without candidate requests. Exact source alignment is recorded separately from supported reading/input status.

Each hypothetical input has empty left context. Imported preceding source text is not observed Sakura session context. These are hypothetical conversion events, not verified user input boundaries. Source alignment, candidate presence and original reading annotations cannot certify Japanese correctness or IME intent.

Administrative owner and transcription editor are separate provider tokens; original author, translation lineage and independent reading verification remain unknown. Import zero human verdicts. Keep owner links conservatively in the existing graph while naming their true semantics. Do not restore old exclusions or claim independence by dropping these links.

## Execution and metrics

All1000 slots retain source, preparation, historical-relation and native outcomes. Authenticate the complete historical inventory, including all previously exposed100 source records and their ruby, whole-source and literal-run input hypotheses. Historical-native inputs have empty-context equality tokens, matching what was actually executed.

Before native work, commit a separate binding for the exact request bytes and runtime identity. At most4000 distinct requests, concurrency2, each30 seconds, total900 seconds, output512MiB, retries0. Preserve the existing18-segment output bound. A rejected snapshot contributes no accepted candidates; unexpected failures stop scheduling and leave explicit unattempted outcomes. Keep every attempted byte/receipt immutable.

Report all-slot counts and measured counts separately, with Top1/5/6/10/32 source presence per input and all-parts presence per sentence. All-parts presence is not a joint N-best rank. Missing source candidates are measured misses; invalid/unexecuted native snapshots are unmeasured. The prior100 diagnostic is a design comparison, not an accuracy baseline. No independent Accuracy/Gold CI or safety pass can be inferred from this source-only cohort.

Training, model inference, calibration/Gold admission, final Test, production integration and restoring exclusions are forbidden in this run. Preserve adopted90.72%, safety0.25%, Gold point99.5%, Wilson lower99.0%, final valid3000 and one-use final Test.
