# Issue #31: 全1,000件の六軸AI補助再確認

**全1,000件の個別再確認・保存・集計を完了した。** 旧「一意」807件にも、意味が曖昧/不明な55件、入力境界の疑義15件、名称/引用等の保護対象208件があった。旧193件だけを見直す方法では、今回の方針を全体に適用できないことが分かった。

原データを変更せず、同一助手による暫定的な診断として保存した。独立人手確認・独立Gold・精度向上実験ではない。90.72%を更新する評価は行っていない。

## 最新: 表記・保護330件の方針対応を完了（2026-11-04）

**表記方針57件と名称/引用保護273件を全件確認し、凍結した表記方針v1へ対応づけた。** 同じAIによる診断を6つのimmutable batchに保存し、前event、元queue、旧六軸判断、旧report、新policyのhashに結合した。人手や独立第二判定ではなく、正解表記集合の発行・ラベル適用は0件である。

| 次に必要な扱い | 件数 | 意味 |
| --- | ---: | --- |
| 正確な表記を保護 | 276 | 名称・引用・識別子等の無条件正規化を禁止。正解認証ではない |
| 個別の表記対を条件付き検討 | 47 | 語義等の既存診断に明示的な未解決フラグがなく、表記対の根拠確認へ進める。許容済みではない |
| 先に読み・入力単位・文脈・意味を確認 | 7 | 表記の同値性を論じる前提が未解決。unknownのまま母集団に残す |

旧表記方針57件のうち3件は保護優先となった。番組題名である可能性、芸名の襲名世代、放送局略称の可能性を、一般の数字・外来語規則で処理しないためである。旧273件の保護は維持した。保護276件中64件には他軸の未解決点もあり、保護によって不確実性を消していない。

全330件の未解決軸は意味47・入力単位20・読み13・文脈4で、軸間に重複がある。保護と未解決は排他的ではない。複数の規則に属する例もあるため、規則別件数を合計して母集団件数としない。[集計JSON](issue-31-spelling-policy-v1.json)に排他的なroute、重複するrule memberships、旧分類との対応を分けて保存した。今回対象外の670件の正解性を認証する集計ではない。

### 凍結した表記契約

[Gold表記方針v1](../research/gold-spelling-policy-v1.json)のSHA-256は `973b25db713a56b11c72e2f1b53bc3f585c8b7efde7b40bd11e51d6eed91306f`。規則は、数字・送り仮名・仮名漢字/繰返し・外来語・字形・英字略号・記号の7種類と、人名・地名施設・組織行事・作品引用・製品識別子等の5種類。名称の種類が未同定の場合はその限界を個票に残し、複数の保護規則への対応は同一性の認証としない。

条件付きの表記対を将来許容するにも、次が必要となる。

1. 意図する語義/指示対象と入力単位を、許可された情報で説明する。単に自然な一候補であることを一意な意図と同一視しない。
2. 同じfull-readingの実converter snapshotに両表記の経路があり、数値・用法・品詞/活用・意味を維持する。LLM提案、読みの近さ、候補への登録だけで代替しない。
3. 名称・引用・型番等は保護を優先する。字体・数字・大文字小文字・記号の無条件正規化は禁止する。
4. 個々の対、根拠hash、方針版、確認者由来を固定した独立評価用の別成果物を用意する。同じAIの今回の判断から許容集合を自動発行しない。

主評価のsource-exact Accuracyと元分母は不変。将来の表記許容集合による評価は副評価として対象数・除外数・未解決数を併記する。意味の違う同音語や読み誤りを表記揺れとして救済しない。AIによる方針対応の完了率を、Goldの正解率・人間の一致率・95%品質区間へ換算しない。

