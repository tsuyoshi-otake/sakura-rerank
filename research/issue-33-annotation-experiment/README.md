# #33 原注釈抽出方式の固定比較実験 v1

**結論：今回の原注釈方式は不採用。** 事前指定した主比較は、同じ985件に対するゲートなし原注釈方式−辞書方式の3 seed平均で **−3.45 pp、対応source-component bootstrap 95% CI −5.10〜−1.89 pp** だった。全seedで悪化し、事前の前進条件を満たさない。原注釈を増やすだけでは改善しなかった。モデル、特徴量、閾値を結果に合わせて変更していない。

これは新規KWDLC source reconstructionの研究結果であり、独立した人手IME Gold精度ではない。旧devの採用値90.72%と直接比較しない。既存モデルの採用状態、0.25%の安全性基準、Gold品質条件、Gates A/Bは変わらない。最終Testは使用していない。追跡は親#1、#33、#49、#32、#34。前段は[固定データ準備](../issue-33-annotation-comparison/README.md)とDraft PR #56。

## 1. 仮説と事前固定した変更

仮説は「辞書から部分読みを再構成する方式より、元の読み注釈と入力単位を保つ方式が未知資料で正しい候補を選べる」だった。二群ともWikipedia 25,000件を共有し、Aozora 25,000件だけを辞書抽出／原注釈抽出で置き換えた。各50,000件、union 75,000件。データ量、初期#29 C2 checkpoint、3 seeds、500更新、batch256、AdamW lr0.0001・weight decay0.01、gradient clip1、元のmasked CEとlabel smoothing0.05、dropout0.1を固定した。

**抽出方式全体の比較であり、読みの品質だけの因果効果ではない。** 入力単位、語彙、読み長、資料内分布、ラベル難度も同時に変わる。形態素注釈・rubyがあることは、IME入力境界、意味、表記意図のGold認証にならない。#48の意味対照品質条件も未達のまま。

実装順に、本文取得前の[execution plan](execution-plan-v1.json)（commit `dc39ee520df68cb99d99ec85905c19b3388e32f5`）、候補実行前の[candidate binding](candidate-binding-v1.json)（`d142dd5fe4e2a1884b2cfb6cd1c1268df92dae2f`）、学習前の[fit binding](fit-binding-v1.json)（`260c1b295a161282c3287194f0d058b4bb446b88`）、全checkpoint保存後・推論前の[evaluation binding](evaluation-binding-v1.json)（`0bc2c449ac849e3d1bdf2c7dd35c19a38360f6f1`）をcommitした。主判定は全seed差が非負かつ平均差の95% CI下限>0。モデルやseedの事後選択を許さない。

## 2. 資料、分離、候補の存在率

KWDLC commit `c6ae49d29eca4e1134c6676d682adf5ed6a25f5a`の予約済み1,000資料を全件取得し、元Git blobとSHA-256を確認した。受信5,684,261 bytes、再試行・差替え0。元の全3,132注釈単位を含め、10,572 eligible入力を二度復元して一致した。前段965,889ノードと結合した979,593ノードの履歴・学習・source graphを順序反転でも全再計算した。過去の実入力は評価隔離用コピー上だけhistorical扱いとし、元データ・train・除外履歴は変更しない。利用範囲は固定planの研究評価に限り、KWDLCの権利・再配布条件は未解決のまま。学習への利用やモデル配布を許可する結果ではない。

eligible入力の162件が歴史的関係で除外され、10,410件が残った。資料ごとの固定主評価1,000枠では985件を保持、15件を隔離し、補充しなかった。判定分母985は全モデル共通。62対照quartets・248行を別集計し、候補が支持する53quartets・212行の条件付き集計も併記する。候補によって主評価を選び直していない。主評価のsource componentsは983、対照全体33、支持対照31。

| 主評価985件の元表記候補 | 存在件数 | 存在率 | 欠落件数 |
| --- | ---: | ---: | ---: |
| Top-1 | 823 | 83.55% | 162 |
| Top-5 | 964 | 97.87% | 21 |
| Top-6（現モデルの入力） | 970 | 98.48% | 15 |
| Top-10 | 972 | 98.68% | 13 |
| Top-32 | 973 | 98.78% | 12 |

