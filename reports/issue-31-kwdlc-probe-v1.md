# KWDLC外部注釈の開発用検証 (#31)

2026-11-04。親 #1、関連 #15/#32/#35。これは新しいGold認証でも最終Testでもない。

## 結果と判断

**固定したtrain 50文書を取得し、全50対象の読みをSakura辞書から推測せず、
外部の形態素注釈から取得できた。実変換による候補存在率は未測定。**
第三者が修正した形態素注釈は読みの独立した由来を提供するが、本IME課題の
意図する出力、入力境界、限定左文脈での一意性までは認証しない。

| 観測 | 件数・結果 |
| --- | ---: |
| 取得・Git blob照合 | 50 / 50文書、計285,207 bytes |
| 初回抽出 | 46成功、4形式未対応 |
| split sentence対応後 | 50 / 50成功、元の46対象は完全一致 |
| Sakura辞書の一意読みと外部注釈が一致 | 29 / 50 |
| 複数の辞書読みのうち一つと外部注釈が一致 | 17 / 50 |
| 対象表記が辞書索引にない | 4 / 50 |
| 表記が索引にあるが外部注釈の読みは含まれない | 0 / 46 |
| 読みが3文字未満 | 8 / 50。分母から除かず、Tier A採用とはしない |
| 実converter照合 | 0 / 50実行。Oracle@1/5/6/10/32はすべてnull |
| 本課題の新規人手判定・独立Gold認証 | いずれも0 |

17件は、従来の辞書一意読みからの生成では選びにくかった対象を扱えることを示す。
4件は索引の表記欠落であり、複数辞書エントリを接続する実converterが出力できない
ことを意味しない。一致46件も正解ラベル46件という意味ではない。
観測単位は文書ごとに選んだ形態素1個であり、一般IME入力の代表標本とはしない。

## 選択・履歴・形式修正

[事前仕様](../research/issue-31-quality/external-annotation-probe-v1.json)を本文取得前に固定し、
[選択receipt](../manifests/kwdlc-probe-selection-v1.json)をcommit `c55a30a` で先に公開した。
KWDLC `c6ae49d29eca4e1134c6676d682adf5ed6a25f5a` の
`id/split_for_pas/train.id` 3,915文書だけから、seed 20261104のhash順で50文書を選択した。
dev/testの区分ファイル本文・文書本文は取得していない。全treeのpath metadataは参照した。

文書内では漢字を含む形態素からhashで1対象を選ぶ。読みの形式・長さ・候補の有無を
見て選び直さない。表記と読みは無正規化で保持し、右文脈を評価入力に渡さない。
左文脈は同じ注釈単位内の直前最大64文字。実験用requestはstable IDと読みだけを含む。

初回の4件は、原文の3文の一部を `-1-01/-1-02` 等の複数注釈単位に分けた形式だった。
「常に3個のS-IDがある」というreaderの仮定が誤っていた。初回コードと
[46成功・4失敗の集計](issue-31-kwdlc-probe-r1.json)をcommit `0348a45` に保存してから修正した。
論理文1〜3の順序、各分割番号01からの連続、重複なし、各EOSを検証する。
sentence_indexは初回からの列挙処理に合わせて0始まりの**注釈単位**位置とし、
分割単位をまたいだ文脈連結は行わない。4件について初回の対象選択結果は存在しなかった。
形式対応は本文取得後の変更として明示し、事前仕様そのものを上書きしていない。

source取得は55回（metadata 5、本文50）、同時実行1、追加取得0。
metadata 5回には、connectorがblobを復号済み文字列で返すのにJSONと仮定した
ローカル処理の失敗後、membershipを明示的に1回再取得した分を含む。自動retryは行っていない。
取得台帳、初回とr2の個票・request・集計、原文bytesを別名で保存した。

## 実変換の不足物

検証済みexporterの要求SHA-256は
`0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf`。
現在のcheckout、Sakura Inputのtargetを含むcheckout、関連tmp、Dドライブの
worktrees/workspaceを調べた範囲では、この検証用実行ファイルを確保できなかった。
別実験の実行ファイルへ置換していない。

`$USERPROFILE/tmp/sakura-input-dictionary-build/system.dic` の実測hashは
`d83e571d41d1e2f804810493b0a7987372800f449ddddf540c94e6d40c675f73` であり、
固定辞書の `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad` と異なる。
一方、今回の辞書比較に使った既存の検証済み表記索引は所定hashに一致している。
索引比較と、辞書バイナリによる実変換は別工程である。

次の実施単位は、既存のexporter・辞書identityを再現または回収し、同じ50 requestを
forward照合すること。既存build scriptはworktree作成を含むため、そのまま起動していない。
復旧コストは、固定toolchain/cacheの有無と再現build結果を確認するまで未確定。
候補存在率を測る期待効果はあるが、Gold品質保証を代替する効果はない。

## 再現と受入条件

PowerShellで `$env:PYTHONPATH='src'` を設定する。元データのある同じcheckoutで実施する。

| Verify | Expect |
| --- | --- |
| `python -X utf8 research/issue-31-quality/inspect_kwdlc_probe.py` | 固定hash照合、50対象を再抽出、46旧成功を保持、辞書比較29/17/4/0、公開JSONとbyte一致 |
| `python -X utf8 -m unittest discover -s tests -p test_kwdlc_probe.py -v` | 16 tests成功。分割順序、部分欠落、改変、上書き、既成功対象の変更を拒否 |
| `python -X utf8 -m unittest discover -s tests -v`（外側timeout 300秒） | 426 tests中421成功、任意PyTorch依存5スキップ、失敗0 |
| 旧検証記録の33artifact hashと、新旧probe artifact hashを比較 | 全件不変。別出力先へのr2再生成も3ファイルbyte一致 |
| `git diff --check` と対象Pythonの`compile`、終了後process確認 | 形式・構文エラーなし、今回のrunner残存0、既存インストール済みworkerは維持 |

実測は[集計JSON](issue-31-kwdlc-probe-v1.json)と
[検証JSON](issue-31-kwdlc-probe-verification-v1.json)に保存。
元個票・原文・取得台帳はignored `data/generated/issue-31-kwdlc-probe-v1/` に保持し、
Gitへ本文を追加しない。提供元READMEも原bytesで保持した。利用条件と出典URL欠落の
制約は事前仕様から継続する。本文再配布・モデル学習の許諾を推定しない。
元学習/dev/holdout・既存モデル・0.25%安全基準・Test利用回数は変更していない。

## 必要範囲と設計影響（IRV）

A. 必要範囲: 固定probe仕様、取得receipt、KNP形式、辞書索引の公開streaming契約、
exporterのidentity/実行契約、新readerと16 tests。B. 拡大理由: 4文書の分割S-IDへの
対応と、既存exporter・辞書binaryの所在確認。モデル/製品内部への調査拡大はしていない。
C. 新しい挙動の所有者は `data.kwdlc_probe`、証拠状態の所有者は上書き禁止のprobe
artifact群。transportと解析を分離し、外部取得は解析関数から行わない。
辞書照合scriptは既存の公開読込契約を利用する。既存ラベル生成・評価の意味は変更しない。
D. 次回は固定sourceと50 requestから再開でき、取得・選択・形式調査を繰り返す必要がない。
exporter復旧と候補照合、他履歴との重複、代表性、IME課題の品質は今後も別途検証が必要。
