# KNBC: 外部評価候補の出典・注釈仕様確認 (#35, parent #1)

**結論: 次の固定済み研究pilot候補に採用する。Gold、学習、calibration、最終Testへの採用ではない。**
採用精度90.72%の改善は未実証。モデル推論、再学習、native要求、元ラベル変更は0件。
安全性0.25%、Gold点99.5%・Wilson95%下限99.0%・最終valid3,000件、Gate A/Bを維持する。

## 今回わかったこと

| 論点 | 確認した根拠 | 判断 |
| --- | --- | --- |
| 原文の由来 | 同梱READMEは81名の大学生に4テーマの記事を依頼したと説明 | Webからの由来不明な転載とは異なる候補。著者と記事の対応は未確認 |
| 注釈 | 提供元は人手による解析済みコーパスと説明。形態素・構文などを含む | Sakura辞書だけから作る読みとは別の根拠になる。個々の読みの誤り率やIME入力意図は未認証 |
| 原表記と修正 | manual.pdf 4.1は、元の誤変換・脱字を残して正しい書き方に基づく注釈とERメモを付ける仕様 | 原表記の完全一致を一律に正解にしない。修正注釈と原表記を別々に保持する |
| 文脈と読み | manual 4.4.1は文脈上の読みと原形を区別。括弧文の抽出仕様も存在 | 形態素境界や文書の前文を、観測したIME入力境界・Sakuraセッション文脈とは扱わない |
| 利用条件 | READMEに使用・再頒布を許す3条項BSD相当の条件 | 著作権表示・条件・免責、名称の宣伝利用制限を保持。データ本体はリポジトリへ含めない |

出典は[公式配布ページ](https://nlp.ist.i.kyoto-u.ac.jp/kuntt/)と、そこからリンクされた
[日付入りUTF-8アーカイブ](https://nlp.ist.i.kyoto-u.ac.jp/kuntt/KNBC_v1.0_090925_utf8.tar.bz2)の
README・仕様書。第三者による人手注釈を、このプロジェクトの独立A/B判定として登録していない。
現在の人手判定・AI言語判定はいずれも0件。

## 実測と未解決の差

配布元の説明は249記事・4,186文。テーマ別は携帯電話79記事/1,278文、京都観光91/1,498、
スポーツ22/522、グルメ57/888。これは提供元の集計であり、今回本文を再計数した値ではない。

アーカイブは4,968,025 bytes、展開後92,175,872 bytes、13,589 entries。
通常ファイル13,334、ディレクトリ254、未追跡のシンボリックリンク1。
`corpus1`配下は4,436ファイルで、249個の`fileinfos`を除くと**4,187個**の文候補ファイルがある。
記事ディレクトリは249個。公式の文数より1個多い理由は、本文を読まずに確定できていない。
余分な1個を恣意的に除外したり、ファイル数を正解文数としたりしていない。

ローカルarchive SHA-256:
`2df066f321f57413dc94404a60273b84a85c67b55fc5d2c8a34926074c1b83a4`。
確認した公式メタデータには暗号学的checksumがなかった。ETagはchecksumとして扱わず、
取得物はHTTPS由来のquarantineに留め、trusted datasetを公開していない。

README 2件・合計6,444 bytesと13ページの仕様書を確認した。
仕様書の全例文をdocumentation exposureとして記録し、将来の独立標本では一致する資料を隔離する。
コーパス本文ファイルの意味的decode・filesystem抽出は0件。本文中の重複や読み品質は未測定。

## 実行・検証

1. `058ef514c3582761e8f7d5d5dd040407e67a3cd9`でplan v1と検査を固定。
   公式GETは完了したが、symlinkを許さない検査が`member_type`で停止。失敗・取得bytesを保存。
2. `c62444e191ec7e9057a8fd19375b2610900b0438`でplan v2を固定。
   同じquarantineを再利用し、リンクを解決せずメタデータとして記録。通常ファイルのREADMEだけを読む。
   hard link・特殊ファイルは引き続き拒否。追加GETは0。
3. `79d1c52e128500a039e87b7e85753a9d34412949`で仕様書露出を予約。
   既存pypdfの文字化け結果を保存し、ブラウザ接続不可も確認。
   `5b52c5b65590b34df208636d5bb4e799791ee703`で固定したPyMuPDFにより13ページを描画し、
   ページ1・5・9の表示と関連本文を確認。新しい専用venvだけにhash固定wheelを導入した。

全**954 tests成功**（新規13、failure/error/skip 0）。7 Pythonファイルの構文・未使用import検査を実施。
別実装のbsdtarで13,589件の順序付き一覧とREADME 2件のbytesを照合。
旧16 artifact・25 fit binding・10 checkpointのhashは不変。
現在のSakura Inputを実行・変更しておらず、productionとの互換性を新たに認証した結果ではない。

再現の入口は`qualify_knbc.py inspect/verify`と`run_owned.py`。既存の予約・結果は上書き不可。
実行したv1/v2のcodeとplanは上記commitで取得し、再実行には別の出力先を固定する。
現在のsynthetic testsは次で実行できる。

```powershell
$env:PYTHONPATH = 'src;.'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest discover -s tests -p test_knbc_documentation.py
```

結果は[集計JSON](../../reports/issue-35-knbc-qualification-v1.json)、
後処理・追跡検証は[verification JSON](../../reports/issue-35-knbc-qualification-verification-v1.json)。
quarantine、失敗記録、仕様書、露出台帳はignoredの
`data/generated/issue-35-knbc-qualification-v1/`に保存する。

## 次に進める範囲と費用

**優先1: 最大100文・20記事のsource-format pilotを、本文を開く前に固定する。**
これは元の1,000件Gold pilotや最終品質保証を代替しない。元ラベルを変更せず、選択枠の失敗も残す。

- KNPの表層・読み・原形・ERの対応と、4,187対4,186の差を確認する。
- 仕様書例文、記事・著者、既存source/input/historyを隔離条件に入れる。未知の対応を独立性とみなさない。
- 修正情報のない原表記、明示的な誤記、表記意図の不確定を分け、読み・入力単位の採用可能数を測る。
- 費用上限は100固定枠・20記事群。fit・閾値選択・最終Testを含めない。
  期待効果は辞書読み由来・原文完全一致由来の誤ラベルを減らせるかの検証で、精度上昇率は未予測。

Tatoebaは既に1,100文を消費しており新規未使用資料ではない。
GSDの固定READMEでは注釈の許諾と元テキストの権利、語彙の読みと表層の読みを区別する必要がある。
既存KWDLC public-train予約は消費済み。これらを新しい独立Testへ読み替えない。
Mozcへの限定検索は結果なしで、データの確認・採用は行っていない。

## Scope / IRV

- **A: 実際の範囲** — source qualificationの6 scripts、3 frozen plans、tool lock/manifest、1 test module、
  README・集計レポート。既存data contractと歴史的integrity checkerを消費者側の契約として参照した。
- **B: 拡張理由** — archive link、PDF文字コード、公式文数とファイル数の差により、
  安全な文書アクセス・別renderer・メタデータ照合が必要になった。本文・モデル内部には広げていない。
- **C: 責任と状態** — researchディレクトリが文書確認を所有し、quarantineと露出台帳をwrite-onceで保持。
  production API・学習データconsumer・既存split・Gold gateの意味や依存関係は変更していない。
- **D: 次回の読取量** — 取得元・条件・文書hash・ER注意点・実数を再調査する必要はない。
  次のpilotはKNP field契約、注釈と原文の対応、完全な露出履歴を読む必要がある。
