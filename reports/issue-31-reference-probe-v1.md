# 外部注釈50件の候補存在率と研究用変換器の再現性（#31 / #32）

固定したKWDLC trainの50件で、原文表記は44件が1位、5件が2位、1件が3位に存在した。
候補欠落は0件。2回の実行は出力バイトまで一致した。これは**外部注釈の表記存在率**であり、
IMEでの一意な正解率・Gold認証・モデル改善率ではない。

以前の[取得時レポート](issue-31-kwdlc-probe-v1.md)では未測定だったforward確認を、
旧認証条件を変更せず、別の研究identityで完了した。過去の未測定・復旧失敗の記録は保持する。
旧データ・ラベル・モデル・安全性基準0.25%は変更していない。再学習・独立Test使用は0件。

## 先に固定した条件

- [再確立計画](../research/issue-31-quality/exporter-reestablishment-plan-v1.json)を
  `4fab57baf5fdbb1730bb780bb6f8021637656bc5`で登録。
- [100件の選択commitment](../manifests/reference-probe-selection-v1.json)を
  `66268eeadb46274e357f29a2f61840964dcb73d8`で公開してから候補内容を参照。
  train 12,516件のIDを固定seedで並べた先頭100件。dev/holdoutはJSON解析前に除外した。
- 最終build recipe・全patch後hash・runnerを
  `7586bd923d8ac1926bf9a1c604b97e834d6203e1`で固定してから2回build。
- [実測identity binding](../manifests/reference-probe-identity-v1.json)を
  `b12db1c5ab5b0c0ca1337665ec654bf784b1b645`で公開してから変換を実行。
- 外部50件は前段の文書取得前に固定した同じ母集団。追加取得・ケース置換なし。
  対象は1文書につき漢字を含む1形態素で、候補の有無で選別していない。
  読みはコーパス注釈列に由来し、Sakura辞書から推定していない。

## 再現性と既存候補との比較

実在するSakura Input sourceは`5eefa2ffe15297e563da281432cece56049a1b09`。
歴史的HEAD・旧binaryそのものの復元ではない。旧exporterの三つのidentity文字列だけを
変更する別patchを使い、既存変換アルゴリズムの調整はしていない。

| 検証 | 結果 |
| --- | --- |
| 独立したarchive directoryからのbuild | 2/2成功、実行ファイル完全一致 |
| 実行ファイルSHA-256 | `3c12f1f603413a597e658a11df0148ca43354299addc9551a2fcf1f4daea9977` |
| 辞書SHA-256 | `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad` |
| train回帰比較 | 100/100一致、不一致0 |
| 外部50件の反復 | 2回とも50/50完了、失敗・timeout 0 |
| 外部出力SHA-256 | `261bf123a358fbf498f1f1b324806eb7b1c5a32a0b7c5f2c045b2a58271c9c28` |

回帰では全候補の順位・表記・cost・fingerprint・entry index・全segment項目、
Top-6 prefix、探索終了状態を比較した。identity変更とそれを含むhashは別記している。
100件の一致から全入力での歴史的同等性を保証しない。runtime内部の旧契約上の状態は
`unverified`のまま。別bindingと実バイナリ・辞書hashを照合したprobe専用経路でのみ受理し、
旧training readerの認証条件やallowlistは不変である。

## 候補存在率：分母は固定50件

| 原文表記の存在範囲 | 件数 | 比率 | Wilson 95%区間 |
| --- | ---: | ---: | ---: |
| Top-1 | 44/50 | 88.0% | 76.2–94.4% |
| Top-5 | 50/50 | 100.0% | 92.9–100.0% |
| Top-6 | 50/50 | 100.0% | 92.9–100.0% |
| Top-10 | 50/50 | 100.0% | 92.9–100.0% |
| Top-32 | 50/50 | 100.0% | 92.9–100.0% |

全50件を分母に含めた。順位分布は1位44、2位5、3位1。原文表記が候補にあるが1位でない
6件は、原文再現を目的とした場合の順位改善余地であり、6件すべてをIMEの誤変換とは断定しない。
全50件の一致候補はsystem dictionary由来で、46件が1segment、4件が2segmentだった。
辞書indexでの単語表記の欠落と、複数segmentを含む実変換での欠落は区別する必要がある。
探索は45件が32候補でtruncated、5件がsearch exhausted。上限外の候補を推定していない。