### 再現・受入検証

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m sakura_rerank.data.pilot_policy_triage --mode spelling --packet data/generated/issue-31-gold-pilot-v1 --ai-policy research/gold-ai-six-axis-policy-v1.json --batches data/generated/issue-31-ai-six-axis-v1 --base-report reports/issue-31-ai-six-axis-v1.json --triage-policy research/gold-spelling-policy-v1.json --ledger data/generated/issue-31-spelling-policy-v1/ledger.jsonl --machine-report reports/issue-31-machine-evidence-v1.json --machine-evidence data/generated/issue-31-machine-evidence-v1/evidence.jsonl
python -X utf8 -m unittest discover -s tests -p test_pilot_policy_triage.py -v
python -X utf8 -m unittest discover -s tests -v
```

| Verify | Expect / 結果 |
| --- | --- |
| 330件のhash chainと元queue/診断の結合 | 対象全件・順序一致、欠落/重複0、6batchの初回記録を保持。許容表記やhuman偽装を拒否 |
| 同一集計2回と別Counter | byte一致、276+47+7=330、旧57/273との対応・各規則・未解決軸が一致 |
| 新旧契約testsと全tests | 新規5成功、旧8継続成功。全353中348成功、既存optional PyTorch 5skip、失敗0。300秒timeout内で完了 |
| AST/compile・diff・既存hash・process | 既存26artifact不変、task runner残存0、既存インストールworker維持 |

検証の詳細は [verification JSON](issue-31-spelling-policy-verification-v1.json)。raw個票は `data/generated/issue-31-spelling-policy-v1/` の6batchと連結ledgerに保存し、Gitには含めない。一時view・作業script・test logは清掃する。旧データ/モデル/政策履歴、独立Test未使用、安全性0.25%を維持している。

**次の工程:** 方針整理を繰り返すだけにせず、#35の評価仕様とcalibration/Test隔離の機械検証へ進む。独立Goldの品質証拠は依然未解決であり、今回の330件を独立Testへ流用しない。モデル・特徴量・ゲート・ラベル方針と統計条件をTest実行前に固定する。Gate A未達・製品リリース未完了を維持する。

**今回のIRV。** A: 既存policy triageの責任、六軸診断とpacket/machine証拠の公開契約、新表記policy、対象330個票、同じtest fileの5追加tests。B: 旧triageは193件の旧分類だけを対象としていたため、同じ責任内に六軸版の明示的modeを追加した。旧API/default modeは維持。C: `pilot_policy_triage` が対応づけの検証と集計を所有し、policyが表記検討条件を所有する。元ラベルやモデルへの書込み経路はない。D: 次回は表記検討の対象と必要根拠をこのpolicy/台帳から取得できる。保護が認証ではないこと、条件付き検討が許容ではないこと、重複する規則件数の扱いは引き続き必要。

## 前段: 新版のsource品質隔離を実装（2026-11-04）

**新しい抽出を明示的にv5で実行すると、左文脈64文字＋対象表記にあるTeX命令残骸と空の書名括弧を検出して、その候補を隔離する。** 原文を推測して埋めたり、正解ラベルを書き換えたりしない。既定は従来のv4で、旧datasetの再現性を維持した。判定に右文脈・後続候補を追加していない。

train全12,516件への反実仮想監査では9件（約0.0719%）が隔離対象だった。TeX残骸3件、空題名6件、重複0件、保持候補12,507件。これは小さい混入原因への修正であり、従来の約4.87%のラベル問題や精度頭打ちを解決したという結果ではない。[集計JSON](issue-31-source-quality-v1.json)と[検証JSON](issue-31-source-quality-verification-v1.json)に分母・hashを保存した。

9件を同じAIが全件確認し、定義した可視の問題を9件で確認した。対象語の局所意味まで阻害されると診断したのは1件で、残る8件は局所的には理解可能だった。したがって、**9件を誤ラベルと数えない**。有用な技術文や固有名詞の例も隔離する可能性がある。独立した正誤検証・false-positive率・モデルの改善幅は未測定。

### 版と状態の契約

- `clean_wikitext` 自体はv4のまま。v5は候補抽出時の追加検査で、既存の段落/文/文字位置、sampling、stable ID、旧stable-ID除外を維持する。漢字隣接・部分入力・通常の非空題名・波括弧だけでは拒否しない。通常パスの保持例も検証したが、登録TeX命令と同じ文字列を含むパスは隔離され得る。
- ルールは固定したTeX命令集合と `『』`（空白のみの中身を含む）。未登録TeX命令、通常の `「」`、画像/テンプレート除去による任意の文脈欠損を網羅するものではない。今回は実証した原因に限定した仕様で、Goldのラベル定義を代替しない。
- CLIは `jawiki-preprocess --cleaner-version conservative_wikitext_v5` で明示選択。manifest schema 5と `candidate_quality_policy=bounded_left64_target_tex_empty_title_v1` を必須にし、旧schemaへの混入・方針違い・件数不整合を拒否する。新規manifestは `measured` で、自ら `verified` やGate A合格へ昇格できない。
- 検査/隔離/理由別/保持/出力byte上限で保存できなかった候補を計数する。全件隔離は既存出力を変えず明示的に失敗する。有限の件数上限がある新規抽出では後続候補の補充が起こり得るため、旧版との精度比較にこの新しい分母を混用しない。
- 今回の既存train監査は全12,516件のroute・元row hashをlocal追跡台帳に残し、元datasetは不変。dev 1,788件とholdout 3,576件はJSON解析前に除外して全ファイルのhashだけ検証した。モデル予測・性能値による選択は行っていない。

### 実装の検証と再現

| Verify | Expect / 結果 |
| --- | --- |
| `test_source_quality.py` | 新規11 tests成功。正常例、境界分割、右文脈不使用、64文字より古い文脈不使用、旧ID除外、版/方針不一致、byte上限、全隔離失敗、非trainの非解析を検証 |
| 旧commitと現行のAST・default出力比較 | cleaner/matcher/ID/samplingの4責任のAST一致。6つの合成入力でv4出力bytesとcounts一致 |
| 全tests・AST/compile・diff check | 348中343成功、既存optional PyTorch 5skip、失敗0。300秒timeoutを設定 |
| train監査を新規directoryに独立2回生成し別Counter照合 | report/evidence両方byte一致、route合計12,516、理由別集計一致。旧24artifact hash不変 |
| runnerと一時物確認 | task runner残存0、既存インストールworker維持。一時script/二回目出力/logを削除。新しいlocal監査台帳のみ保持 |

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m unittest discover -s tests -p test_source_quality.py -v
python -X utf8 -m unittest discover -s tests -v
# 出力先は新しいdirectoryを指定する。既存台帳の上書きは拒否する。
python -X utf8 -m sakura_rerank.data.source_quality_audit --source data/generated/issue15-v5-slot120/frozen-split.jsonl --source-sha256 0651bfaa3fb67da7980dcbbe4ad5de6e383e2878c726ace53a189d74519b1d82 --output-directory data/generated/issue-31-source-quality-reproduction
```

