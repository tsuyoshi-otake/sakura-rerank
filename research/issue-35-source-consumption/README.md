# #31/#32/#35: 入力範囲を固定した次の1,000文と、本文露出の履歴

2026-11-06 / Parent #1 / [固定した消費契約](contract-v1.md) / [全集計JSON](../../reports/issue-35-source-consumption-v1.json)

**本文を読む前に選んだ次の1,000文で、原文の全変換区間がTop-32候補に存在する文は873件だった。**
Top-1では556件、Top-6では816件。原文候補の存在を測る研究指標であり、モデルAccuracyやGold品質ではない。
採用モデルの記録値90.72%・安全性0.25%は不変。モデル推論・再学習・Gold/calibration採用・final Testは0。

もう一つの成果は、読みが不備でも確認済みの本文を露出履歴に含める境界の補強。
既存の中立source nodeだけでは履歴除外が発火しない合成例を再現し、実データでも関連ありへ追加する入力1件を検出した。
最終的な文単位の内訳は、関連あり483、確認した関係では関連なし483、入力保留34。
不明な原著者・翻訳元まで独立と証明した分類ではない。

## 本文確認前に固定したもの

[前回100文](../issue-35-source-units/README.md)で決めた、原文・送り仮名・位置を保持する連続範囲を主対象にした。
P/S記号はliteralとして残し、ruby内部を分割しない。入力だけの固定カナ投影、読み128・target256・最大32部分、
未対応文字や不備を保留する条件を[plan](plan-v1.json)とともに `7f13399ec009bfaa8e55e43bcef402031e4170da` でcommitした。
左文脈は空。本物のSakura確定履歴を持たないsource文から、session文脈を作ったとは扱わない。

前回取得済みの `tatoeba-jpn-weekly-20261031` の許諾済み文とHrkt注釈のjoin248,947文から、
既閲覧100文を除き、ID・固定seedのhash順だけで1,000文を予約した。編集者quota・本文内容・候補順位による選別なし。
自然な内訳は編集者記録あり428、記録なし572。逆順のmetadata処理でも同一選択だった。
[selection binding](selection-binding-v1.json)を `834425573899125486cbefb990021c346cf2f4e1` でcommitしてから本文をdecodeした。
失敗後の入替え0、追加source取得0。

未選択分も前回byte取得・metadata走査の履歴を持つ。同じexportの次の枠であり、独立Gold Testと呼ばない。
原著者・翻訳元の不明、公式暗号digestがない暫定取得という前回の限界も引き継ぐ。
管理ownerと注釈editorは別々の来歴で、独立した判定者や原著者へ読み替えない。
provider仕様の根拠とlicense pinは[前回の取得レポート](../issue-35-source-pilot/README.md)とplanに残している。

## 1,000文の終端

| 原文・入力の状態 | 文数 | 処理 |
|---|---:|---|
| 原文対応し、連続範囲を構築 | 966 | 1,237入力部分、重複読みを除く1,230要求 |
| 原文対応するが未対応の文字・読み | 4 | 推測せず保留 |
| rubyの全読みが空などの不備 | 30 | 補完せず保留 |
| 合計 | 1,000 | 入替え・分母からの削除なし |

原文と注釈の機械的対応は970件。これは970件の日本語変換を正解認証した数字ではない。
1,000文全てのsource coverageを保持し、不備のある34文も後続の露出管理から消さない。

native要求は[別binding](native-binding-v1.json)を `56d6541771a2f21e501aae2975874f214fd16bf4` で固定してから実行した。

| 1,230固有要求の終端 | 件数 |
|---|---:|
| 既存候補契約を通過 | 1,221 |
| 18区間上限を含む出力契約で棄却 | 9 |
| 候補数棄却 / 未実行 / 再試行 | 0 / 0 / 0 |

並列2、要求ごと30秒、全体900秒、出力512MiBを上限とした。実処理78.308秒。
無効snapshotの一部を救済せず、9件は未測定として全出力を保存した。
全区間を測定できた文957、native未測定9、入力保留34。観測済み部分だけの数は別集計とした。

