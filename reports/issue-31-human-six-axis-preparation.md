# Issue #31: 六軸・独立二重人手pilotの準備

ユーザーが指定した全1,000件・独立した人間A/B・第三者C・AIは補助のみという条件に対応する。旧packet・AI判定・193件triage・元データを変更しない。PR #36はDraftを維持する。

## 検証rubric

| Verify | Expect |
| --- | --- |
| 新しいprepareを2つの新規directoryで実行し全file hashを比較 | 旧1,000件と完全同一集合、A/B各1,000件、全byte一致 |
| 配布packetのallowlist契約テスト | モデル予測/順位・旧分類・AI理由・元stable ID・相手の判定なし、A/B別IDと順序 |
| 人手割当・六軸・履歴・seal・裁定の契約テスト | AI/同一人物/露出申告/旧方針/改変/早期裁定/古い根拠/固定後訂正を拒否 |
| 合成データで一致率・裁定率・軸分布を照合 | 初回と最新を分離、unknownを隠さない、未提出とunknownを区別、品質はnull |
| 旧reportと12artifact hash、全unit tests、compile、diffを確認 | 元データ・既存証拠不変。全件一致でもGate Aはfalse |
| 終了後のtask runner・一時fileを確認 | runner残存0、task temp削除、配布物・履歴だけ保持 |

## 結果と現在位置

**新しい人手判定方針v1を凍結し、全1,000件のA/B資料・回答template・第三者裁定・集計の準備を完了した。実際の人手判定は0件。** A/B/Cの担当者は未指定のため、状態は `awaiting_assignment`。助手は人間2名や第三者を代行していない。

| 項目 | 結果 |
| --- | --- |
| 対象 | 旧pilotの1,000件と同一、旧分類による選別なし |
| A/B資料 | 各25件×40batch、各1,000件、別ID・別順序 |
| 再現性 | 全168ファイルを2回生成しbyte一致 |
| 人手実績 | A=0、B=0、C=0。割当・独立性確認も未完了 |
| Gate A / Gold品質 | 両Gate A false、正解率null、認証Gold 0、独立holdout valid 0 |

凍結方針は [policy JSON](../research/gold-human-six-axis-policy-v1.json)、運用手順は [protocol](../research/gold-human-six-axis-protocol.md)。準備物のhashは [manifest](../manifests/issue-31-human-six-axis-v1.json)、人手開始前の状態は [status](issue-31-human-six-axis-status-v1.json)、検証は [verification](issue-31-human-six-axis-verification-v1.json) に保存した。

## 指示に対応した点

1. 原文照合・読み・入力単位・文脈・意味・表記意図を独立した軸にし、各軸に値と具体的理由を必須化した。旧一意807件も同じ対象に含む。
2. A/Bには旧分類・AI提案・モデル予測・変換器順位・旧case IDを含めない。相手の資料とcoordinator資料も配布しない。対象表記自体は提示するため、原goldに対する盲検とは呼ばない。
3. A/B全1,000件の提出で最新event集合を固定する。固定前のC裁定と、固定後のA/B訂正を拒否。Cは異なる人間で、固定されたA/B根拠hashに基づく不一致裁定だけを行う。
4. 初回A/B一致率、現在/固定時一致率、軸別分布、裁定必要率・完了率を別集計。unknown同士の一致と、両者が判断できた部分の一致を区別する。人手の一致をGold正解率に変換しない。
5. 既存eventの削除・差替えを拒否し、各役割と各caseの前event hashを保存。新roundは、hashで固定した前roundの全eventを保持する。元データへの書戻し経路を持たない。

## 独立原文証拠の限界

既存packetには抽出済みの原goldはあるが、独立照合のための原文証拠はない。この版では原文軸を全件 `unverifiable` に制限した。原gold自身との一致を原文照合成功とする循環を避けるためである。

したがって、この軸の粗一致率が100%になっても情報量はなく、判定可能な分母は0、対応率はnullになる。六軸の記録運用と残る五軸の判断を進めることはできるが、原文確認済みGoldとして品質を認証することはできない。原文証拠の追加は、許可された文脈範囲と履歴を守る別版で設計する。右/未来文脈やhost文書は追加していない。

## 検証実績

- 全309テストを実行し失敗0、既存optional PyTorch tests 5件skip。新規16テスト全成功。300秒timeoutで実行した。
- 全件同意でもGate Aが通過しないこと、unknownだけの100%一致に正解率を付けないこと、初回と訂正後の一致が別集計されることを合成データで検証。
- 別人・AI排除・独立性宣言、六軸欠落・候補外・原文根拠なしの照合成功、早期/古い根拠の裁定、固定後訂正、checkpoint不一致・履歴削除・上書き、書込失敗後cleanupを検証。
- source queueのSHA-256を固定し、全168ファイルを独立2回生成して一致。配布packetは再生成したallowlist内容と完全比較し、余計なAI助言ファイルやフィールドがあれば拒否する。
- 旧12artifactのhash不変。旧human/AI/triage policyとAI/triage集計も旧commitと照合し不変。最終holdoutの本文は解析せず、保全のためbytes hashのみ確認した。
- 静的コンパイル・diff check成功。実行後にtask所有Python/test/training/ORT processが残っていないことを確認。既存インストールのSakura Input workerは維持した。
- Sakura Input HEAD: `d586fae572d32aa76512994dca616dadef2899b1`。本番コード、既存モデル、候補生成を変更していない。

## 保存物・未完了条件

Git対象外の保存物:

- `data/generated/issue-31-human-six-axis-v1/`: 不変の配布資料とcoordinator用template。
- `data/generated/issue-31-human-six-axis-round-000/`: 人手記録0件の初期状態とcheckpoint。

一時生成の複製、テスト出力、検証用scriptは `~/tmp/gold-human-six-axis-20261104/` から削除し、上記の継続作業用資料だけを残す。PR #36はDraft/未マージ。

未完了なのは、対象ケースのAI提案を見ていない独立した人間A/Bと第三者Cの割当・確認、および実際の2,000件のA/B判断と必要な裁定である。人手の代わりとなる架空のeventは作成していない。識別名・宣言の検証は機械的な契約検査であり、実在・独立性はcoordinatorによる確認が必要。この条件は今回のユーザー指定に由来する。

## IRV記録

- **A. 実際の範囲:** 旧pilotのpacket/人手履歴契約とテスト、193件triage方針、Issue #31、今回の六軸policy・packet・状態遷移・集計・16契約テスト。学習器やモデル内部は不要。
- **B. 拡大理由:** 旧の単一verdictから六軸へ意味が変わるため、既存履歴を変換せず新しいrecord typeと凍結policyが必要だった。独立性を守る提出完了barrier、初回一致率とunknown分母の契約も新設した。
- **C. 責任と状態:** `human_six_axis_pilot` が新しい人手runの状態・seal・集計を所有。既存 `gold_pilot` のpacket読取と不変directory公開を再利用するだけで、旧判定状態は変更しない。学習・Gate Aへの依存を追加していない。
- **D. 次回:** この方針・protocol・新moduleとテストから、割当と人手eventの取込みを進められる。モデル実験履歴やAI個票を読む必要はない。人間の実在確認、独立性確認、語の根拠確認は自動テストでは省略できない。
