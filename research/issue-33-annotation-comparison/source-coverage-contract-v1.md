# 完全な出典照合とモデル入力の上限を分離する

全体の比較条件は[plan v2](plan-v2.json)と[policy v1](policy-v1.md)のまま。
原文復元162,502件とその別検算は完了した。混合scopeの初回検査は、Wikipediaの132,289個のsource-only nodeのうち1個が515個のsignatureを持ち、旧metadata validatorの512個上限に収まらず停止した。原row、候補、モデル入力の上限違反ではない。

この段階では、**source-only nodeに限り1,024個までの完全なsignatureを保持する新しい版の検査契約**を使う。既存の512個上限を持つvalidatorと全旧成果物は変更しない。新validatorはneutral nodeの厳密な3field schema、ID、出典identity、hash書式、unique/sorted signatureと上限を全件確認する。real inputを持つhistorical/train/evaluation nodeには既存のvalidatorをそのまま使う。

完全なsentence signatureを切り詰めたり、問題の文/段落/記事を捨てたり、窓へ置き換えて旧relationを失ったりしない。新しい1,024個上限を超えた場合も明示的な失敗とし、部分的なtrusted scopeを公開しない。1,024個は新しい出典metadataの資源上限であり、モデルの文脈64・読み32・候補32、Top6、学習件数、品質判定の変更ではない。

relation生成は固定済みのarticle/author/input/paragraph/exact/near coreを再利用し、Jaccard 0.8、1,000,000 nodes、4,000,000 recorded edgesは維持する。旧範囲の入力では元graphと同じtyped edgesになること、515-signatureのneutral nodeが歴史とのnear関係を保持すること、real inputの512上限やneutralの架空input禁止が変わらないことをテストする。

保存済みの元source paragraphとcoverageをそのまま使い、原Wikipedia dumpの再読取りや原文・ラベルの書換えはしない。失敗したscopeのreservation/結果を保持し、新scopeは別rootに保存する。前段のsource復元・別検算は、それを実行したcommit/receiptへ結び付ける。

この修正は数値や学習を先に進める許可ではない。全source/input closure、固定quota、全数値/provenance検証、未使用研究評価と別fit bindingが必要。安全性0.25%、独立Gold、Gate A/B、最終Testは不変。
