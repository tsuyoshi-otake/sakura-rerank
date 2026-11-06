# Gold品質証拠の限定監査 (#31, #35)

**採用精度90.72%からの改善は未実証。独立Gold Testは0件、リリースは未完了。**
2026-11-07、親#1。出典注釈の来歴と、IMEとして正しい変換の品質保証を区別した。
今回の監査単位は完了した。自動取得・探索・再学習を繰り返す段階ではない。

## 実験上の成果と限界

[損失配分の実験](../issue-33-loss-balance/README.md)では過剰修正が減り、
悪化していた原注釈方式からゲートなし平均が+1.3491pp回復した。しかし固定ゲート後は
80.6071%から80.1574%へ低下し、不採用となった。これは研究用原文一致の集団であり、
採用devの90.72%と横比較しない。

[将来分割案](../issue-35-consumption-partition/README.md)の615入力/47出典成分は
metadata上の反実仮想。現在は全枠消費済みで、来歴とGoldも未認証のため独立Testは0。
今回も新規fit・閾値選択・calibration・最終Test・元データ/モデル変更は0である。

## 一次資料で分かった範囲

| 出典 | 確認した証拠 | 現行IME Goldに不足する証拠 |
|---|---|---|
| KNBC | 形態素等の注釈と、原文誤字を残して訂正解釈を注釈する方針 | 原文一致だけでは正しい変換ではない。形態素/読みの注釈は実際の確定入力境界・表記意図と別。抽出後IME集団の独立品質監査がない |
| KWDLC | 人手修正した言語注釈、2014論文§6.5の複数判定者実験 | その一致度は著者/読者表現・述語項構造等。形態素等を共同確認した後の実験を、読み/IMEの独立正解率へ転用できない |
| Tatoeba | 文のcorrectnessフィルタ、transcription生成/編集状態、編集者の来歴 | exportの文フィルタはtranscriptionの独立正解率ではない。IMEの表記意図・入力境界も未認証 |
| AJIMEE-Bench | 推定読み・切り出し境界の人手確認と複数許容解。200件、文脈あり/なし各100件 | 有用な公開難例だが最低valid3000に不足。作成手順は現行品質閾値の監査結果ではなく、誤変換例由来の集団を代表Testとも区別する |

これらは出典の誤ラベル率を測った結果ではない。第三者の人手注釈は有用であり、
自分たちで人を募集しない方法も排除しない。来歴・作成手順・判定者間一致率・
読みの正しさ・意図した変換の正しさを同じ指標にしない。

AJIMEEはWikipedia入力誤りデータv2から切り出し、読み推定後に人手確認したもの。
実ユーザーのkeystroke/IME確定ログを観測した集団とは推定しない。公開評価の
学習/閾値選択への転用はしない。今回payload・予測は開いておらず、露出履歴も
未確認のため未使用Test登録は行っていない。

## 固定出典・証拠の再確認

[集計JSON](../../reports/issue-31-gold-evidence-v1.json)に固定commit/Git blobと
取得UTF-8本文のSHA-256、既存PDFのSHA-256を保存した。原文や候補はGitへ追加しない。

