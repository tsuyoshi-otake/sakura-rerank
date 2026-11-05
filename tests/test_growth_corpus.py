from collections import Counter
import json
import unittest
from unittest.mock import patch

from sakura_rerank.data import growth_corpus as growth
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash, text_sha256


def metadata(work, author="1", **changes):
    row = {"作品ID":str(work), "人物ID":author, "役割フラグ":"著者", "作品著作権フラグ":"なし",
        "人物著作権フラグ":"なし", "文字遣い種別":"新字新仮名", "分類番号":"NDC 913",
        "テキストファイルURL":f"https://www.aozora.gr.jp/cards/000001/files/{work}_txt.zip",
        "テキストファイル符号化方式":"ShiftJIS"}
    return dict(row, **changes)


def source():
    return dict(corpus="jawiki",snapshot_date="2026-08-01",article_id="jawiki-page-1",page_id="1",
        revision_id="2",paragraph_hash="a"*64,sentence_hash="b"*64,
        sentence_shingle_hashes=["c"*64],template_cluster_id=None)


class GrowthCorpusTests(unittest.TestCase):
    def test_history_only_decodes_source_object(self):
        line=canonical_json_bytes(dict(stable_id="old-1",source=source(),gold_surface="UNSEEN",
            candidate_snapshots={"unread": "CANDIDATES"}))
        original=json.loads
        def guarded(raw):
            self.assertNotIn(b"UNSEEN",raw)
            self.assertNotIn(b"CANDIDATES",raw)
            return original(raw)
        with patch("json.loads",side_effect=guarded):
            self.assertEqual(growth.history_metadata(line)["source"],source())

    def test_history_rejects_duplicates_and_unknown_source_fields(self):
        line=canonical_json_bytes(dict(stable_id="old-1",source=source()))
        for bad in (line+line,line.replace(b'"source":',b'"foreign":'),canonical_json_bytes(dict(stable_id="old-1",source=dict(source(),extra=1)))):
            with self.assertRaises(ValueError):growth.history_metadata(bad)

    def test_source_partition_and_sampling_use_frozen_hash_contract(self):
        for n in range(100):
            key=str(n)
            expected="evaluation" if int(canonical_json_hash([20261105,"aozora",key,"partition"]),16)%10<2 else "train"
            self.assertEqual(growth.partition("aozora",key),expected)
            self.assertEqual(growth.wiki_page_selected(key),int(canonical_json_hash([20261105,"jawiki",key,"sample"]),16)%100==0)
            self.assertEqual(growth.wiki_page_selected(key,1),int(canonical_json_hash([20261105,"jawiki",key,"sample"]),16)%100==1)
            self.assertFalse(growth.wiki_page_selected(key) and growth.wiki_page_selected(key,1))
        with self.assertRaises(ValueError):growth.wiki_page_selected("1",100)

    def test_metadata_selection_ignores_order_and_excludes_rights_or_duplicate_rows(self):
        authors={p:next(str(i) for i in range(1,100) if growth.partition("aozora",str(i))==p) for p in ("train","evaluation")}
        rows=[metadata(i,authors["train" if i<20 else "evaluation"]) for i in range(40)]
        expected,report=growth.select_aozora(rows,4,4)
        self.assertEqual(expected,growth.select_aozora(list(reversed(rows)),4,4)[0])
        forbidden=expected[0]["work_id"]
        modified=[dict(r,作品著作権フラグ="あり") if r["作品ID"]==forbidden else r for r in rows]
        self.assertNotIn(forbidden,{r["work_id"] for r in growth.select_aozora(modified,4,4)[0]})
        self.assertNotIn(forbidden,{r["work_id"] for r in growth.select_aozora(rows+[next(r for r in rows if r["作品ID"]==forbidden)],4,4)[0]})
        self.assertEqual(report["selected_partitions"],{"train":4,"evaluation":4})
        with self.assertRaises(ValueError):growth.select_aozora(rows,9,4)

    def test_aozora_keeps_ruby_base_and_quarantines_annotation_without_joining(self):
        raw=("TITLE\n"+"-"*30+"\nnotes\n"+"-"*30+"\n前の｜文章《ぶんしょう》。\n東京［＃外字］大学。\n次の文章。\n底本：book\nPRIVATE FOOTER").encode("cp932")
        paragraphs,counts=growth.aozora_paragraphs(raw)
        self.assertEqual(paragraphs,["前の文章。","次の文章。"])
        self.assertEqual(counts["annotation_or_gaiji_line_quarantined"],1)
        with self.assertRaises(ValueError):growth.aozora_paragraphs(raw.replace("底本：".encode("cp932"),b"none:"))

    def test_extractor_uses_only_bounded_prior_context_and_complete_document_hash_order(self):
        dictionary=[dict(surface="文章",readings=["ぶんしょう"])]
        extractor=growth.GrowthExtractor(dictionary)
        paragraphs=["あ"*80+"文章。", "別の文章。", "後の文章。"]
        rows=extractor.document(paragraphs,"aozora","1","v1","train",2,Counter())
        all_rows=extractor.document(paragraphs,"aozora","1","v1","train",10,Counter())
        self.assertEqual(rows,sorted(all_rows,key=lambda r:r['stable_id'])[:2])
        first=next(r for r in all_rows if r['source']['paragraph_hash']==text_sha256(paragraphs[0]))
        self.assertEqual(first['left_context'],"あ"*64)
        self.assertFalse(first['independent_gold_eligible'])
        self.assertEqual(first['label_kind'],'source_exact_weak_supervision')
        changed=extractor.document([paragraphs[0]+"未来の別文。"],"aozora","1","v1","train",10,Counter())[0]
        self.assertEqual(first['left_context'],changed['left_context'])
        self.assertEqual(first['target'],changed['target'])


if __name__ == "__main__":
    unittest.main()
