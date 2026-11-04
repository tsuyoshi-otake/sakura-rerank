# #35 独立評価仕様・隔離監査・Test使用台帳 v1

2026-11-04。親 #1、依存 #31/#32/#34。基点 `3ecb8d1fa3c6b9f53672f555f205f0b105db70b0`。
Sakura Inputの確認済みHEADは `d586fae572d32aa76512994dca616dadef2899b1`。

## 完了したこと

[評価手順v1](../research/independent-evaluation-protocol-v1.md)を記録し、
別記事にある同じbounded入力も検出する隔離監査と、失敗後もTestを消費済みとして
保持する使用台帳を実装した。実データのTest実行、Gold認証、閾値選択、再学習は0回。
仕様の固定は、実際の標本・モデル・Gold証拠を固定した実験事前登録の完了ではない。

既存のsource component検査だけでは、別記事・別段落の同じ左文脈/読みを検出できない。
新しい `splitter.audit_evaluation_partitions` は記事・段落・template・類似文の関係と
完全一致入力の関係を同じ連結成分にする。履歴、train、calibration、Testの全組合せを
監査し、元行を変更・除外しない。全tierを分母に残す。旧split割当と旧履歴除外は不変。

Test使用台帳は `unused → reserved/consumed → completed | failed`。
予約をfsyncした後でのみ使用記録を返し、active予約は1件に限定する。
同じ入力・記事・段落等はモデル、ラベル、revision、stable IDを変えても再予約できない。
失敗時に予約を取り消さない。並行writerは待機ループを作らず拒否する。
結果記録用のevent数・byte容量を予約時に確保する。

## 検証結果

- 全369 tests: 364成功、既存optional PyTorch 5 skip、失敗0。新規16件は全成功。
  runnerには300秒の上限を設定。終了後のtask-owned runner残存0を確認。
- 合成例で、source交差がすべて0でも同じ入力が1群あれば漏洩として検出。
  source→input→sourceの推移的な交差も1成分として検出し、関係する新規3行を数える。
- 入力順によらず監査結果は一致。ラベル変更は内容hashを変えるがTest再利用tokenを変えない。
  同時予約は1件のみ成功。失敗・ID/revision変更・別planによる再利用を拒否。
- 履歴編集・末尾切落し・途中書込み・旧head・fsync例外・残存lock・誤った終端を検証。
  fsync例外でも書込み済みの予約を消さず、確認なしに評価を開始しない。
- 旧splitterの全21関数/class定義のAST一致、既存30artifactのSHA-256不変。
  compileとdiff検査成功。既存installed workerは本作業の所有物ではなく保持。

機械可読証拠、コード/仕様hash、対象artifact一覧、合成監査結果:
[verification JSON](issue-35-evaluation-protocol-verification-v1.json)。
全テストは `PYTHONPATH=src` の下で `python -m unittest discover -s tests`。
局所検証は `python -m unittest tests.test_evaluation_protocol -v`。

## 限界と残作業

監査は渡された履歴についての検証であり、渡されなかった過去の露出を証明できない。
台帳はhashの整合性と再使用を検査するが、Goldの正しさやモデルartifactを認証しない。
近似重複の再使用はtoken一致だけで防げず、完全な過去sourceを含む隔離監査が必要。
外部に保存したheadがなければ末尾削除を発見できない。別台帳の作成や評価器外での閲覧を
技術的に禁止するものでもない。実評価器への組込み、アクセス管理、独立した保存先が必要。

未実装: 全履歴inventoryの網羅性検証、artifactを実際に照合する開始条件、
モデル実行器、指標/統計の計算、calibration。独立Gold品質の証拠方法も未解決。
Gate A/Bはfalse、安全性0.25%不変。代表標本と依存性を考慮した検出力設計が未確定なため、
今回の仕様には実験開始を許可する宣言を含めていない。

次の優先は指標計算とartifact照合を、合成例・既存devの明示的な研究用途で検証すること。
期待効果は、分母の不一致や失敗例除外を防ぎ、同一条件でv1/r2/#29を測れるようにすること。
精度上昇の見積りはしない。今回の全suite実行時間は15.193秒、GPU学習・新モデル推論は0回。
次の指標/照合実装と契約検証の計画見積は1–2 engineer-days。実Gold構築・
統計的に有効な独立評価の証拠取得は方法未確定のため工数を確定できない。
Testは準備が整うまで開かず、一度使った後のモデルや閾値修正には新しい独立Testが必要。

## 実際の範囲・設計への影響（IRV）

A. 対象は既存data contract、splitterとその契約tests、atomic IOの公開契約、
#35/#1要求、既存pilotの重複報告。変更責任はsplitterの新しい読取り専用監査と
独立した消費台帳。検証は新規1test fileと全suite。仕様・結果・索引を追加。

B. source関係の推移閉包を入力一致と統合するため、splitter内部のcomponent builderを
確認した。原文/候補の品質判断とは別責任なので、その実装へは拡張していない。
台帳を通常のatomic replacementで上書きすると以前の予約を失い得るため、
失敗時も保持する追記、外部head、排他writer、明示的終端を設計した。

C. 既存dataset/ラベル/model stateの所有者は不変。splitterは隔離集計とtokenを返す。
台帳はそのreceiptのhashとtokenを消費記録に結び付ける。台帳からsplitter internals、
モデル、Gold判定への依存はない。将来の評価器が両責任の公開契約を接続する。
旧割当/除外の意味変更や本番依存は追加していない。

D. 次回は評価手順、`audit_evaluation_partitions`、台帳公開関数、対応testsから開始できる。
類似文joinの内部を再読せず、supplied-historyのみの保証と外部headの保持条件を理解する
必要がある。これらをGold認証・アクセス隔離の保証と混同しないことが新しい契約事項。
