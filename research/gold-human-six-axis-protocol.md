# 全1,000件・六軸・独立二重人手pilot v1

対象Issue #31（親#1）。[凍結方針](gold-human-six-axis-policy-v1.json)の識別子は `gold-human-six-axis-v1`。旧 `gold-pilot-v1`、AI policy、193件triageは履歴として保持し、この人手契約へ変換・流用しない。人手以外のeventは受理しない。

## 固定したもの

- 方針SHA-256: `cc5d321e3f68e126cbb3199edd8f306d459f6330bd59ffae6f5c095797e20fee`。CLIに固定し、同じ版での変更を拒否する。Gitの `.json` はLF固定。
- 対象queue SHA-256: `f43649996c9d175ea6a18239591e5bcde1001db93a8d14a849d6bc4b93b9e3c9`。旧1,000件と完全同一で、旧807/193分類による選別をしない。
- 六軸: 原文照合、読み、入力単位、文脈、意味、表記意図。全軸に値と理由が必要。各値の意味は方針JSONで定義する。
- 原文の独立証拠は既存packetに含まれない。この版の原文軸は全件 `unverifiable` とし、原gold自身との照合を原文認証にしない。残る五軸の判定を進められるが、原文確認済みGoldにはならない。
- 字体・数字・送り仮名・音写・略号・中黒の一括同値化を禁止。名称・引用を保護する。形態素境界とIME確定境界を同一視しない。右/未来文脈や実host文書を追加しない。

## 人物・資料・独立性

coordinatorがA/B/Cの実在と、互いに異なる人間であることを確認する。A/Bは全1,000件を別々に判定し、Cは第三者として裁定する。識別名は個人名である必要はなく、ASCII英数字と `._-`、64文字以内のaliasでよい。実名との対応・独立性確認の記録はcoordinatorが非公開で保持する。

coordinator用の `assignment.template.json` は全項目未記入であり、人手割当の実績ではない。各役割の `reviewer_kind=human` と、人物確認・別人・対象ケースの過去AI提案未閲覧・ケース別AI補助不使用・seal前に他者判定未閲覧の宣言が全て必要。coordinatorの識別名と確認日時も記録する。機械が人間の実在や内心の独立性を証明できるわけではない。

1. Aには `reviewer-A/`、Bには `reviewer-B/` だけをコピーして渡す。各資料に方針とGUIDEを含む。coordinator directory、全repository、過去report、193件AI提案、相手用資料は渡さない。
2. 各自が25件×40batchの全件について六軸・理由・許容候補集合を記入する。A/Bのcase番号と順序は別で、旧AI case IDも表示しない。候補は表記順。原gold自体は監査対象として見えるため、ラベル盲検とは呼ばない。
3. 判定者はpacketを編集せず、別の作業先へ回答を保存する。人手の六軸・理由・候補をAIが補完・推測してはいけない。coordinatorはJSON化・日時・hashの計算を機械的に補助できるが、提出された判断を変更しない。原提出物は別途不変保存し、eventとの対応を確認する。
4. A/B双方の全1,000件の有効な提出が揃った時点で、最新A/B event集合・方針・割当をhashでsealする。途中の一致率や相手の内容をA/Bへ戻さない。固定後にA/Bを追記訂正するとエラーになる。
5. seal後の不一致だけをCへ渡す。C用資料はA/Bの六軸・理由・候補集合・根拠event hashを含むが、判定者のidentity・旧AI提案・モデル情報を含めない。Cは理由を持って裁定し、証拠不足ならunknownを残す。

AIの役割は方針・配布物の整備、構造検証、hash・集計に限る。ケースの意味判断を人手として代行しない。露出や相談が判明した場合はそのrunを独立判定として認証せず、coordinatorが記録を保全して再実施方針を決める。人物や方針を同一run内で差し替えない。

## 回答・追記・裁定

各回答templateの `axes` に六軸の `value` と `reason` を記入する。`accepted_surfaces` は凍結候補内の辞書順・重複なしの明示集合。表記意図がuniqueなら1件、multipleなら2件以上、それ以外は空。読み・入力単位・文脈・意味の前提条件を満たさない許容表記は拒否する。旧goldを含めることを強制しないが、候補外の修復を推測して確定しない。

各eventは `record_type=human_six_axis_assessment`。共通のpolicy/packet/assignment hash、実判定者alias、役割、timezone付き判定日時を持つ。`previous_event_sha256` は同じcase/roleの直前event、`previous_log_sha256` はそのrole全体の直前eventのcanonical JSON hash。初回はnull。A/Bの `basis_sha256=[]`、`seal_sha256=null`。Cは現在のA/B event hashをA,Bの順に指定し、seal hashにも結び付ける。

