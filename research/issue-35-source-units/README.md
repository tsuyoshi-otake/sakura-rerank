# #31/#32/#35: 所有者の意味と、変換する入力範囲を分離する

2026-11-06 / Parent #1 / Source: [PR60の100文pilot](../issue-35-source-pilot/README.md)

**ふりがな部分を個別に変換すると原文表記を得られない52文で、句読点ごとの範囲では全区間の原文表記がTop-32に入った。** 逆方向は1文。これは同じ100文での候補存在の診断であり、モデル精度やGold品質の改善値ではない。採用モデルの記録値90.72%は不変。

もう一つの結果は、Tatoebaの管理ownerだけの関係を診断上取り除くと、履歴接続が84文268注釈から12文43注釈へ減ること。旧sourceの著者関係528,894本と全入力・本文関係は維持した。元の除外は一件も復帰していない。

[全集計・検証JSON](../../reports/issue-35-source-units-v1.json) / [plan](plan-v1.json) /
[native入力binding](native-binding-v1.json) / [未実行分だけの継続binding](native-continuation-v1.json)。
独立Gold、calibration、Gate A/Bとリリースは未完了。安全性0.25%を含む既存条件を変更していない。

## 固定した検証

前回の100文をすべて使い、追加取得・入替え0。原文表記と注釈が対応する98文、空読みで保留した2文を同じ分母に残した。
これは既に閲覧したpilotを使う設計検証で、未使用の評価データとは呼ばない。
planを `1226b2dbc1e6bdbd59ec629619a8011736403f67`、全426要求を
`0fe29e14f3025267c499d8b6164b427d23676320` で固定してから実行した。

| 入力仮説 | 作り方 | 測定できるもの |
|---|---|---|
| 文全体 | 原文全体の読みを一つの要求にする | 同じ全読みの候補順位 |
| 句読点等で区切った範囲 | 記号は原文どおり保持し、その間の連続する読みをまとめる | 各範囲に原文表記があるか。全体の同時順位ではない |
| ruby部分 | 元のruby baseを個別に変換する | 元注釈の全baseがそれぞれ候補にあるか。語・形態素とは呼ばない |

句読点等はUnicodeのP/S分類で扱い、ruby baseの中は分割しない。これは句・文節や実ユーザーの確定範囲を認証するルールではない。
漢字のbaseに続く仮名を捨てず、原文の全文字と位置が復元できることを要求した。
入力だけに固定のカタカナ→ひらがな1対1写像を適用し、長音は保持した。30文で写像が必要だった。
原文表記・元の読みを変更せず、NFKC、長音の補完、辞書による読み推定は行わない。
未注釈の漢字・英数字・空白、未対応読み、制御文字は明示的に保留する契約。今回の98文は3仮説とも入力長等の事前条件に通過した。
128文字の読み、256文字のtarget、最大32変換部分という上限も固定した。

左文脈・右文脈をホスト文書から取得する処理はない。今回の文全体は、source全文を一度に入力したと仮定した変換要求であり、
実際のSakura確定履歴を持つsessionデータではない。モデルへ新しい文脈や特徴量を渡した実験でもない。

## 管理ownerだけを外した関係診断

