# #40 文脈条件付きGRUの固定予算比較

2026-11-05。親 #1、依存 #31/#32/#39、後続 #41。**実験・検証完了、条件付き構造は不採用。次の研究比較もC2を使う。** 製品採用モデルと既存90.72%の報告は変更していない。以下は別母集団での原文表記一致であり、独立Gold精度ではない。

## 判断

同じ50,000例・初期重み・500更新・3 seedsで、候補GRUの初期状態だけを左文脈状態へ変更した。主評価991件で条件付き構造はC2より8件、8件、4件多く原文に一致し、平均差は+0.6727ポイントだった。ただし3つのpaired 95%区間はすべて0をまたぎ、候補支持のある文脈対比212件での差も0、+3、−5件だった。事前の採用条件を満たさない。

主評価の改善は主に破壊の減少で、救済数は増えていない。条件付き構造で文脈を空にすると対比例の一致が5、2、4件増える。文脈への反応は強まったが、正しい文脈判断を獲得した証拠にならない。単に接続方法を変える案から、本文の言語事前学習を独立に検証する #41 へ進む。

## 評価枠を先に固定した

- KWDLC固定commit `c6ae49d29eca4e1134c6676d682adf5ed6a25f5a` の公開train 3,915文書から、既露出50+250文書を除き、本文を開く前に1,000文書をhash順で予約。公開dev/testは取得していない。KWDLCは研究評価だけに使用し、学習・原文再配布に転用しない。
- 最初の既露出250文書で、想定した代表表記フィールドが存在しないことを確認した。0 eligibleの[初回結果](../../reports/issue-40-contrast-feasibility-v1.json)を保存し、原注釈のlemma/POSを使う[別のfeasibility](../../reports/issue-40-contrast-feasibility-v2.json)で6組24例を得た。異lemmaは語義の違いやIME意図の保証ではない。
- 全1,000文書取得成功、Git blobとSHA-256を照合。原形態素の読み・表層を変更せず、左文脈8–64文字、読み2–32文字などの[適格性](plan-v1.json)を適用。10,657対象と、対象が取れない単位も含む3,127の原文単位を監査した。
- 既存411,200履歴行と合わせ424,984ノードで出典・文章・近似文・実入力の推移的隔離を実行。source-onlyノードに架空の読み/input hashを作らない。91対象・8文書を隔離した。主評価の予約1,000枠は991保持、8履歴関係、1対象なしとしてすべて保存した。
- 同読み/POS・異lemma/表層の2種類×2文脈、4つの異文書/文脈を持つ61組244例を選択した。主評価との重複20例を一度だけ数え、ユニーク対象1,215例。生の原文から再抽出・全関係の再計算・別の四つ組再計数を行い一致した。

1,000件はGoldの最終品質保証ではなく、開発研究の評価予約枠である。原文表記の再現は意味・表記意図の一意性を証明しない。今回の結果を見た評価枠は、次の実験の未使用評価枠とも最終Testとも呼ばない。

## 候補生成の上限

固定reference exporterと辞書を使い、830読みのうち268を同一identityの既存証跡から再認証、562を個別に新規実行した。全1,215対象で候補取得成功、未知失敗・未実行・候補表層の文字切り詰め0。全native出力を再認証し、学習開始前に数値入力を再生成して全配列の一致を確認した。

| 母集団 | n | Top1 | Top5 | Top6 | Top10 | Top32 |
|---|---:|---:|---:|---:|---:|---:|
| 主評価 | 991 | 792 | 971 | 974 | 977 | 977 |
| 全選択対象（重複除去） | 1,215 | 870 | 1,176 | 1,181 | 1,194 | 1,194 |

主評価のbaseline誤り199件中、182件はTop6に原表記がある。17件はTop6欠落、14件はTop32にもない。対比61組のうち両表記がTop6にある53組212例を、モデル予測を見る前に別集計対象へ固定した。候補欠落を除いて全体の精度を上げる処理はしていない。

変換器の実在sourceは `5eefa2ffe15297e563da281432cece56049a1b09`、別研究identityを使用。作業開始時のSakura Input HEADは `c53f1f179b5424ed335a44dddf8a16cd46648920`。新しい本番挙動や旧binary全面同値を推定していない。binary、辞書、全入力hashは[forward manifest](../../manifests/context-contrast-forward-v1.json)に固定した。

## 学習と比較の契約

