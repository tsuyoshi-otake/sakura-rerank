# #41 本文による文字事前学習の比較

2026-11-05。親 #1、#40でC2構造を維持した後の独立した研究実験。**事前学習3回・下流6 fits・新規研究評価・CPU検証を完了し、この事前学習条件は不採用とした。** 採用モデル、既存90.72%の報告、0.25%の安全性基準は変更していない。

## 結論と次の判断

Wikipedia・青空文庫の学習用文章断片から831,492個の因果的な次文字windowを作り、同じC2に2,000更新の事前学習を加えた。次文字lossは初期100更新平均14.81–14.84から最終100更新平均6.45–6.48へ下がった。しかし、新しい主評価975例の原文一致は、事前学習なしより−8、−10、−1例、平均−0.6496ポイントだった。3つのpaired 95%区間はすべて0を含む。候補が両方存在する文脈対比224例でも−3、−1、0例で、事前の採用条件を満たさない。

救済は各seedで3件増えた一方、破壊は11、13、4件増えた。空/シャッフル文脈への反応も限定的で、次文字の学習が候補を文脈から選び分ける能力へ移ったとは確認できない。一般に言語事前学習が無効という証明ではなく、固定語彙・短い文章断片・tied-head・今回の更新数と下流条件での否定的結果である。

結果を見て追加更新・閾値調整・best-seed選択へ戻らない。次に調べるべきは、同読みの異候補を文脈で区別する学習例が十分か、弱い原文再現ラベルとIME意図がどこで食い違うか、外部の候補採点器がこの区別を実際にできるかである。#33の学習信号監査と条件付き後続 #42 が入口になる。#34には別のcalibrationが必要で、今回の評価枠を流用しない。

## 本文と評価の分離

[計画](plan-v1.json)をcommit `057b2cee79c2b8ada5e9c584e60ba7625fee7637` で固定した。KWDLC固定公開train 3,915文書から、既露出50+250+1,000文書を除いた新しい1,000文書を本文参照前に予約。全件を取得し、Git blobとSHA-256を照合した。取得276.733秒、失敗/再試行/置換0。公開dev/testを開かず、KWDLCは評価専用で学習にも再配布にも使用しない。

10,723原形態素対象と、対象がない単位を含む3,148原文単位を抽出した。424,984の過去履歴行と、出典・同一文章・近似文・実入力の全推移的関係を検査。全1,000枠の内訳は、主評価975、履歴関係19、対象なし6。対象の入れ替えなし。異lemma/表層・同読み/POSの63組252対比例を選び、主評価との重複27を除いたユニーク対象は1,200例となった。異lemmaは異語義やIME意図の保証ではない。

学習側は、既に出典隔離済みのWikipedia/青空train 164,320断片を、原データ6世代、frozen入力、全growth評価出典、旧1,300+新1,000 KWDLC文書・全対象に対して再検査した。許可済みgrowth trainを評価履歴と取り違えず、評価出典は残す。218,189履歴行との関係で1,818断片を除外し、162,502断片を保持した。これらは同じ元データの別版出力であり、既存train/dev/holdoutを変更していない。

同じliteral本文断片を重複除去して162,291種とし、各断片で固定hash順の最大6位置を選択。直前8–64文字から次の1文字だけを予測する。正解読み、候補順位、未来文字を入力に含めない。全windowの同一入力/出力を重複除去し、各文章源最大500,000という固定上限を適用した結果、Wikipedia500,000、青空331,492、計831,492 windowを得た。これは短い学習用本文断片の試験であり、Wikipedia全文による大規模言語モデル学習ではない。元snapshot/license/hashは先行growth manifestを引き継ぎ、新しい窓・出典・履歴は[データmanifest](../../manifests/language-pretraining-data-v1.json)に固定した。

原文再抽出・全出典関係を再実行し、全windowの出典位置、literal hash、文字hash、paddingを別のscalar式で再計算して一致した。選択順・6位置/文章源capも再生成して一致。[cohort検証](../../reports/issue-41-language-cohort-verification-v1.json) / [学習入力検証](../../reports/issue-41-language-data-verification-v1.json)。

