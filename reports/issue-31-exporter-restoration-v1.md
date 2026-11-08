# 固定変換環境の復旧結果 (#31 / #32)

2026-11-04。親 #1、元のexporter実装 #3。新たなGold認証・モデル評価・本番変更ではない。

## 到達点

**固定辞書は完全復旧した。旧exporterの同一性は復旧できていない。**
旧辞書・旧変換器として別物を使うことを避け、未測定の50件は未測定のまま保持した。

| 対象 | 結果 |
| --- | --- |
| 固定辞書 | 38,456,565 bytes、SHA-256 `6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad`。既存identityと完全一致 |
| 旧Sakura Input HEAD | ローカル本体・関連checkoutにobjectなし。GitHub commit APIも422 / No commit found。消失原因は未確定 |
| 復旧候補ソース | `5eefa2ffe15297e563da281432cece56049a1b09`。過去監査の8ソースfingerprintが一致。辞書報告はCRLF化すると既存hash一致 |
| 復旧候補のビルド | 3回成功し、すべて `8e87dfc190085636266f40fa0d1baf8944517bacb8fe933317ba597c260c9a3d`。旧hash `0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf` と異なる |
| 50件のforward照合 | 実行0。Oracleはnullを維持 |

8ファイルの一致は、旧コミットの全tree一致を証明しない。候補ソースの出力が
3回一致することも、旧バイナリの復旧・候補出力の同値性を証明しない。
LF/CRLFを変えても同じバイナリだったため、今回の差の原因として改行差は否定できる。
正確な差の原因は特定できていない。過去manifestにはRust/Cargo等のpinはあるが、
MSVC linkerとWindows SDKの版はない。この記録不足が原因だとは断定しない。

## 辞書の回収と出所

[既存v1.0.0リリース](https://github.com/tsuyoshi-otake/sakura-input/releases/tag/v1.0.0)の
`sakura_setup.exe` を取得した。公式asset metadataの10,843,801 bytesとSHA-256
`9800e19b8bb6ab25ae3d3dfe4089218d44c84b376b6af30ccb52c33a657c66b8` に一致した。
**インストーラーを起動せず**、内部の辞書を静的に抽出した。

既存tar/7-ZipではこのInno Setup 6.7.0コンテナを開けなかったため、
[innoextract Windows build 670](https://github.com/UserUnknownFactor/innoextract_win/releases/tag/670)
を作業用一時ディレクトリで使用した。2026-02-23公開で3日制約を満たす。
archive SHA-256は `79b69b9b1fcd98f42ccd4b245efdf6a03bcfb674ba6af482f5a46891c9ed4d14`、
実行ファイルhashは集計JSONに保存した。製品依存・常設ツールには追加していない。
最初のpath filterは対象0件となったため、成功終了コードだけで回収済みとせず、
別出力先への抽出後にファイル数1・サイズ・辞書hashを検証した。
辞書に同梱されたsource lock・第三者notice/licenseとSakura Input LICENSEの計6ファイルも
原bytesで保持し、hashを記録した。新しい再配布権限を推定していない。

## ビルド実験の履歴

`recover_exporter.py` は既存Git objectsをarchiveし、作業専用ディレクトリで実行する。
新しいgit worktreeや本体checkoutの変更は不要。元exporterソースは
`06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1`、patch/lock/toolchainは旧manifestの値を固定した。
Cargoはoffline/locked、2 jobs、各600秒上限。identity allowlistを書き換えない。

1. 初回は必要な `include_str!` 用TOMLを3ファイルarchive対象から漏らして失敗した。
   構成不足であり、ソースやコンパイラの故障とは扱わない。初回receipt/logも保存した。
2. 同じGit commitから3ファイルを加えたLF版がビルド成功。旧binary hashとは不一致。
3. 別ディレクトリでRust/TOMLをCRLFにしてビルド。2と同一hashで旧binaryとは不一致。
4. 保存した再現scriptを新しいディレクトリで実行。2・3と同一hash。
   scriptは`built_different_binary`、意図した終了コード3で認証を拒否した。

元の不足物・初回失敗・測定版は、既存の固定成果物に上書きしていない。
保存した候補binaryは`unverified-recovery-exporter.exe`であり、旧HEADを埋め込んだ
元exporterの実行用コードを含むため、変換や学習データ生成には使っていない。

## 再現・受入確認

| Verify | Expect |
| --- | --- |
| `python -X utf8 research/issue-31-quality/recover_exporter.py --output <USERPROFILE/tmp/新規専用dir> --checkout-eol lf` | この環境では旧hashと異なる測定hash、`built_different_binary`、終了コード3。allowlist変更なし |
| 同じcommandを既存出力dir、またはtmp外のpathで実行 | ビルド前に拒否、既存ファイル不変、新規dir生成なし |
| 固定辞書を`Get-FileHash -Algorithm SHA256`で照合 | 上表の固定hashと一致 |
| `PYTHONPATH=src python -m unittest discover -s tests -v`（外側timeout 300秒） | 426 tests中421成功、任意PyTorch依存5 skip、失敗0 |
| 旧33artifactと前回probe artifactのhash比較、構文compile、`git diff --check`、終了後process監査 | 全入力不変、構文・diff問題なし、今回のbuild/test/extraction runner残存0 |

PowerShellのPYTHONPATH設定は `$env:PYTHONPATH='src'`。
集計は[復旧JSON](issue-31-exporter-restoration-v1.json)、実測tests・hash確認は
[検証JSON](issue-31-exporter-restoration-verification-v1.json)。
再開用辞書・未認証binary・全試行receipt/logはignored
`data/generated/issue-31-exporter-restoration-v1/` に保持する。ダウンロードinstaller、
展開ツール、ソース展開、ビルドcache等の一時物は本工程末に削除する。

## 次の実施単位

[再確立仕様](../research/issue-31-quality/exporter-reestablishment-plan-v1.json)を、新identityの
実装・converter実行前に固定した。実在するソースHEADを正しく記録した別の研究用
identityを作り、独立2 buildと、事前選択した最大100件の旧train snapshotとの
全候補・segment・cost・fingerprint・終端状態の一致を検証する。元dev/Testは使わない。
有限の回帰一致を旧binaryの全面同値性とは呼ばず、新しい研究基準として記録する。
差が出れば50件probeへの採用を止め、原因を調査する。

期待効果は独立読み50件の候補存在率を測定できる状態への復旧。費用上限は
独立2 build（各600秒）、最大100 train request、50件probeの2回実行（各120秒）、
関連契約と全tests。Gold品質保証、再学習、Gate A/B通過を代替しない。
旧validator/allowlist、元データ・モデル、0.25%基準、Test利用回数は維持する。

## 必要範囲と設計影響（IRV）

A. 既存build/exporter契約、data契約、source fingerprint、公開releaseのartifact metadata、
研究用再現scriptが必要だった。B. 旧commitとbinaryが欠落していたため、所在確認から
Git履歴・source archive・installer内辞書の静的回収まで広がった。
C. 今回の新挙動は研究用復旧scriptが所有し、測定状態は追記するreceiptが所有する。
既存validator/モデル/本番への依存や意味変更はない。
D. 次回は回収済み固定辞書と実在するsource commit、3回一致した未認証測定版、
再確立仕様から開始できる。旧commit同一性を推測する探索は繰り返さず、新identityと
過去candidateとの互換性を明示的に検証する必要がある。
