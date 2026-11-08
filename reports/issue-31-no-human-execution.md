# Issue #31: 人手待ちを外した実行方針

ユーザーから人手を確保できない旨が示されたため、独立した人間A/B/Cの割当を現在の実行条件から外す。担当者の確保をユーザーの次作業にはしない。人手用policy・packet・初期roundは未使用の履歴として保存し、AIや機械判定を投入して人手実績へ置き換えない。

## 現在の実行対象

1. 全1,000件を対象に、別保存の抽出source spanと凍結変換snapshotを機械照合する。旧807/193分類による選別はしない。
2. 機械的に確認できる整合性と、読み・意味・入力単位・表記意図のAI判断を区別して記録する。AI判断は参考ラベルであり独立Goldではない。
3. 人手なしで検証できない点はunknownとして残す。曖昧例を削除して正解率を上げたことにしない。原データ・モデル・0.25%基準を維持する。

## 検証rubric

| Verify | Expect |
| --- | --- |
| `pilot_evidence_audit`を異なる出力先に2回実行し全file hashを照合 | 全1,000件、結果一致、欠落・重複なし |
| selected-readerの合成契約テスト | 対象外・holdout本文をJSON解析しない。hash/同一性/coverage不一致を拒否 |
| source/frozen/packet対比と差分テスト | exactとNFKCのみ一致を区別し、不一致を隠さない |
| 全unit tests・compile・旧12artifact hash確認 | 既存契約の回帰なし、元データ・モデル不変 |
| 実行後のprocess/temp確認 | task runner終了、一時file削除、継続用evidenceだけ保持 |

## 実行結果

**人手待ちを現在の実行条件から外し、全1,000件の機械的な根拠照合を完了した。** 実行モードは [manifest](../manifests/issue-31-no-human-execution-v1.json) に記録した。旧人手用policy・packet・空の初期roundは履歴として不変保存する。人手実績は0件のまま。

| 検証項目 | 結果 |
| --- | ---: |
| 抽出source spanの対象表記と凍結goldの完全一致 | 1,000 / 1,000 |
| 抽出時左文脈とpilot左文脈の一致 | 1,000 / 1,000 |
| source / frozen / packetの出典対応 | 1,000 / 1,000 |
| frozen row hash・候補集合・gold分割のpacket対応 | 1,000 / 1,000 |
| 全読み・全表記を覆う保存済み候補経路の構造検査 | 31,503候補、1,000入力分 |

今回はNFKC正規化のみで一致する例0、対象表記の不一致0。正規化のみ一致するケースを完全一致へ吸収しない検査も合成テストで確認した。集計は [evidence JSON](issue-31-machine-evidence-v1.json)、検証記録は [verification JSON](issue-31-machine-evidence-verification-v1.json) に保存。

## 確認できた範囲と残る不確実性

別保存の `source-spans-a.jsonl` が存在し、そのSHA-256はv5の検証済みmanifestと一致した。ファイル全体98,452,202 bytes・24,064行をhash確認し、対象train 1,000件だけをJSON解析した。凍結データ423,416,617 bytes・17,880行もhash確認し、holdout 3,576行を解析前に除外、JSON解析は対象train 1,000件だけに限定した。右/未来文脈は取得していない。

これは同じ抽出処理に由来する**抽出済みsource spanと変換データの整合性**である。Wikipediaの未加工原文に対する忠実性、抽出器自体の正しさ、文脈に合う読み、意図された表記、実際のIME入力単位を独立に認証したものではない。既存のhuman packetへ原文証拠を追加したわけでもないため、凍結human方針の原文軸unverifiableは変更しない。

候補経路の検査は、保存されたsnapshotのUTF-8 byte境界・連続範囲・全読み/全表記の被覆・辞書由来gold契約を再検証したもの。変換器を今回新たに実行した結果ではなく、辞書の読みが文脈に適合するかの証明でもない。

