# #49: 原注釈から始める訓練データ採取の検証

2026-11-05 / Parent #1 / Related #31, #32, #33, #35, #48

**原文の読みと範囲を先に保存する採取器を実装し、546作品を検証した。再学習に進める容量・品質条件は成立していない。** 原ルビ132,729枠から仮候補101,625件を作れたが、全出典との隔離を通過したのは1,741件、従来の候補条件まで満たすのは693件だった。4独立出典の対比は0組。新fit・モデル推論・最終Test利用・Gold認証は0。採用モデルの記録値90.72%は更新していない。

量の不足には二つの異なる理由がある。全作品の本文を照合すると、短文一致を含む推移的な関係が作品・著者を大きな成分へ結びつけた。また、辞書一致で事前選択しない原ルビ対象では、原表記が候補にない場合が多かった。後者はルビ範囲とIME入力単位の未検証性を含むため、全件を変換器の誤りとは呼ばない。

## 仮説と固定した条件

[採取plan](plan-v1.json)を`04fe8fc`、実装を`7179dcc`で固定した。#48で認証済みの青空文庫訓練用546作品だけを使い、新規作品や既露出の評価語・誤り一覧を追加していない。元zip、取得receipt、decoded bytes、旧cleaner、文分割をhash認証する。旧抽出器・元データ・既存モデルは不変。

対象は原ルビのbase全体1..32文字、読みは原注釈全体2..32文字。読み比較の全角片仮名→平仮名写像以外は変更せず、原読みも保存する。部分ルビから読みを割り当てず、旧仮名・長音・表記の正規化をしない。入力は同じ段落の直前8..64文字で、実セッションの記録ではなく合成source prefixと明示する。意味・表記意図・IME境界を自動認証せず、全行を`training_eligible=false`、`independent_gold_eligible=false`で保存する。

元cleanerが保持した164,540段落の全文をsource coverageに含める。対象がない文も含み、512文字超の文はsource-onlyの512文字window・stride256にする。これらから訓練対象は作らない。元cleanerが注記/外字のため隔離した12,765行は保持本文に含まれず、捨てた本文まで監査済みとは主張しない。source-only nodeに偽のinput hashを付けない。

分離には既存の同記事/作品、著者、段落、文shingleのJaccard>=0.8、実際の左文脈+読みの一致と全推移的関係を使う。従来500,000件のadapterを変更せず、同じcoreが既に持つ上限1,000,000件の別adapterを追加した。小規模fixtureでは旧adapterと除外・componentが完全一致する。

Sakura Inputは開始時HEAD `3aa36b991329d9a7e924950a5d356db3d4f28f35`、別作業の未commit変更あり。終了確認時は`b78a8f9ab3a3254fd5431664947a41320f58db0d`でcleanだった。どちらの作業中checkoutも今回の挙動根拠にしていない。別に固定された研究用converter（SHA-256 `3c12f1f603413a597e658a11df0148ca43354299addc9551a2fcf1f4daea9977`）と辞書を使った。production側の変更は行っていない。

## 全件の終端と出典分離

| 原ルビ132,729枠の第一終端 | 件数 |
|---|---:|
| 仮候補として抽出 | 101,625 |
| 読みの文字数が範囲外 | 15,273 |
| 左文脈が8文字未満 | 14,468 |
| 対象を含む文が512文字超 | 768 |
| 非音韻/編集注釈等 | 518 |
| base構文未解決 | 77 |

第一終端は排他的で全132,729枠を覆う。範囲外・文境界など重複するフラグは[抽出集計](../../reports/issue-49-annotation-preparation-v1.json)に別保存した。101,625件の原位置、注釈、原文の左文脈を別の位置計算で照合し、全件一致した。暗黙の漢字base97,411件、明示base4,214件。

履歴218,189、元訓練164,320、全保持本文のcoverage349,466、新仮候補101,625、合計**833,600 node**を同時に照合した。

| 分離結果 | 件数 |
|---|---:|
| 新仮候補の通過 | 1,741 |
| 新仮候補の履歴関係による除外 | 99,884 |
| 元訓練164,320件の新監査での除外 | 55,787 |
| うち前段で許容された訓練行との追加のつながり | 53,969 |
| 全source component / 最大成分node | 115,953 / 535,344 |

旧成果物の割当を修正した値ではなく、新たな監査結果である。従来の1,818除外も維持。逆順833,600 nodeの再実行で除外・component・集計・保持行が完全一致した。候補近重複の概念的pair数224,532,832と、実際のsignature比較453,223は別指標であり、全組合せを走査していない。

## 短文一致の診断と限界

大量除外を見た後、[読取り専用診断plan](relation-audit-plan-v1.json)を`3b75b80`で追加固定した。除外を戻す規則や文字数の閾値は導入していない。

履歴218,189件の内訳は、旧六世代のsplit未保持115,251、既知の旧train12,516、dev1,788、final-holdout3,576、予約済みgrowth評価55,418、既露出KWDLC研究評価29,640。旧frozenファイルはIDとsplit markerだけ読み、Gold・候補をdecodeしない。旧trainやsplit不明まで含むため、履歴一致をすべて評価漏れと呼ばない。

