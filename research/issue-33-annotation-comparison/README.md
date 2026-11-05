# #33: 辞書抽出と原注釈抽出を同量で比較する準備

2026-11-05 / Parent #1 / Related #31, #32, #49

**Wikipediaと青空文庫を各25,000行ずつ含む、50,000行の比較群を2群準備した。共通Wikipediaは同じ25,000行で、union 75,000行の全11配列・26,775,000要素が別式による再計算とbyte一致した。** 元の辞書抽出162,502行を原位置へ結び直し、混合時の履歴分離を全関係から確認した。

今回の完了範囲は比較用データと実験条件の準備。新fit・モデル推論・追加native要求・最終Test利用・Gold認証は0で、**新しい精度改善は未測定**。採用モデルの記録値90.72%、安全性0.25%、独立Gold・Gate A/Bの条件は変更していない。リリース目標は継続中。

## 先に固定した比較

[方針v1](policy-v1.md)、[plan v1](plan-v1.json)を`55d26ed`で固定し、既存入力のbyte上限だけを訂正した[plan v2](plan-v2.json)を`b828445`で固定した。対象は**抽出方式全体の効果**である。原ルビを使うと読み、入力単位、表記分布、難易度も変わるため、純粋な読み品質だけの因果効果とは呼ばない。

両群は同じC2、初期#29 checkpoint、3 seed（20260814 / 20261103 / 20261104）、各500更新、batch256、既存損失・optimizerを使う計6fit。候補条件を満たしたstable ID昇順で各出典25,000行を選ぶ。閾値探索、途中評価、best seed選択、学習回数追加は行わない。原recordのtraining/Gold flagsはfalseのままで、研究fitは別bindingと未使用研究評価の準備成立後に限る。

原表記再現は実IMEの唯一の正解ではない。入力単位、意味・用法、表記意図は未認証で、#48の意味対比品質条件も代用しない。右文脈・著者・監査metadataは特徴量へ渡さず、既存のbounded left context/reading/candidate契約を使う。

## 原文と混合範囲の実測

| 対象 | 実測 |
|---|---:|
| 原位置を検証した辞書抽出行 | 162,502（Wikipedia 103,689 / 青空58,813） |
| Wikipedia対象ページ / 実際に消費する原段落 | 17,744 / 62,404 |
| 追加した完全なsentence coverage | 132,289 nodes |
| 全履歴を含む混合inventory | 965,889 nodes |
| 比較元の全行 / 隔離された行 / source通過 | 198,094 / 5,273 / 192,821 |
| 候補条件通過: Wikipedia / 辞書青空 / 原注釈青空 | 101,663 / 53,549 / 35,592 |

元4,827,732,824-byte Wikipedia dumpを一回走査し、3,100,497ページ中の対象ページから固定cleanerで原段落を復元した。全行の原位置、左文脈、対象、revision、stable-ID preimage、辞書由来readingを確認した。これは文脈上の読みの認証ではない。