保持したlocal成果物は `data/generated/issue-31-source-quality-v1/` のreport、全train route台帳、AIによる9件のinspection。生コーパス・個票ID・対象本文はGitへ追加していない。現行Sakura Input HEADは引き続き `d586fae572d32aa76512994dca616dadef2899b1`。本番実装、元データ、モデル、独立Test、安全性基準0.25%は変更していない。

**次の重点:** 小さい抽出ノイズへの対策はできた。続いて表記方針57件と名称/引用保護273件を、許容・保護・情報不足の条件に対応づける。読み/IME入力単位/意図の違いを定義した上で、#35の独立品質証拠と一度だけ使うTestを設計する。Gate Aは未通過、独立Gold品質の証拠方法は未解決、製品リリースは未完了。

**今回のIRV。** A: source品質ルール1module、train監査1module、抽出器・manifest validator・CLI・JSON schemaの接続、新規tests1file、既存抽出testsと公開契約が必要。B: 単純なregex追加だけでは旧manifestを新挙動に誤用するため、版契約と候補件数の終端処理まで調査を広げた。C: `source_quality` が検出規則、抽出器が新規候補の隔離、`source_quality_audit` が既存trainの未適用route記録、`tier_a` がmanifest受入を所有。純粋な規則からdataset/CLIへの逆依存はない。D: 次回は同じ品質predicateを抽出と影響監査で共有でき、規則を二重実装する必要がない。版ごとの互換性・samplingと停止上限・実測分母の違いは引き続き理解が必要。