## 原文候補の存在と改善余地

「全区間」は各変換部分の原文表記がそれぞれTop-kに入ること。全体を同時に選ぶN-best順位ではない。
以下は露出履歴補強後の最終slice。元の関連判定とnative集計も別artifactで保持している。

| 対象 | 全文数 | 全区間測定可 | Top-1 | Top-5 | Top-6 | Top-10 | Top-32 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 全予約文 | 1,000 | 957 | 556 | 799 | 816 | 842 | 873 |
| 確認した関係では履歴接続なし | 483 | 479 | 253 | 387 | 400 | 419 | 435 |
| 履歴接続あり | 483 | 478 | 303 | 412 | 416 | 423 | 438 |
| 入力保留 | 34 | 0 | — | — | — | — | — |

測定可能な957文のうち、84文は少なくとも1部分で原文がTop-32にもない。
Top-32には全区間揃うがTop-1では揃わない文は317、Top-6までに揃う文に限定すると260。
これは固定モデル比較へ進む候補存在の根拠であり、317/260件が意味的にも正しく修正できるという認証ではない。
今回の自然な編集者構成は前回80/20の設計pilotと異なり、873/1,000と89/100を精度の増減として比較しない。
Accuracy、修正成功/破壊率、独立Goldの95%CI、安全性判定は未測定。

## 本文露出を失わない関連判定

旧988,073 nodeへ、前回100 source・312 ruby入力・実際のnative533出現を加えて履歴989,018 nodeとした。
533出現は全426固有要求を覆い、nativeへ渡した通り空の左文脈で入力hashを作った。
今回の1,000 sourceと1,237入力を加えた991,255 nodeを正逆順で照合した。管理ownerの関係は保持した。
初回は関連あり482文/652入力、関連なし484文で、実処理215.998秒だった。

完了監査で、中立source coverageは「既に意味内容を確認した」という履歴とは別であることを確認した。
読みが不備のsourceに有効入力がなくても、同じ/関連本文を後で独立扱いしないためには明示した露出印が必要。
合成2-node例では既存中立グラフは除外0、新しい露出overlayは関連入力を除外した。

[露出binding](source-exposure-binding-v1.json)を `bddb778d1a00edb997464eddb41513ef220bedc9` で固定し、
前回の空読み2文を含む全100 source nodeを明示的に露出済みとして再検証した。
全991,255 nodeの正逆順結果は一致。新しく入力1件・文1件が履歴接続ありとなり、最終483/483/34になった。
追加検証206.517秒、native再試行0。既存の除外を復帰させず、fake reading/input hashも作らない。
前回のsourceと同様、今回の全1,000文も将来の消費履歴へ引き継ぐ必要がある。

## 次に進めることと費用

| 優先 | 作業 | 期待効果 | 費用・条件 |
|---|---|---|---|
| P0 #35/#33 | 固定済みv1/r2/#29等について、既存エンコーダ・candidate数・長さ・fallback契約との対応を確認し、同じ原文再現入力で比較を固定 | Top-6に候補がある260文の差をランキングが埋めるか、長い入力への分布変化に弱いかを切り分ける | 今回の保存候補を再利用できる。新しい評価bindingと同一分母・CPU条件を先に固定。fit不要、Goldや本番精度への読み替え不可 |
| P0 #31/#35 | 読み・意味・入力意図・表記意図を独立した証拠で確認する品質工程を維持 | source対応や編集者名だけをGoldと誤認しない | 今回970機械対応、966入力可でもGold0。1,000件pilotは最終保証ではなく、最終valid3,000件/点99.5%/Wilson下限99.0%を維持 |
| P1 #32 | 入力を作れない本文も含む露出ledgerを次の予約へ引き継ぐ | 今回実際に見つかった1件のような未検出接続を防ぐ | 今回全graph照合は約216秒、露出追補約207秒。旧関係を保持し、公開Testや既閲覧文を新規枠へ戻さない |
| P1 #34 | 真の独立calibrationが成立してから信頼度とRisk-Coverageを比較 | 0.25%を維持して救済と破壊を識別する | 今回は閾値変更0。source再現だけでは安全性を認証しない |