「元表記の存在」は条件付きsource-exact検査であり、人間が許容する全表記の存在率ではない。Top-32欠落12件を一律に候補生成不良と認定しない。1,212 selected rowsに対して792固有requestを実行し、失敗・未実行0。固定したSakura Inputのclean HEADは `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`。11配列・432,684要素を別の数値式で全件照合した。request IDのnamespaceが以前と異なるため、再利用0は「全読みが新規」の意味ではない。

## 3. 全モデルを同じ985件で比較

ベースラインは823/985=83.55%、誤り162件。Rは誤→正、Hは正→誤、Wは表記を変えた誤→誤。修正失敗数はH+W、適用数はR+H+W。Precision=R/適用数、Recall=R/162、修正対象への適用率=(R+W)/162。元表記と同値の候補選択は破壊として数えない。各数値の全分子・分母、Wilson CI、対応component CI、Top-6に元表記が存在するのに不正解となった件数は[全結果JSON](../../reports/issue-33-annotation-experiment-models-v1.json)に保存した。候補取得・推論失敗は全条件0。

### ゲートなし・文脈あり

| モデル | 正解/985・Accuracy | Accuracy 95% CI | 救済 R | 破壊 H | 誤→誤 W | 修正失敗 H+W | baseline差 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| reference29 | 820・83.25% | 80.89〜85.58% | 40 | 43 | 31 | 74 | -0.30 pp |
| dictionary-s20260814 | 824・83.65% | 81.32〜85.84% | 48 | 47 | 36 | 83 | +0.10 pp |
| dictionary-s20261103 | 837・84.97% | 82.70〜87.13% | 49 | 35 | 36 | 71 | +1.42 pp |
| dictionary-s20261104 | 835・84.77% | 82.44〜86.93% | 51 | 39 | 36 | 75 | +1.22 pp |
| annotation-s20260814 | 796・80.81% | 78.25〜83.25% | 58 | 85 | 49 | 134 | -2.74 pp |
| annotation-s20261103 | 797・80.91% | 78.35〜83.32% | 58 | 84 | 49 | 133 | -2.64 pp |
| annotation-s20261104 | 801・81.32% | 78.78〜83.70% | 57 | 79 | 49 | 128 | -2.23 pp |

| モデル | 適用数/985 | 修正対象適用率 (R+W)/162 | Precision R/適用数 | Recall R/162 | 破壊率 H/823 | 破壊率95%片側上限 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| reference29 | 114 (11.57%) | 43.83% | 35.09% | 24.69% | 5.22% | 6.69% |
| dictionary-s20260814 | 131 (13.30%) | 51.85% | 36.64% | 29.63% | 5.71% | 7.22% |
| dictionary-s20261103 | 120 (12.18%) | 52.47% | 40.83% | 30.25% | 4.25% | 5.60% |
| dictionary-s20261104 | 126 (12.79%) | 53.70% | 40.48% | 31.48% | 4.74% | 6.14% |
| annotation-s20260814 | 192 (19.49%) | 66.05% | 30.21% | 35.80% | 10.33% | 12.24% |
| annotation-s20261103 | 191 (19.39%) | 66.05% | 30.37% | 35.80% | 10.21% | 12.11% |
| annotation-s20261104 | 185 (18.78%) | 65.43% | 30.81% | 35.19% | 9.60% | 11.46% |

| seed | 原注釈−辞書方式 | 対応差の95% CI | 正解数の差 | 支持候補付きcontrastの差 |
| --- | ---: | --- | ---: | ---: |
| 20260814 | -2.84 pp | -4.67〜-1.12 pp | -28 | -5 |
| 20261103 | -4.06 pp | -5.79〜-2.34 pp | -40 | -4 |
| 20261104 | -3.45 pp | -5.17〜-1.83 pp | -34 | -1 |