[Tatoeba公式Help](https://tatoeba.org/en/help)は、文をadoptすると編集できるownerになると説明している。
[公式Contributor Guide](https://en.wiki.tatoeba.org/articles/show/what-you-can-do-and-how-to-do-it)も、ownerが元の作成者と異なる場合があると記載している。
そのため管理ownerを原著者のidentityと同一視しない。ただし、同じ管理者による校正傾向や未知の元出典が独立性へ影響しないと保証するものでもない。

前回と同じ988,485 node、元のcomponent hash・268除外を再現した後、今回のTatoeba100文と312入力仮説に限って管理owner関係320本を診断上外した。
旧著者528,894本は保持。入力、source単位、段落・完全/類似本文の関係はそのまま。
別方法として今回のowner metadataだけをnullにして全グラフを再構築し、全nodeの分割、除外、保持edgeの両端と型が一致した。

| 条件 | 履歴につながる文 | その入力仮説 |
|---|---:|---:|
| 前回の保守的な全関係 | 84 | 268 |
| 今回の管理owner関係だけを診断上除去 | 12 | 43 |

100文の管理owner groupは18、最大groupには31文が属する。
前回の「全著者/ownerを取り除く」診断の交絡を解消し、同じ43入力という結果を今回sourceだけの変更で確認した。
処理215.075秒。元データ・旧除外・split・Gold/calibration採用は変更しない。
不明な原著者や翻訳元を推定して埋めず、この診断結果だけで独立Testへ採用しない。

## 最初の停止と未実行分の継続

初回native実行は13要求が検証済み、1要求が失敗、412要求が未実行で停止した。
変換器自体は正常終了して32候補を返したが、その出力は19区間を持ち、既存データ契約の最大18区間に違反していた。
これは「正解候補がなかった」という観測ではなく、候補snapshotを採用できない状態。

初回report・全14要求の入出力とreceiptを保存した。既試行要求を繰り返さず、
`6a773ebed465f296f4be7de20b0249e7d21e9fd8` の継続bindingで未実行412要求だけを許可した。
既存validatorのContractErrorは未測定の終端として記録し、独立した未実行要求へ進む。
その他の予期しない失敗は停止する。区間上限18を緩和せず、棄却snapshotから一部候補だけを取り出して採点することもしない。

| 全426固有要求の終端 | 件数 | 扱い |
|---|---:|---|
| 既存契約を通過 | 401 | 原文候補の順位を測定 |
| 出力契約で棄却 | 6 | 全snapshotを未測定として保持 |
| 変換器の候補数チェックで棄却 | 19 | 有効候補リストなし。原文候補欠落とは数えない |
| 未実行 / 再試行 | 0 / 0 | 全要求を一度だけ試行 |

6要求はすべて18を超える区間を含む。文全体の5要求、句読点範囲の1要求だった。
候補数チェックの19要求はすべて文全体。全98文で長さ条件を満たしてもnative結果が評価可能になるとは限らない。
出力のうち一部候補が17/18区間でも、別候補が19〜23区間ならsnapshot全体を棄却する既存契約を維持した。

並列2、各要求30秒、初回全体900秒、継続600秒の上限。自動retry0。
継続の実処理25.834秒、観測した出力14,020,700 bytes、上限512 MiB以内。
runnerの終了コード0だけでは完了を判定せず、requested・attempted・measured・rejected・not-attemptedの全数を別途照合する。

## 同じ100文での候補存在

以下の「全区間あり」は、すべての変換部分で原文表記がそれぞれTop-k候補にある文の件数。
文全体のTop-kと同時に選べる候補の順位は別の指標。独立正解率・実使用Accuracy・モデル改善幅には読み替えない。

| 仮説 | 全文数 | 測定できた文 | native未測定 | 注釈保留 | 全区間Top-1 | Top-5 | Top-6 | Top-10 | Top-32 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 文全体 | 100 | 74 | 24 | 2 | 49 | 66 | 66 | 68 | 68 |
| 句読点等ごとの範囲 | 100 | 97 | 1 | 2 | 65 | 87 | 87 | 89 | 89 |
| ruby部分ごと | 100 | 98 | 0 | 2 | 23 | 37 | 38 | 38 | 38 |

句読点範囲は122変換部分、rubyは312部分を測定した。部分数が多いと「全部分成功」が難しくなるため、
単に89対38を51ポイントの精度改善とは言わない。
同じ文での対応表は、両方Top-32にあり37、句読点範囲だけあり52、rubyだけあり1、両方欠落7、
句読点範囲が未測定でruby欠落1、注釈保留2。
文全体の候補を測定できたが原文がTop-32にない6文は、他の2仮説でも部分候補が欠落していた。

この結果は「ruby baseを完全な変換単位として切り出す」方法を優先して見直す根拠となる。
送り仮名等を含む連続した範囲には原文候補が存在しても、短く切った読みでは存在しない場合がある。
52文すべての語義や入力意図を認証したわけではない。各層80/20の数値もJSONに保存した。
意図的な層別・既閲覧の100文、共有owner、未認証label、native未測定があるため、
独立Accuracy/Gold品質の95%信頼区間は未計算・未認証とする。安全性の合格判定は行わない。

## 次の改善と検証費用

| 優先 | 改善 | 期待効果 | 検証コスト・条件 |
|---|---|---|---|
| P0 #31/#35 | 連続した原注釈と送り仮名等を保つ入力範囲を、新しいsource消費契約として固定する | 52文で見えた候補存在の差を、断片教師を避ける設計につなげる | 現100文は設計用。別の未使用枠を予約する前に範囲・literal・読み投影・保留条件を凍結。今回native426要求は約27秒の実処理 |
| P0 #32/#35 | owner、原著者、翻訳元、レビュー履歴を別の来歴として扱う | 管理権限を原著者と誤解した推移的除外を避け、必要な依存関係を保持する | 今回のfull graph再構築約215秒。旧著者・入力・本文関係を保持し、不明な作者を同定済みにしない。旧除外を回収する処理は追加しない |
| P1 #32 | 文全体のnative棄却を独立して監査する | 候補生成の欠落と、区間数/候補数の契約上の未測定を区別する | 保存した25要求のbyte列から開始でき、再試行不要。上限を無断で緩和せず、実際の入力範囲・runtime/feature契約との整合を先に確認 |
| P1 #35/#34 → #33 | 新規sourceの独立研究評価・calibrationが成立してから同予算比較 | 入力範囲改善がランキングや破壊率に効くか測定する | 今回fit0・モデル推論0。Gold点推定99.5%/Wilson下限99.0%/final valid3,000件、安全性0.25%、最終Test一回使用を維持 |

## 再現・検証

Sakura Inputの観測HEAD `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88` はcleanで、planに記録しnative前後でも照合した。
使用したreference exporterのsource HEADは `5eefa2ffe15297e563da281432cece56049a1b09`。
binary SHA-256 `3c12f1f603413a597e658a11df0148ca43354299addc9551a2fcf1f4daea9977`、
dictionary SHA-256 `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad` を前後確認した。
これは固定研究exporterによる診断であり、現在のproduction HEADとの候補同値性を今回証明したとはしない。
既存Python 3.13.13環境を使用し、新規依存・build・worktreeは0。

```text
python research/issue-35-source-units/stage_owner.py prepare prepare_units.py 180 --plan-commit 1226b2dbc1e6bdbd59ec629619a8011736403f67
python research/issue-35-source-units/stage_owner.py owners diagnose_selected_owner.py 1200 --plan-commit 1226b2dbc1e6bdbd59ec629619a8011736403f67 --implementation-commit 0fe29e14f3025267c499d8b6164b427d23676320
python research/issue-35-source-units/stage_owner.py native unit_native.py 1050 execute --commit 0fe29e14f3025267c499d8b6164b427d23676320
python research/issue-35-source-units/stage_owner.py continuation resume_native.py 720 --binding-commit 6a773ebed465f296f4be7de20b0249e7d21e9fd8
python research/issue-35-source-units/stage_owner.py full-tests-r2 check_units.py 900 --result full-unit-tests-r2.json
python research/issue-35-source-units/stage_owner.py verify-r2 verify_units.py 420
python research/issue-35-source-units/publish_units.py
```

`PYTHONPATH=src`と所有するTEMPを設定する。初回の非時間情報を含むreceiptまでhash-boundなので、
継続bindingの再現には保存した初回artifactが必要。別マシンの新しい実行では新しいbindingを作り、
既存rootや過去receiptを上書きしない。

全732テスト成功、失敗/skip0。新規31契約は入力範囲・投影・全分母・owner限定・旧edge維持・
未実行分だけの継続・棄却を成功にしないことを検査する。
全100文、312原位置、426一回限りの終端、9指標group、全native成功/棄却を別式で再計数した。
旧16artifact・25学習binding・10checkpointは不変。
初回native停止と初回verifier失敗の記録を残した。後者は実行済みplan生成器の未使用`ROOT` importで、
数値検算はその前に通過していた。hash-boundの実行時コードを保存し、この1件を静的検査の既知所見として明示した。
他の未固定/runtime importの未使用は0、15 Pythonファイルの構文compileは成功。
全所有runner・native workerの終了を確認し、今回専用のTEMPを削除した。
再現用private artifactは `data/generated/issue-35-source-units-v1/`、失敗と検証履歴は
`.codex/goal-loop/issue-35-source-units/` に保持する。未マージの
`issue-35-source-units-v1` branchを復旧用に残し、ユーザーの既存差分は変更していない。

## IRV・状態の所有

**A. 範囲:** `tatoeba_input_units.py`が入力投影とexact範囲、`source_owner_diagnostic.py`が選択sourceだけの関係診断を所有する。
4つの関連testと既存のinput/snapshot/graph契約、source pilotのhash-boundな100文が理解範囲。
研究stageとplan/native/continuation bindingが副作用・予約・終端を所有する。原文や個別候補はignored rootだけに置く。

**B. 拡大:** 18区間を超える実出力で初回処理が止まったため、既存snapshot契約とnative validatorまで追跡した。
過去の著者まで消す診断を避けるため、関係edgeの保持と全グラフ再構築も必要だった。
別のモデル構造・production・Gold判定を調査範囲へ広げていない。

**C. 依存と状態:** 新しい研究consumerは既存のimmutable候補契約・graph APIを呼ぶ。
既存contract、区間上限、学習/Gold/admission/production APIの変更は0。
source ownerの省略は診断出力のみで、splitを書き換える権限を持たない。
native棄却は未測定の終端であり、部分成功が信頼済みdatasetへ進む経路はない。

**D. 次回:** 同じ形式の入力範囲は2つの新moduleと4testから確認でき、rubyを形態素と誤認する調査を繰り返さずに済む。
snapshotの18区間上限、候補数棄却、sourceからの仮説と本物のIME範囲の違いは次回も理解が必要。
巨大な履歴の再構築費用は残る。計測の途中停止があっても、既試行・未実行・棄却を混ぜずに再開する契約を再利用できる。
