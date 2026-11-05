# 原注釈再現の弱教師・数値準備方針 v1

Parent #1 / Issue #33 / Related #31, #32, #49

目的は、#54で候補条件を満たした35,592件について、原注釈のliteral表記を候補から再現する研究用の数値入力を準備し、その全入力を許可段落と認証済み候補へ追跡すること。実IMEの唯一の正解、意味対比、独立Gold、Gate A/Bを認証する方針ではない。

## この工程で許可する消費

- #53の許可段落receiptと#54の最終検証に結び付く、全35,592件の数値生成・読取り検証だけ。旧pool/数値cache/body pretraining/checkpointからのデータ補完はしない。
- 原左文脈8–64文字、原注釈の読み2–32文字、literal対象1–32文字、認証済みの同じ読みのTop-6候補をそのまま用いる。原sourceは変更せず、読み推測、suffix補完、NFKC置換、許容表記の追加を行わない。
- model encoderへ渡す行はstable ID/component/corpusとleft_context/reading/target/request IDだけに射影する。右側source、境界観測、原文全文、著者情報、review flagsは特徴量に渡さない。候補もsurface/local cost/source category/segment source categoriesだけに射影し、その前に元のfull-reading snapshotを認証する。
- 既存C2の文字hash/長さ/Top-6/7特徴量契約を固定する。padding、mask、source-target indexを含む全tensorを別計算で照合する。数値キャッシュは全件新規生成し、旧cacheをコピーしない。

## 品質と学習実行を混同しない

元recordの`training_eligible=False`と`independent_gold_eligible=False`は変更しない。数値arrayの`gold`という既存互換keyは、この課題の原表記候補indexであり、独立Goldの判定を意味しない。source fidelityと原読み注釈は証拠として保持し、IME入力単位・意味/用法・表記意図は未解決のまま記録する。

この工程はモデルfit、モデル推論、eval/calibration/Test作成、body pretraining、checkpoint再利用を許可しない。後続の研究fitには、cache/検証/本policyのhash、課題の範囲、未解決品質の扱い、source比・件数・更新予算、未使用研究評価を別planで固定する必要がある。#48の意味対比の品質条件を、原表記再現で代用しない。Wikipediaの混合は同じ消費範囲での認証が済むまで行わない。

人手・AIの判定を生成したことにはしない。AI補助が必要になった場合は別の`ai_teacher`履歴とし、人手や独立性の証拠を捏造しない。Gold99.5%点推定・Wilson95%下限99.0%・最終valid3,000件、安全性0.25%、最終Test一回限り、採用モデルは不変。

## 証拠・失敗・後続利用

全原注釈132,729枠、抽出後101,625、段落隔離後93,973、候補条件通過35,592の分母を保持する。辞書外や欠落を置換せず、条件非通過58,381件を別終端に残す。

各数値行は原row/paragraph consumption/snapshot/projectionとtensorのhashを持つappend-only chainにする。外側manifestが件数・終端hash・ファイルSHA-256・array schema・policyを固定し、欠落・順序変更・改変・末尾切落しを検出する。失敗は明示終端とし、部分cacheを検証済みと公開しない。

保存直後は`prepared_unverified`。別計算による全tensor検証と保存byteの照合後に、別のwrite-once検証receiptを作る。読取り側はmanifestと検証receiptの期待hashを外部planから受け取り、許可された数値検証purposeだけを認める。自己申告passや、hash未固定のcacheを学習許可にしない。