別検算では保存段落bytesを元paragraph hash・位置式と照合し、青空は元archiveも認証して位置を確認した。**Wikipedia dump全体を二度parseした検証ではない。** 既存原注釈35,592行は[#55の証拠](../issue-33-consumed-numeric/README.md)を再認証した。

原833,600-node graphの全typed edges・audit・分離結果は新backendと一致した。その後、新coverageを加え、旧隔離25,966段落を保持したまま全関係を構築した。実際の消費scopeでは813,852 nodesを使い、履歴へつながる入力0を確認。順序を反転した再構築も一致した。旧representative edgesの間引きではない。各行の候補snapshotも元bytesまで認証し、欠落を別表記や旧cacheで補完していない。

根本的な修正は、**完全なsource metadataと実際のモデル入力の上限を分けたこと**。新coverageの1 nodeには515 signature hashesがあり、従来の512上限を超えた。[source-only契約](source-coverage-contract-v1.md)と[scope plan](scope-plan-v1.json)を`6db536c`で先に固定し、neutral metadataのみ1,024まで受け付ける新boundaryを追加した。実入力512、Jaccard 0.8、全signature、元source、旧隔離は不変。長い原文を切り詰めたり、該当行を消したりして通していない。

## 数値と重複の検証

| 固定50,000行内の記述統計 | 辞書抽出群 | 原注釈抽出群 |
|---|---:|---:|
| Wikipedia / 青空 | 25,000 / 25,000 | 25,000 / 25,000 |
| 読み種類 | 16,311 | 16,827 |
| 同じ読みで複数表記がある行 | 12,106 | 12,552 |
| 原表記が候補Top-1の行 | 40,132（80.264%） | 34,186（68.372%） |
| 同集合の読み最多表記に一致する行 | 47,040（94.080%） | 46,635（93.270%） |
| 完全モデル入力の重複 / 競合label / component間重複 | 5組 / 0 / 0 | 5組 / 0 / 0 |

これは**訓練元の記述統計**で、モデル精度・独立評価・IME正解率ではない。原注釈群には2文字読み7,196行があり、辞書抽出群にはない。難易度や入力分布が変わることも、方式全体の比較と定義した理由になる。結果を見て読みや出典比を再調整していない。

各群の5組10行は、両群に共通するWikipedia内の同じ5組である。各群の一意モデル入力は49,995。両群で共通の25,000行を一度だけ収めたunion 75,000行では406組812行が同一モデル入力で、一意入力は74,594。競合label・component間重複はunionでも0。固定集合を事後に重複削除せず、訓練内の反復として明示した。全履歴cacheのtensor比較を新たに実施したという意味ではなく、履歴分離はsource/実入力graphで確認している。

各行は原source位置、許可段落receipt、元行、candidate snapshot、最小encoder projection、tensor hashを結ぶ。producerと別の既存検算式で全75,000行の値とbytesを照合し、11配列・26,775,000要素、row chain、label/input hashが一致した。展開配列192,150,000 bytes、新NPZ 13,102,563 bytes。数値出力のconsumerは検証専用で、単独ではfitを許可しない。

cache manifest SHA-256: `4939d5dc96a860854085c6d36ee2f2baf0f232804a98cbbe626526f5623707e9`。row chain終端: `f119dcd99af0a6a9ce2d523d2feeaaec47a8976714d85b511bb9d34e17ca0e4d`。

## 未使用研究評価と次の実行条件

KWDLC public-train 3,915文書から、既露出2,300文書をすべて除き、本文取得前にhash順で新1,000文書を予約した。選択順・membership・既露出との重複0を別検算した。予約後の残りは615文書。**今回本文取得0、モデル採点0**で、public dev/testやリリース最終Testではない。

| 次の工程 | 期待効果・成立条件 | 固定した費用・上限 |
|---|---|---|
| 予約済み評価集合の準備 | 両訓練群・全履歴からの分離を確認し、1文書1対象で主評価500件以上。失敗を含む全1,000枠を保持し、文書を交換しない | 原本文5,684,261 bytes、各準備stage最大1,800秒。取得・候補処理の実時間は未測定 |
| 別fit bindingと計6fit | 同じC2で抽出方式の効果を測る。全6checkpointを固定するまで評価しない | 500更新×6、各fit最大1,800秒、途中探索0 |
| 一回の研究比較とCPU検証 | 3seed平均のpaired差と共通component bootstrap95%区間。救済・破壊・Precision/Recall・適用率・失敗/fallback・文脈介入も報告 | bootstrap2,000回。固定seedの各群exportはwarmup200＋10,000回、batch1、ORT 1/1 thread、GPU off |

主比較は原注釈群−辞書群の原表記一致率差。全seed点差が非負かつ平均差95%下限が正の場合だけ後続研究候補へ進める。研究gate margin>1.7は固定し、calibrationや閾値探索に使わない。いずれも独立Goldによるproduction採用判定ではない。

KWDLCは評価専用で学習・語彙補完・再配布に使わず、原文権利と元URLの制限は既存planのまま扱う。Gold点推定99.5%以上・Wilson95%下限99.0%以上・最終valid3,000件、安全性0.25%、最終Test一回限り、Gate A/Bは不変。

## 再現、失敗記録、検証

新source producerは`d84c093`、新scope producerは`de97ccb`、成功numeric producerは`8b6c245`。各reportが実装file hashと入力/出力hashを固定する。Sakura Inputのclean HEAD `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`は観測記録だけで、今回production挙動には利用していない。

以下の失敗は上書きせず保持した。

1. plan v1の既存入力上限512MiBに対し、固定済み辞書poolが764,553,112 bytes。parse前に停止した。plan v2はこのSHA-bound入力だけに正確なbyte上限を与え、新artifact上限512MiBを維持した。
2. neutral coverageの515 signatureを実入力用512上限で拒否した。別source契約を固定して全関係を再検証した。原文を削除・短縮していない。
3. 最初のnumeric生成は全要素一致後のdirectory renameでPermissionError。既存の上限付きWindows publication/backoffを再利用し、新rootで再実行した。旧失敗はfailedのまま保存し、NPZ・ledger・indicesは再実行とbyte一致した。元のOS error番号・lock所有者は未記録なので、antivirus等が原因とは断定しない。

unit runnerの最初の517件/11 import errorは、専用一時runnerの`sys.path`不足だった。runnerだけを訂正して644件成功、最終numeric修正後も**644 tests成功、failure/error/skip0**。原入力復元6件とneutral graph4件の新契約、既存のWindows publication/retry契約を含む。12 Python filesのAST/import参照検査、元16+25artifact hash不変、`git diff --check`、raw追跡0も確認した。型checkerは実行していない。

```text
PYTHONPATH=src python research/issue-33-annotation-comparison/recover_sources.py
PYTHONPATH=src python research/issue-33-annotation-comparison/verify_sources.py
PYTHONPATH=src python research/issue-33-annotation-comparison/verify_reservation.py
PYTHONPATH=src python research/issue-33-annotation-comparison/prepare_cohorts.py
PYTHONPATH=src python research/issue-33-annotation-comparison/prepare_numeric.py
PYTHONPATH=src python research/issue-33-annotation-comparison/verify_preparation.py
PYTHONPATH=src python -m unittest discover -s tests -v
```

生成はwrite-onceで、既存rootへの再実行は拒否する。再現時は保存済みreceiptの照合か、別の事前固定rootを使い、既存失敗を削除してやり直さない。検証専用scriptも既存reportを上書きしない。既存Python3.13.13/NumPy2.3.5環境を読取り利用し、新依存の導入0。所有runnerは上限時間・process-tree終了とterminal receiptを持つ。

実時間はsource生成681.959秒、別位置検算45.153秒、成功scope525.935秒、成功numeric37.361秒、最終unit27.111秒（各外側runner）。新モデル未作成のためモデルparity/CPU10,000回は後続工程である。

結果: [原文復元](../../reports/issue-33-annotation-comparison-source-v1.json)、[原位置検証](../../reports/issue-33-annotation-comparison-source-verification-v1.json)、[混合scope](../../reports/issue-33-annotation-comparison-scope-v1.json)、[全数値検証](../../reports/issue-33-annotation-comparison-numeric-v1.json)、[研究評価予約](../../reports/issue-33-annotation-comparison-reservation-v1.json)、[完了検査](../../reports/issue-33-annotation-comparison-checks-v1.json)、[cleanup](../../reports/issue-33-annotation-comparison-cleanup-v1.json)。Gitへ保存するのはaggregateだけで、原文・読み・候補・stable IDs・NPZは含めない。

本単位は4反復で6基準を検証する。Codexが直接検証し、外部agentや人手のレビューは生成していない。専用`~/tmp/issue33-annotation-comparison-20261105/`は削除し、所有runner残存0を確認。再現・失敗回復用としてignored `data/generated/issue-33-annotation-comparison-v1/`、`.codex/goal-loop/issue-33-annotation-comparison/`、未マージbranch `issue-33-annotation-comparison-v1`を保持する。リリース全体は未完了。

## IRVと責務

A. 必要な範囲は原位置復元、neutral source graph、固定cohort選択、数値化と検算、未使用評価予約。新source module2、test file2、研究scripts8、方針/plan/coverage契約を中心に、既存source・candidate・encoder・関係生成の契約を参照した。回帰は全644件で、production変更はない。

B. 青空だけの分離ではWikipedia混合後の分離を保証できないため、全履歴graphまで調査した。515-signature失敗からsource metadataと実入力の違いが判明し、上限の所有責務を分けた。Windows publicationの失敗には既存の検証済みhelperを再利用し、無関係なrefactorはしていない。

C. `reconstruction_inputs.py`が原文位置/読みprovenance、`reconstruction_graph.py`が完全neutral metadataの受入れを所有する。関係生成そのものは固定済みcoreに依存し、元の実入力validatorは変更しない。研究scriptsがreservation・cohort・numeric・明示terminalを所有する。新しいGold判定・ラベル編集権限は導入しない。

D. 次のfitは元4.8GB dumpを再parseせず、plan・source/scope/numeric検証receiptとhashから入力の根拠を追える。新たに理解すべき契約はsource-only上限とmodel-input上限の区別、原表記再現とIME正解の区別、数値検証とfit実行許可の区別。Windows transient publicationの学びは既存memoryにあり、重複追記していない。