1. [KNBC公式説明](https://nlp.ist.i.kyoto-u.ac.jp/kuntt/)と既存マニュアル§4.1/§4.4.1。
   固定archiveは`KNBC_v1.0_090925_utf8.tar.bz2`。13ページのrender記録を注釈品質の
   証明と呼ばず、古い`visual_layout_verified=false`も変更しない。
2. [KWDLC固定README](https://github.com/ku-nlp/KWDLC/blob/c6ae49d29eca4e1134c6676d682adf5ed6a25f5a/README.md)、
   [2012論文](https://aclanthology.org/Y12-1058.pdf)、
   [2014論文](https://www.jstage.jst.go.jp/article/jnlp/21/2/21_213/_pdf/-char/ja)。
   2014年§6.5、印刷235–237ページで一致実験の対象を確認。論文全体のローカルhashは未取得。
3. Tatoeba固定commitの[export SQL](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/docs/database/scripts/weekly_exports.sql)
   と[transcription実装](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/src/Model/Table/TranscriptionsTable.php)。
   download pageは1回の読取が429で終了し、連続retryなし。未取得を出典全体に証拠がない証明に使わない。
4. [AJIMEE固定README](https://github.com/azooKey/AJIMEE-Bench/blob/401666cd56d1a570c2021798b64b6da4396bfd45/README.md)。
   データCC-BY-SA3.0、評価コードCC0と記載。READMEの例も新規独立Testにしない。

## 判定と外部前提

実環境で`evaluation_admission.VERIFIED_GOLD_CERTIFICATES`の要素数0を確認した。
未認証計画をデータ/モデル読取前に拒否する契約は変更なし。fixtureの1000/1000や
3000件を実績にしない。独立品質の監査分母・正解数・precision・CIは未取得の`null`。

Gold点99.5%以上、Wilson両側95%下限99.0%以上、最終valid3000以上、Oracle@6>=97%、
完全来歴・漏洩なしを維持。pilot1000件の運用一致率は最終品質保証と別である。
raw converter/native local両基準の破壊率0.25%、独立calibration、全条件固定後の
最終Test1回も維持した。

**外部前提は、現行IMEラベル定義に対する品質を確認できる、十分な件数の既存
第三者データと監査証拠である。** 自前人手募集を必須へ戻さず、AIを人手に偽装せず、
AI一致を独立正解率にも変えない。直前の準備・除外調査・分割案から同じ不足が継続し、
今回の限定監査でも解消しなかったため、リリース目標をblockedとする。
どの公開データでも達成不可能という結論ではない。適合artifactが得られた場合は
品質・来歴・利用条件・履歴を確認して未使用集団を先に固定し、その後に比較へ進む。

親#1の同予算GRU/minGRU/Tiny Transformer、v1/r2/#29/current Tiny比較、Gate Bの
改善/安全性、Gate Cの製品往復・資源・量子化、Gate Dのnative/session/privacy/
fallback/運用検証も未完了。Gold不足だけにrelease scopeを縮小していない。
精度改善幅とGold収量は未知。AJIMEEは将来の補助難例比較の候補である。
新artifactの検証費用は入手後に測定し、現時点で人員・工数や改善幅を捏造しない。

## 検証・保存・IRV

900秒上限の既存ownerで全1095 testsを再実行し、failure/error/skip0、70.612秒で終了。
親15636/子72996と該当task commandの残存なし。旧16 artifact/25 fit binding/
10 checkpoint/7 reportは不変。新実装/test/依存/branch/worktreeは0。型checkerは未実行。
既存admission/安全性契約は全suiteに含まれる。`git diff --check`と変更artifact検査も行う。

```text
PYTHONPATH=src;.
python -B research/issue-35-consumption-partition/run.py tests --output <new-private-root>
python -B research/issue-33-data-growth/verify_integrity.py
git diff --check
```

ignored recoveryは`data/generated/issue-31-gold-evidence-v1/tests-01/`の検証記録、
rubric/journalは`.codex/goal-loop/issue-31-gold-evidence/`。専用TEMPや新corpusは作成なし。

- A 範囲: 4出典の注釈方針、admission契約と関連tests、固定評価仕様、親#1のrelease条件。
- B 拡大: KWDLC一致度の対象を該当節で確認し、人手なしで使えるIME専用データの可能性を
  固定AJIMEE READMEで追加確認。payloadやモデル比較へは広げていない。
- C Architecture: 状態owner・reader・trust set・splitter・runner・model/native契約は変更なし。
- D 将来IRV: 上表から未証明の対象を確認できる。新artifactの品質/来歴/利用条件/露出確認は
  引き続き必要。実装構造の改善はない。既存memoryと重複する規則は追加しない。