## 追補: 疑義50件の証拠確認（2026-11-04）

読み18件、入力境界31件、文脈欠陥10件の**和集合50件**を確認した。元の20batchと判断はそのままに、別のimmutable補足台帳へ全50件の根拠・未保証点を保存した。今回も同じAIによる診断で、外部資料の利用は独立した判定者の追加を意味しない。集計は [doubt evidence JSON](issue-31-doubt-evidence-v1.json)、実行証跡は [verification JSON](issue-31-doubt-evidence-verification-v1.json)。

| 追加証拠に基づく区分 | 件数 / 対象50件 | 含意 |
| --- | ---: | --- |
| 外部一次資料が読みを支持 | 3 | 読みの根拠を補強。入力者の意図や表記の一意性の認証ではない |
| 外部資料の文脈読みと割当が衝突 | 2 | 自然な全語発音と、任意の部分変換入力を区別する必要がある |
| 部分入力として成立し得る | 23 | 漢字隣接・語の途中だけを理由に誤りとしない。実際の確定操作は未観測 |
| 文脈問題に対応する処理機構を再現 | 2 | 数式残骸と空の書名括弧。元wikitextを再取得した因果証明ではない |
| 根拠不足を維持 | 20 | 固有読み、読み変化、用法、欠落原因を確定できない |

この区分は50件の診断結果であり、改善率・誤ラベル率・認証正解率ではない。母集団1,000件の分母、旧診断、unknownを保持する。ラベル適用0、認証Gold0、両Gate A false、独立Test未使用、学習0。

**確認できたこと。** 辞書index全368,341行を1回のstreamでhash検証し、50件すべての対象表記は割当と一致する一意読みを持つと確認した。一方、左文脈の末尾32文字以内と対象を連結した長い辞書語が見つかったのは3件。これは左側重複の下限であり、残る47件に語境界の問題がないという主張ではない。右文脈は追加していない。

読みの支持3件は、大学の公開人物記載1件と郵便番号検索の町名記載2件による。衝突2件は、郵便番号検索の町名一覧1件と、動物園の実務者による飼育個体・標本の解説1件に文脈上の全語読みが明記されることを根拠とする。後者は実務者の一次解説であり、唯一の規範の証明にはしない。いずれも当日の資料で、過去snapshotの同一性まで保証しない。検索結果snippetだけでは採用せず、ページ本文の対象一致を確認した。同字の別地域・別代の人物の資料は根拠にしなかった。5件の参照先URLと資料名は個別事例を特定するため、ignored local台帳 `data/generated/issue-31-doubt-evidence-v1/supplement.json`（sha256 `c4a458f7f942b9bc7faef5ddbaa9456653381f885560c4d45fc53d936b32355f`）だけに保持する。

2026-11-08（#92）: 上の段落から事例を特定する参照先と資料名を外した。変更はこの段落と本注記だけである。変更前のbytesはsha256 `4a32cb012dbfa0b7c3f2e94f7ed5954b6a1c8b9f5072f42d0620eebdcfc54502` で、既存の検証報告7件の`old_artifact_hashes_unchanged` が記録するのはこの変更前の版である。同日、`reports/issue-31-doubt-evidence-v1.json` の `source_excerpt_sha256` のkeyをlocal台帳のsource id（人名・地名を含む）から、そのid辞書順の中立ラベル `source-1`〜`source-5` に置き換えた。excerpt hash値と他のfieldは不変で、変更前sha256は `80f1723222fa7226bc9d62f6e434bbafcd5a16939cc962a61ba0fc7e4a406209`、変更後は `7ea80477d29febe068da6eb622550dd8e85272d5143553b09092de5f923d10bf` である。生成元 `pilot_doubt_evidence.aggregate` も同じ規則で出力する。