## 候補上限と固定学習

同じ認証reference exporter/dictionaryで764読みを測定し、344を既存証跡から再認証、420を新規取得した。1,200対象すべて成功、候補表層の文字切り詰め0。全native出力の再認証と数値配列の再生成も一致した。[候補結果](../../reports/issue-41-language-candidates-v1.json)。

| 母集団 | n | Top1 | Top5 | Top6 | Top10 | Top32 |
|---|---:|---:|---:|---:|---:|---:|
| 主評価 | 975 | 796 | 945 | 949 | 954 | 955 |
| 全選択対象 | 1,200 | 874 | 1,155 | 1,161 | 1,171 | 1,172 |

主評価のbaseline誤り179例中、153例はTop6に原表記があり、26例は欠落（Top32でも20例欠落）。両表記Top6支持のある対比は56組224例。モデル結果を見て母集団を変更していない。

文字hash語彙13,312、embedding/GRU128、C2のパラメータ構造は固定。tied embeddingを訓練時の出力行列に使い、PADを予測対象から除いた。LM中に更新するのはembedding/encoderだけで、scorerは初期値を完全保持。新しい推論パラメータ・語彙・右文脈は加えない。

事前学習は3 seedsで各2,000更新×512、AdamW lr=1e-4/weight_decay=.01、clip=1、最終stepのみ保存。下流は初期#29または各seedのLM後重みから、同じWikipedia25,000+青空25,000例、500更新×256、既存C2 listwise CE/smoothing=.05、同じoptimizer設定。下流開始時にRNGとoptimizerをリセットする。

[fit binding](../../manifests/language-fit-v1.json)をcommit `0f68712bfe665baa9fae6441e8f278fed828d021` で固定後、3 LM runs/6 fitsを完了した。未実行/失敗0、実行本体168.920秒（runner171.928秒）、LM部分は28.974/27.045/27.186秒。最大100万window・合計GPU4時間以内を維持。model/optimizer checkpoint、全loss、seed、実行receiptを別保存した。

訓練プロセスには評価配列/原文/候補のopenを拒否するaudit hookを入れ、評価byte認証を学習byte認証から分離した。事前学習なしの3 controlは#40の同条件C2と全tensorが完全一致。全7モデルをcommit `853f23028355aa0cd6c8ce336493725b674ab52f` の[evaluation binding](../../manifests/language-evaluation-v1.json)で固定した後に初めて予測した。途中評価・評価入力を使う学習・最良seed選択なし。[学習receipt](../../reports/issue-41-language-training-v1.json)。

## 全seedの原文一致と修正結果

主評価のbaselineは796/975=81.6410%。**IMEのGold精度ではない。** R=救済、H=元の原文一致を破壊、W=誤りから別の誤りへ変更、修正失敗=H+W。修正対象適用率=(R+W)/179、Precision=R/(R+H+W)、Recall=R/179。全体適用率・各率のWilson/paired区間、候補欠落時の分母、empty/shuffleも[全結果JSON](../../reports/issue-41-language-models-v1.json)に保存した。

表の区間は出典成分単位のpaired bootstrap 95%（2,000反復、seed20261105）。主評価972成分、全対比27/支持対比28成分。出典と対比グループを結合して依存を扱うが、Gold品質やIME母集団の独立性は認証しない。

| gateなし | 原文一致率 | R/H/W | 修正失敗 | 修正対象適用率 | Precision / Recall | baseline差 [95%区間] pt |
|---|---:|---:|---:|---:|---:|---:|
| reference29 | 82.56% | 41/32/33 | 65 | 41.34% | 38.68% / 22.91% | +0.92 [−0.82, +2.67] |
| LMなし seed20260814 | 81.74% | 47/46/39 | 85 | 48.04% | 35.61% / 26.26% | +0.10 [−1.74, +2.05] |
| LMあり seed20260814 | 80.92% | 50/57/38 | 95 | 49.16% | 34.48% / 27.93% | −0.72 [−2.77, +1.34] |
| LMなし seed20261103 | 81.54% | 44/45/35 | 80 | 44.13% | 35.48% / 24.58% | −0.10 [−1.85, +1.74] |
| LMあり seed20261103 | 80.51% | 47/58/37 | 95 | 46.93% | 33.10% / 26.26% | −1.13 [−3.18, +0.92] |
| LMなし seed20261104 | 81.85% | 47/45/38 | 83 | 47.49% | 36.15% / 26.26% | +0.21 [−1.64, +2.15] |
| LMあり seed20261104 | 81.74% | 50/49/39 | 88 | 49.72% | 36.23% / 27.93% | +0.10 [−1.84, +2.15] |