[事前登録](model_plan.json)と[fit binding](../../manifests/context-model-fit-v1.json)をcommit `2f3c86640d5509aeb9c619485f8607c59eb8e373` で固定した。#29初期重み、同じWikipedia 25,000+青空25,000例、500更新×256、AdamW lr=1e-4/weight_decay=.01、clip=1、listwise CE/smoothing=.05、seeds 20260814/20261103/20261104。途中評価なし。学習プロセスは評価配列を開かない。

条件付き構造は同じembedding・一層GRU・7特徴・scorerを使い、候補のh0だけを一度計算した左文脈状態に置換する。パラメータ名・数・形、読み符号化、損失、語彙、ゲートは同一。空文脈はゼロh0でC2に一致する。右文脈・host文書は使わない。

6 fitsすべて完了、失敗/未実行0、runner実測88.485秒。C2の3 checkpointは先行データ増強実験の同条件controlと全tensorが完全一致した。全モデルをcommit `a4af7e05fcbac9f4561f5f988b503f62d31859bf` の[evaluation binding](../../manifests/context-model-evaluation-v1.json)で固定してから、#29 referenceを含む7モデル×intact/empty/固定shuffleの21条件を実行した。best-seed選択や後出し閾値探索はしていない。

shuffleはmain/non-mainと文脈長8–15/16–31/32–64で層化し、事前hash順で1つ循環移動した。singleton 0。固定gateは従来のmargin>1.7の参照値で、calibrationに適合させたものではない。

## 全seedの主評価結果

以下はCPU-PyTorchのintact条件、分母991。元のGPU集計も[保存](../../reports/issue-40-context-models-v1.json)し、CPU再集計で置き換えていない。主評価の全結果・主比較はCPU/GPUで一致する。

R=baseline誤りを救済、H=baseline正解を破壊、W=誤りから別の誤りへ変更。修正失敗=H+W、変更総数=R+H+W。修正対象適用率=(R+W)/199、Precision=R/(R+H+W)、Recall=R/199。差はbaseline 792/991=79.9193%からのポイント差。角括弧は出典成分単位paired bootstrap 95%区間（2,000反復、seed 20261105）。主評価988成分、対比全体31成分/候補支持32成分で、出典と対比グループの依存を結合した。

| gateなし | 原文一致率 | R/H/W | 修正失敗 | 修正対象適用率 | Precision / Recall | baseline差 [95%区間] pt |
|---|---:|---:|---:|---:|---:|---:|
| reference29 | 81.84% | 43/24/30 | 54 | 36.68% | 44.33% / 21.61% | +1.92 [+0.30, +3.52] |
| C2 seed20260814 | 81.74% | 55/37/30 | 67 | 42.71% | 45.08% / 27.64% | +1.82 [+0.00, +3.73] |
| 条件付き seed20260814 | 82.54% | 54/28/28 | 56 | 41.21% | 49.09% / 27.14% | +2.62 [+0.81, +4.44] |
| C2 seed20261103 | 81.43% | 53/38/29 | 67 | 41.21% | 44.17% / 26.63% | +1.51 [-0.40, +3.43] |
| 条件付き seed20261103 | 82.24% | 53/30/28 | 58 | 40.70% | 47.75% / 26.63% | +2.32 [+0.50, +4.13] |
| C2 seed20261104 | 81.53% | 56/40/30 | 70 | 43.22% | 44.44% / 28.14% | +1.61 [-0.20, +3.52] |
| 条件付き seed20261104 | 81.94% | 52/32/29 | 61 | 40.70% | 46.02% / 26.13% | +2.02 [+0.20, +3.74] |

| 固定gateあり | 原文一致率 | R/H/W | 修正失敗 | 修正対象適用率 | Precision / Recall | baseline差 [95%区間] pt |
|---|---:|---:|---:|---:|---:|---:|
| reference29 | 80.93% | 11/1/5 | 6 | 8.04% | 64.71% / 5.53% | +1.01 [+0.40, +1.72] |
| C2 seed20260814 | 80.73% | 9/1/4 | 5 | 6.53% | 64.29% / 4.52% | +0.81 [+0.20, +1.42] |
| 条件付き seed20260814 | 80.63% | 8/1/4 | 5 | 6.03% | 61.54% / 4.02% | +0.71 [+0.10, +1.31] |
| C2 seed20261103 | 80.73% | 9/1/4 | 5 | 6.53% | 64.29% / 4.52% | +0.81 [+0.20, +1.42] |
| 条件付き seed20261103 | 80.63% | 8/1/4 | 5 | 6.03% | 61.54% / 4.02% | +0.71 [+0.10, +1.31] |
| C2 seed20261104 | 80.83% | 10/1/5 | 6 | 7.54% | 62.50% / 5.03% | +0.91 [+0.30, +1.61] |
| 条件付き seed20261104 | 80.52% | 7/1/4 | 5 | 5.53% | 58.33% / 3.52% | +0.61 [+0.10, +1.21] |