各資料の短い転記抜粋、URL、日時、保証範囲と限界をlocal台帳に保存した。excerpt hashは**保存した転記のhash**であり、サーバーから取得したページ全体のbyte hashではない。参照先の将来不変性や抜粋解釈の自動的な正しさを保証しない。

**修正対象の根拠。** 現行 `clean_wikitext` はmathタグの中身を残してタグを取り去る。合成例 `<math>\mbox{ for } x</math>` でTeX残骸が保持されることを再現した。また、合成書名中のテンプレートを除去すると `『』` が残る。pilotで見えた同種の問題に対する再現可能な機構だが、当該原文で同じ変換が起きたと証明したものではない。空の題名があるだけで対象語の正解が必ず壊れるわけでもない。

### 次の実装とリリースまでの順序

所有者の「リリースまで」の継続目標に従い、必要な実装・検証へ進む。以下の旧記録にある「#33/#34/#35未承認」は当時の範囲である。ただしGate順序、安全性0.25%、独立Test一回限り、既存artifact不変、既定有効化の別承認は維持する。人手割当を前提条件へ戻さず、未検証の品質を合格へ置換しない。

| 優先 | 実施内容と期待効果 | 検証コストと完了条件 |
| --- | --- | --- |
| 1 | 新版の抽出処理で数式残骸・空題名を検出し、原因別の隔離を記録する。破損文脈の混入を抑える | 旧cleaner再現を保持する版契約、合成の肯定/否定例、trainだけの影響監査。旧labelを上書きしない。効果量は未推定 |
| 2 | 57件の表記方針と273件の保護対象を仕様へ対応づける。全語入力と部分確定を別条件とする限定課題を設計 | 330件の対応確認、50件程度の制御課題と実converterのforward証拠。一般日本語の独立Gold/Testへ転用しない |
| 3 | #35のGold・calibration・Testを隔離し、モデル/特徴量/gate/label方針/統計条件を事前固定 | 独立品質の証拠方法は未解決。pilot再読やAI一致率から点99.5%・Wilson下限99.0%を捏造しない。Test結果を見た変更・逐次追加は禁止 |
| 4 | 品質を確立して#34/#33の比較、同一候補・全件分母でGate A/B、その後Windows CPU Gate Cと本番Gate D | #1の等予算GRU/minGRU/Tiny Transformer比較、未見辞書回帰、95%CI、安全性、性能・fallback・privacyを個別に判定。公開前検査も実施。研究結果の保存を製品リリース完了としない |

今回確認したSakura Input HEADは `d586fae572d32aa76512994dca616dadef2899b1`。辞書/元datasetの固定HEADとは区別し、現在の製品実装を変更していない。

