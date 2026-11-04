# Issue #31: Gold方針の具体化と193件の追跡可能な論点整理

この記録は、AI pilot v1の非一意193件に対する方針整理である。旧判定・元データを修正せず、別台帳で各案件の次の検証を指定する。人手確認、独立二重判定、Gold認証の代替ではない。

## 実施前の検証条件

| Verify | Expect |
| --- | --- |
| 新規triage CLIで旧packet・AI policy・集計・batch履歴を照合 | 旧reportと完全一致。対象は非一意193件のみ、欠落・重複0 |
| 各案件の旧event hashと新方針hash、連鎖hashを検証 | 旧判定の差替え、異なる方針、未承認のlabel適用を拒否 |
| CLIを2回実行し、別のCounter計算と照合 | 同一の集計。Gate A/Test/humanの虚偽昇格なし |
| 凍結生成版の境界コードと現在版を照合し、合成例で再現 | 漢字/異なる文字種の境界検査の限界を、実データ修正なしで確認 |
| unittest・静的コンパイル・diff check・12既存artifact hashを確認 | 失敗0、旧artifact不変。最終holdoutを解析しない |
| 実行後のプロセスと作業ファイルを点検 | task所有runnerなし。一時ファイル削除、保存台帳のみ残す |

## 結果

**193/193件の論点整理を完了。ラベル確定は0件。** 25件×40batchと10件の自己訂正を含む旧AI pilotを検証し、非一意193件の全件について、この助手が凍結packetと旧理由を再読して確認ルールと個別理由を記録した。分類は人手判定でも独立第二判定でもなく、同じAIによる方針整理である。旧1,000件の判定と元データは変更していない。

集計は [JSON](issue-31-policy-triage-v1.json)、検証結果は [verification JSON](issue-31-policy-triage-verification-v1.json)、機械可読なルールと方針案は [triage policy](../research/gold-pilot-triage-policy-v1.json) に保存した。1,000件中193件は旧判定に基づく選択集合であり、母集団の誤ラベル率を推定する標本ではない。

### 旧「表記同値」113件の内訳

| 次に必要な検証 | 件数 / 113 | 判断 |
| --- | ---: | --- |
| 表記方針 | 65 / 113（57.5%） | 数字15、送り仮名11、仮名漢字・反復21、異体字6、外国名の歴史的漢字表記12。明示集合の検討対象であり採用済みではない |
| 名称・引用の表記保護 | 34 / 113（30.1%） | 固有名・題名・引用・正式な名称の一部、またはその可能性がある。無条件の正規化から保護する |
| 語義・用法の再検証 | 8 / 113（7.1%） | 異なる語や特殊読みを含む。意味が近いことを表記同値の根拠にしない |
| 原語・略号と読みの再検証 | 6 / 113（5.3%） | 英字・音写・略記は言語や文体の選択を含み、意図された出力の同値とは限らない |

34件は「正式名称の誤りを発見した件数」ではない。限られた左文脈で名称や引用の可能性があるため、置換から保護する対象数である。65件も読み・慣用性・表記意図が未認証であり、正解数に加算しない。

### 残る80件

- 旧「文脈不足」64件: 語義の問題46、同一人物・名称・題名の特定16、提示または代替候補の読みの根拠を先に確認すべきもの2。候補にあるという理由だけで、特殊な読みを曖昧性の証拠にしていた問題もある。
- 旧「読み不整合」3件: 複合語の内部で切り出された読みの疑い。文脈に適合した全単位の読みと実変換の検証が必要。助手の判断だけで修正読みを確定しない。
- 旧「未解決」8件: 左側から語中境界が観察できる4、右境界を確認できない3、専門用語の読みが未確認1。右文脈を補わず保留を維持する。
- 旧「抽出ノイズ」5件: 文脈欠落と対象ラベルへの影響を分けるべきもの4、未処理の機械的markupを直接観察できるもの1。前者4件を直ちに誤ラベル・判定不能として除外してはならない。後者も対象語の誤りを自動的に証明しない。

合計は113+64+3+8+5=193。旧「一意」807件は今回の再評価対象外であり、新方針で認証されたことにはならない。旧報告の807/1,000を正解率として用いない。AI分類の変更可能性が残るため、品質についての95%信頼区間は算出しない。

## 根本原因として確認できたこと

### 1. 辞書の一意な読み・forward一致は文脈中の読みを保証しない

v5 source manifestの抽出版は `0e9dca182b0319988f49a89c28b9e9f602ebe70f`。その `jawiki_preprocess.py` と現行ファイルのAST全体が一致した。`_character_class` は英数字・ひらがな・カタカナだけを分類し、漢字は `None`。`_safe_match_boundaries` は同じ文字種の隣接を拒否するが、漢字境界や漢字と仮名の境界には語としての検証がない。