| 固定gateあり | 原文一致率 | R/H/W | 修正失敗 | 修正対象適用率 | Precision / Recall | baseline差 [95%区間] pt |
|---|---:|---:|---:|---:|---:|---:|
| reference29 | 81.74% | 10/9/7 | 16 | 9.50% | 38.46% / 5.59% | +0.10 [−0.82, +0.92] |
| LMなし seed20260814 | 82.05% | 8/4/7 | 11 | 8.38% | 42.11% / 4.47% | +0.41 [−0.31, +1.13] |
| LMあり seed20260814 | 82.26% | 12/6/10 | 16 | 12.29% | 42.86% / 6.70% | +0.62 [−0.21, +1.54] |
| LMなし seed20261103 | 82.05% | 8/4/7 | 11 | 8.38% | 42.11% / 4.47% | +0.41 [−0.31, +1.13] |
| LMあり seed20261103 | 82.05% | 11/7/8 | 15 | 10.61% | 42.31% / 6.15% | +0.41 [−0.41, +1.33] |
| LMなし seed20261104 | 81.95% | 7/4/8 | 12 | 8.38% | 36.84% / 3.91% | +0.31 [−0.31, +1.02] |
| LMあり seed20261104 | 81.95% | 10/7/11 | 18 | 11.73% | 35.71% / 5.59% | +0.31 [−0.51, +1.13] |

| 事前主比較: LMあり−なし | 一致増減 /975 | 差とpaired 95%区間 pt | 支持対比の増減 /224 |
|---|---:|---:|---:|
| seed20260814 | −8 | −0.8205 [−2.1495, +0.5128] | −3 |
| seed20261103 | −10 | −1.0256 [−2.2495, +0.1027] | −1 |
| seed20261104 | −1 | −0.1026 [−1.1294, +0.9250] | 0 |

LMありで文脈をシャッフルして主評価winnerが変わる数は0/1/0件、原文一致の変化はいずれも0件。空文脈では1/8/5件のwinnerが変わり、一致は0/+1/+2件。少なくとも今回の候補順位へ有効な文脈利用が移ったという根拠にはならない。

従来gateはmargin>1.7を固定した参照で、独立calibration済みの値ではない。gate後のHはreference29=9/796、control=4/796、LM=6/796・7/796・7/796。全条件で点推定も0.25%を上回り、exact両側95%上限は順に2.1354%、1.2816%、1.6334%/1.8035%/1.8035%。source-exactの破壊をそのまま実IMEの誤修正認証とはしないが、安全性合格は主張できない。この結果を使って閾値を調整しない。

## CPUと再現可能性

推論は初めからCPU PyTorch FP32/1threadに固定し、7モデル×3文脈=21条件すべて成功。#40で見つかったGPU/CPU丸めの問題により、GPU scoreを最終winnerの参照にはしていない。ONNXは事前指定seed20260814のLMあり/なしをCPU同士で照合した。

| Windows CPU/ORT各1thread、batch1 | p50 ms | p95 ms | p99 ms | max ms | 失敗 |
|---|---:|---:|---:|---:|---:|
| LMなし | 0.4881 | 0.6235 | 0.7767 | 1.8400 | 0/10,000 |
| LMあり | 0.4886 | 0.6598 | 0.8466 | 9.4244 | 0/10,000 |