## 再現・検証・保持物

Sakura Inputの観測clean HEADは `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`。
固定reference exporter/dictionaryは前回と同じidentityで前後認証した。現在productionとの候補同値性の証明ではない。
Python3.13.13の既存環境を読み取り使用し、新規依存・build・worktreeは0。

```text
python research/issue-35-source-consumption/stage_owner.py selection prepare_cohort.py 180 select --commit 7f13399ec009bfaa8e55e43bcef402031e4170da
python research/issue-35-source-consumption/stage_owner.py decode prepare_cohort.py 180 decode --commit 834425573899125486cbefb990021c346cf2f4e1
python research/issue-35-source-consumption/stage_owner.py history isolate_consumption.py 1200 execute --commit d0fd88220b67a32951986f4fc9afcf519344433c
python research/issue-35-source-consumption/stage_owner.py native native_consumption.py 1050 execute --commit 56d6541771a2f21e501aae2975874f214fd16bf4
python research/issue-35-source-consumption/stage_owner.py source-exposure source_exposure_audit.py 1200 execute --commit bddb778d1a00edb997464eddb41513ef220bedc9
python research/issue-35-source-consumption/stage_owner.py full-tests-r2 check_consumption.py 900 --result full-unit-tests-r2.json
python research/issue-35-source-consumption/stage_owner.py verification verify_consumption.py 420
python research/issue-35-source-consumption/publish_consumption.py
```

`PYTHONPATH=src`と専用TEMPを設定する。全stageはwrite-onceで、既存rootへの再実行は許可しない。
新規実行には別root/commit/bindingが必要。今回の初回結果・露出追補・最終sliceを上書きしない。

全755テスト成功、失敗/skip0。新規23契約。全1,000文・1,237原位置・1,230native終端・6指標groupを
別の計算で照合し、失敗34文も再確認した。旧16 artifact・25学習binding・10 checkpointはhash不変。
今回の14 Pythonファイルを構文compileし、未使用import0。検証はCodex自身が直接実施し、外部reviewerの判定とは扱わない。
初回750テストと履歴判定も保存した。2巡目で露出管理を補強し、全項目の再検算に通過した。

private再現物は `data/generated/issue-35-source-consumption-v1/`、rubric/履歴/cleanup記録は
`.codex/goal-loop/issue-35-source-consumption/` に保持する。未マージの既存branch
`issue-35-source-units-v1` とDraft PR61を継続使用する。再現用private rootは8,666ファイル・73,188,732 bytes。
所有process残存0を確認し、今回専用TEMPを削除した。ユーザーファイルの削除0。
最終検証receiptは同goal-loopの `result.json`。Gate A/B・独立Gold・リリースは未完了。

## IRVと責任範囲

**A. 範囲:** `tatoeba_consumption.py`がmetadata予約と連続原文の消費を、`source_exposure.py`が明示した本文露出の伝播を所有する。
関連3 test、既存source/input/native/graph契約、研究stageと固定bindingが理解範囲。

**B. 拡大:** 完了監査で「入力を作れなかった既閲覧本文」の露出が中立coverageに埋もれることを再現したため、
source-only exposureの補強と全graph再確認まで広げた。モデル構造・training・productionへ範囲を広げていない。

**C. 依存と状態:** 元sourceと旧グラフはimmutable。消費側が露出済みsource IDを所有し、overlayは既存関係から除外を追加するだけ。
旧validatorや学習/Gold/admissionの契約は変更0。各stageの予約・出力・終端は研究runnerが所有する。

**D. 次回:** metadata選定、送り仮名を保持する入力、入力不備でも残る露出は2 moduleと3 testで確認できる。
次の予約は全1,000 sourceの消費履歴を必ず読む。中立inventoryと実際の本文露出、原文再現とIME正解の違いは引き続き理解が必要。