区間はこの小さい選択済みdevelopmentサンプルに対する二項モデルの記述統計。
文書・用例の関連や対象抽出条件を考慮した一般IME母集団の区間ではない。
Gold精度99.5%、安全性0.25%、ラベルの一意性はこの数値から認証できない。
旧devや採用モデルの90.72%とはデータ・identity・評価目的が異なり、改善幅を算出しない。
モデル適用・ゲート適用を行っていないため、修正成功/破壊・Precision/Recallは今回の測定対象外。

## 検証・失敗履歴・保存

[機械検証JSON](issue-31-reference-probe-verification-v1.json)に全実行receipt、
独立再集計、保護対象hashと区間の計算値を保存した。
[最終チェック記録](issue-31-reference-probe-checks-v1.json)はテスト・静的検査・再集計の
byte一致・process終了・cleanupを記録する。

- Verify: `PYTHONPATH=src python research/issue-31-quality/verify_reference_probe.py`。
  Expect: converterを再実行せず、binding・全100件比較・全50件集計・反復出力・旧成果物の
  hashを再確認できる。旧33artifact、以前のprobe 10artifact、原文50ファイルは不変。
- Verify: `PYTHONPATH=src python -m unittest discover -s tests -v`、外側timeout 300秒。
  Expect: 全437 tests中432成功・既存optional PyTorch 5skip・失敗0。
  新規11件はidentity/全件会計/改変拒否とLF/CRLF両archive適用契約を検証する。
- Verify: 対象Pythonファイルのcompile、`git diff --check`、Git追跡対象と実行processの監査。
  Expect: source/manifest/集計のみがcommit対象、rawデータ・binaryはGit対象外、所有runner残存0。

最初の二つのbuild preflightはコンパイル前に停止した。原因はGitの改行設定で、
exporterのLFと歴史的coreのCRLFを別々に保持する必要があった。
全4個のcore patch後ファイルhashを固定し、最終recipeの2回build前にテストで再現・修正した。
候補結果を見て変換処理や許容値を調整していない。失敗receiptも保存した。
後段の独立再集計helperは初回にschema field名を誤記して停止したため、公開contractの
`limit`に修正した。変換出力や測定値の修正はない。

ローカル再現材料はGit対象外の`data/generated/issue-31-reference-exporter-v1/`に保存する。
別dictionary復旧directoryとKWDLC取得directoryも保持する。task専用tmpのbuild treeは
保存材料を照合して削除済み（1,158ファイル、121,480,447 bytes）。所有runner残存0を前後で確認し、
cleanup/process記録を同じprobe directoryに残した。

## 次の判断と費用

1. 優先は外部注釈をIME課題に変換するときの正解定義。原文再現と、左文脈・読みから一意に
   意図を決められることを分ける。今回は読みを辞書から作る循環を避けられたが、
   意図・表記・入力境界の独立保証は未解決。次は既存の50件のうち1位非一致6件を含め、
   どの属性を機械証拠で決められ、どこを未確定に残すか仕様化する。
   費用は既存50件内の証拠照合と仕様作成。追加コーパス取得・学習・Test消費は不要。
2. その仕様が固定されるまで規模拡大や最終Test生成を行わない。代表性・履歴全体の重複検査・
   valid 3,000件以上・品質保証は別途必要。50/50を根拠にその費用を省略しない。
3. #34の独立calibrationと#33の比較学習は、その根拠が揃ってから行う。
   今回の結果だけではモデル精度の期待増分を推定できない。Gate A/Bとリリースは未完了。

## 調査範囲と構造への影響（IRV）

A. 必要範囲はprobe admissionの責任、固定source/profile/selection/binding、build/run/replay
script、候補snapshot contract、新規2 test file、既存のsource/候補検証、前段の証拠hash。
モデル内部・devの新規解析は不要だった。

B. build再現でlinker/SDK/library inventoryとarchiveの改行・4ファイルpatchに範囲が広がった。
これは実バイナリの同定に必要であり、モデル改善のための探索ではない。

C. 新状態は独立した選択・build・binding・run receiptが所有する。probe validatorがその
受理契約を所有し、既存snapshot検証を再利用する。旧training/Gold admissionは変更しない。
新しい本番依存や製品動作変更はない。

D. 次の同種probeは固定binding・入力契約・replay scriptから確認でき、dictionaryの復旧や
build環境探索を繰り返す必要が減る。母集団選択、権利、注釈品質、意図、リークの根拠は
新しい課題ごとに必要であり、今回の契約で代替したとは扱わない。
