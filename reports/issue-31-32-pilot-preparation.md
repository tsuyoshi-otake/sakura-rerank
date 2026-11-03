# Gold pilot準備と既存データ監査の結果

2026-11-04。親#1、実行対象#31/#32。**資料と検証処理は準備済み、人手判定は0/1,000件。** #33/#34/#35の実装・再学習は開始していない。

## 完了した作業

- [Gold方針v1](../research/gold-pilot-policy-v1.json)を固定。一意正解・表記同値・文脈不足・読み/分割/表記誤り・抽出ノイズ・未解決を区別。候補外の修正は推測しない。
- [判定手順と再現コマンド](../research/gold-pilot-protocol.md)を整備。A/Bを独立させ、不一致は別の人Cが裁定。実在・独立性の確認はcoordinatorが所有する。
- trainの12,467入力群から固定seedで1,000群を選択。A/B各25件×40batchと未記入フォームを生成。資料にはモデルの予測、元の順位、split、過去AI判定を含めない。raw textとIDはGit管理外。
- 追記履歴のhash chain、過去roundとのprefix照合、A/Bの訂正による古い裁定の失効、未解決の継続状態を検証。提案overlayは元データへ適用しない。

pilot manifest: [集計・hash](../manifests/issue-31-gold-pilot-v1.json)。初期状態: [pending 1,000 / finalized 0](issue-31-gold-pilot-status-v1.json)。人手イベント数0、両Gate Aはfalse、final holdout valid countは0。1,000件が全件一致した場合も品質保証を完了しない。

## #32 再監査

[読取り監査JSON](issue-32-frozen-audit-v1.json)で以下を再現した。source全体のSHA-256を認証し、final holdout3,576行はJSON解析前に除外。モデルscoreは読み込んでいない。

| 対象 | train | dev |
|---|---:|---:|
| 全行 | 12,516 | 1,788 |
| Top-1にgold | 11,120 | 1,586 |
| Top-5にgold | 12,435 | 1,778 |
| Top-6にgold | 12,466 | 1,780 |
| Top-10にgold | 12,502 | 1,787 |
| 同一入力の重複群 / 余剰行 | 41 / 49 | 0 / 0 |

train/dev交差は**8群、train側10行、dev側8行**。左文脈・読み・Top-6表記だけでなく、候補コストとsegment/source情報まで含めても8群一致。これは特徴生成前の入力一致の検査であり、前回の数値テンソル一致検査とは定義を区別する。gold競合は0。記事/段落/文/テンプレートのexact交差は0。

near-duplicateの全再計算は今回行わず、旧split reportの測定値を前回の再評価から参照している。新しい監査JSONも未再計算と明記する。新splitの生成・旧行の除外・候補生成の変更は行っていない。Tier Aはoracle選別済みであり、一般入力の候補性能や独立Testの品質をこの表から主張しない。

## 検証

- packetを独立に2回生成し、**全165ファイルのSHA-256が一致**。audit JSONも2回byte一致。
- 新規20テストで、train限定・重複除外・holdout非解析・blind項目・UTF-8分割・hash/bounds失敗・異なるhuman・AI拒否・空フォーム拒否・判定訂正・裁定失効・全件一致でもGate A false・出力上書き拒否・失敗cleanup・過去履歴差替え拒否を検証。
- 全suite **278件、失敗0、skip5**。skipは既存PyTorch依存テストで、この環境にoptional PyTorchがないため。新規テストのskipは0。新規4 Pythonファイルcompile成功、`git diff --check`成功。
- 元sourceのhash、および前回再評価に記録したcache/logit/report/manifestのhashを再照合して一致。元データ・既存モデル・評価データを変更していない。
- 今回起動したtest/Python/ORT/workerの残存0。既存のinstalled Sakura Input workerは本作業の所有物ではなく停止しない。

## 保持するローカル成果物と次の担当

- `data/generated/issue-31-gold-pilot-v1/`: 人手配布資料とcoordinator-only対応表。対応表はA/Bへ配布しない。
- `data/generated/issue-31-human-events.jsonl`: 空の人手event入力。A/B/Cの実際の判定だけを追記する。
- `data/generated/issue-31-review-round-000/`: 0件時点のimmutable初期履歴。次roundは`--previous-round`でこの履歴へ接続する。

担当者A・B・裁定者Cの割当は未確認。次の開始条件はその割当であり、AIによるhuman判定の代行はしない。本格Gold構築はpilotの判定分布・不一致・裁定負担・所要時間を確認した後の別判断。

## Scopeと学習

A: source contract・human audit・既存reviewer・split契約、pilotと診断の2モジュール、対応2testを対象とした。既存の再評価成果物もGitから確認可能にする。
B: 既存reviewerにはsplit/順位とGate A用の契約があり、blind pilotにそのまま使えなかったため、別record kindとローカルJSON資料に限定した。新しいWeb UIや本番への探索は行っていない。
C: source/旧gold/既存splitの所有者は不変。新規state ownerはpilotのevent履歴。提案からdatasetへの書込み経路は設けず、Gate Aへ依存しない。
D: 次回は方針・実行手順・2モジュール・2testから開始できる。verified learning: provenanceの交差0でもbounded入力8群が重複しうる。pilot完了と独立品質保証には異なる終端を設ける必要があり、全件一致でもfalseを維持するテストで確認した。
