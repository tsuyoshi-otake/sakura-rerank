# #32: 原文を保持したまま、利用する段落と左文脈を隔離する

2026-11-05 / Parent #1 / Related #31, #35, #49

**重複に接する段落全体を利用対象から外す事前固定の試験で、原文照合・履歴分離を確認した仮候補は93,973件となった。** 旧#49の全取得本文を使う条件で残った1,741件をすべて含む。これは利用する本文の範囲を変えた結果であり、旧除外の誤り、学習許可、Gold品質やモデル精度の改善を示さない。

今回の成果は、本文の利用範囲を追跡するsidecarと、分離・原位置を実データで検証した研究実装。学習採用・旧除外の復帰・新fit・モデル推論・native要求・最終Test・Gold認証は0。採用モデルの記録値90.72%と安全性0.25%を変更していない。リリース目標は継続中。

## 固定した仮説と利用範囲

仮説は、評価側と関係する本文を実際に消費しなければ、同じ作品内の別段落まで一律に捨てる必要があるかを検証できる、というもの。[前段の接続経路](../issue-32-source-relations/README.md)で、短文例外や近重複閾値の調整を優先する根拠は得られなかった。そこで文字数による例外を設けず、原文の段落全体を隔離する一つの方針を[plan v1](plan-v1.json)、commit `0956550529066046f4c5d294a4c9ce79412b79de`で実測前に固定した。実装は`14f3ca1b4c73184fb0749f30626bb133f84f6b5d`。

- 元の833,600 nodeをすべて隔離判定に使う。履歴218,189、未使用の旧訓練pool164,320、全文coverage349,466、新仮候補101,625。履歴の旧train・dev・holdout・露出評価・split不明を削除しない。
- 作品・著者・実入力の関係で履歴に接するsourceは隔離する。加えて、段落・同一文・類似文・実入力の関係で履歴に接する段落を丸ごと隔離する。Jaccard .8や元の関係定義は不変。
- 原文内の`article_id + paragraph_hash`を一単位とする。同じ作品内の同一段落は同じ判断を共有するが、各候補ではrevision・段落位置・原行・注釈位置を別に照合する。左文脈は同じ許可段落内の直前8–64文字だけ。削除箇所をまたいで文章をつなぎ直さない。
- 提案した利用グラフは全履歴と許可段落coverage・新仮候補だけ。旧poolは隔離判定の橋として残し、実際の利用には含めない。元の全取得本文グラフ・除外・split・source byte列は保存する。

削除後のグラフは残ったnodeから既存coreで作り直す。以前の代表edgeを単にフィルターすると、代表nodeを消したとき、残ったmember同士の正当な関係まで消えるためである。新しいグラフでも作品/著者/実入力/本文の全関係を適用し、仮候補が一件でも履歴へ接続すれば成功成果物を公開しない。

Sakura Inputのclean HEAD `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`をplanへ記録したが、その挙動・production codeは今回利用していない。外部データ取得・依存追加も0。

## 同じ分母での結果

| 対象 | 利用範囲内・原文照合用 | 隔離または未解決 | 全件 |
|---|---:|---:|---:|
| 一意な原文段落単位 | 134,298 | 本文/実入力関係25,966 | 160,264 |
| 原文中の段落出現回数 | 137,526 | 本文/実入力関係27,013、coverage不明1 | 164,540 |
| 原注釈から抽出済みの仮候補 | 93,973 | 本文/実入力関係7,652 | 101,625 |

段落の同一出現をまとめるため、単位数と出現回数は異なる。coverage不明1段落も未解決の終端として保持し、許可へ倒していない。作品/著者/実入力だけによる隔離は今回0だったが、この検査を取り除いてはいない。

原注釈の全132,729枠も分母を維持した。仮候補101,625に至らなかった31,104枠は、読み長15,273、左文脈不足14,468、文長768、編集注記等518、base未解決77。今回の利用範囲変更でこれらを取り込んでいない。

旧条件の1,741仮候補は全件残り、今回の利用範囲で追加分離された仮候補は92,232件。新しい利用グラフは585,069 node（履歴218,189、許可coverage272,907、仮候補93,973）。**全仮候補の履歴接続は0**で、逆順にnodeを渡した全再構築でもcomponent hash・除外・集計が一致した。

残る仮候補は507作品、137著者、42訓練componentに分布する。93,973件を独立標本数とは扱わない。この42は分割上の関連集合数であり、独立性の統計認証でもない。全取得sourceの旧除外99,884件を復帰させたのではなく、使わない本文を含めない別の利用案を測った。

## 原位置・左文脈と禁止する利用者

全93,973件を元の546作品の認証済み原byte列へ戻し、base・原ルビ・読み・段落/文/行/注釈位置・revision・出典metadata・同段落の左文脈を照合した。別検算は原CP932行と注釈regexから入力を再計算し、新しい`verify_consumption`を呼ばずに保存receiptと一致した。段落出現の全164,540件、単位台帳160,264件、仮候補終端101,625件も再集計した。

receiptはhashと位置だけで、原文や読みをreport/logへ出さない。元の`training_eligible=False`と`independent_gold_eligible=False`は維持する。新boundaryが許すconsumerは`source_verification`だけ。training、body pretraining、numeric cache、model inference、checkpointは拒否する。

