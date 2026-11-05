# 原注釈抽出方式の研究比較方針 v1

Parent #1 / Issue #33 / Related #31, #32, #49

比較するのは、青空文庫の辞書一致抽出と原ルビbase抽出という**抽出方式全体**である。読みだけでなく入力単位、読み/表記の分布、難易度も変わるため、純粋な読み品質だけの因果効果とは呼ばない。両方式とも原表記を再現する弱教師であり、実IMEの唯一の正解や意味対比の認証ではない。

## 同じ消費範囲で比較する

1. 前段で認証した全歴史metadataと元833,600-node inventoryを保持する。旧pool、旧除外、元label、split、modelは変更しない。
2. 辞書抽出側は#41で許容された原文fragmentのみを候補とする。原注釈側は#55の35,592行のみを候補とする。どちらも元原文のparagraph/revision/位置/context/targetを検証する。Wikipediaは元dumpの対象ページから必要な原段落を復元し、全sentence coverageを作る。本文全部をモデルへ入力しない。
3. Wikipediaの新しい段落coverageを元inventoryへ加え、article/author/inputのidentity relationと、paragraph/exact sentence/near sentence/inputのcontent relationで全歴史へ接続する段落を隔離する。#53の既存隔離段落を復帰させない。
4. 実際に消費するのは隔離されていない原段落の左文脈と対象だけ。青空文庫は#53の許可coverage、Wikipediaは今回復元したcoverageを用いる。候補入力全体について全関係を再構築する。旧representative edgesの間引きはしない。歴史に接続する入力は採用しない。
5. fixed C2のTop6でexact targetが一意に存在し、全入力/候補が長さ上限内の行だけを使う。各群はWikipedia25,000＋青空25,000、stable ID昇順で選ぶ。Wikipediaは両群で同一行・同一順序。候補欠落を読み推測や別表記で補わず、固定件数に足りなければ停止する。

候補取得は保存済みの認証されたsnapshotだけを使う。原row、実際の消費範囲、candidate、projection、tensorを結ぶ証拠を別artifactへ保存する。特徴量にはbounded left context、reading、candidate surface/cost/source/segment categoriesだけを渡す。右文脈・author・境界フラグ・review metadataは使わない。

## 弱教師の扱い

原recordのGold/training flagsを昇格させない。辞書一致は辞書由来の弱い読み証拠、原ルビは原注釈由来の読み/範囲証拠として区別する。IME境界、語義・用法、表記意図は未解決のまま保存する。旧cache、隔離本文、追加body pretrainingで不足を埋めない。#48の意味対比品質条件を満たしたと主張しない。

別のfit bindingがplan/policy、各群の全数値/provenance/検証receipt、初期#29重みと実装をcommitで固定し、全開始条件を満たした場合に限り、この課題専用の研究fitを実行できる。#55の数値検証receipt単体はfitの許可ではない。実際の6fitは同一C2、同じ初期重み、3seed、500更新、batch256、同じ損失/optimizerで固定する。途中評価・best-seed選択・閾値探索・学習回数追加はしない。

## 未使用研究評価と採否

未使用のKWDLC public-train membershipから、既露出2,300文書を除いた1000文書を本文取得前にhashで予約する。public dev/testとリリース用最終Testは使用しない。全歴史、両訓練群、今回消費するsource coverageとの分離を確認し、原注釈による対象を固定する。KWDLCは評価専用で、学習や語彙補完には使わない。原権利者の許諾と元URLの制限は未解決のままで、再配布しない。

主評価は3seed平均の原表記一致率の差（原注釈方式−辞書方式）1比較。source componentを単位とする同じbootstrap drawを全seedへ適用し、平均差の95%区間を出す。全seedの点差が非負かつ平均差の下限が正なら、後続研究の候補として進める。各seedの差と区間、救済/破壊、Precision/Recall、適用率、空/シャッフル文脈、全対比も記録するが、事後選択に使わない。合格しなければ現行を維持する。

これは独立Goldやproduction採用ではない。Gold点推定99.5%以上・Wilson95%下限99.0%以上・最終valid3,000件、安全性0.25%、最終Test一回限り、Gate A/Bと本番統合の条件は不変。原注釈再現の改善からリリース条件を飛ばさない。
