# KNBC固定format pilot — #35 / parent #1

**100固定枠を処理し、99注釈文・1空注釈ファイルを確認した。Goldや精度向上の実証ではない。**
採用精度90.72%、安全性0.25%、Gold点99.5%・Wilson95%下限99.0%・最終valid3,000件を維持する。
元データ・ラベル・モデル・split・productionを変更せず、native・推論・fit・calibration・最終Testは0。

## 分母と選択

[前回の出典確認](../issue-35-knbc-qualification/README.md)と同じ版固定archiveを使用した。
メタデータは249記事・81接頭辞グループ、記事名に対応する文候補4,186ファイル、
`fileinfos`249ファイル、記事名の形式に対応しない1ファイルに分かれる。
81グループという数が執筆者数と一致しても、著者対応を認証したとは扱わない。

planを`6daa84cb923556da2d5df52f2237c3ec6a90de4e`で固定してから選択した。
形式不明の1件を含む記事を診断用に固定し、残り19記事をsource/archive/seedのSHA-256順位で選択。
各記事5枠を確保し、不明ファイルをその記事の最初の枠とした。**99文候補+不明1件、20記事・19グループ**。
不明ファイルの結果を見て差し替えていない。これは例外を意図的に含むformat診断で、無作為な品質監査ではない。

意味的decode前に全4,187対象の29,172,085 bytesをopaqueにhash化し、完全な同一byte群が0であることを確認。
同名複製という当初の仮説はメタデータで否定されたため、名前だけで除外しなかった。
選択結果・各byte hash・全枠露出方針を`ee9f945b357d64ba2991e0ee9dfae459068eb2a2`でcommit後にdecodeした。

## 結果

| 指標 | 件数・意味 |
| --- | --- |
| 固定枠 / 意味的読取の試行 | 100 / 100 |
| 読み取れた注釈文 | 99 |
| 保留 | 1。69 bytes、headerとEOSのみで形態素なし |
| 保存した形態素field組 | 1,479 |
| 読み欄の機械分類 | ひらがな1,275、同一の記号203、仮名入力には未対応1 |
| ER修正マーカーのある文 | 5。文節行3・基本句行2。形態素メモ欄は0 |
| 原形曖昧マーカーのある文 | 47。形態素メモ欄では72個 |
| 読み曖昧・品詞曖昧マーカー | ともに検出0。実際の読み品質や意味の一意性の測定ではない |
| マーカーの組合せ | 検出なし52、原形曖昧のみ42、原形曖昧+ER5 |
| 原表記・IME入力単位・Gold認証 | すべて0 |

文候補4,187という前回の暫定値は、**通常の名前を持つ4,186候補と空注釈1件**に分離できた。
4,186件全体を本文検証したわけではなく、99件を読み取った結果である。
空注釈の失敗枠も消費記録に残し、元ファイルは保存している。

修正メモを形態素欄だけで探す実装は、今回の5件をすべて取りこぼす。
一方、原形曖昧47件を誤ラベル・読み曖昧47件として扱う根拠はない。
surface・reading・lemma・grammar・構造行・notes・alternativeを分離して保存し、
ERの適用範囲や修正後ラベルは推測していない。修正/曖昧マーカーの分解は、選択後のformat説明用診断である。

既に露出した提供元文書との全文字列一致診断は0件。
8文字以上の注釈表記を空白除去して比較した限定的な診断で、断片・近似重複・全履歴隔離の証明ではない。
本文表記の出典復元、著者対応、source/input/history隔離は未検証。

## 残る独立評価候補の上限と次の判断

| 隔離条件 | 対象候補 | 残る文候補の上限 |
| --- | ---: | ---: |
| 使用した20記事 | 348 | 3,838 |
| 予約した19接頭辞グループを保守的に隔離 | 1,400 | **2,786** |

後者の予約を維持する。著者対応は未確認であり、前者だけを採用して独立性を主張しない。
2,786は品質・文書例・既存履歴の除外前のmetadata上限であり、valid Gold数ではない。
**1文1評価例なら、KNBC単独では最終valid3,000件を満たさない。**
件数を増やす目的で隔離を戻したり、1文から作る評価例を独立標本とみなしたりしない。

1. **P0: Goldの評価単位の既存契約を照合し、追加出典を確保する。**
   期待効果は独立Test3,000validと別calibrationの母集団確保。
   次の費用は提供元metadata・読み注釈・利用条件の確認まで。追加本文やモデル実行は別予約後とする。
2. **P0: 消費済み99件で原文対応とER適用範囲を固定する。**
   期待効果は原誤記や句単位メモを誤った単語Goldへ変換することの防止。
   現在の99件を再利用し、追加の原文表現へアクセスする場合はidentityと露出範囲を別途固定する。

この100枠は、元の1,000件Gold pilotや最終品質保証の代替ではない。
人手判定・AI言語判定の登録も0件。

## 再現と検証

実行順は`pilot.py freeze`、`run_owned.py select --commit 6daa84c...`、
`pilot.py seal --commit 6daa84c...`、`run_owned.py decode --commit ee9f945...`、
`run_owned.py verify --commit ee9f945...`、`run_owned.py tests --commit ee9f945...`。
`publish_pilot.py`はraw field・診断・容量と旧artifactを再検算して集計する。
結果はwrite-once。再実行には別の出力先を先に固定し、既存予約を削除・上書きしない。

全**972 tests成功**（新規18、failure/error/skip0）、5 Python構文・未使用import検査。
別実装のbsdtarで4,187ファイル・29,172,085 bytesを全件照合し、heapによる別選択実装も100枠一致。
100消費eventのhash chain、1,479組のsurface/reading/lemma/notes/grammar、診断・容量集計を検証した。
旧16 artifact・25 fit binding・10 checkpoint不変。製品APIや既存モデルを検証・更新した結果ではない。

証拠: [集計JSON](../../reports/issue-35-knbc-format-pilot-v1.json)、
[後処理検証JSON](../../reports/issue-35-knbc-format-pilot-verification-v1.json)。
raw選択・全失敗枠・hash台帳はignoredの`data/generated/issue-35-knbc-format-pilot-v1/`に保持。
将来の履歴bindingは、全100消費枠、20記事、19グループ、全byte alias台帳を読む必要がある。

## Scope / IRV

- **A: 範囲** — `knbc_source.py`と18契約テスト、研究用3 scripts、plan/consumption binding、
  source metadata・既存文書・全枠台帳。既存KWDLC専用parserを流用・変更していない。
- **B: 拡張理由** — ファイル名例外、ERの実際の格納場所、将来の候補容量を解くため、
  例外枠と選択後のfield/capacity診断を追加した。モデル・source全本文閲覧へは広げていない。
- **C: 責任と状態** — source adapterが予約/parse、研究stageがimmutable bytesと消費台帳を所有。
  既存graph・training consumer・production契約は変更していない。Gold等へのadmission権限を持たない。
- **D: 次回** — 取得・format探索を繰り返す必要はない。固定したfield契約と全消費履歴を利用する。
  原文/ER範囲と、完全な履歴隔離・評価単位の理解は引き続き必要。
