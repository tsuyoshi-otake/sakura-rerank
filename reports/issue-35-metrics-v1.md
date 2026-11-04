# #35 同一分母の指標計算と歴史的dev再計算

2026-11-04。親 #1。基点 `f2bd3e31c1d928a856e362c4229181e099973187`。
確認したSakura Input HEADは `d586fae572d32aa76512994dca616dadef2899b1`。

## 実装と目的

全モデルを同じ行・同じ候補・同じ旧ラベルで数える指標計算を実装した。
修正成功R、正しい変換の破壊H、誤→別誤W、実際の表記変更Aを区別する。
候補番号だけが変わり表記が同じなら修正に数えない。名称の異体字等を勝手に同値化しない。
タイムアウト、stale、malformed、missing、error、unavailable、gate棄却はlocal fallbackとして
元の分母に残す。結果行の欠落はattempt不明・run未完了とし、未試行や成功を推定しない。

Accuracy、修正対象への適用率、Precision/Recall、改善幅、RER、候補存在率、
MRR@6、最初の正解表記に基づくNDCG@6を集計する。
各モデルのbaselineとの差を必須比較に含め、共通component resampleによる95%区間、
exact McNemarと固定比較集合内のHolm補正を計算する。harmには両側95%区間と
片側95%上限を併記。分母0とbootstrapの不定な反復を隠さず、退化した区間も明記する。

APIと計算規約: [metric contract v1](../research/evaluation-metrics-v1.md)。
これはartifact照合・独立Gold認証・最終評価を開始する処理の完了ではない。

## 歴史的スコアによる確認

凍結dev 1,788件、baseline正解1,586件・誤り202件を使用。
train 12,516件と旧holdout 3,576件はJSON解析前に除外した。
キャッシュの全有効特徴・文字列符号化・mask・length・padding・Gold indexを照合。
モデル実行・学習・閾値の選び直し・ラベル変更は0回。

以下は保存済みスコアと旧ラベルの再計算であり、独立評価ではない。
Issue-21 C2は採用recipeの履歴参照で、別途exportされたr2 binaryを今回実行したものではない。
v1も今回実行していない。最終的なv1/r2/#29同条件・独立Gold比較は残っている。

| 保存スコアと固定gate | 正解数 / Accuracy | 修正成功R | 修正失敗H+W | 破壊H | 誤→別誤W |
|---|---:|---:|---:|---:|---:|
| #21 C2、gateなし | 1,639 / 91.6667% | 91 | 62 | 38 | 24 |
| #21 C2、#21のL>2.7 | 1,616 / 90.3803% | 34 | 5 | 4 | 1 |
| #29、gateなし | 1,643 / 91.8904% | 87 | 54 | 30 | 24 |
| #29、固定L>1.7 | 1,622 / 90.7159% | 39 | 6 | 3 | 3 |

全指標・区間・比較集合: [再計算JSON](issue-35-metrics-dev-v1.json)。
#29 gatedでは、誤り対象への適用率20.7921%、Precision 86.6667%、Recall 19.3069%、
baseline差+2.0134 percentage points、RER 17.8218%。
paired bootstrapの差の95%区間は+1.3423～+2.7405 points。
今回のdev-only component集合は1,788 singletonであり、履歴全体の独立性を証明しない。
反復参照したdevのp値や区間を確認的な独立評価と扱わない。

#29 gatedのharmは3/1,586=0.1892%だが、片側95%上限は約0.4881%。
このデータで安全性0.25%を95%で確認したという結論にはならない。
Gold品質・独立性・実運用の失敗率も未認証で、release_eligibleはfalse。
offlineスコアから再構成したstatus件数は実運用の障害観測ではない。

## 照合で発見した参照先の違い

初回の検証用スクリプトが、#21のL>2.7の結果を、旧再評価のr2_gatedへ対応付けていた。
後者は#25の信頼度gate L>2.9の結果なので一致しなかった。
正しい参照先は `issue-21-retrain-experiment.json` の
`per_model.C2-s20260814.dev_tau_gated`。34 rescue・4 harm・39 overrideが全て一致した。
閾値、モデル、評価計算を件数に合わせて変更していない。
残る3条件も該当する過去結果と一致。gate policyと選択元まで含めて実験を識別する必要がある。

## 検証

- 全382 tests: 377成功、既存optional PyTorch 5 skip、失敗0。新規13件は全成功。
  最終suiteは14.612秒、300秒timeout付きで実行。task-owned runner残存0を確認。
- Clopper–Pearson/WilsonをSciPyの別実装と158条件で照合。
  最大絶対差はそれぞれ約1.48e-13、3.33e-16。McNemarは小標本のexact Fractionと照合。
  0害でn=1,196/1,197、n=10,000で害16/17の安全性境界も契約testで確認。
- 1,788件の再計算CLIを2回実行し、出力byte一致。新Testは使用していない。
  旧33artifactのhash不変、従来splitter21定義のAST不変、前段のpartition監査JSON不変。
  共有component構築は監査とbootstrapが同じ関係を使う契約testで確認。
- compile/diff検査成功。NumPy 2.5.2と検証用SciPy 1.18.0は既存環境を使用し、installは0回。
  元データ、モデル、ラベル、旧結果、0.25%基準は不変。

詳しいhash・環境・参照先訂正記録: [検証JSON](issue-35-metrics-verification-v1.json)。
再現: `PYTHONPATH=src` の下で
`python research/issue-35-evaluation/recompute_dev.py --output <未作成の出力ファイル>`。
独立Testが利用可能になるまで、この計算器の検証をTestの結果で行わない。

## 次工程とIRV

次は、データ/モデル/特徴/ゲート/品質証拠を実際のartifact hashで照合する開始条件を実装し、
前段のTest使用台帳と接続する。期待効果は異なる候補・gate・版を誤って比較する事故の防止。
新しい精度上昇は見積もらない。全suiteの確認コストは今回約15秒、学習/GPU費用は0。
独立Gold証拠、全履歴inventory、代表標本・依存性の設計、calibration、本評価、
Gate C/Dの完了は別途必要。リリースは未完了。

A. 実際の対象は既存のranking/統計計算の公開責任、data契約とcomponent構築、
固定cache生成の行順/特徴契約、#21/#25/#29選択記録と旧再評価。新責任は指標集計と
統計計算の2モジュール、対応1test file、dev専用再計算CLI。全suiteで回帰確認。

B. cacheにstable IDがないため、同じGold index列だけでは行対応を確認できず、
公開encoder/feature関数から全dev tensorを照合した。gate参照先の混同も照合範囲を広げた。
productionコードやモデルの再学習へは拡張していない。

C. source/input componentの所有者はsplitterに維持し、公開membership関数を追加。
指標集計は同一case集合とterminal observationsを受け取り、統計計算へ十分統計量だけを渡す。
品質認証やファイル状態の所有権は持たない。既存の分割・モデル責任は変更していない。

D. 次回はmetric contract、2計算モジュール、対応testsから開始できる。
既存モデルの学習内部を再読せずに失敗・分母・surface判定を検証できる。
将来のadapterはモデルbinary、gate選択元、cohort、componentとattemptの由来を明示する必要がある。
