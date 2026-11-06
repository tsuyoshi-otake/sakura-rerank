# #35/#32: 外部の読み注釈を使う100文のsource pilot

2026-11-06 / Parent #1 / Related #31, #33, #34

**Tatoebaの248,947文から、本文を見る前に100文を固定した。98文では原文と読み注釈の表記が対応したが、現行の全履歴隔離を通過したのは14文・44注釈だった。** 原文対応をGold品質や実際のIME入力単位の認証として扱わない。採用モデルの記録値90.72%、安全性0.25%、Gold品質条件、最終Test一回使用は不変。今回のfit・モデル推論・native候補取得・本番変更は0。

[集計・hash・検証JSON](../../reports/issue-35-external-source-pilot-v1.json) /
[取得・選択plan](plan-v1.json) / [本文閲覧前の100枠固定](selection-binding-v1.json) /
[全履歴binding](history-binding-v1.json)。元データ・モデル・過去の実験を変更せず、新しいsidecarに結果を保存した。

## 出典を選んだ根拠

| 候補 | 公式資料で確認した事項 | 今回の判断 |
|---|---|---|
| Tatoeba | 日本語文とふりがなを別exportで配布。transcriptionのUsernameは見直し・修正の来歴を表すが、exportには読みの更新日時やneedsReviewがない | 100文のsource適合性pilot。編集者を独立人手判定者に読み替えない |
| UD Japanese GSD | SUW/LUW/文節等の注釈と変換工程を記載。UniDicInfoの語彙読み・発音等は異なるフィールド。注釈のCC BY-SA 4.0と原文の権利説明を分けている | 今回はデータ未取得。注釈とIMEの表記読みの対応、原文利用条件を確定する前に混入しない |
| Kyoto Japanese Dependency Corpus | 公式ページが研究メンバー向け配布と明記 | 制限されたデータの取得・会員登録なし |