3 seed平均は辞書方式84.47%、原注釈方式81.02%。平均差のCIは、同じsource component drawを全seedに共有する2,000回bootstrap（seed20261105）で直接計算した。個別seedのCI端点を平均していない。個別seedと副評価の有意差は多重比較補正した採用根拠ではない。source componentで全依存を除去できたとの認証はなく、CIは本研究母集団と方式に条件付く。

### 固定ゲート margin > 1.7・文脈あり

| モデル | 正解/985・Accuracy | Accuracy 95% CI | 救済 R | 破壊 H | 誤→誤 W | 修正失敗 H+W | baseline差 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| reference29 | 822・83.45% | 81.16〜85.69% | 9 | 10 | 4 | 14 | -0.10 pp |
| dictionary-s20260814 | 834・84.67% | 82.40〜86.84% | 13 | 2 | 3 | 5 | +1.12 pp |
| dictionary-s20261103 | 835・84.77% | 82.45〜86.90% | 14 | 2 | 3 | 5 | +1.22 pp |
| dictionary-s20261104 | 834・84.67% | 82.40〜86.82% | 14 | 3 | 3 | 6 | +1.12 pp |
| annotation-s20260814 | 837・84.97% | 82.64〜87.13% | 24 | 10 | 15 | 25 | +1.42 pp |
| annotation-s20261103 | 840・85.28% | 82.94〜87.40% | 26 | 9 | 15 | 24 | +1.73 pp |
| annotation-s20261104 | 839・85.18% | 82.78〜87.32% | 24 | 8 | 16 | 24 | +1.62 pp |

| モデル | 適用数/985 | 修正対象適用率 (R+W)/162 | Precision R/適用数 | Recall R/162 | 破壊率 H/823 | 破壊率95%片側上限 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| reference29 | 23 (2.34%) | 8.02% | 39.13% | 5.56% | 1.22% | 2.05% |
| dictionary-s20260814 | 18 (1.83%) | 9.88% | 72.22% | 8.02% | 0.24% | 0.76% |
| dictionary-s20261103 | 19 (1.93%) | 10.49% | 73.68% | 8.64% | 0.24% | 0.76% |
| dictionary-s20261104 | 20 (2.03%) | 10.49% | 70.00% | 8.64% | 0.36% | 0.94% |
| annotation-s20260814 | 49 (4.97%) | 24.07% | 48.98% | 14.81% | 1.22% | 2.05% |
| annotation-s20261103 | 50 (5.08%) | 25.31% | 52.00% | 16.05% | 1.09% | 1.90% |
| annotation-s20261104 | 48 (4.87%) | 24.69% | 50.00% | 14.81% | 0.97% | 1.75% |

固定ゲート後の原注釈群は救済24〜26件、破壊8〜10件。辞書群は救済13〜14件、破壊2〜3件。原注釈群のゲート後Accuracyが一部高いことを理由に、主比較の不採用判断を覆さない。辞書群の破壊2/823=0.243%は点推定だけなら0.25%以下だが、95%片側上限は0.763%であり安全性条件を満たさない。原注釈群の片側上限は1.75〜2.05%。両群とも安全性認証なし。

全seed・全context・全populationのPrecision/Recall/適用率には95% CIを保存している。表のAccuracy CIは対応source-component bootstrap、破壊上限は行独立を仮定したexact binomial片側95%。JSONには両側exact CIもある。これらを独立Goldの保証と混同しない。独立calibrationを使うRisk-Coverage分析と閾値選定は#34の別工程で、今回の985件から採用閾値を選ばない。

## 4. 文脈と失敗の診断

全7モデルを同じCPU backendで文脈あり／空／固定shuffleの21条件で一度ずつ評価した。原注釈群は文脈を空にしたとき主評価のwinner変化が各3/985件、正解数差は−1、0、+1件。shuffleではwinner変化4、5、4件、正解数差0、−3、−2件だった。この実験から、原注釈方式が有効な文脈識別を獲得した証拠は得られていない。

