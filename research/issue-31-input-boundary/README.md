# #31 / #32: 記号・入力境界と候補欠落の監査

## 到達点

#39の全1,000枠について、原文・読み注釈を変更せずに、記号を含む一括変換と記号で区切った変換を実測した。以前の保留253枠のうち251枠を研究仮説として測定可能にした。これはGold認証ではなく、ユーザーがその範囲を実際に一括入力したという証拠でもない。

旧747枠のTop1/5/6/10/32は全て不変。学習・モデル推論・独立Test使用・ラベル変更は0。安全性0.25%、Gold品質99.5%点推定/Wilson下限99.0%、最終valid 3,000件の条件を変更していない。

## 固定した方針

- 原注釈の読みがひらがな/長音ならphonetic。表記と読みが完全一致し、全文字がUnicode P*/S*ならliteral。長音はphoneticを優先する。
- `whole`: literalを含む原注釈の読みをそのまま一括変換する。
- `literal_split`: literalをそのまま保存し、それを挟む連続phonetic部分だけを別々に変換する。形態素間の追加分割はしない。
- `morpheme_diagnostic`: 各形態素を別々に変換する診断。製品の入力境界方針ではない。
- 非対応注釈・代替注釈・境界超過は未解決とする。読みの推測、句読点削除、NFKC、候補を見た対象交換は行わない。

原sourceは固定KWDLC train 250文書。第三者の形態素注釈を読みの出典に用いる。原著作者の許諾・source URLの制約は残り、学習や再配布へ転用しない。原文由来のprefixは人工的な左文脈であり、観測されたIME sessionではない。

## 測定結果

一括変換は996枠で候補を取得、2枠はexporter拒否、2枠は非対応注釈。拒否は「空の認証済み候補」として扱わず未測定に残した。

| 原入力方針 | 全枠 | 一括測定 | 一括Top1 | 一括Top6 | 一括Top32 | 記号分割測定 | 分割Top1 | 各部分Top6存在 | 各部分Top32存在 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 形態素 |250|250|207|247|247|250|207|247|247|
| 1基本句 |250|250|202|240|240|250|202|241|241|
| 2基本句 |250|250|170|222|226|250|171|223|227|
| 3基本句 |250|246|150|209|219|248|152|212|222|
| 合計 |1,000|996|729|918|932|998|732|923|937|

**各部分の候補に原表記が存在することは、結合した候補が全体Top-kに入ることを意味しない。** 表の分割Top1は各先頭候補を実際に結合した原文一致。各部分Top-kは組合せのoracleであり、順位や費用を統合したN-bestではない。このデータではTop1結合一致と全部分のTop1一致に差はなかったが、文字の境界がずれる合成例を別テストで検証した。

同じ998枠で、記号だけの分割はTop1 **732**、全形態素の分割は**686**だった。細切れにするだけでは原文再現が46枠悪化する。異なる長さ方針の対象は同一例の長さ操作ではないため、表の差を長さだけの因果効果とはしない。

## 旧43欠落をどこまで切り分けたか

旧747測定枠のうちTop32に原表記がなかった43枠を、構成語の実変換と同一辞書hashの索引で調べた。

| 観測された不一致 | 枠数 | 次に検証する責務 |
|---|---:|---|
| 構成語の表記が辞書索引にないものだけを含む |32| 語彙・固有名・表記許容方針と外部資料 |
| 表記はあるが注釈の読みが索引にないものだけを含む |5| 文脈依存の読み・活用・注釈/辞書の対応 |
| 上の両方を含む |1| 両方の証拠を分離して確認 |
| 全構成語の原表記は個別Top32にあるが一括では欠落 |5| 合成経路・費用・品質フィルタ・探索打切り |

全998枠の構成語診断では、原表記が個別Top32にない読み/表記ペアは50種類。39は表記が索引に存在せず、11は表記が存在しても注釈の読みが索引にない。索引に同一の読み/表記ペアがあるのに個別Top32にない例は、この50種類にはなかった。

**索引との不一致は誤ラベルの認定ではない。** 外部表記の正当性、引用・名称保護、活用や語義は未認証。5枠の一括探索終了状態はいずれも`truncated`だが、これだけでは単純な候補数増加で回収できると断定できない。全体では一括Top32欠落64枠中54枠に個別構成語の欠落があり、10枠は全構成語が個別に存在した。

## 失敗も保存した実行経路