辞書に対象surfaceだけを入れた**合成例**では、`科学館` から `科学`、`理学部` から `学部`、`見ている` から `ている` が切り出される。英字の対照例 `Alphabet` 中の `Alpha` は拒否された。これらはWikipediaから転載した例ではない。再現結果はverification JSONに保存した。

この結果は「漢字隣接を全て禁止すべき」という意味ではない。日本語は分かち書きがなく、それを行うと有効な語も失う。確認できたのは、**現在の文字種境界検査だけでは語の単位・文脈に合う読み・ユーザーが実際に確定した入力境界を保証できない**という契約上の限界である。pilotの個々の境界疑義がすべて誤りと実証されたわけではない。

### 2. 正しさを一つのラベルで表していた

旧分類には、原文の再現、意味の一致、表記意図、文脈の欠落、読みの妥当性が混在していた。同じ意味の旧字体でも固有名・引用には使えないことがあり、読みの候補があるだけで同義語や曖昧な語だと判定するのも不十分。前文の欠落だけで対象ラベルまで無効とするのも過剰である。

これはランキング改善前に解決すべき測定上の問題である。今回、devのモデルスコア・予測・候補順位を追加参照せず、モデル精度が何pt改善するかも推定していない。

## Gold方針案の具体化

方針案は今回のtrain pilotから得たもの。独立calibration/Test用に凍結済みの最終仕様ではない。既存のhuman policy v1とAI policy v1の内容・hashは変更しない。

1. **判定軸を分ける。** 原文一致、読み、入力単位、文脈の完全性、意味を限定できるか、意図された表記、判定者の由来を別に記録する。unknownを正解や誤りへ押し込まない。
2. **名称・題名・引用を保護する。** 数字種、新旧字体、仮名漢字、ローマ字、中黒、略号の一括正規化を禁止する。保護することと原goldを正しいと認証することは別。
3. **主評価と副評価を分ける。** 既存source-exact評価と分母を保持。意味の許容集合は、固定方針に基づき独立に裁定した明示集合だけを別評価し、対象数・対象外数・元母集団での保持率を併記する。難例の削除で品質を上げたとは主張しない。
4. **入力単位の出典を記録する。** 合成辞書spanを実際の部分確定入力とみなさない。全語・句を対象とする評価と、明示的に設計した部分確定の課題を別の層にする。右/未来文脈を評価入力へ追加しない。適切な単位を根拠づけられなければ保留する。
5. **全1,000件へ一貫して適用してから品質を論じる。** 今回193件だけの方針整理で807件を自動認証しない。AI自己再判定は人手二重確認や独立性の代わりにならない。pilotは最終品質保証ではない。

品質目標は点推定99.5%以上、Wilson 95%下限99.0%以上、独立した最終holdout valid 3,000件以上を維持する。安全性0.25%も維持。独立Testはモデル・特徴量・ゲート・ラベル方針を固定して一度のみ。今回の作業ではGold版の生成、学習、閾値選択、#33/#34/#35の実装を行っていない。

## 優先順位・期待効果・検証コスト

以下は実測工数ではなく計画上の条件付き見積。精度改善幅は未測定。

| 優先 | 作業 | 期待効果 | 検証コスト・完了条件 |
| --- | --- | --- | --- |
| 1 | #31の判定軸・保護規則・入力単位を固定し、全1,000件へ一貫した判定 | 表記差・曖昧性・ノイズの混同を減らす | 1判断30–60秒なら、2名×1,000件で約17–34 reviewer-hours＋裁定。単独AIによる試行時間を人手実績に換算しない |
| 2 | #31/#32の境界・文脈読みを小規模な制御課題で検証 | 辞書一意読みで見逃す誤りと、正当な部分入力を区別 | 仮に50課題を1課題2–5分で検証するなら約2–5時間。実読みの根拠、全単位のforward一致、正当な隣接例の保持を確認してから抽出変更案を判断 |
| 3 | #35の評価設計を確定する | pilot・calibration・一度限りのTestを分離し、同じ問題の再発を防ぐ | 文書の分母・入力group・ラベル方針・固定手順の照合。実装前に全要件を満たす設計が必要。実装工数は別途見積 |

#34の独立calibrationによるゲート改善、#33のモデル比較はこの後。48件の救済候補を扱う際にも、0.25%を緩和せず、誤修正と救済を識別する能力を検証する。

## 再現・検証・保存物

`PYTHONPATH=src` を設定して実行する。コマンドは読取専用で公開用集計だけを標準出力に返す。