保存済み予測の[読み長別・事後診断](../../reports/issue-33-annotation-experiment-length-diagnostic-v1.json)では、主評価の2文字213件で原注釈−辞書の正解差は−2、−6、−5件。3〜4文字614件では−20、−29、−25件で、全差−28、−40、−34件の大半を占める。**2文字入力だけを除けば解決する、とは言えない。** 5〜8文字156件でも−6、−5、−4件。9文字以上は2件だけで両群正解0。

前段の学習データprofileでは変換器Top-1と元表記の一致が辞書群40,132/50,000=80.264%、原注釈群34,186/50,000=68.372%。原注釈群は救済も増える一方、ゲートなし破壊79〜85件に対し辞書群35〜47件。誤りの多い学習例の構成と変更傾向の関係が次の検証仮説になる。ただし、読み品質・境界品質・資料分布それぞれの因果寄与はまだ分離されていない。今回の評価語彙や正解ラベルを学習へ戻さず、診断結果を使った短読みの一律除去や閾値緩和はしない。

## 5. 実行・数値・安全境界の検証

6 fitsは全て500 updates、各128,000例の提示、同じ初期C2 weightsから実行した。学習専用readerは75,000行の来歴chainと数値を認証し、実プロセスのaudit hookで許可されていないdata配下の読み出しを拒否した。評価配列ロードfalse、拒否対象データへの読み出し試行0、KWDLC学習行0。全6 checkpointが確定してから評価を開始し、未実行・途中選択0だった。

各群の事前指定seed20260814をFP32 ONNXへ出力した。Windows CPU、GPU無効、batch1、ORT intra/inter-op各1、warmup200、各10,000実行。辞書群p95=0.7624 ms・p99=1.005569 ms、原注釈群p95=0.73201 ms・p99=0.972235 ms、各失敗0。最大値は各3.6391 ms／7.5237 msで、ハードな最大遅延保証はしない。1,212行×3contextでTorch CPUとのwinner差0、atol/rtol=1e-5で全一致、最大絶対差2.861023e-6。これはモデル呼び出し時間で、production worker往復時間やGate B合格ではない。

[直接検証](../../reports/issue-33-annotation-experiment-verification-v1.json)は保存予測から126集計を1行ずつ別計算し、3 seedの差をcomponentごとに合算する別bootstrap実装で平均差とCIを再現した。全1,000元blob、全source/cohort artifacts、20,000 latency samplesも照合した。既存16 artifactsと固定25 artifactsのhashは不変。外部モデルや人間のレビューを実施した記録ではない。

全unit suiteは**658件、failure/error/skip0**。新規14件は数値境界6、学習reader/bytes境界4、共有seed統計4。初期のimport smokeは旧研究moduleとの`cohort`名衝突で候補実行前に失敗したため、既存frozen codeを変えずに参照を分離した。次のunit testでWindowsに`os.O_ACCMODE`がないことを確認し、`os.O_WRONLY | os.O_RDWR`と両open形式の契約テストで修正した。実データの学習・評価・CPU測定は全て最初の実行で完了した。

17 Python filesのAST parse/compileとimport参照を検査した。実行済みhash-bound `prepare_fit.py`に未使用import `rows`が1件残る。元の実験bytesを保持するため当該記録は変更せず、静的検査のadvisoryとして明記する。lint警告0や型検査済みとは報告しない。新しいruntime機能の欠落ではない。Windows audit flagsの検証済み注意点をproject memoryへ1件追加した。

外側runner実測は取得283.640秒、全graph247.761秒、候補102.101秒、6 fits103.017秒、全推論22.075秒、CPU20.419秒、全unit35.742秒。これは今回の環境での実測で、次回の所要時間を保証しない。

## 6. 次の改善を選ぶ順序と費用