1. 方針を`8627f98`で固定し、全入力・実装を`c5dead9`で固定。2,148種類の読みのうち722種類は#39の同じbinary/辞書による認証済みsnapshotを再利用した。
2. 初回100読みバッチはexit 2。固定ASCIIエラーは`converter returned an invalid candidate count`。exporterは不適合候補数を検出するとbatchの出力を一括取消するため、候補内容から原因の読みを特定できなかった。失敗100、未実行1,326、追加認証snapshot 0の結果を保存した。
3. `d6dfea8`で、同じ1,426追加読みを1読み/プロセスで診断する別計画r2を固定。並行2、各30秒、全体600秒、retry 0。既知の候補数拒否は独立した終了状態とし、それ以外は新規投入を停止する。
4. **1,424成功・2候補数拒否・予期しない失敗0・未実行0、112.689秒**。拒否2読みはいずれもliteralを含む2文字以上。両方とも記号分割では構成部分を測定できた。旧snapshot validator、converter、辞書は変更していない。

現在のSakura Input HEADは`c53f1f179b5424ed335a44dddf8a16cd46648920`として記録した。挙動の根拠は現在checkoutではなく、source `5eefa2ffe15297e563da281432cece56049a1b09`から復元した既存reference exporterである。

## 再現・検証

必要な原文・候補・実行ログはignored local `data/generated/issue-31-input-boundary-v1/`に保存。原sourceは`data/generated/issue-39-context-pilot-v1/`、binary/辞書は従来のreference artifactsを用いる。生の入力や原文はGit・端末ログへ出さない。既存の出力への上書きは拒否する。

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
# 既存証拠の認証・再集計。変換の再実行はしない。
python research/issue-31-input-boundary/publish.py
python research/issue-31-input-boundary/component_audit.py
python research/issue-33-data-growth/verify_integrity.py
python -m unittest discover -s tests -v
```

元の出力が存在しない研究環境で初回から再現する場合は、plan固定→`prepare.py`→input binding固定→`forward.py --input-commit c5dead92e5c4ca704cf6259fb8a678d01b280b40`→r2計画固定→`isolated_forward.py --execution-commit d6dfea8989e89705dba898de57b1441512409b70`の履歴を保つ。元の失敗記録を消して成功だけへ置き換えない。

実測・原因診断の初版は`07d1309`に保存。未使用importの削除後の検証結果は`verification-r2`/`components-r2`に追記し、v1結果とスクリプトの履歴を残す。候補の再実行や指標変更は伴わない。

- Verify: 250 sourceのGit blob/byte size/SHA-256と旧1,000枠、新viewsを再生成。Expect: 原入力と完全一致。
- Verify: 全requestのnative receipt、binary/dictionary identity、candidate prefix/full-reading coverageを検査し、別のscalar処理で再集計。Expect: 全指標一致、旧747枠の結果不変、拒否例を分母に保持。
- Verify: literal/代替/長さ/部分数/部分失敗/結合Top1とoracleの相違、timeout/native失敗、全回帰suiteを実行。Expect: 全テスト成功、既存16 artifactと25 fit-bound artifact不変、所有runner残存0。

最終結果は**489 tests成功、skip 0**（runner 21.912秒）。9 Python fileの構文検査、対象diff検査、元artifact 16件/fit-bound 25件のhash照合、raw成果物のignoreと公開JSONのraw field不在を確認した。所有runner残存0、専用tmpを削除済み。[完了チェック](../../reports/issue-31-input-boundary-completion-v1.json)にlogと実装のhashを記録した。

## 優先順位と限界

1. #31/#32: 原表記/読み不一致を、外部資料・表記意図と結びつけて扱う。外部注釈を辞書に合わせて正解へ書き換えない。辞書から作った短い旧devの候補存在率を外部の長い入力へ外挿しない。
2. #40: 読みが同じで文脈により表記が異なる対象を、独立した未使用研究populationから固定する。現在の9枠だけでは識別能力の検証が足りない。研究評価データの用途と学習用途を分ける。
3. 文脈比較の条件が揃ってから小型条件付きGRU、次に#41の言語事前学習を比較する。原文一致の改善をGold精度や製品採用条件と混同しない。

独立した人手Goldは依然0、Gate A/B・最終独立Test・製品採用は未達。この監査は「現行90.72%が改善した」という報告ではない。

## IRV

A. 必要範囲は、既存KWDLC span reader、研究input boundaryの純粋関数、入力/実行/集計scripts、native receipt公開validator、対応テスト。既存の全学習や製品内部は変更していない。

B. 予想外の範囲拡大はbatch全体を失敗させる候補数検査。固定exporterと歴史的conversion入口の分岐だけを追加確認し、別実験r2で個別失敗を特定した。原因分類では同一辞書hashの索引reader契約とmanifestを追加確認した。

C. 注釈境界の所有者は既存reader、literal/分割仮説は`input_boundary.py`、実行と終了receiptはresearch scripts、Gold admissionは従来の別責務。raw stateは専用ignored directoryだけが保持する。製品・学習・Gold admissionへの依存を追加していない。

D. 次の境界監査は本方針・純粋関数テスト・snapshot認証契約から開始できる。一括N-bestと部分oracle、未測定と候補欠落の区別は今後も読む必要がある。独立Goldの定義や合成候補の順位統合を解決したとはしない。