```powershell
python -X utf8 -m sakura_rerank.data.pilot_policy_triage --packet data/generated/issue-31-gold-pilot-v1 --ai-policy research/gold-pilot-ai-policy-v1.json --batches data/generated/issue-31-ai-pilot-v1 --base-report reports/issue-31-ai-pilot-v1.json --triage-policy research/gold-pilot-triage-policy-v1.json --ledger data/generated/issue-31-policy-triage-v1/triage.jsonl
python -X utf8 -m unittest discover -s tests -p test_pilot_policy_triage.py -v
python -X utf8 -m unittest discover -s tests -v
```

境界の合成例は次で再現できる。抽出版のsourceは `git show 0e9dca182b0319988f49a89c28b9e9f602ebe70f:src/sakura_rerank/data/jawiki_preprocess.py` で取得でき、今回の検証では現行版とAST全体を比較した。

```powershell
@'
import json
from pathlib import Path
from sakura_rerank.data.jawiki_preprocess import ExtractorConfig, SurfaceMatcher
v = json.loads(Path('reports/issue-31-policy-triage-verification-v1.json').read_bytes())
for e in v['synthetic_boundary_examples']:
    index = [dict(schema_version=1, record_type='system_dictionary_surface_index',
                  surface=e['surface'], readings=[e['reading']])]
    actual = [list(x) for x in SurfaceMatcher(index, ExtractorConfig()).matches(e['text'])]
    assert actual == e['expected']
print('4 synthetic boundary checks passed')
'@ | python -X utf8 -
```

- 集計を2回再現し、別Counter計算でも193件・各分類数が一致。これは計算検証であり独立ラベル判定ではない。
- 293 tests成功、既存optional PyTorch tests 5 skip。新規8 tests全成功。300秒のsubprocess timeoutを設定して実行。静的コンパイル成功。
- 12既存artifactのSHA-256不変。既存AI report・全batch・自己訂正履歴を完全照合。最終holdout本文は解析せず、保全確認のためバイト列hashのみ計算した。
- Sakura Input HEADは `d586fae572d32aa76512994dca616dadef2899b1`。本番コード・モデル・既存データは未変更。
- 保存する個票はGit対象外の `data/generated/issue-31-policy-triage-v1/triage.jsonl`。旧event、case evidence、旧report、新policyのhashと、前のeventのhashに連結する。公開JSONには本文・case IDを含めない。
- この193件snapshotは不変。以後の方針・判定改訂は新しい版に旧版のhashを参照して保存する。旧ledgerを書き換えてCLIを再実行しても旧公開hashとは一致せず、旧版の証拠にはならない。
- Gate A両方false、human review=0、独立二重判定false、独立Test false、独立holdout valid=0、ラベル適用false。
- 実行後のプロセス一覧にtask所有のPython/test/training/ORT runnerは残っていなかった。既存インストール済みのSakura Input workerは別プロセスとして維持した。一時作業用の `~/tmp/gold-policy-20261104/` は削除し、上記のGit対象外ledgerだけを継続作業の証拠として保存する。

**残る限界:** 同じ助手による再読であり、旧goldを見たアンカリングはある。方針が改善されたかは新方針に基づく全pilotの一貫した判定で検証する必要がある。専門読み・正式表記の外部照合は未実施。今回は誤ラベルの認証・修正件数を増やした作業ではなく、判断の混同を可視化し次の検証を指定した作業である。

## IRV記録

- **A. 実際の範囲:** Issue #31、旧pilot policy/protocol/report、AI batch契約、packet読取契約、triage方針・集計・8契約テスト。境界調査ではv5 source manifest、`jawiki_preprocess.py` の文字種・match・span生成と関連テストを参照した。
- **B. 拡大理由:** 193件の分類を読むだけでは、語中の切出しを誤りと断定できないため、凍結抽出版とそのpublic matcherまで調査を拡大。研究全体の変更は必要なかった。一般的な局所Issueより広い資料が必要だったのは、旧ラベル意味と生成時の入力単位契約が別責任だったため。
- **C. 変更責任と状態:** 新しい `pilot_policy_triage.py` が読取専用の照合・集計を所有。旧AI ledgerが旧判定の状態を所有し、新ledgerは検証先の指定だけを所有する。training/evaluationのラベル状態とは接続しない。既存moduleは変更せず、既存packet読取・AI履歴検証・canonical hashへ依存する。
- **D. 次回のIRV:** 新しい論点整理ではrule定義、旧report hash、triage集計契約を入口にできる。ただし言語的判定の正しさ、個別読みの根拠、入力単位の妥当性は依然として個票と根拠を確認する必要があり、コード検証で省略できない。
