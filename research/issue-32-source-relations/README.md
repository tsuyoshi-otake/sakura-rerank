# #32: 本文の一致が作品全体の除外へ伝わる経路

2026-11-05 / Parent #1 / Related #31, #35, #49

**同じ作品・著者・実入力の関係だけでは履歴接続は0件だが、本文一致を加えると新候補99,884件が明示的な評価側へつながる。** 前回の直接一致38組だけを診断上取り除いても、新候補99,884件と追加接続した旧訓練53,969件はすべて接続したままだった。短文の例外リストやJaccard閾値変更だけで解決するという見立ては支持されない。

今回の成果は、固定された全母集団について接続理由を追跡・検算できる実装と証拠である。除外復帰・ラベル採用・新fit・モデル推論・最終Test利用は0。採用モデルの記録値90.72%は更新していない。Gold品質、安全性0.25%、独立評価とリリースは未完了で、スレッドの「リリースまで」の目標は継続する。

## 固定した問い・責務・入力

[前段#49](../issue-49-annotation-first/README.md)の833,600 node（履歴218,189、旧訓練164,320、全保持本文coverage349,466、新仮候補101,625）をそのまま使用した。既存の原文・候補・model・splitは書き換えない。historyはhashとroleを扱い、評価Gold/候補/誤り一覧をdecodeしない。読みや候補文字列をreport/logへ出さない。

所有責務は、既存分離グラフの接続証拠と固定した診断条件の計算。作品/article、著者/template、実際のinput hashをまとめた単位を本文関係と区別する。これは現行の除外規則を置換するAPIではない。全グラフのcomponent hashと除外は#49に一致しなければ停止する。

[plan v1](plan-v1.json)を`fb3b558`、実装を`ce6dbf0`で固定。入力・core・旧reportのhash、node最大1,000,000、代表接続最大4,000,000、各stage1,200秒、並列1を記録した。Sakura Inputは`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`、cleanを確認してmanifestへ記録したが、今回その挙動やproduction codeは使っていない。依存追加・外部データ取得・native probeも0。

## 検算で見つけた診断処理の欠陥と修正

v1の全グラフは#49と一致した。ただし合成3-nodeの検算で、同じ文signatureの2件と、その両方にJaccard=.8で一致する1件について、完全一致edgeだけを外すと一方の正当な類似文経路が失われた。1本の代表near edgeは、完全一致group内の接続を前提にしていたためである。

初回plan・実装・出力を保存し、[plan v2](plan-v2.json)を`61fdeeb`で追加固定した。異なるsignature間の一致ごとに、両側の全memberを結ぶ二部グラフのspanning treeを保存する方式へ変更し、`e502f36`で実装を固定した。n×mの全pair列挙ではなくn+m−1本なので、元の4,000,000上限内で各診断条件の連結性を保てる。元のJaccard探索・.8閾値・除外規則・母集団は変えていない。

修正前に失敗した契約が修正後に成功し、各signature pairの証拠が全memberを覆うことも実データで検証した。v1の全除外は有効な再現結果だが、v1の条件変更比較と経路距離を最終結果として使わない。以後の数値はv2。

## 全接続と固定した6条件

全833,600 nodeから**1,990,445本**の型付き代表接続を保存した。作品712,876、著者528,894、実入力5,164、段落463,073、同一文signature278,532、異なる類似signature間1,906本。最後の1,906本は872 signature pairを覆う。概念上の近重複record pair224,532,832を全列挙せず、実際のsignature比較は既存coreと同じ453,223回。

以下は履歴へ接続する行数であり、切断した行を学習に採用できるという表ではない。全条件で全nodeと全historical roleを残した。

| 診断条件 | 旧訓練164,320行 | うち#49で追加接続53,969行 | 新候補101,625行 |
|---|---:|---:|---:|
| 作品・著者・実入力だけ | 0 | 0 | 0 |
| 上記＋段落一致 | 46,268 | 46,180 | 93,793 |
| 上記＋同一文signature | 55,669 | 53,851 | 99,881 |
| 上記＋同一/類似文signature | 55,787 | 53,969 | 99,884 |
| 現行の全関係 | 55,787 | 53,969 | 99,884 |
| 全関係から#49の直接一致38組だけを除く | 54,955 | 53,969 | 99,884 |

38組は、履歴と新coverageが直接共有した段落7組と同一文signature31組。診断では該当369本の代表edgeを除くが、すべての正当な異signature類似関係を残す。追加接続53,969件と新候補99,884件には別経路があり、これだけを例外扱いしても解決しない。旧832件の診断上の切断も、採用許可や汚染なしの証明ではない。

また、同一文signatureだけでも新候補99,881件がつながり、類似文関係が追加するのは3件だった。全旧訓練の差も118件。類似度の閾値を調整することを最優先にはしない。

全グラフは115,953成分、最大535,344 node。全265,945訓練行のcomponent hashと155,671行の除外理由が#49と完全一致した。元の旧train/dev/holdoutの割当やlabelは変更していない。

## 評価側へ至る経路と解釈の限界

履歴roleは前段と同じく、旧六世代split不明115,251、旧train12,516、dev1,788、final-holdout3,576、予約growth評価55,418、既露出KWDLC研究評価29,640。未知roleや旧trainをグラフから取り除かず、「全履歴を起点」と「明示的な評価だけを起点」の2通りの経路証明を作った。

**全除外155,671行には、明示的な評価へ至る経路がある。** 旧trainやsplit不明を起点から外すだけでは、今回の除外件数は減らない。これは現行の関係定義に基づく接続の証明であり、全行のラベル誤りや、測定されたモデル精度への汚染量を証明するものではない。

| 評価までの本文接続数 | 新候補 | #49で追加接続した旧訓練 |
|---|---:|---:|
| 1 | 81,834 | 33,014 |
| 2 | 18,047 | 20,837 |
| 3 | 3 | 118 |
| 接続なし | 1,741 | 0 |

距離は作品・著者・実入力をまとめた成分間の本文edge数。各訓練例自身の文章が評価例に一致する件数でも、元の全record pairグラフの最短距離でもない。同じ作品/著者にある一つの本文一致から、直接重なっていない別の例へ除外が伝わり得る。経路は一つの証拠であり、唯一の原因ではない。

全到達成分についてparent edgeの合法性、seed role、距離の単調減少、cycleなし、未到達の明示終端を検証した。全履歴側100,056成分、明示評価側11,847成分が到達し、両方について全訓練行の距離・関係種別・選択rootの集計を別計算で再現した。

## 改善案と次に検証する範囲

| 優先 | 改善案 | 期待効果・条件 | 費用の見通し |
|---|---|---|---|
| P1 #32/#35 | 原文の全coverage台帳と、実際に学習へ渡す本文単位を分ける。重複する本文単位とその文脈を隔離した後にも、作品/著者・実入力・残る本文で分離を保証できるか検証する | 短文の長さで一致を無視することなく、未使用本文まで含む作品全体の除外が必要か検証する。現行規則とは別の設計案であり、採用条件・除外・利用範囲を事前登録し、旧閉包を保存する。回収行数だけで選択しない | 今回の全構築144.4秒、全検算89.0秒が目安。次は既存metadataと原位置を使うdry-run、fit0。回収量は未測定 |
| P1 #31/#49 | 原注釈baseとIMEの全入力単位、読み、表記意図を分ける | 分離後に残った候補だけでも正解性は未認証。重複を解消しても、そのままGoldや訓練許可にはしない | 固定済み1,741対象・1,215読みのsource/snapshotを再利用。追加native要求は別予約 |
| P2 #33 | 量・品質・分離が確立してから同予算の順位学習比較 | データ増強の効果をモデル改善へ結びつける。独立研究評価、同じ出典比/件数/更新予算を事前固定 | 条件未成立のためfit開始0、精度改善幅とfit費用は未測定 |

次の分離案では、隔離した本文が左文脈、候補教師、body pretraining、cache等から再流入しないことが必要。作品/著者のcross-split、実同入力、評価例の再利用、final Testを使った規則選択を許可しない。原文を書き換えずsidecarで利用範囲を追跡し、未解決の範囲は採用しない。現行規則の単なる閾値緩和として実装しない。

安全性0.25%、Gold点推定99.5%/Wilson下限99.0%/最終valid3,000件、最終Test一回限り、Gate A/Bは不変。人手なしを独立Goldの偽装で埋めず、リリース条件は残る。

## 再現と検証

既存研究環境Python 3.13.13を読取り利用し、依存追加なし。固定sourceの所有・ライセンス・取得証拠は#49→#48→#33のhash chainを認証する。新たな外部データは0。初回は記録された実装/plan commit、入力artifact、未使用の出力rootが必要。実行済みrootは消去・上書きせずverifierを使う。

```text
PYTHONPATH=src python research/issue-32-source-relations/run_audit.py
PYTHONPATH=src python research/issue-32-source-relations/verify_audit.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

| Verify | Expect / 実測 |
|---|---|
| 既存coreとのfixture parity、全component hash比較 | 全833,600 nodeと265,945訓練所属・155,671除外が一致 |
| 小規模全pair oracle、型付きedgeの全件照合 | 1,990,445合法edge、872 near signature pairの全memberと接続を検証。概念pair224,532,832一致 |
| 逆順の独立group構築による6条件の再計算 | 全集計・保存component所属が一致 |
| 全parentとseed、距離、未到達終端の検算 | 両経路証明がacyclic、全訓練分母・集計が一致 |
| 回帰、static、artifact不変性、cleanup | 599 tests成功、skip0。5 Python filesのAST/import確認、旧16+25 artifact不変。所有runner0、専用tmp削除済み |

結果：[v2集計](../../reports/issue-32-source-relations-v2.json)、[全検算](../../reports/issue-32-source-relations-verification-v2.json)、[完了チェック](../../reports/issue-32-source-relations-checks-v2.json)、[後片付け](../../reports/issue-32-source-relations-cleanup-v2.json)。[v1集計](../../reports/issue-32-source-relations-v1.json)は初回証拠として保存し、上記の限界を適用する。モデル未変更のためONNX parity/CPU10,000回の再測定は対象外。

再現用のignored `data/generated/issue-32-source-relations-v1/` と `data/generated/issue-32-source-relations-v2/` を保持する。edge/parent binaryは候補や原文を含まず、node位置は固定stable-ID順・hashで元metadataへ戻せる。専用 `~/tmp/issue32-relations-20261105/` は削除済み。未マージbranch `issue-32-source-relations-v1` と `.codex/goal-loop/issue-32-source-relations/` はレビュー/継続用に保持する。

## IRVと検証済みの学び

A. 必要だった範囲はデータ契約、前段#49の母集団/roleと原位置、既存splitterのgroup/near join契約、研究用edge/path module、認証/実行/検算scripts3、test file1、plan2。全回帰599件。学習器やproductionには変更しない。

B. 接続数だけで原因を説明できないため、型付き証拠とsource/input単位の経路まで調査を拡大した。検算で条件変更時の圧縮前提が壊れると分かったため、near pairの完全二部関係を保存する証拠形式へ修正した。分類や閾値の試行錯誤には拡大していない。

C. `relation_witnesses.py`がグラフ証拠・診断labels・経路の終端を所有する。研究scriptsは認証、固定条件、write-once成果物、別検算を所有する。既存splitter・annotation isolation・元split/labelの所有権と意味は不変。private coreへの依存は既存探索を変えず再利用するためで、元hash、fixture parity、全pair検算を契約とした。

D. 次の分離Issueは、元学習器や全過去実験を再読せず、固定node/edge/parent証拠から本文一致と作品/著者単位の関係を調べられる。新たに必要なのは、取得済み全sourceと実際に消費する本文・文脈の区別を契約化すること。検証済みの学びは、**全グラフでのparityだけでは関係種別を除く比較の正しさを証明できない**こと。削除対象でない関係を保つ証拠を各条件で確認する必要がある。今回の単位は2反復で検証通過、スレッド全体のリリースは未完了。
