# #33: 許可段落から数値入力までを追跡する準備

2026-11-05 / Parent #1 / Related #31, #32, #49

**候補条件を満たした35,592件を全件新規に数値化し、11配列・12,706,344要素を別実装とバイト単位で照合した。** 各行は許可段落receipt、原注釈row、認証済みsnapshot、encoderへ渡す最小限のデータ、数値行のhashへつながる。今回のcache内でモデル入力の完全重複・競合ラベル・component間重複は0だった。

成果は追跡可能な研究用数値準備であり、モデル精度の改善やラベル認証ではない。新fit・モデル推論・native要求・最終Test利用・旧training labelの採用変更・Gold認証は0。採用モデルの記録値90.72%、安全性0.25%、独立GoldとGate A/Bは未更新で、リリース目標は継続中。

## 固定した方針と対象

[weak-teacher policy v1](weak-teacher-policy-v1.md)と[plan v1](plan-v1.json)を`049622b96da83a4007714ad7acf372ce5ae849f6`で固定した。[前段#54](../issue-49-consumed-contrast/README.md)の全candidate-supported行をstable ID昇順で処理し、結果を見た抽出や不足分の補完は行わない。実装は`359462d`で固定した。

この数値準備が表す課題は、原注釈のliteral表記を候補から再現すること。実IMEの唯一の正解、意味の異なる対比、独立Goldではない。元recordの`training_eligible=False`と`independent_gold_eligible=False`は不変。既存互換array keyの`gold`も、この課題の原表記候補indexを指すだけであり、Gold品質の判定ではない。

全原注釈132,729枠、抽出後101,625、段落隔離後93,973、候補条件通過35,592の分母を保持する。候補非通過58,381件を別のラベルで埋めたり、旧pool・数値cache・body pretraining・checkpointから補充したりしていない。Wikipediaとの混合は未実施で、同じ消費範囲の認証を後続条件とする。

Sakura Input clean HEAD `bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88`をplanへ記録したが、そのproduction挙動を利用していない。元source/候補のライセンスと取得identityは#54以前の固定hash chainを認証する。依存追加、外部データ取得、native起動は0。

## 原文から特徴量までの契約

`consumed_numeric.project`は、source receiptのstable ID、段落単位、revision、原行hash、原位置、左文脈/読み/対象のhashを照合する。snapshotのreading/request IDとTop-6 prefix、対象の一意性・辞書経路・長さ条件も確認する。これらの上流artifactは、前段の最終検証receiptを認証したうえで、元候補のinput/output bytesまで再照合する。

encoderへ渡すrowは、stable ID/component/corpusとleft context/reading/target/request IDの7項目だけ。candidateはsurface/local cost/source category/各segmentのsource categoryだけへ射影する。原文全文、右側文字、著者情報、境界判定metadata、review flagsは渡さない。同じreadingのcandidate projectionが対象表記によって変われば停止する。

既存C2の固定契約を再利用した。文字hash語彙13,312、左文脈64・読み32・候補表記32文字、Top-6、7特徴量。入力の切詰めが不要な確認済み行だけを対象にし、hash語彙やfeature式は変更していない。元のsource文字列、ラベル、候補順位やcostも不変。

| 数値準備の対象 | 実測 |
|---|---:|
| 行 / 読み種類 / source component | 35,592 / 8,991 / 38 |
| 配列数 / 検証した要素数 | 11 / 12,706,344 |
| 全配列の展開サイズ | 91,186,704 bytes |
| 新規NPZの保存サイズ | 6,074,341 bytes |
| 完全に同じモデル入力 / 競合label / component間重複 | 0群 / 0群 / 0群 |

重複は、この新cacheのモデル入力8配列の全bytesに対する値。原文が違ってもhash文字IDなどが同一となるケースを含めて検査した。これは全履歴cacheとのtensor照合を新たに実施したという意味ではない。履歴との出典・実入力分離は、前段#53の保存済み証拠とその入力hashに依拠する。

## 保存・読取り・別検算

各rowは原row、paragraph consumption、full snapshot、projectionのSHA-256と、入力/label tensorのSHA-256を持つ。行番号・直前hashを含むchainにし、外側manifestが全件数・chain終端・ファイルSHA-256・array schema・policyを固定する。IDや読み/原文をGitへ公開せず、raw ledgerとNPZはignored pathに保持する。

builderはwrite-once reservationを作り、`cache.partial/`に全配列とledgerを保存してfsyncし、manifestを最後に書いてから新しい`cache/`へ移す。失敗は明示terminalにし、完了途中の成果物を検証済みとしない。cache manifestは保存時の`prepared_unverified`を変更せず、成功した別検算は別のwrite-once receiptに残す。

readerは外部から渡された期待manifest hashを照合し、目的を`source_annotation_numeric_verification`に限定する。学習・model inference・body pretraining・Gold評価のpurposeを拒否する。原recordとmanifestのGold/training flagsもfalseを必須とする。

ファイルは上限内のbytesを保持して認証し、後から同じpathが差し替わっても別のbytesを読まない。NPZの全member名、展開byte上限、NPY headerのshape/dtype/orderを確認し、object arrayをNumPy load前に拒否する。配列は一度だけ展開し、mask/長さ/padding/finite値/label位置と全row chainを検査したうえでread-onlyにする。

別検算はproducerの`growth_numeric.encode`や文字/feature生成関数を呼ばず、元文字列と認証済みcandidateから11配列を再構築した。全値とbytes、入力projection、各row hashと重複集計が一致した。`gold`/正解maskの名前にかかわらず、検証したのは原注釈との対応であり、日本語の意味やユーザー意図の正しさではない。

cache manifest SHA-256: `789315c6443d51b3f98f6e12c7195759fee8d4e691c776ff57a4f7f5f358f292`。このhashだけで後続fitを許可せず、policy・最終検証receipt・別fit planを併せて固定する。

## 次の改善と費用

| 優先 | 次に必要な範囲 | 期待効果・条件 | 費用の根拠 |
|---|---|---|---|
| P1 #33/#49 | 研究用弱教師としてのfit条件を明示し、未解決のIME境界/意味/表記の扱い、比較集合、未使用研究評価を固定する | 原表記再現と実IMEの正解を混同せず、データ追加が読みprior・文脈識別に与える効果を測れる。#48の意味対比の品質条件を代用しない | 新cacheを再利用でき、追加nativeは不要。新fitの件数/更新予算/評価費用は実行前に別固定 |
| P1 #32/#33 | Wikipedia側も許可source・candidate・featureの同じ契約で認証し、混合時のsource/実入力/tensor重複を調べる | 旧50,000行・source比の比較を組む場合、青空だけの安全な準備と混合全体を混同しない | 本工程の新規生成65.253秒、全検算77.389秒が目安。旧cacheの無条件再利用はしない |
| P2 #34/#35 | 品質条件が成立した後の独立calibration・安全性検証・一度限りの最終Test | 研究用source再現の結果を独立Gold性能と区別して採否を判断できる | 現在のGold認証・最終Test利用0。Safety 0.25%と既存Gateを維持 |

人手判定やAIレビューをこの工程で生成していない。Gold点推定99.5%以上・Wilson95%下限99.0%以上・最終valid3,000件、安全性0.25%、最終Test一回限りは不変。今回のcache生成成功はリリース完了ではない。

## 再現・検証・資源の終端

既存研究環境Python 3.13.13、NumPy 2.3.5を読取り利用。source/feature codeと成果物はplan/hashで固定し、新規rootでのみ生成する。既存rootを消去して再実行せず、保存済み成果物はverifierで照合する。各stage上限1,200秒、100,000行、各artifact/展開archive512MiB。

```text
PYTHONPATH=src python research/issue-33-consumed-numeric/build_cache.py
PYTHONPATH=src python research/issue-33-consumed-numeric/verify_cache.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python research/issue-33-data-growth/verify_integrity.py
git diff --check
```

13新規契約を含む**634 tests成功、error/failure/skip0**。source/snapshot改変、禁止purpose、ラベル昇格、row chain切落し・改変、mask/padding/非finite値、object/shape不正archive、認証直後のpath差替えを検証した。5 Python filesのAST/import確認、元16+25artifact hash不変、raw artifact追跡0。Codexが直接検証し、別agentや外部reviewerは使用していない。

本単位は1反復で全6基準を通過。結果：[準備](../../reports/issue-33-consumed-numeric-v1.json)、[全tensor検証](../../reports/issue-33-consumed-numeric-verification-v1.json)、[完了チェック](../../reports/issue-33-consumed-numeric-checks-v1.json)、[cleanup](../../reports/issue-33-consumed-numeric-cleanup-v1.json)。モデル未変更のためONNX parity/CPU10,000回の新測定は対象外。

再現用のignored `data/generated/issue-33-consumed-numeric-v1/`、`.codex/goal-loop/issue-33-consumed-numeric/`、未マージbranch `issue-33-consumed-numeric-v1`を保持する。専用`~/tmp/issue33-consumed-numeric-20261105/`は削除し、所有test/worker/native runner残存0を確認した。

## IRVと検証済みの学び

A. 必要な責務はsource/candidateの消費制限、固定C2の数値生成、保存/読取りとprovenance、全tensor別検算。新module1、研究scripts3、test file1、policy1、plan1を中心に、前段のsource/候補認証契約と既存encoder式を読んだ。全回帰634件、モデル/production変更0。

B. ファイルhashと実際に展開するbytesを一致させる必要があり、NPZ/NPY headerと認証済みbytesの保持まで調査を広げた。model inputが文字列hashではなく固定token IDs/特徴量であるため、全tensorの重複検査も行った。全履歴の再学習やproduction実装には拡大していない。

C. `consumed_numeric.py`が射影・array/ledger契約・読取りpurposeを所有する。builderは一度限りの生成とpublication/失敗終端、verifierは別formulaと上流との全件照合を所有する。元のlabel/split/Gold認証の所有権は移さない。既存C2 encoderはhash固定して再利用し、productionへの依存追加は0。

D. 次のfit準備は全zip/旧実験を再読せず、policy・cache manifest・row chain・最終検証receiptの組から必要な入力を追跡できる。新たに必要なのは、数値検証purposeと研究fitの実行条件を区別すること、混合する別sourceにも同じ消費契約を適用すること。認証済みbytesを保持して読取り後のpath差替えを避けるという既存memoryの原則は、新たなcache契約テストでも確認した。同じ原則を重複してmemoryへ追加していない。
