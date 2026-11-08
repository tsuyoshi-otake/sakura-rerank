# #49: 分離済み原注釈の候補存在と対比容量

2026-11-05 / Parent #1 / Related #31, #32, #33, #35

**93,973仮候補の全読みを実変換器のsnapshotと照合し、35,592件が既存の候補条件を満たした。4つの異なる出典componentにまたがる対比は10組を確認した。** 前段#49の候補条件通過693件・対比0組から、次の弱教師実験を具体的に検討できる容量へ進んだ。ただし母集団の利用範囲が異なる比較であり、モデル精度の改善ではない。

全22,636読みを認証し、既存6,207読みを再利用、新16,429読みを取得した。失敗・拒否・未実行0。候補の有無で元の93,973件や原注釈132,729枠を分母から消さない。学習採用・新fit・reranker推論・最終Test・Gold認証は0。採用モデルの記録値90.72%、安全性0.25%、Gate A/Bと独立Goldの条件は不変で、リリース目標は継続する。

## 仮説・固定した対象・責務

[前段#32](../issue-32-consumed-source/README.md)が確認した、許可段落内の原注釈base・読み・直前8–64文字だけを対象にした。取得済み全source、旧除外、旧splitは保存する。異なる読み/表記/文脈の信号が残るかを調べ、辞書で先に対象を選んだ集合の高い候補存在率を外挿しない。

[plan v1](plan-v1.json)を`784bd2da86d6fbcae39b966dcc57939ceb7c7bbb`で固定し、原位置、文字種の隣接、注釈種別、明示的な旧仮名文字、既存のreview flagsを観測した。隣接文字から正解・誤りを判定せず、送り仮名の推測追加、読みの書換え、表記正規化を行わない。原文の右側文字種は監査用metadataであり、モデル入力に渡さない。全件のIME入力単位・意味/用法/表記意図は未認証のまま。

対比は固定の既存selectorを使用する。同じ読みについて異なる原表記2種、それぞれ異なる文脈2件、全体で4つの異なるsource componentを要求する。作品単位の対比は別集計。1読みにつき最大1組、表記type数32までの保守的な選択なので、確認した組数は存在を証明した下限であり、最大容量ではない。表記差も意味差の認証ではない。

現在のSakura Input clean HEADは`bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`として記録したが、そのproduction挙動は使用していない。候補取得は従来のhash認証済み研究exporter・辞書identityを再利用した。新しいsource取得・依存追加・モデル変更は0。

## 失敗を保存した実行変更

初回は計画fileの認証時に停止した。Windowsの`Path.write_text`が末尾LFをCRLFに変え、Gitに固定したbyte列と1 byte違っていた。全input hashは一致し、改行を除くpolicyは同一だった。失敗terminalと元working bytesを保存し、計画をコミット済みbytesへ復元して別の`attempt-02`で再開した。認証を緩めず、初回はデータ処理・native要求0。

次の準備は全93,973入力を照合して完了したが、追加読み16,429が事前上限16,000を429超えたため、計画通り`native_budget_blocked`となった。対象を間引かず、原準備結果を保存した。[plan v2](plan-v2.json)を`9a684fb2c5ac82dea9be1f1db8b6283344ec22e2`で追加固定し、既存exporterの100読みbatch契約を利用した。元の順序と全request byte列を維持し、165batch、並列1、各30秒、全体900秒、再試行0とした。source/label/contrast規則は変えていない。

全request・source profile・identity・codeの[binding](../../manifests/consumed-contrast-forward-v2.json)を`ec477ea1528e022035dbc4576d484af50bad0758`でcommitしてから実行した。過去#33は323batchを87.507秒で処理しており、辞書/process起動を読みごとに繰り返す必要がないと判断した。今回のnative取得は**165batch・42.405秒**、前後の認証・集計込み58.469秒。異なる母集団間の時間比を性能改善倍率とはしない。

既知のbatch拒否ならそのbatch全件を未測定として残して次の固定batchへ進む。予期しない失敗は終端を保存して停止し、後続を未実行にする。成功・失敗とも元の読み集合を変更せず、失敗batchから部分的な認証snapshotを採用しない。これらは合成契約で検証し、今回の実測は全batch成功だった。

## 全件分母の候補存在

| 原注釈の表記が存在する範囲 | 件数 / 93,973 | 割合 |
|---|---:|---:|
| Top-1 | 18,215 | 19.3832% |
| Top-5 | 34,547 | 36.7627% |
| Top-6 | 35,592 | 37.8747% |
| Top-10 | 37,370 | 39.7667% |
| Top-32 | 38,754 | 41.2395% |
| Top-32に原表記なし | 55,219 | 58.7605% |

Top-6に一意の原表記、2候補以上、system dictionary経路、target/候補の長さ条件を満たすのは35,592件。残る58,381件はTop-6の対象条件を満たさない。これは「候補面で弱教師の検討対象になる」条件であり、ラベル採用・IMEでの一意な正解性ではない。

原132,729注釈枠のうち、旧抽出条件で31,104枠、段落隔離で7,652仮候補、今回の候補条件で58,381件が通過しない。残る35,592件を合わせて全枠を説明できる。今回のキャッシュ再利用や取得失敗で消えた対象は0。

この表は原注釈baseに条件付けたsource再現率で、Gold精度でも採用モデル精度でもない。旧devの88.70%や辞書surfaceで事前選択した集合とは分母・課題が違う。Top-32欠落55,219件を、すべて候補生成器の欠陥や誤ラベルと分類していない。原注釈baseと実際の入力単位、読み/表記意図は別に検証する必要がある。

## 量と対比信号を分けた結果

| 指標 | 分離済み全件 | 候補条件通過後 |
|---|---:|---:|
| 行数 | 93,973 | 35,592 |
| 読み種類 | 22,636 | 8,991 |
| 作品 / 著者 / component | 507 / 137 / 42 | 459 / 129 / 38 |
| 複数の原表記を持つ読み | 4,302 | 657 |
| その読みの行数 | 58,858 | 9,038 |
| 4作品で確認した対比 | 1,449組 | 272組 |
| 4componentで確認した対比 | 68組・272行 | 10組・40行 |
| component対比を確認した読みの全行 | 6,166 | 770 |

全保存quartetについて、異なる4 component/文脈、同じ読み、2表記各2行、元対象内のIDであることをselectorとは別に検算した。NFKC/かなの同値警告が立ったcomponent対比は両集合とも0だが、意味の異なる正解を認証したとは扱わない。

候補条件通過集合では、同集合で数えた読みごとの最多表記だけで33,163/35,592行（93.1754%）が一致する。これはin-sampleの記述統計であり、未使用評価でのモデル成績ではない。単一表記の読みは8,334種類なので、単純な増量で文脈識別が強くなるとは限らない。固定selectorの下限10組を「存在する対比の最大数」とも断定しない。

同一の左文脈＋読みの重複は全件で4群・余剰5行、候補条件通過後は0。競合表記はどちらも0だった。ただし観測された矛盾がないことは、日本語としての曖昧性がないことを保証しない。

## 境界観測の意味と限界

全件の注釈は明示base3,926、暗黙の漢字base90,047。候補通過後は明示1,598、暗黙33,994だった。対象の末尾が漢字で直後がひらがなとなる観測は全件84,531、候補通過後31,095件。これは名詞＋助詞にも語幹＋送り仮名にも起こるため、一律に不完全な入力・誤ラベルとして除去できない。

右側の漢字隣接は全件5,043、候補通過後2,667件。明示的な「ゐ/ゑ/ヰ/ヱ」markerは全件8、候補通過後0だが、旧仮名遣い全体を検出したことにはならない。原文字列や候補をreport/logへ載せず、分類件数だけを公開している。

原文/注釈の存在・位置を確認したことと、IME入力単位・意味・表記意図の品質認証を分けた。全35,592候補条件通過例も、その品質軸は未認証。人手判定や独立Goldを捏造せず、元の`training_eligible=False`と`independent_gold_eligible=False`を維持する。

## 次の改善・期待効果・費用

| 優先 | 次に固定する範囲 | 期待効果と残る条件 | 費用の根拠 |
|---|---|---|---|
| P1 #31/#49 | 原注釈の再現を目的とする研究用弱教師の利用方針と、実IME入力の正解認証を区別する。境界/語義/表記が未解決な例の扱いを固定する | 35,592件を無条件に正解へ昇格させず、どの課題の教師として使えるか明確にする。単純な漢字/仮名隣接による除外は採らない | 認証済み原位置・全snapshotを再利用でき、新native要求は不要。個別AI補助を行う場合もai_teacherとして別記録し、人手品質証拠にしない |
| P1 #32/#33 | 許可段落receiptと実際の教師/feature/cacheを接続する利用契約を固定する。候補通過35,592件と4component対比10組の容量を前提に同量比較を設計する | 青空25,000行という旧量条件は候補面で満たすが、意味の対比は未認証。旧poolや隔離本文の再流入防止、Wikipedia側の同じ利用範囲認証が必要 | 新規取得費用は0。全source観測68.1秒、全candidate検算65.0秒が再検証コストの目安。新fitの予算と研究評価は別固定 |
| P2 #33/#34/#35 | 品質・消費範囲を固定後、同件数/同更新予算で弱教師・対比の効果を比較し、独立calibrationで安全性を判定する | 元devを繰り返し選択に使わず、読みpriorだけの改善と文脈効果を分離できる。改善幅は現在未測定 | 新fit/モデル推論0。独立Goldと一度限りのTestの要件は残る |

Gold点推定99.5%以上・Wilson95%下限99.0%以上・最終valid3,000件以上、安全性0.25%、最終Test一回限りの条件は変更しない。

## 再現・検証・終端

既存研究環境Python 3.13.13を読取り利用し、依存追加0。元sourceライセンス/取得/解析identityは#49→#48→#33のhash chain、候補は固定reference identityへ結び付ける。過去のcode/plan/failed outputsは保存した。未使用rootでの初回再現には記録した各commitが必要で、既存rootを消して再実行しない。

```text
PYTHONPATH=src python research/issue-49-consumed-contrast/run_audit.py prepare
PYTHONPATH=src python research/issue-49-consumed-contrast/forward_batches.py prepare
PYTHONPATH=src python research/issue-49-consumed-contrast/forward_batches.py execute --binding-commit ec477ea1528e022035dbc4576d484af50bad0758
PYTHONPATH=src python research/issue-49-consumed-contrast/verify_audit.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

最終verifierは既存/新規snapshotのinput/output bytesと保存receiptのhash、identity、原文の全境界観測、全93,973件の存在順位/候補条件を直接照合する。準備時のproofだけでは採用せず、最終検証を必須とする。全22,636snapshotの再認証、Top-k別計算、全quartetの契約、逆順profileが一致した。旧16+25artifact不変、**621 tests成功・skip/error/failure0**、8 Python filesのAST/import確認、raw artifact追跡0。Codexが直接検証し、独立した別agent/reviewerは使用していない。

本作業単位は3反復で6基準を通過。初回認証失敗、v1のbudget停止、v2の実行/検証を混同しない。結果は[準備](../../reports/issue-49-consumed-preparation-v1.json)、[候補・対比](../../reports/issue-49-consumed-contrasts-v2.json)、[最終検証](../../reports/issue-49-consumed-contrast-verification-v2.json)、[完了チェック](../../reports/issue-49-consumed-checks-v2.json)、[cleanup](../../reports/issue-49-consumed-cleanup-v2.json)。モデル未変更のためONNX parity/CPU10,000回の再計測は対象外。

再現用のignored `data/generated/issue-49-consumed-contrast-v1/`には失敗原本、`attempt-02/`の準備、`attempt-02/batched-forward-v2/`のnative成果物・全検算を保持する。`.codex/goal-loop/issue-49-consumed-contrast/`と未マージbranch `issue-49-consumed-contrast-v1`も継続用に保持。所有runner残存0を確認し、専用`~/tmp/issue49-consumed-contrast-20261105/`は削除済み。

## IRVと検証済みの学び

A. 必要だった責務は、原注釈boundaryの観測と対比集計、既存snapshot認証、native実行/失敗終端、別検算。新module1、研究scripts5、test files2、plan2とbinding1。既存のsource/分離/候補validator/contrast契約を再利用し、全回帰621件を実行した。モデル・production・旧splitは変更しない。

B. 全読みが16,000上限を超えたため、既存#33の100読みbatch契約と実測まで調査を広げた。読みごとのprocess/dictionary起動を減らす構造へ変更し、失敗時にbatch全memberを観測可能にする契約を追加した。元のsource/label規則は広げていない。

C. `annotation_contrast.py`が観測と保守的な対比集計を所有する。研究scriptsは凍結input/receipt、実行予約と終端、最終検証を所有する。sourceの正解認証と学習許可は別責務のまま。新しいsemantic依存は、100読みまでの固定native/validator契約であり、productionへの依存追加は0。

D. 次のIssueは、原zipや全候補取得をやり直さず、原位置/consumer receipt・全snapshot・対比witnessから利用方針と比較を設計できる。新たに必要なのは、このsource再現課題と実IMEの正解を区別する条件、全cache/featureが許可範囲だけを消費する証拠である。検証済みの学びとして、Windowsでcanonical artifactを生成するときは`write_bytes`または明示的なLFを使い、Git固定bytesとの一致を確認する。今回の改行不一致を条件緩和で回避しない。