Precision/Recall/適用率/一致率/破壊率のWilson区間とpaired区間、破壊のexact区間、全244/212対比例、empty/shuffleの全数値は[CPU JSON](../../reports/issue-40-context-models-cpu-v1.json)に保存した。丸めた+0.00を有意な改善と読まない。

| 事前主比較: 条件付き−C2 | 一致増減 /991 | 差とpaired 95%区間 pt | 支持対比の増減 /212 |
|---|---:|---:|---:|
| seed20260814 | +8 | +0.8073 [−0.2016, +1.8163] | 0 |
| seed20261103 | +8 | +0.8073 [−0.2016, +1.8163] | +3 |
| seed20261104 | +4 | +0.4036 [−0.6054, +1.4113] | −5 |

全3比較の区間下限>0、非負の点差、正の平均差、支持対比で2 seeds以上改善という事前規則のうち、区間と対比の条件を満たさない。C2増強controlも今回の外部主評価ではreference29を上回らず、以前の4,000件研究評価での向上が全分布へ移るとは言えない。

固定gate後のHは全モデル1/792=0.1263%だが、独立行仮定でのexact両側95%上限は0.7015%（片側0.5976%）。点推定が0.25%未満でも安全性を認証できない。さらにGoldラベルと集団独立性は未認証であり、Gate A/Bは未通過。

## CPU実行と失敗を含む数値監査

Windows11、Python3.13.13、Torch2.12.1+cu130、ONNX1.19.1、ORT1.23.2。GPU無効、CPUExecutionProviderのみ、batch1、intra/inter各1thread、200 warmup、事前指定seed20260814の各10,000回。モデル呼び出しだけの計測で、worker往復やGate C全体の証明ではない。

| モデル | p50 ms | p95 ms | p99 ms | max ms | 失敗 | FP32 ONNX bytes |
|---|---:|---:|---:|---:|---:|---:|
| C2 | 0.4852 | 0.6313 | 0.7833 | 1.5029 | 0/10,000 | 7,467,219 |
| 条件付き | 0.4916 | 0.6273 | 0.7869 | 1.3948 | 0/10,000 | 7,468,149 |

1,215行×3文脈でCPU-PyTorch/CPU-ONNXを照合し、両モデルとも順位差0、最大score差1.91e-6以下。既存atol/rtol=1e-5、p95<=2ms、p99<=5msを変更していない。[最終CPU結果](../../reports/issue-40-context-cpu-r4.json)。

失敗した3実行も別の結果として残した。

1. [r1](../../reports/issue-40-context-cpu-v1.json): ONNX exporterへlistを一引数として渡したためTypeError。tupleへ直し、モデル・入力は変更していない。
2. [r2](../../reports/issue-40-context-cpu-r2.json): CPU-ORTを既定GPUのscoreと直接比較して許容誤差を超えた。7モデル×3条件の[backend監査](../../reports/issue-40-context-numerical-audit-v1.json)を追加し、CPU参照を別途保存した。
3. [r3](../../reports/issue-40-context-cpu-r3.json): 最初の10,000回計測後、NumPy boolがcanonical JSONに保存できずContractError。残った全latency samplesを保存し、native bool変換と失敗時finalization順序を修正してr4を実行した。

既定GPUとCPUでは最大score差0.0012624、gateなしで2条件各1例のwinner差があった。C2 seed20261103/intactはCPUで対比の一致+1、条件付きseed20261103/shuffleは−1。主評価・全gate判定・構造採否は不変。TF32無効GPUでもCPUとのscore差は最大2.15e-5残るが、全winnerは一致した。数値許容幅を緩めず、CPUの全指標を追加保存した。以後は最終評価前に推論backend・精度設定・export比較先を明示固定する。

## 再現・検証

固定仕様→入力→学習→評価のcommit順は以下。原文・生成データ・checkpoint・binaryはGitへ入れず、`data/generated/issue-40-context-contrast-v1/` に再現用として保持する。書き込みはwrite-once。既存成果物のある場所で生成コマンドを再実行して上書きしない。