canonical JSON hashは `sakura_rerank.data.contracts.canonical_json_hash(event)`。assignmentの参照hashも同関数を使う。JSONファイルそのもののbytes SHA-256と混同しない。Cの訂正は同じ固定A/Bを根拠に追記できる。旧eventの削除・差替え・時刻逆転・未記入templateの投入は拒否する。

六軸の値と許容集合が一致したものを一致と数える。自由記述理由の文字列一致は要求しない。値が同じでも理由に内容上の矛盾がある可能性は、機械的な一致率で解消されない。人手運用の問題点としてcoordinatorが記録し、方針変更を同じrunへ遡及適用しない。

## CLIと不変round

`PYTHONPATH=src` を設定する。準備物は既に生成済みなので、以下のprepare/bootstrapは新しい出力名での再現確認用。既存directoryは上書きしない。

```powershell
python -X utf8 -m sakura_rerank.data.human_six_axis_pilot prepare --source-packet data/generated/issue-31-gold-pilot-v1 --policy research/gold-human-six-axis-policy-v1.json --output data/generated/issue-31-human-six-axis-v1
python -X utf8 -m sakura_rerank.data.human_six_axis_pilot bootstrap --packet data/generated/issue-31-human-six-axis-v1 --output data/generated/issue-31-human-six-axis-round-000
```

初期roundのcheckpoint（`round.json` bytes SHA-256）:

`a2620b04aef8a17d1721e5d6a6deb7376702089d22aa05223a582858ecc0e9b3`

実際の人手割当確認と判定が届いた後、coordinatorが原提出物との対応を確認してevent履歴全体を組み立て、次を実行する。下記のassignment/events入力ファイルは**まだ存在するとは限らず、架空の人手記録を作成してはいけない**。

```powershell
python -X utf8 -m sakura_rerank.data.human_six_axis_pilot advance --packet data/generated/issue-31-human-six-axis-v1 --assignment data/generated/issue-31-human-assignment.json --events data/generated/issue-31-human-six-axis-events.jsonl --previous-round data/generated/issue-31-human-six-axis-round-000 --previous-round-sha256 a2620b04aef8a17d1721e5d6a6deb7376702089d22aa05223a582858ecc0e9b3 --output data/generated/issue-31-human-six-axis-round-001
```

以後は直前のroundと、別保管したそのcheckpointを指定する。旧event列をそのままprefixとして保持し、追加だけを受け付ける。各roundはevent、割当、集計、所見、不一致資料、seal、ファイルhash一覧を新directoryに保存する。失敗時は出力を公開せずstagingをcleanupする。hashは失われた記録を復元しないため、coordinatorが過去roundとcheckpointを独立に保管する。

## 状態と指標

| 状態 | 意味 |
| --- | --- |
| `awaiting_assignment` | A/B/Cの確認済み割当なし。人手実績0 |
| `awaiting_dual_review` | A/B双方の1,000件提出が未完了。C向け個票は未公開 |
| `awaiting_adjudication` | A/Bを固定済み。未裁定の不一致あり |
| `pilot_findings_complete_no_gold` | 二重判定と必要な裁定の所見が揃った。Gold認証ではない |

- **初回一致率:** 各caseのA/B初回event同士を比較する。訂正があっても初回値を保持する。
- **現在/固定時一致率:** A/Bの最新event同士を比較する。初回と併記し、Cによる裁定を一致数に加えない。
- **六軸一致:** 各軸の一致数/両者提出数、両者unknown系の数、両者とも判定可能な部分の一致数/その分母を併記。分母0はnull。未提出とunknownは別。
- **裁定:** 不一致数/両者提出数と、不一致数/元1,000件、裁定依頼解禁数、裁定完了数/不一致数を区別。全件揃う前の不一致はCへ解禁しない。A/B/C各自の実判定case数と最終所見の軸分布を報告する。
- **品質:** 一致率は正解率ではない。source軸のunknown同士は粗一致に含まれるが、判定可能部分の分母には入らない。全件の所見が揃ってもGate A両方false、Gold認証数0、独立holdout valid0。unknownを排除して分母を改善しない。

元ラベルへの書戻し、学習用overlay、モデル再学習、独立Test利用、#33/#34/#35実装は行わない。pilotの結果・定義不足・運用時間を確認してから本格Gold構築を判断する。