したがって、今回の範囲では転記・対応・構造の不整合は見つからなかったが、先の193件で見つけた意味・表記・境界の疑義は解消していない。元データのラベルは一切変更せず、正解率や品質信頼区間をこの一致率から作らない。

## 人手を前提にしない継続方針

- **機械証拠を優先する:** 全件の出典対応、候補・経路、重複・リーク、再現性を確認し、確認済み範囲を限定して報告する。今回はそのうちsource/packet/経路の照合を完了した。
- **AIの役割を明記する:** 言語上の疑義の整理と仮説作成を行い、理由・方針・過去判定への参照を別台帳に保持する。同じ助手の複数回判定を独立レビューや一致率の証明にしない。既存の1,000件AI判断と193件triageを保持する。
- **正解を定義できる制御課題を設計する:** 入力意図が予め明示される限定課題で、全語入力と部分確定を分け、実変換のforward確認を条件にする。これは一般的な日本語全体のGold品質とは別の検証。最初は50課題程度の設計から始め、対象・期待出力・失敗条件を実験前に固定する案とする。生成/変換の変更はまだ実施していない。
- **未保証を残す:** 未加工原文の忠実性や意味・表記意図を独立に裏付けられないケースはunknownとして保持する。人手不要になったことを理由に、品質目標や0.25%安全基準を緩和しない。独立Test・モデル改善・学習再開は元の承認範囲に従う。

人手なしの進行と、独立Goldを認証済みと呼ぶことを分ける。担当者の確保をユーザーへ返さず、実行可能な分析・検証を進める。

## 再現と検証

`PYTHONPATH=src` を設定し、新しい出力先を指定する。既存出力は上書きしない。

```powershell
python -X utf8 -m sakura_rerank.data.pilot_evidence_audit --packet data/generated/issue-31-gold-pilot-v1 --source-spans data/generated/issue15-v5-slot120/source-spans-a.jsonl --source-manifest manifests/jawiki-tier-a-source-spans-v5-slot120-verified.json --frozen data/generated/issue15-v5-slot120/frozen-split.jsonl --output data/generated/issue-31-machine-evidence-v1
python -X utf8 -m unittest discover -s tests -p test_pilot_evidence_audit.py -v
python -X utf8 -m unittest discover -s tests -v
```

2回の出力はreport・個票ともbyte一致し、別Counter計算で1,000件全件と各checkを照合。全316テストで失敗0、既存optional PyTorch 5件skip、新規7件全成功。300秒timeoutで実行し、compile/diff checkも成功した。旧12artifact、人手方針、空の初期roundのhash不変を確認。終了時にtask所有のPython/test/training/ORT runnerは残っていなかった。既存インストールのSakura Input workerは維持した。

Sakura Input HEADは `d586fae572d32aa76512994dca616dadef2899b1`。旧凍結抽出版は `0e9dca182b0319988f49a89c28b9e9f602ebe70f`。保存する個票と集計はGit対象外の `data/generated/issue-31-machine-evidence-v1/`。`~/tmp/gold-no-human-20261104/` の複製・検証script・test logは削除する。Gitには本文やcase IDを含めず集計とhashのみを保存。

## IRV記録

- **A. 範囲:** 既存packet/binding、source-span manifest、source-span/record検証契約、frozen reader、対応する合成fixture。新たな責任は選択した1,000件の機械証拠照合と7契約テスト。
- **B. 拡大理由:** packetにはない抽出時source spanを探し、原gold自身との循環照合を避けるため生成前段の契約まで調査した。モデル内部・訓練・本番改修には広げていない。
- **C. 状態所有:** `pilot_evidence_audit` はread-onlyの照合と新規evidence出力を所有。既存のsource-span/record validatorと不変directory公開を利用し、人手eventやラベル適用へ接続しない。
- **D. 次回:** この機械照合のコマンド・manifest・reportから始められる。意味の妥当性や入力単位は、この構造検査とは別の根拠が必要であり省略できない。
