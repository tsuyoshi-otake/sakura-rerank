# 文脈・入力単位pilotの実施結果 (#39)

2026-11-05。親 #1。#39の最初の固定pilotを実装し、250文書・1,000対象枠の取得、抽出、履歴監査、実変換、再計数を完了した。**モデル実験へ進む前に、注釈中の記号とIME入力境界、文脈対比例の不足、長い入力の候補欠落を扱う必要がある。**

これは既存のGold 1,000件pilotとは別の、外部注釈に基づく研究用調査。モデル学習・モデル推論・独立Test利用・Gold認証は全て0。既存ラベル・モデル・評価と安全性0.25%は不変。

## Issueの分割と依存関係

| Issue | 責務 | 現在の状態 |
| --- | --- | --- |
| [#39](https://github.com/tsuyoshi-otake/sakura-rerank/issues/39) | 入力単位と文脈識別の最大1,000対象pilot | 本レポートの実装・実測・検証を完了。PRは未マージ |
| [#40](https://github.com/tsuyoshi-otake/sakura-rerank/issues/40) | 独立GRUと文脈条件付き小型GRUの比較 | 文脈対比の評価枠・学習用途・候補条件の確定待ち |
| [#41](https://github.com/tsuyoshi-otake/sakura-rerank/issues/41) | 同じ小型構造で言語事前学習の有無を比較 | #40の構造と評価枠の固定後 |
| [#34](https://github.com/tsuyoshi-otake/sakura-rerank/issues/34) | OOF適用器と独立calibration | 候補選択モデル・calibration確保後。既存Issueを再利用 |
| [#42](https://github.com/tsuyoshi-otake/sakura-rerank/issues/42) | 外部教師の適格性と候補採点を先に検証 | 条件付き後続。教師優位性なしに蒸留しない |

全5件をGitHubの実際のsub-issueとして #1 に関連付け、親の一覧にも登録した。#31が注釈/表記/入力意図、#32が候補と隔離、#35が独立評価の責務を引き続き持つ。

## 固定した母集団と実行

KWDLC commit `c6ae49d29eca4e1134c6676d682adf5ed6a25f5a` の公開train 3,915文書から、旧probe 50文書を除き、seed 20261105のhash順で250文書を本文取得前に選択した。公開dev/testの本文・membershipを開いていない。4方針は形態素、基本句、2基本句、3基本句。形態素境界をIME確定境界と同一視せず、比較する入力方針として明示した。

[plan](plan-v1.json)を `0f8c5af08f730b83a1d6352776b0960be2299eda` で固定。250件全て取得成功、計1,420,137 bytes、113.741秒。Git blob・byte数・SHA-256照合済み。逐次実行、再試行0、差替え0。許可範囲はNLP研究調査であり、原文の再配布やモデル学習用途への自動転用はしていない。提供元の権利者個別許諾・URL欠落の制約は継続する。[提供者の固定README](https://github.com/ku-nlp/KWDLC/blob/c6ae49d29eca4e1134c6676d682adf5ed6a25f5a/README.md)

各文書の各方針で1対象を位置hashにより選び、**読みの有効性と候補成績を見る前に**固定。注釈どおりの表記・読みを連結し、読みの推測、NFKC化、句読点除去を行わなかった。文脈は同じ注釈単位内の直前最大64文字。実セッションで観測された文脈ではない。後方の文章は特徴へ入れない。

2回の抽出はbyte一致。1,000枠中747枠が固定したかな読み条件を満たし、253枠は特殊な読み表記として保留。変換前に[入力binding](../../manifests/context-pilot-input-v1.json)を `7f1fff8c9bd41e3361cdf6c11e5cba4a45ead6f0` でcommitした。722種類の読みを固定reference converterで8 batches実行し、全件検証成功、失敗0、実行2.347秒。読みが同じ場合だけ、文脈・user辞書を参照しない同一converter snapshotを共有した。

## 候補存在率の実測

「正解」は原文注釈の表記との完全一致であり、IMEで許容される唯一の正解を認証したものではない。全方針250枠ずつを残す。下表の割合は**実変換できた件数を分母とする条件付きの候補存在率**。未測定を候補欠落とは数えない。

| 入力方針 | 全枠 | 実変換済み | 未測定 | Top-1存在 | Top-6存在 | Top-32存在 | Top-6 / 実変換済み |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 形態素 | 250 | 250 | 0 | 207 | 247 | 247 | 98.80% |
| 基本句 | 250 | 201 | 49 | 161 | 192 | 192 | 95.52% |
| 2基本句 | 250 | 165 | 85 | 110 | 145 | 149 | 87.88% |
| 3基本句 | 250 | 131 | 119 | 86 | 112 | 116 | 85.50% |
| 合計 | 1,000 | 747 | 253 | 564 | 696 | 704 | 93.17% |

Top-5/10を含む全20計数は[JSON](../../reports/issue-39-context-pilot-v1.json)に保存した。合計で、測定済み747件中43件はTop-32にも原文表記がない。Top-6→32の追加は8件だけ。見つかった704件は全てsystem dictionary経路で、418件は複数segmentだった。

**短い辞書見出しの評価で高かった候補存在率を、長い入力へ外挿できない。** ただし、各方針は異なる位置の対象を選び、かな条件を満たした部分集合も異なる。長さだけによる因果効果や、実ユーザー入力での候補欠落率を示す比較ではない。この候補存在率をモデルAccuracyと呼ばない。

## 読み・重複・文脈課題の不足

- 特殊な読み表記253枠のうち**251枠は、注釈上の表記と読みが一致する句読点・記号のliteral tokenだけが、かな限定条件から外れる原因**だった。残る2枠にはそれ以外の非かな/非literal注釈がある。253誤ラベルとは解釈しない。記号を入力中のliteralとするか、変換範囲外へ置くかはIME入力単位の仕様であり、今回の結果を見て一律削除しない。
- 読み10文字以上は346 / 1,000枠（実変換できた中では157 / 747）。全1,000枠が既存の読み32文字・表記32文字の長さ範囲内だった。長い課題は得られたが、読み形式と入力境界の問題が残る。
- 同じ読みで表記と左文脈が異なるものは**3組9枠**、全て複数文書にまたがる。意味の違いか表記の違いかは未認証。この規模では文脈識別モデルの優劣を判断する評価枠として不足している。
- pilot内の同じ左文脈＋読みは6重複群、余剰6枠、異なる入力994件、同一入力のラベル衝突0。同一文書4方針の依存もあるため、1,000独立標本として扱わない。
- 既知409,419履歴recordとの出典・段落・文・Jaccard>=0.8・同一入力の推移的な照合で、**15文書60枠**が履歴につながった。940枠は今回照合した履歴から隔離されていた。全枠を監査分母に保持し、60枠を独立評価へ流用しない。

履歴監査は六つの過去source生成、旧固定データの入力hash（ラベル/candidateはdecodeしない）、3本のWiki/Aozora増強source、旧KWDLC 50文書を対象とし、60.948秒。私的コーパス等も含めた全世界の重複なし、独立Gold、または公開Test汚染なしを自動認証するものではない。履歴の範囲とhashをJSONに列挙した。

## 次の判断

1. **#31/#39: 記号とIME入力単位の方針を先に固定する。** 251枠は読み誤りとして修正せず、「literalを含む入力」と「変換確定境界」を別方針にする場合の仕様を作る。今回のplan・1,000対象・253保留を保存し、追加検証は新versionで事前登録する。
2. **#31/#40: 文脈対比の研究評価枠を確保する。** 無作為に位置を選ぶだけでは3組9枠しか得られなかった。注釈由来の同読み・異表記群を取得/候補成績と独立したルールで集める設計を別に固定する。意味・表記意図の未確定を正解へ昇格しない。必要量に達しなければ不足として報告する。
3. **#32/#40: 長い入力の候補欠落を分類する。** 43件のTop32欠落と8件のTop6外を区別し、読み・入力境界・表記・辞書経路・探索上限のどこに原因があるかを調べる。モデルを大きくしても候補にない表記は選べない。Gates A/B前の製品protocol v2へは進まない。

#40〜#42を開始条件なしに走らせない。まず上記の入力課題を成立させ、学習に利用できるsource、同一候補・分母、未使用の研究評価枠を固定する。独立Goldがない現状で、AI一致や原文一致を最終品質保証へ置換しない。

## 実装・検証・再現

責務は `data.context_pilot` が4入力方針・保留状態・集計、research scriptsが取得・immutable artifact・converter実行を所有する。旧KWDLC readerの公開抽出契約で文書形式を検証し、旧reader/Gold admission/旧モデルへ変更を加えていない。

- 新規12契約を含む**475 tests成功、skip 0**。runner全体28.813秒。代替注釈、文脈境界、長さ、空の入力方針、未測定と候補欠落、HTTP 429/Retry-After停止、hash不一致と未試行全件の終端を確認。
- 原文と候補snapshotから別のscalar集計で、全4方針・全20 Top-k計数・状態・経路・対比群が一致。[検証receipt](../../reports/issue-39-context-pilot-verification-v1.json)。追加のconverter実行0、モデル実行0。
- 既存増強実験の元成果物16件とfit固定25件はhash不変。旧KWDLC 50原文もGit blob再照合。7 Python filesの構文解析、diff/artifact追跡検査、runner終了と一時領域cleanupを[完了receipt](../../reports/issue-39-context-pilot-completion-v1.json)に記録。
- 原文、対象、source予約、候補、履歴の個票、実行/テストログはignored `data/generated/issue-39-context-pilot-v1/` に保持。Gitへ原文・データセット・candidate snapshot・バイナリを追加していない。
- Sakura Inputの観測HEADは `c53f1f179b5424ed335a44dddf8a16cd46648920`。現行checkoutの挙動を推定せず、従来のhash固定reference exporterと辞書を使用した。

環境は既存の[固定lock](../issue-33-data-growth/env/uv.lock)。`PYTHONPATH=src python -m unittest discover -s tests` で契約を検証できる。実測stageは `acquire.py` → `prepare.py extract` → 入力binding commit → `prepare.py audit` / `forward.py` → `verify_publish.py`。既存出力の上書きを拒否するため、再生成はplan/予約を引き継いだ別の出力版で行い、既存receiptを削除して再実行しない。

pilot内の追加分布計数は、固定targetsとhistory-relationsに対し以下で再現できる（本文は出力しない）。

```python
groups = defaultdict(list)
for row in targets:
    groups[(row["left_context"], row["reading"])].append(row)
duplicate_groups = sum(len(g) > 1 for g in groups.values())
duplicate_excess = sum(len(g) - 1 for g in groups.values())
label_conflicts = sum(len({r["target"] for r in g}) > 1 for g in groups.values())
historical_documents = len({r["document_id"] for r in targets
                            if r["stable_id"] in relations["excluded"]})
```

## IRV

A. 必要範囲: 旧KWDLC public reader、reference snapshot/native receipt契約、既存source/input isolation API、新しい4方針と取得/生成/forward/再計数script、12新規契約。B. 拡大理由: 新しい入力方針で句読点が読み列へ入り、過去の見出し抽出と異なる未測定が生じた。後出し修正を避けるためliteral由来とIME境界判断を分離して報告した。C. 状態の所有者は各stageの上書き禁止artifactと終端receipt。モデル・既存データ・Gold admission・製品の契約を変更しない。D. 次回は4方針と保留状態の契約を再利用できる。新しい入力境界の意味、source用途、文脈対比の正解根拠と評価分母は改めて理解・検証が必要。