| 履歴と新coverageの直接一致 | 段落hash | 同一の正規化文shingle集合 |
|---|---:|---:|
| 一致group | 7 | 31 |
| 元文字列4文字以下 | 2 | 13 |
| 元文字列5..9文字 | 5 | 15 |
| 元文字列10..19文字 | 0 | 3 |
| 元文字列20文字以上 | 0 | 0 |
| 記号/句読点/空白だけ | 0 | 0 |
| 接続する青空作品数 | 36 | 110 |
| 直接接触する訓練component数 | 1 | 1 |

これはJaccard>=0.8の全edgeではなく、完全一致の部分集合。31組のうちgrowth評価に接する22組、KWDLC研究評価6組、旧train1組、split不明3組は非排他的である。段落7組にもgrowth評価・KWDLC研究評価との一致がある。したがって「訓練履歴を誤って除外しただけ」「短文を全部無視すればよい」とは判断できない。

追加53,969件はすべて青空行。新監査後に残る旧青空は4,844、Wikipediaは103,689。最大の除外訓練成分には旧55,746行と新99,884行が入り、追加53,969行もそこにある。ただし一つのedgeへの因果帰属や、すべての行の実際の評価汚染を示す値ではない。全直接一致のmember集合と全訓練componentの件数を別集計で検算した。

## 実converterでの候補確認

隔離済み1,741対象、42作品、33著者/成分、1,215読みを固定した。同一converter/dictionaryの旧475読みを認証して再利用し、新740要求を[manifest](../../manifests/annotation-first-forward-v1.json)と`c715fa1`で固定後に実行した。並列2、各30秒、全体900秒、再試行なし。新740件すべて完了、失敗/未実行0。対象1,741件すべてのsnapshotを再認証し、別のsurface集計で一致した。

| 原表記の存在 | 件数 / 1,741 | 割合 |
|---|---:|---:|
| Top-1 | 330 | 18.9546% |
| Top-5 | 659 | 37.8518% |
| Top-6 | 693 | 39.8047% |
| Top-10 | 724 | 41.5853% |
| Top-32 | 741 | 42.5617% |
| Top-32に原表記なし | 1,000 | 57.4383% |

Top-6に一意な対象があり、2候補以上・system dictionary経路・対象/候補切詰めなしを満たすのは693件。候補がない/Top-6非一意という終端は1,048件で、全件分母に残る。複数表記が得られる読みは6群だが、2表記×2文脈×4独立source componentの証拠は0組だった。

選択器とは別に各表記のcomponent数も数えた。6群すべてで「2個以上のcomponentを持つ表記が2種類ある」という必要条件が成立せず、今回の0組が貪欲選択の取り逃しによるものではないことを確認した。

**この表はGold精度でも、モデル精度でもない。** 旧#48のTop-32 162,500/162,502は辞書surfaceで事前選択した別母集団で、今回との差をモデルの悪化と解釈できない。原ルビbaseが活用語の漢字部分だけを覆う場合など、注釈として正しくてもIMEの全入力単位を表さない可能性が残る。送り仮名の追加や歴史的仮名遣いの変換を推測で行っていない。未検証の正解性を前提に95%の精度保証は算出しない。

## 改善の優先順位と費用

| 優先・所有Issue | 次に解決すること | 期待する効果と条件 | 検証コスト |
|---|---|---|---|
| P1 #32 / #35 | 作品/著者の分離単位と、短い文の一致を含む重複証拠を区別して再設計可能か検証する | 全文監査を維持しながら、何が実際の再利用禁止の根拠か説明できるようにする。既知評価との一致を自動解除しない。現行規則と全除外を保存し、新規則は実行前固定 | 今回の全closure126.1秒、逆順検証約103秒。まず既存833,600 nodeのmetadataとedge証拠で検証、モデルfit0 |
| P1 #31 / #49 | 原ルビのbase・読みとIME全入力単位、旧仮名/保護表記を別軸で診断する | 候補欠落1,000件を入力単位の不整合・表記意図・真の候補不足へ切り分ける。未来文字からの読み補完やAI正解認証は行わない | 現行1,741件のsource/snapshotを再利用。全546作品の抽出88.6秒、今回の新740候補55.9秒が実測目安。追加要求は別に予約 |
| P2 #49 / #33 | 上記の仕様が確立した訓練候補から、同じ出典比・件数の対比比較を作る | 例数の増量を学習信号の増加へ結びつける。精度改善幅は未測定。現在の693件で25,000青空行の固定quotaを埋めない | 成立した容量を測った後、未使用研究評価・同一50,000行・同じfit予算を別登録。現時点のfit費用は未見積 |

最終Testを使った規則選択はしない。人手がない現状をAI認証の捏造で埋めず、研究用弱教師と独立Goldを分ける。安全性0.25%、Gold点推定99.5%/Wilson下限99.0%/最終valid3,000件、Gate A/B、最終Test一回限りの条件は不変。