| 段階 | 固定commit / 証拠 | Verify | Expect |
|---|---|---|---|
| 原文予約・適格性 | `864a37588abaae12b07db5d21e8924865fde5c5d` / [plan](plan-v1.json) | `acquire.py`, `prepare.py`, `isolate_select.py`, `verify_cohort.py` を原文manifestと照合 | 全1,000枠、991主例、61対比、1,215ユニーク、full-source closure再現 |
| 実候補 | `33ec9735932bc29cadf863e7a4637072efa60bf1` / [manifest](../../manifests/context-contrast-forward-v1.json) | `forward.py execute --input-commit <SHA>` / 学習前の `prepare_fit.py` 再認証 | 562新規全成功、268再利用、全配列一致、旧入力不変 |
| 6 fits | `2f3c86640d5509aeb9c619485f8607c59eb8e373` / [plan](model_plan.json) | `fit_models.py --fit-commit <SHA>` | 同じ50,000例/500更新、3 control tensor完全再現、失敗0 |
| 推論 | `a4af7e05fcbac9f4561f5f988b503f62d31859bf` / [manifest](../../manifests/context-model-evaluation-v1.json) | `evaluate_models.py infer/report --evaluation-commit <SHA>` | 全21条件、全seed、固定gate・shuffle、全分母保存 |
| CPU r4 | `1e63dff69caf11e4fe7c0e44f895a5fd646f6711` | `benchmark_models.py --evaluation-commit <SHA> --implementation-commit <r4 SHA>` | CPU同士で同じ許容差、20,000計測、失敗0 |

上表は履歴再現の入口であり、一括で既存outputへ再実行する手順ではない。保存済み結果の非破壊検証は `PYTHONPATH=src` の固定環境で以下を実行する（`verify_results.py` の出力はwrite-onceのため、既存reportは内容/hash照合に使う）。

```text
python -m unittest discover -s tests -v
python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

**519 tests成功、skip/失敗0**。27 Python filesのAST検査、旧16 artifactと既存fit binding 25 artifactのhash不変。`verify_results.py` は評価集計関数を呼ばずscalarで全252集計と1,764の率/Wilson区間を再計数し一致した。CPU quantileも生10,000samplesから再計数した。[検証結果](../../reports/issue-40-context-result-verification-v1.json) / [全テスト](../../reports/issue-40-context-checks-v1.json) / [終了・cleanup](../../reports/issue-40-context-cleanup-v1.json)。所有runner残存0、専用tmp削除済み。

## IRV・責務・残る限界

A. 実際に必要だった範囲は、原形態素対比抽出、全原文の隔離、bounded native候補実行、条件付きGRU、固定fit/evaluation、backend/CPU検証。主契約は `context_contrasts.py`、`context_source_isolation.py`、`context_conditioned.py`、`reference_execution.py` と各対応test、および3つの事前plan/4 manifests。関連する旧converter認証・C2 training contract・統計APIだけを追加参照した。

B. 想定を超えた調査は代表表記メタデータ欠落、対象を作れない原文単位の履歴隔離、GPU/CPU数値差。単なる構造変更では評価枠の不足と数値backend差を隠すため、評価の前提まで範囲を拡張した。通常のlocalized Issueの3ガイド/450行目安を超えるが、無関係な本番リファクタはしていない。

C. 原形態素選択の状態は抽出module、履歴成分はsource-isolation、候補実行のterminal receiptはbounded executor、モデル重みはfit binding、評価値はevaluation bindingが所有する。新モデルの意味依存は候補h0→左文脈状態の一つ。既存splitter/旧入力契約/公開モデル/本番経路は変更しない。source-only契約は偽input等価を禁止する。

D. 次の本文事前学習比較は、上記の固定C2/control再現、backend差、候補再利用の条件を再調査せず入口として使える。一方で、今回のKWDLC枠は露出済みと理解し、新しい原文windowの権利・全履歴隔離・未使用研究枠・LMと下流学習の境界は新たに検証する必要がある。

残る制約は、原文一致とIME意図の差、既存語彙/hash衝突、短い形態素中心の抽出、母集団移動、独立Goldとcalibration不足。研究結果を安全性認証へ昇格させない。安全性0.25%、Gold品質99.5%点推定/Wilson下限99.0%、最終valid 3,000件、最終Test一回限りは維持する。#34は独立calibration後、#41は別の事前登録比較として実施する。