これは**今回の研究用boundaryの契約**であり、既存学習pipeline全体を置き換えたわけではない。実際に採用するには、許可範囲だけから教師・feature・cacheを生成したというprovenanceと、隔離本文の再流入を拒否する統合が必要。原文照合だけではIMEで確定する入力単位、用法・表記意図、独立Gold品質は決まらない。旧1,741件で測ったTop32=741という候補存在率を、新93,973件へ外挿しない。

## 次に進める改善と費用

| 優先・責務 | 次の検証 | 期待効果 | 費用・停止条件 |
|---|---|---|---|
| P1 #31/#49 | 原注釈baseとIME入力単位を区別した固定条件、全件終端、出典を分離した対比容量を確認 | 大幅に増えた仮候補のうち、順位学習に使える読み・表記・文脈の対比があるか判断できる | 既存source/receiptを再利用するmetadata監査から着手。native追加要求は読み件数・上限・cache identityを先に固定。現在は候補存在率・Gold品質・精度効果は未測定 |
| P1 #32/#35 | 利用範囲receiptを教師・feature生成へ接続し、元本文や旧cache/checkpoint経由の再流入を拒否する | 保存した分離証拠と実際の消費byte列を一致させる | 今回は試験136.9秒、別検算121.7秒。統合費用は入出力契約の範囲を確定して見積もる。未認証ラベルや未許可consumerは拒否 |
| P2 #33 | 上記が成立した場合に、同量・同予算の順位学習を独立研究評価で比較 | 量だけでなく正しい対比を増やした効果を測定する | 新fit開始0。旧devや最終Testで方針・閾値を選ばない。精度改善幅は未測定 |

最終Test一回限り、独立calibration、安全性0.25%、Gold点推定99.5%以上/Wilson95%下限99.0%以上/最終valid3,000件以上、Gate A/Bは不変。AIや原文一致を人手認証と偽らず、人手不在をユーザーへ差し戻す前提にも戻さない。未認証の品質条件を明示して、検証可能な研究を続ける。

## 再現・検証・資源の終端

既存研究用Python 3.13.13を読取り利用した。planは前段のplan/report/core/source hashを連鎖して認証し、最大1,000,000 node、各stage1,200秒、artifactごと512MiBを固定する。初回実行は記録された実装commitと未使用の出力rootが必要。実行済みrootは消さず、後続の照合にはverifierを使う。

```text
PYTHONPATH=src python research/issue-32-consumed-source/run_trial.py
PYTHONPATH=src python research/issue-32-consumed-source/verify_trial.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

| Verify | Expect / 実測 |
|---|---|
| 固定plan・input/core hash、旧artifact照合 | 一致。旧16+25 artifact不変、旧full-source除外不変 |
| 新規8契約を含むfull suite | 607成功、error/failure/skip0。全段落隔離、原位置改変、禁止consumer、代表node削除を検証 |
| 逆順taintと利用グラフ全再構築 | 全unit判断・仮候補終端・component・監査値が一致、履歴接続0 |
| 原行からの入力再計算と全分母検算 | 93,973入力、164,540段落出現、132,729原注釈枠を確認 |
| static・artifact追跡・cleanup | 5 Python filesのAST/参照import確認、実データの追跡0、所有runner0、専用tmp削除。詳細は下記機械記録 |

初回focused testの3件は合成sourceに必須header/footerがなく、新boundaryへ到達する前に失敗した。既存の`raw_source` fixtureを再利用して修正した。production parserや方針は緩めていない。修正後のfocused8件とfull607件は成功。モデル未変更のためONNX parityやCPU10,000回測定は今回の対象外。

結果：[集計](../../reports/issue-32-consumed-source-v1.json)、[全検算](../../reports/issue-32-consumed-source-verification-v1.json)、[完了チェック](../../reports/issue-32-consumed-source-checks-v1.json)、[後片付け](../../reports/issue-32-consumed-source-cleanup-v1.json)。再現用のignored `data/generated/issue-32-consumed-source-v1/`、検証経過の`.codex/goal-loop/issue-32-consumed-source/`、未マージbranch `issue-32-consumed-source-v1`を継続用に保持する。専用`~/tmp/issue32-consumption-20261105/`は削除済み。

## IRVと検証済みの学び

A. 必要だった範囲はデータ境界契約、前段のgraph/出典/原位置契約、新module1・研究scripts3・test file1・plan1。元splitterの公開研究adapterを再利用し、学習器・production codeへ変更していない。全回帰607件を実行した。

B. 代表nodeの削除で既存edge証拠を使い回せないため、残nodeでの全再構築へ検証を拡大した。原位置照合も単なる同一hash確認ではなく、原行からの入力別計算を行った。分類規則を件数に合わせて試行する方向へ拡大していない。

C. `consumed_source.py`が段落利用判断と厳密な原位置receiptを所有する。scriptsは入力認証、write-once台帳、実行終端、別検算を所有する。既存source抽出・split・学習許可の所有権は不変。追加依存は固定annotation metadataと既存分離coreへの研究契約で、consumerの許可を暗黙に広げない。

D. 次の利用範囲統合は、全過去モデル実験を再読せず、このplan・unit/target/consumption台帳・全検算から開始できる。新たに理解すべき事項は、原文の保管と実際の利用を区別し、全consumerのbyte列を同じ許可範囲へ結び付けること。検証済みの学びは、**nodeを削除する比較では、以前の代表edgeをフィルターするだけでなく、残nodeの関係を再構築する必要がある**こと。今回の単位の検証通過と、品質・精度・リリース完了は分けて扱う。