根拠: [Tatoeba配布仕様](https://tatoeba.org/ca/downloads)、
[日本語export一覧](https://downloads.tatoeba.org/exports/per_language/jpn/)、
[GSD公式README](https://github.com/UniversalDependencies/UD_Japanese-GSD/blob/7bc20119f476b552635e0640644e577b6fd3606b/README.md)、
[Kyoto JDC公式案内](https://www.lsta.media.kyoto-u.ac.jp/resource/data/word-dep/home.html)。

Tatoebaの書式と抽出条件は、公式コードcommit
`f2c80b81032630648f7896182174a9f5784ccde2` の
[weekly_exports.sql](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/docs/database/scripts/weekly_exports.sql)、
[ふりがな形式](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/src/Model/Entity/FuriganaTrait.php)、
[transcription生成](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/src/Model/Table/TranscriptionsTable.php)、
[原文変更時の処理](https://github.com/Tatoeba/tatoeba2/blob/f2c80b81032630648f7896182174a9f5784ccde2/src/Model/Behavior/TranscriptableBehavior.php)で照合した。
原文変更時の再生成処理があるため、単に「古い読みが残る実装」とは断定しない。exportだけでは更新順・稼働版・編集意図は認証できない。

## 取得、許諾、閲覧の境界

固定snapshotは `tatoeba-jpn-weekly-20261031`。2026-11-06 00:04 UTCのHEAD検査後、
planを `98c74d4eb51c9a479101503c6a08907400601cdc` でcommitした。
条件付きGETを00:14:43–00:14:54 UTCに実施し、両ファイルのURL・byte数・ETag・Last-Modifiedが一致した。

| ファイル | bytes | local SHA-256 |
|---|---:|---|
| jpn_sentences_detailed.tsv.bz2 | 4,462,456 | ef4b273dec34a6d4c3be746189c5dd2fafe88e614aa059ec59c6897cd57a9b42 |
| jpn_transcriptions.tsv.bz2 | 4,281,664 | a38dc822673fc43b57b25eaa3baa1b87d13beeb83adb8cec188914c94a13ca45 |

公式index・response headerに暗号学的digestは見つからなかった。ETagを公式hashと呼ばず、
**公式HTTPSからの暫定取得**として保存する。既存の信頼済みdataset manifestやGold認証へ昇格しない。
週次URLが更新された場合は再現取得を停止する。再現には保存した当該byte列が必要。

配布仕様のCC BY 2.0 FRを記録し、元ファイルのattributionはprivate artifactに保持した。
原文exportにはlicense条件がある一方、transcription exportのSQLには同じ条件がない。
そのため原文exportに存在しない98件は、読み内容の良し悪しにかかわらず選択対象から外した。
これは98件の権利侵害や誤ラベルを認定したという意味ではない。

全exportのID・言語・script・編集者の有無を機械的に走査し、原文248,947、読み249,045、
原文所属が確認できる編集者記録あり108,248・なし140,699を確認した。
その後seed 20261106のhash順で80文・20文を固定し、
`c7626f1c9345fc7e2d5208f276f9f0e4d548921c` のbinding commit後に限って100組の本文と読みをdecodeした。
本文・モデル結果に基づく補充や選び直しは0。

取得は並列1・自動retry0・request timeout30秒・全体180秒。展開は各128 MiB・50万record・1record65,536 bytesまで。
調査ページの429には冷却時間を置き、データGETは2回とも成功。失敗時は予約・partial・終端を保持し、信頼済みの部分成果物を出さない。
元本文、読み、ユーザー名、選択ID、個別の関係はcommit/report/logに出さない。

## 100文の判定結果と限界

| 指標 | 編集者記録あり80文 | 記録なし20文 | 合計 |
|---|---:|---:|---:|
| 原文と注釈表記が完全対応 | 80 | 18 | 98 |
| 空の読みを含み解析保留 | 0 | 2 | 2 |
| 対応を確認できたwhole-ruby注釈 | 251 | 61 | 312 |
| 全履歴と関係する注釈 | 233 | 35 | 268 |
| 現行隔離を通過した仮説 | 18 | 26 | 44 |
| 認証済みIME Gold / calibration採用 | 0 | 0 | 0 |

空読みは2文内の3注釈に存在した。失敗2文を分母から削除しない。
98/100は文字列構造の照合結果であり、日本語変換の正解率ではない。80/20は意図的な層別標本で、
全corpusの割合とも異なる。Gold正解率の点推定・95%区間は算出できない。
今回の人手A/B/C判定は0。AIや同一辞書の一致を第三者の正解証拠にしていない。

形式は `[base|reading|reading]` をexactなcode pointで復元し、空の一文字分readingはwhole-baseに連結する。
baseの途中を単語として分割せず、かな変換・NFKC・表記の書換えはしない。
[MySQL公式のexport仕様](https://dev.mysql.com/doc/refman/8.4/en/select-into.html)に基づくescapeと物理改行を扱い、未対応形式は明示的に保留する。

312注釈中、1文字base196、直後ひらがな271、直後基本漢字31、直前基本漢字28。
これらは重なる観測であり誤り分類ではない。助詞、送り仮名、複合語境界を文字種だけでは区別できず、
whole-rubyでも意味的に完全なIME入力単位とは限らない。
右側文字は監査だけに使い、入力仮説は原文の左64文字と原注釈readingに限定した。
この原文prefixも実際にSakuraで確定したsession textではなく、source-only仮説である。

## 全履歴の隔離と接続理由

過去988,073 node、今回100文の全coverage、312入力仮説を合わせた988,485 nodeを使用した。
旧割当と既除外は保存。source・owner group・bounded input・完全/近似本文の関係を全件再構築し、
正順/逆順の除外・component hash・集計が一致した。処理は226.402秒。
84文・268注釈が履歴に接続し、14文・44注釈が残った。2文は入力仮説を作れなかった。
入力を持つ成分は17、うち履歴から隔離された成分は14。

「履歴」は旧train・split不明・研究評価等を含む。84文すべてが直接重複したことや、
本番精度にその分の漏洩があることを示す数値ではない。
Tatoebaのownerは管理上の所有者であり、原著者の同一性を保証しない。
今回は保守的にowner tokenをgroupとしたが、翻訳リンクや未記録の元出典もまだ追跡できていない。

結果を見た後の原因調査として5条件を固定し、全nodeと旧関係を残して診断した。
元の全component hash・全268除外は完全一致した。直接同じ左文脈＋読みを持つ仮説は12、
直接の原文hash一致は0だった。

| 診断条件 | 履歴へ接続する注釈 | その注釈を含む文 |
|---|---:|---:|
| 元の全関係 | 268 | 84 |
| 全著者/owner edgeなし | 43 | 12 |
| bounded input一致edgeなし | 0 | 0 |
| source単位・著者/owner・input一致のみ | 268 | 84 |
| 本文一致・類似だけ | 0 | 0 |

これは**12個の直接入力一致が、同じsource単位や所有者等の関係を通じて拡大する問題**を示す。
新しい文が84件そのままコピーされていたという解釈は誤りである。
著者/ownerなし条件は過去sourceの著者edgeも除く全体診断であり、Tatoebaのownerだけの因果効果を測った値ではない。
次の設計検証ではTatoebaの管理ownerを原著者と同一視せず、旧sourceの著者関係を保った比較が必要。
今回の5条件は事後の原因調査に限定し、除外復帰・採用・split更新は0。追加診断は141.634秒だった。

## 改善の優先順と検証コスト

| 優先 | 次の改善 | 期待する効果 | 検証コスト・採用条件 |
|---|---|---|---|
| P0 #31/#35 | whole-rubyから語・句全体の読みと入力範囲を確定できる証拠を設計する | 辞書やrubyの部分文字列を正解とする誤りを減らす。改善幅は未測定 | 今回100文・312位置を使う仕様検証、追加fit0。文脈・意味・表記意図まで未認証の例をGoldにしない |
| P0 #32/#35 | 原著者、owner、翻訳元、実際に消費する文の関係を分けた分割契約を先に固定する | 無関係な文の一括排除と見落としを区別し、新規評価の実効容量を測る | このpilotは設計用に消費済み。全履歴照合は今回約226秒。ルールを凍結して別の未使用枠で検証し、旧除外を戻さない |
| P1 #35/#34 | 上記条件を満たす新規研究評価と別calibrationを確保する | 救済と破壊を識別するgateを独立に検証できるようにする | 100文pilotの通過44注釈は品質保証でも必要標本数でもない。Gold品質条件と0.25%の95%安全評価を満たす設計を先行 |
| P2 #33 | 品質・分割・評価が成立後、同予算で学習変更を比較する | #59で確認した過剰修正の原因とデータ品質を改善につなげる | 今回の学習0。係数・gateをこの100文や旧devで調整しない。期待Accuracyを先に捏造しない |

未選択のexportはbyte取得・metadata走査のみであり、本文を解釈していない。
それだけで独立Testとして使えるとは宣言せず、source lineageと今回の閲覧履歴を含めて分離を検証する。
独立Goldの点推定99.5%以上・Wilson下限99.0%以上・final valid3,000件以上は未達。
Gate A/Bとリリースは未完了である。

## 再現・検証・実行状態

既存Python 3.13.13環境を使用。依存追加0。取得前plan、本文閲覧前selection、隔離前history bindingを別commitで固定。
原ファイルが保存された未使用checkoutで、`PYTHONPATH=src`と所有するTEMPを設定して各stageを実行する。
実行済みprivate rootに同じ処理を再実行するとwrite-once予約で停止する。過去receiptは消さない。

```text
python research/issue-35-source-pilot/stage_owner.py acquire acquire_dated_exports.py 240 --plan-commit 98c74d4eb51c9a479101503c6a08907400601cdc
python research/issue-35-source-pilot/stage_owner.py metadata select_metadata_pilot.py 180 --plan-commit 98c74d4eb51c9a479101503c6a08907400601cdc
python research/issue-35-source-pilot/stage_owner.py alignment audit_selected.py 180 --selection-commit c7626f1c9345fc7e2d5208f276f9f0e4d548921c --implementation-commit c7626f1c9345fc7e2d5208f276f9f0e4d548921c
python research/issue-35-source-pilot/stage_owner.py isolation isolate_pilot.py 1200 --binding-commit 5b0fc5221dec3056207718f55acf80b74f41223d
python research/issue-35-source-pilot/stage_owner.py verify verify_pilot.py 420
python research/issue-35-source-pilot/stage_owner.py relation-diagnostic diagnose_relations.py 900 --implementation-commit 9f51f787409c417ec30c52ff1c40be8b81a21629
python research/issue-35-source-pilot/stage_owner.py full-tests-r2 check_pilot.py 900 --result full-unit-tests-r2.json
python research/issue-35-source-pilot/publish_pilot.py
```

全701テスト成功、失敗・skip0。うち新規25件はexact span、escape、null、文字数/展開上限、
不正markup、原文対応と意味正解の区別、conditional HTTP、429/403、取得長不一致と部分取得を検査する。
別式で全metadataから100 IDを再選択し、別regexで312位置を再構成、2文内3空読み・全隔離件数を再計数した。
旧16artifactと25学習bindingはhash不変。直前比較の10 checkpointもhash不変。
学習・評価を再実行せず確認した。
Python 15ファイルの構文compileと未使用import検査も通過。所有runner/worker残存0、
今回の専用tempは削除済み。再現用のprivate artifactは
`data/generated/issue-35-source-pilot-v1/`、検証履歴は
`.codex/goal-loop/issue-35-source-pilot/` に保持する。
未マージのbranch `issue-35-external-source-pilot-v1` は復旧用に保持し、ユーザーの既存差分は変更しない。

## IRVと責務

**A. 実際の範囲:** sourceの配布契約、metadata抽出、exact ruby parser、履歴隔離、集計が対象。
公開契約は`src/sakura_rerank/data/tatoeba_source.py`、2つの`test_tatoeba_*`、このREADME。
研究stageと3bindingがwrite-onceの状態遷移を所有し、既存graphとデータ認証APIを利用する。
source原文は新しいignored rootのみが所有する。

**B. 拡大:** 84文の履歴接続の理由を確認するため、既存relation contractまで調査を拡張した。
全既知履歴を用いる必要があり、旧研究のbinding chainも認証する。
追加の関係除去診断は結果閲覧後の原因調査で、採用条件・分割・閾値を選ぶ実験ではない。

**C. 構造:** 新しい標準ライブラリのみのsource decoderをdata層に追加した。
研究コードから既存隔離APIへの依存はあるが、既存training/Gold/production API、状態所有者、semantic contractは変更していない。
ネットワークの終端はacquisition/stage owner、全100枠の終端はaudit、隔離結果はsidecarが所有する。

**D. 次回:** 同じ形式のsourceでは公式書式とescape/rubyの実装を再調査せず、parserと契約テストから開始できる。
新しいsource rights・日時・来歴と全履歴bindingは毎回必要。履歴を旧研究chainから構築する費用は残る。
将来の検証済みmetadata snapshot APIで再構築を減らせるが、今回に無関係な大規模refactorはしていない。