### 追補の再現・受入条件

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m sakura_rerank.data.pilot_doubt_evidence --packet data/generated/issue-31-gold-pilot-v1 --machine-report reports/issue-31-machine-evidence-v1.json --machine-evidence data/generated/issue-31-machine-evidence-v1/evidence.jsonl --reviews data/generated/issue-31-ai-six-axis-v1 --prior-report reports/issue-31-ai-six-axis-v1.json --dictionary data/generated/system-dictionary-index.jsonl --dictionary-manifest manifests/system-dictionary-index-verified.json --supplement data/generated/issue-31-doubt-evidence-v1/supplement.json
python -X utf8 -m unittest discover -s tests -p test_pilot_doubt_evidence.py -v
python -X utf8 -m unittest discover -s tests -v
```

| Verify | Expect / 結果 |
| --- | --- |
| 上記集計を2回、別Counterで再計数 | byte一致、和集合50件、欠落/重複0、合計50。全1,000件の旧判断にhashで結合 |
| 新契約tests | 改変・欠落・順序違い・人手偽装・ラベル昇格・不正source・証拠なしの断定を拒否。9件成功 |
| 全tests、AST/compile、diff check | 337中332成功、既存optional PyTorch 5skip、失敗0。300秒timeout内で完了 |
| 旧artifact/hash確認 | 元dataset/モデル/旧policy/旧診断/空human round等22件不変。holdout本文は未解析 |
| runner/temp確認 | task所有runner残存0、既存インストールworker維持。一時script/logを清掃し、local補足台帳だけ保存 |

公開Gitには集計・hash・検証器・合成testsのみ収録する。raw個票と短い転記抜粋は `data/generated/issue-31-doubt-evidence-v1/supplement.json` に残す。従来台帳と辞書indexがある環境で集計を再現できるが、Git単独でAI判断を生成し直す手順ではない。

**追補のIRV。** A: 対象責任は既存AI診断に対する読み/境界/文脈の補足証拠。既存packet・machine・AI集計の公開契約、辞書manifest、cleaner該当処理、新validator1file/9testsが必要。B: 辞書から自然な文脈発音が決まらないため、5つの一次資料とcleanerへ調査を広げた。製品・学習器内部は未調査。C: `pilot_doubt_evidence` が補足証拠の読取り検証と集計を所有し、旧状態やGate判定への書込み経路を持たない。D: 次回は旧1,000件の判断を再探索せず50件の結論と不足根拠を参照できる。外部資料の限定的な支持と入力意図の違い、新版cleanerと旧版再現性の区別は引き続き必要。

## 実施前の検証条件

| Verify | Expect |
| --- | --- |
| 各50件batchを保存直後にvalidate | 全件に五つの明示的な言語判断と個別理由。自動validや旧分類のコピーなし |
| machine evidenceとpacketのhash照合 | 全1,000件のsource軸が既存機械照合と結び付き、原文の独立認証に昇格しない |
| 全20batchの集計と別Counter計算 | 欠落・重複0、合計1,000、同じ出力を再現 |
| 新旧の条件付き集計 | 旧807件を含め全件を確認。旧193件だけの率を母集団品質としない |
| 契約tests、全tests、compile、旧artifact hash | 証拠不一致・人手偽装・履歴改変を拒否。元データ・モデル不変 |
| 終了後のprocess/temp確認 | task runner0、一時物削除、必要な判定ledgerのみ保存 |

## 固定した条件

- [AI用方針v1](../research/gold-ai-six-axis-policy-v1.json)を最初の再読前に凍結。SHA-256は `dd1671662c8506c2a8182279e775952f25ddf69bba2eb1c861367d9c81accc1b`。旧人手方針とは別で、旧方針を改変していない。
- 対象は既存train pilotの同じ1,000件。旧分類を表示せず、50件×20batchを助手自身が読み、全件について読み・入力単位・文脈・意味・表記の5判断と個別理由を明示した。原文軸は先行する機械照合のcase hashに結びつけた。
- 表示情報は読み、対象表記、最大64文字の左文脈、保存済み正解分節。必要時の候補表示は表記順に限定する設計だが、今回の再読では追加候補一覧を開いていない。モデルの予測/順位/スコア、右文脈、host文書、holdout例は使用しない。
- 判定者は `ai_teacher / codex-primary` の1者。同じ助手の再読で過去のcaseへの露出があり、source goldも見える。独立性・blind・人間の判定者間一致率を主張しない。
- 各batchは新規作成のみで保存しhashを記録。今回の保存後の訂正は0件。将来の訂正は初回を残す追記台帳でcaseの前eventとjournalの前eventを参照する。修正ラベル、許容表記集合、確定した修正読みは出力していない。

## 全件の分布

すべて同じ1,000件を分母とする。各軸内では排他的、軸間では重複する。以下はAI判断の分布であって誤ラベル率や正解率ではない。

| 軸 | 暫定判断の件数 |
| --- | --- |
| 原文との対応 | 別保存の前処理sourceとの完全一致1,000、独立した原文正しさの認証0 |
| 読み | 通常の読みとして適合982、具体的疑義4、根拠不足14 |
| 入力単位 | 合成課題として成立しそう969、切出し境界の疑義31 |
| 文脈 | 評価を妨げる欠陥を観察しない990、欠陥はあるが対象評価可能9、評価を妨げる欠陥1 |
| 意味 | 左文脈に支持される909、具体的な別語義等が残る19、材料不足72 |
| 表記 | 一般的な表記として成立しそう668、表記方針未確定57、名称/引用等の保護273、判断材料不足2 |

「意味が支持される」は唯一の入力意図を保証しない。「入力単位が成立しそう」は実IMEの部分確定操作を観測した意味ではない。「一般的な表記として成立しそう」は他の候補が不正だという意味ではない。5軸とも通常/支持に当たる組合せは609件あるが、これも認証済みGoldの件数ではない。

## 旧807件も未認証のまま再確認した結果

| 観点 | 旧一意807件 | 旧要確認193件 | 全1,000件 |
| --- | ---: | ---: | ---: |
| 今回の確認済み | 807 | 193 | 1,000 |
| 読みの疑義 / 根拠不足 | 0 / 4 | 4 / 10 | 4 / 14 |
| 入力境界の疑義 | 15 | 16 | 31 |
| 文脈欠陥: 非阻害 / 阻害 | 4 / 0 | 5 / 1 | 9 / 1 |
| 意味: 曖昧 / 材料不足 | 13 / 42 | 6 / 30 | 19 / 72 |
| 名称・引用等の保護 | 208 | 65 | 273 |
| 表記方針未確定 | 13 | 44 | 57 |

旧分類と今回の軸は意味が違う。旧「表記同値」や「文脈不足」から今回の「支持」への移動を改善率として扱わない。特に、元表記が文脈に自然であるという今回の判断は、旧分類で意図した一意性より弱い主張である。元の807/193分類、初回判定、10件の旧自己訂正、193件triageはすべて保持した。

旧807件の保護対象208件は、208件の誤りを発見した意味ではない。名称や引用の実際の表記を確認せずに一般語の正規化規則を適用してはいけない、という判断である。境界31件も全件を誤りとせず、正当な部分入力の可能性を残す。

## 人手なしで進める優先順位

| 優先 | 次に検証する内容 | 期待効果 | 検証コスト・完了条件 |
| --- | --- | --- | --- |
| 1 | 読み18件・入力境界31件・文脈欠陥10件を、既存証拠と切出し規則に対応づける。重複を除いてから対象数を固定する | 誤りの疑い、情報不足、正当な部分入力を分離し、不適切な一律除外を避ける | 最大59件の証拠確認。各件に根拠の種類/未保証点/再現条件を記録。専門読み等は根拠が得られなければunknownを維持 |
| 2 | 表記方針57件と名称・引用保護273件について、正規化禁止・保留・限定許容の条件を仕様として分ける | 表記揺れと固有表記の混同を減らす。正解候補を無条件に増やすことを防ぐ | 330件の仕様への対応確認と代表的な合成契約例。許容候補集合や修正ラベルの適用は別作業 |
| 3 | 入力意図を事前に明示した制御課題50件程度の設計を作る。全語入力と部分確定を別条件にする | 人手のいない環境でも、限定した仕様に対する再現可能な正否を測る準備になる | 課題・観測可能情報・期待出力・失敗条件を先に固定。実変換のforward証拠が必要。一般日本語の独立Gold/Testとして転用しない |

Accuracyの期待増分は未推定。読み/境界/表記方針を変えた効果は、このpilotのAI分布から計算できない。全1,000件の分母を保ち、unknownや保護対象を落として見かけの精度を上げない。#33再学習、#34ゲート実装、#35独立Test実装は始めていない。0.25%基準、Goldの品質目標、独立Testを一度だけ使う条件を維持する。

人手割当を次の条件には戻さない。一方、同じAIの再読回数を増やしても独立Goldの正解率は認証できないため、95%信頼区間や人手一致率を今回の分布から作っていない。

## 再現と検証

集計は [JSON](issue-31-ai-six-axis-v1.json)、検証証跡は [verification JSON](issue-31-ai-six-axis-verification-v1.json)。Git対象外の個票台帳は `data/generated/issue-31-ai-six-axis-v1/` の20ファイル。元packet/機械証拠とこの台帳がある環境で、次のコマンドが集計を再現する。公開Git単独には本文やcase IDを含めないので、個票の再生成や同じAI判断の再現を保証するコマンドではない。

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m sakura_rerank.data.ai_six_axis_review --packet data/generated/issue-31-gold-pilot-v1 --machine-report reports/issue-31-machine-evidence-v1.json --machine-evidence data/generated/issue-31-machine-evidence-v1/evidence.jsonl --policy research/gold-ai-six-axis-policy-v1.json --reviews data/generated/issue-31-ai-six-axis-v1 --baseline-reviews data/generated/issue-31-ai-pilot-v1 --baseline-policy research/gold-pilot-ai-policy-v1.json --baseline-report reports/issue-31-ai-pilot-v1.json --previous-report reports/issue-31-ai-six-axis-v1.json
python -X utf8 -m unittest discover -s tests -p test_ai_six_axis_review.py -v
python -X utf8 -m unittest discover -s tests -v
```

