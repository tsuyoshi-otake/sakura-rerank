# Gold 1,000件pilotの実行契約

親#1、実行範囲#31/#32。2026-11-04承認に基づく。目的は**正解定義・二重人手判定・裁定・履歴管理の運用を検証すること**。1,000件が全件validでも、Gate A・最終品質保証・独立Testは未完了とする。#33/#34/#35の実装、再学習、元データへの修正適用は含めない。

## 対象と責任

現行v5 train 12,516件から、左文脈・読み・Top-6候補表記順が同じ行を一群とし、各群のstable ID最小の代表を固定seed 20261104のhash順で1,000群選ぶ。モデルの予測/誤りやdevの結果を選択に使わない。これは既存trainでの運用pilotであり、独立したGold Testではない。選別された群に対する割合を元母集団の品質推定と呼ばない。

source JSONLをSHA-256で固定し、final-holdoutはJSON解析前に捨てる。元のtrain/dev/holdout、ラベル、モデル、manifestには書き戻さない。準備物は`data/generated/issue-31-gold-pilot-v1/`に保存し、Gitへは集計manifest・状態reportだけを入れる。人手イベント・提案overlay・原文・IDをGitへ入れない。

`frozen_diagnostics.read_projection`がsource検証と限定投影を所有し、`frozen_diagnostics.audit`が集計を所有する。`gold_pilot`はpilot抽出、ローカル資料、判定履歴の検証、未適用提案、終端状態を所有する。既存Gate Aの`human_audit`と別record kindを使い、既存のapplyコマンドには渡さない。元のsplitterや学習器を変更しない。

## 人手の割当と判定

1. coordinatorが異なる判定者A・Bと、両者とは別の裁定者Cを割り当てる。識別名はASCII英数字・`._-`の64文字以下。AIをhumanとして記録しない。識別名だけでは実在確認できないため、担当者の実際の作業と独立性はcoordinatorが確認する。
2. A/Bには各自の`reviewer-A/`または`reviewer-B/`と`policy.json`だけを渡す。各25件×40batch。元stable ID、split、converter順位、モデル名・予測、過去AI判定は見せない。候補は表記順、A/Bのケース順は別。原goldは監査対象として明示するため、ラベル自体に対してblindではない。
3. [方針v1](gold-pilot-policy-v1.json)の優先順で判定し、対応する`responses-NNN.template.jsonl`を各自の作業先へコピーして独立したJSONL eventを保存。未記入nullは判定として受理されない。両者が`verdict`と`accepted_surfaces`の両方で一致したら終結（`unresolved`は一致しても裁定）。不一致はCへ送り、CがA/Bの正確なevent hashを根拠に裁定する。
4. 訂正は旧eventを残した追記。`previous_event_sha256`に同じcase/roleの直前eventのcanonical JSON hashを指定する。A/Bが訂正した場合、古いhashを参照する裁定は失効し、必要なら再裁定になる。`unresolved`は完了数に含めない。

判定者は資料本文を外部サービスへ送信しない。source確認が必要な案件は推測せず`unresolved`として、coordinatorが許可された証拠を再整理する。1,000件の運用時間、agreement、裁定率、定義不足を記録し、本格Gold構築の費用・方針を別途判断する。

## 実行コマンド

repo rootで`$env:PYTHONPATH='src'`を設定する。標準ライブラリのみ、新規依存なし。

```powershell
python -m sakura_rerank.data.frozen_diagnostics --source data/generated/issue15-v5-slot120/frozen-split.jsonl --source-sha256 0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82 --output reports/issue-32-frozen-audit-v1.json
python -m sakura_rerank.data.gold_pilot prepare --source data/generated/issue15-v5-slot120/frozen-split.jsonl --source-sha256 0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82 --policy research/gold-pilot-policy-v1.json --output data/generated/issue-31-gold-pilot-v1
python -m sakura_rerank.data.gold_pilot reconcile --packet data/generated/issue-31-gold-pilot-v1 --events data/generated/issue-31-human-events.jsonl --output data/generated/issue-31-review-round-001
```

出力先は毎回新しい名前とする。既存出力は上書きしない。判定未開始のeventsは空ファイルであり、架空の判定を埋めない。reconcileは判定履歴全体を受け取り、入力eventのsnapshotも新しいroundへ保存する。2回目以降は必ず`--previous-round data/generated/issue-31-review-round-001`等を渡す。過去event列の欠落・差替えを拒否し、前回report hashも保存する。coordinatorが過去roundを保持し、この引数の省略を新しい開始として承認しない。**hash chainは削除された過去roundを自動復元する仕組みではない**。

event形式（この例は構造説明のみ。実在する判定として投入しない）:

```json
{"case_id":"p-<packetのcase_id>","role":"A","reviewer_id":"human-A","reviewer_kind":"human","reviewed_at":"2026-11-04T10:00:00+09:00","verdict":"unresolved","accepted_surfaces":[],"reason":"実際の判断根拠を記載","queue_sha256":"<manifestの値>","policy_sha256":"<manifestの値>","previous_event_sha256":null,"basis_sha256":[]}
```

`accepted_surfaces`は辞書順で重複なし。新しい読みや候補を生成しない。Cの`basis_sha256`は現在のA/B event hashをその順に2個指定する。event hashは`contracts.canonical_json_hash(event)`。コマンド出力にはraw textを出さず、詳細な資料はignored directory内だけに置く。

終端状態は`awaiting_dual_review`、`awaiting_adjudication`、`pilot_complete_no_gate`。不正なschema、hash、役割、日時、履歴、候補外surfaceはエラー終了し、そのroundの成果物を作らない。全件終結しても`gate_a_human_audit_pass=false`、`gate_a_owner_authorized_audit_pass=false`、`final_holdout_valid_count=0`。提案overlayは常に`pilot_proposal_not_applied`であり、元goldを書換えない。

## 検証rubric

| Verify | Expect |
|---|---|
| `python -m unittest tests.test_gold_pilot tests.test_frozen_diagnostics` | deterministic train-only抽出、holdout非解析、hash/bounds失敗、blind資料、異なるhuman、訂正・裁定失効、未完了終端、全件でもGate A false、上書き拒否・失敗後cleanup |
| prepareを新しい2ディレクトリで実行し全ファイルhash比較 | 1,000件、全ファイルbyte一致。元source hash不変 |
| frozen auditを2回実行しJSON hash比較 | 全分母・重複件数一致、元split変更なし、モデルscore未読 |
| `python -m unittest discover -s tests` | 全既存契約・human audit・split・model/report回帰成功 |
| compile、`git diff --check`、process audit | syntax/空白問題なし、今回のtest/worker残存0 |

## 変更範囲とIRV

A: source契約、既存human audit/reviewerの公開状態、splitterの分割契約、再評価report、関連testsを確認。
B: 元のreviewerはsplit/順位を含み、Gate A用なので、pilotのblind配布と合否分離に別record kindが必要だった。既存UIを変更せずローカルJSON資料と検証CLIに限定した。
C: sourceの所有者・旧gold・元split・本番契約は不変。新しい状態所有者はpilotのみ。`gold_pilot`から読取り診断契約へ一方向に依存し、学習やGate A applyへ依存しない。
D: 次のpilotでは方針・2モジュール・対応testsから開始でき、全実験履歴やmodel internalsを読む必要がない。独立test/本格Goldの契約は今回実装していない。