200 warmup後に各10,000回。全1,200例×3文脈のCPU-PyTorch/ONNX順位差0、最大score差1.91e-6以下、atol/rtol=1e-5不変。FP32 ONNXは両方7,467,219 bytes。最大9.4244msも除外していない。p95<=2ms/p99<=5msを満たすが、これはモデル呼び出しのみでworker往復・memory・Gate C全体の証明ではない。[CPU結果](../../reports/issue-41-language-cpu-v1.json)。

| 段階 | 固定commit | Verify | Expect |
|---|---|---|---|
| 予約・計画 | `057b2cee79c2b8ada5e9c584e60ba7625fee7637` | `reserve.py`、plan/selection/tree/member hash照合 | 本文アクセス前の1,000固定枠、過去1,300と非重複 |
| 候補入力 | `ac07836f3c1a0d02a7b152e6a70ffb1177e1b099` | `cohort.py verify`、`forward_candidates.py verify --input-commit <SHA>` | 全原文/closure再現、全候補/数値入力再認証 |
| 学習入力 | `0f68712bfe665baa9fae6441e8f278fed828d021` | `prepare_language.py verify`、fit binding hash照合 | 全831,492 windowの因果性と文字ID再計数、評価open拒否 |
| モデル評価 | `853f23028355aa0cd6c8ce336493725b674ab52f` | `evaluate_language.py infer/report --evaluation-commit <SHA>` | 同じ7モデル/3文脈、全失敗・固定分母、元結果保存 |
| 結果検証 | `verify_results.py` | scalar再計数、paired区間再計算、checkpoint tensor比較、latency再計数 | 126集計/882率・区間/3主区間一致、3controls完全一致 |

生成stageはwrite-onceの履歴再現入口であり、既存outputを上書きするコマンドではない。既存結果を持つcheckoutでは、以下の非破壊検証を固定環境で実行できる。

```text
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

530 tests成功、skip/失敗0。学習開始前にも同じ530 testsを通過。結果の別再計数で126集計、882の率/Wilson区間、3つの主paired区間が一致し、control tensorとLMのscorer不変も再確認した。初回検証と未使用import除去後の再検証は別receiptで保持している。[初回](../../reports/issue-41-language-result-verification-v1.json) / [再検証](../../reports/issue-41-language-result-verification-r2.json) / [回帰・静的検査](../../reports/issue-41-language-checks-v1.json)。旧16 artifactと旧fit binding25 artifact不変。所有test/train/ORT/native worker残存0、専用tmp削除済み（[cleanup](../../reports/issue-41-language-cleanup-v1.json)）。

原文、生成window/数値入力、model/optimizer、native/ORT出力、全logはGitへ含めず、`data/generated/issue-41-language-pretraining-v1/` に再現用として保持する。過去のデータ・モデル・失敗・評価は変更していない。独立Gold、人手IME認証、最終Test、Gate A/B、製品リリースは未完了。

## IRVと責務

A. 必要だった範囲は、固定source取得、原文/履歴cohort、因果window、訓練専用tied head、fit/evaluation binding、CPU結果。既存C2、候補実行、原文抽出/隔離、統計の公開契約を再利用し、本番コードは参照更新していない。主入口はこのREADMEとplan、責務別moduleと対応test。

B. 単なるLM追加より広がったのは、#40で露出済みの評価枠を再利用できず、全履歴の更新と新しいcohortが必要だったため。また、LMは順位用候補の有無で学習原文を選別しないため、全164,320 train断片を再検査した。通常のlocalized Issueのガイド/行数目安を超えるが、追加範囲は新しい学習入力と評価独立性に限定した。

C. `language_windows.py`が因果位置選択、`language_pretraining.py`がtied headと更新対象、`reserved_source_acquisition.py`が取得と全terminal receiptを所有する。実験側はcohort/fit/evaluationのimmutable境界を所有する。LMから公開rankerへの変更は保存するembedding/encoder重みだけで、推論パラメータや依存を追加しない。

D. 次の類似実験は、bounded取得・因果window・評価open拒否・CPU parityを再設計せず検証済み契約として使える。次の比較では、学習目的と文章源の偏り、今回の評価露出、同読み対比の学習信号、独立calibration/Goldの不足を新たに確認する必要がある。今回のloss改善を意味理解やGate合格に置き換えない。