集計CLIを2回実行してbyte一致。別Counter計算でも全件/全軸/旧分類別の集計が一致した。各batchに全50件、全件の明示的な軸・理由・機械証拠hashがあることを検証し、欠落・重複0件。

新規12契約テスト成功。全328テスト中323成功、既存optional PyTorch 5件skip、失敗0。300秒timeoutを設定し16.984秒で終了した。変更したPythonのAST/compileとdiff checkを確認。従来のデータ・モデルを含む12artifactに加え、旧policy/結果、凍結人手policy、機械個票の計19artifactのhash不変を照合した。

task所有のPython/test/training/ORT runnerは残っていない。既存インストールのSakura Input workerは別プロセスで維持。一時script/notes/test logは `~/tmp/ai-six-axis-20261104/` から削除し、必要な個票台帳と公開集計を保存する。別セッションの未コミットファイルは変更しない。

## IRV記録

- **A. 必要範囲:** 五つの言語判断と機械原文軸の契約、既存packet読込・機械証拠・旧AI台帳の検証契約、新しい集計CLIと12契約テスト、今回のpolicy/集計/本文。比較用には `pilot_policy_triage.load_baseline` の既存公開契約を再利用した。
- **B. 拡大理由:** 旧807件を全件対象とするため、193件triageの限定範囲を越えて全1,000件を再読した。旧分類の移行を正解率と誤認しないため条件付き集計を追加。モデル内部や本番実装の調査へは広げていない。
- **C. 状態と責任:** `ai_six_axis_review` がAI由来の検証・履歴継続・集計を所有する。状態はimmutable batchと追記訂正。source軸は検証済み機械証拠を参照し、Gold認証や人手event、ラベル適用へ接続しない。CLIの旧分類比較だけが既存baseline検証に依存する。
- **D. 次回:** 読み・境界・文脈・意味・表記の確認先をこの台帳から選べるため、候補生成や旧分類器を再読して対象を探す必要がない。一方、支持と一意性の違い、判定者の非独立性、機械照合の保証範囲は理解する必要が残る。これは再利用可能な証拠整理であり、モデル構造の改善ではない。