## 再現・検証・保存

事前条件: 記録されたcommitとhashの原artifactが手元に必要。Python 3.13.13の既存研究環境を読み取り利用し、依存追加なし。新規rootでの初回コマンドは以下。既存rootはwrite-onceなので消去・上書きしない。

```text
PYTHONPATH=src python research/issue-49-annotation-first/prepare_annotations.py prepare
PYTHONPATH=src python research/issue-49-annotation-first/prepare_annotations.py isolate
PYTHONPATH=src python research/issue-49-annotation-first/verify_annotations.py prepare
PYTHONPATH=src python research/issue-49-annotation-first/verify_annotations.py isolate
PYTHONPATH=src python research/issue-49-annotation-first/forward_annotations.py prepare
PYTHONPATH=src python research/issue-49-annotation-first/forward_annotations.py execute --binding-commit c715fa1a6006208effcdaaac50395cb7e68c5b18
PYTHONPATH=src python research/issue-49-annotation-first/verify_forward.py
PYTHONPATH=src python research/issue-49-annotation-first/audit_relations.py
PYTHONPATH=src python research/issue-49-annotation-first/verify_relations.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

実行済みrootでは`verify_*`を使う。新規再生成は実装/plan/bindingの記録commitを再現し、保存済み出力rootと混同しない。nativeの途中失敗後に同じ予約を再利用しない。

| Verify | Expect / 今回の検証結果 |
|---|---|
| 全作品再抽出と独立の元位置/注釈照合 | 132,729終端、101,625位置、349,466 coverage、per-work/全体hash一致 |
| 全833,600 nodeを逆順で再計算 | 除外・component・保持行・旧行の追加関係が一致 |
| 認証済み実snapshotの別surface再計数 | 1,215読み・1,741行、全Top-k/eligible/失敗分母一致 |
| tuple-keyによる逆順の直接一致再集計 | 段落7+文signature31の全member集合、旧/新訓練component件数一致 |
| 全回帰 / static / 不変性 / cleanup | 590 tests成功、skip0。12 Python filesのASTとimport利用を確認。旧16+25 artifact不変、所有runner0、専用tmp削除済み |

集計と証拠：[抽出](../../reports/issue-49-annotation-preparation-v1.json)、[抽出検証](../../reports/issue-49-annotation-preparation-verification-v1.json)、[分離](../../reports/issue-49-annotation-isolation-v1.json)、[分離検証](../../reports/issue-49-annotation-isolation-verification-v1.json)、[候補](../../reports/issue-49-annotation-candidates-v1.json)、[候補検証](../../reports/issue-49-annotation-candidate-verification-v1.json)、[関係診断](../../reports/issue-49-annotation-relations-v1.json)、[関係検算](../../reports/issue-49-annotation-relation-verification-v1.json)、[完了チェック](../../reports/issue-49-checks-v1.json)、[後片付け](../../reports/issue-49-cleanup-v1.json)。モデルを変更していないので、CPU10,000回/ONNX parityの再測定は対象外。

raw原文/ID/位置/読み/候補/実行logは再現用のignored `data/generated/issue-49-annotation-first-v1/`へ保持する。Gitにはcode、固定plan、hash/件数のaggregateだけを収録する。専用`~/tmp/issue49-annotation-20261105/`は削除し、未マージの研究branchは回復・レビュー用に保持する。

## IRV・検証済みの学び

A. 実際の責務は原注釈の全base抽出、source-only coverageの隔離、candidate receiptの再利用/実行、関係診断、検証・保存。入口はこのREADME、純粋処理2 modules、研究scripts7、関連tests3、固定plan2とnative binding。既存parser/splitter/native runnerは契約を再利用し、全回帰590件を実行した。

B. 全保持本文の追加でnodeが従来adapter上限を超えたため、coreの既存1,000,000件上限を確認し、旧adapterを変えず別の境界を作った。大量除外後は元の歴史組立とID/split markerまで調査を拡大した。短文一致から全作品へつながることと、全履歴が評価ではないことを分けるために必要だった。モデル内部・production変更には拡大していない。

C. `annotation_first.py`が抽出終端とsource evidence、`annotation_isolation.py`が閉包の上限/validationを所有する。共通scriptは既存artifact認証、stage scriptは新write-once成果物とnative実行の終端、検証scriptは独立再計数を所有する。元ラベル/元分割の所有権は移さない。既存のprivate splitter coreへの意味的依存はparity契約で監視する。production/runtimeの依存変更は0。

D. 次のIssueは原zipや旧訓練器の内部を再探索せず、保存した全base・終端・source node・候補receipt・直接一致witnessを入口にできる。新たに理解すべきなのは、原注釈≠IME単位≠独立Goldという区別と、source分離単位と短文の重複証拠の関係。全文coverageは従来の対象行だけの監査より新たな接続を見つけるが、接続した全行を誤ラベル/実評価漏れとは断定できない。これは今回の再計算で確認した学びであり、未検証の除外緩和策をmemory規則へ昇格しない。