| 優先 | 追跡・次工程 | 期待する改善の仕組み | 最初の検証コスト・止める条件 |
| --- | --- | --- | --- |
| 1 | #33・#49：学習データだけで変更傾向と分布を監査 | 正しいTop-1の保持と必要な救済の学習比率、元表記の曖昧さ・入力単位・資料差を分け、過剰修正の仮説を絞る | 既存75,000行と候補・来歴cacheの集計。新規取得・native実行・GPU fitは0から開始。今回の985評価語・ラベルを条件にしない。仮説と比較条件を固定するまで追加fitなし |
| 2 | #34：候補順位と適用可否の学習を分け、独立calibrationで検証 | 救済できる誤りを保持しつつ、正しい変換への介入を減らす | train内分割／OOF設計と未使用calibration確保が必要。Precision/Recall/Risk-Coverage・片側95%上限を事前固定。0.25%を満たさなければ採用しない |
| 3 | #31・#35：元注釈とIME正解の差を明示した品質証拠・独立評価 | ラベルと推定精度の信頼性を上げ、方式選択の妥当性を測る | 独立したGoldの証拠は未確保。人手0をAI判定で置き換えて認証しない。point99.5%、Wilson下限99.0%、最終valid3,000以上、一度だけのTest条件は維持 |

今回の原注釈方式をさらに同じ評価で調整しない。未消費のKWDLC候補615資料も、次の比較・校正方針なしには取得しない。v1・r2・#29の独立Gold比較、Gate A/B、production実装、リリースは未完了。研究の不採用判断と製品完成を分ける。

## 7. 再現・保存範囲・IRV

固定planとbinding、スクリプト、集計だけをGitへ保存する。原文・読み・候補・stable IDs・配列・checkpoint・ONNX・raw logsは追跡しない。公開JSONは[publication map](../../reports/issue-33-annotation-experiment-publication-v1.json)でlocal元artifact SHAと公開SHAを対応付ける。[取得集計](../../reports/issue-33-annotation-experiment-acquisition-v1.json)、[source](../../reports/issue-33-annotation-experiment-source-v1.json)、[cohort](../../reports/issue-33-annotation-experiment-cohort-v1.json)、[候補](../../reports/issue-33-annotation-experiment-candidates-v1.json)、[学習](../../reports/issue-33-annotation-experiment-training-v1.json)、[CPU](../../reports/issue-33-annotation-experiment-cpu-v1.json)を併用する。

再計算用の保存先は`data/generated/issue-33-annotation-experiment-v1/`。上書き・削除による再実行を禁止し、既存receiptと固定コードを先に確認する。各stageは`run_stage.py`が一度だけ予約し、wall deadlineと子processの終了を所有する。新しい実験は別plan・別artifact rootで予約する。Python環境と全versionはfit/CPU reportに記録済み。全unit再検証コマンドは`python -m unittest discover -s tests -v`。実際の全suiteは同じdiscoverを行う`unit_checks.py`をbounded runnerから呼び、終了receiptを保存した。

- **A 実際の理解範囲**：既存データ契約、前段のsource/numeric/selection、native候補契約、C2 fit harness、3 seed統計、CPU出力、17 Python files（新研究14＋test3）。実験の解釈に必要な一連の境界であり、production codeは変更しない。
- **B 拡張理由**：全履歴の接続閉包、frozen module間のimport名衝突、生成済み#21 harnessの相対path、Windows open audit flags、共有seedのCIは一つの入口だけでは保証できなかった。無関係なrefactorは行っていない。
- **C 責任と契約**：学習許可と読み取り状態は`experiment_fit_contract.py`、平均差の対応bootstrapは`experiment_statistics.py`、stageのterminal状態は`run_stage.py`が所有する。既存data moduleの公開APIは変えず、研究層から既存契約へ依存する。ラベルの認証は行わない。
- **D 次回の理解範囲**：同種実験はplan→binding→集計→直接検証の順に辿れ、raw全文を読む必要はない。新たに理解すべき契約はtrain-only read許可、3 seedで共有するcomponent draw、write-onceのstage終了条件。意味品質をsource一致で代用できない制約は残る。

Goal-loopの7条件・2反復の最終状態、静的検査、追跡artifact検査、process終了と一時領域削除は[完了検査](../../reports/issue-33-annotation-experiment-checks-v1.json)、[cleanup](../../reports/issue-33-annotation-experiment-cleanup-v1.json)、`.codex/goal-loop/issue-33-annotation-experiment/`へ記録する。unmerged branchと上記ignored artifact rootは再現用に保持する。
