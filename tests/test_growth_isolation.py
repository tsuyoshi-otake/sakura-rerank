from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.growth_isolation import historical_input_metadata, isolate


def row(identity, population, sentence, article=None, context=None):
    return dict(stable_id=identity,population=population,
        input_hash=canonical_json_hash([context or identity,"よみ"]),
        source=dict(article_id=article or identity,paragraph_hash=text_sha256(sentence),
            sentence_hash=text_sha256(sentence),sentence_shingle_hashes=sentence_shingle_hashes(sentence),template_cluster_id=None))


class IsolationTests(unittest.TestCase):
    def test_source_input_transitive_component_quarantines_both_populations(self):
        records=[row("a","train","ABCDEFGHIJ","article-1","shared"),
                 row("b","train","klmnopqrst","article-1"),
                 row("c","evaluation","UVWXYZ12345",context="shared"),
                 row("d","evaluation","あいうえおかきくけこ")]
        excluded,components,report=isolate(records)
        self.assertEqual(excluded,{key:"cross_partition_relation" for key in "abc"})
        self.assertEqual(components["a"],components["b"])
        self.assertEqual(components["a"],components["c"])
        self.assertNotEqual(components["a"],components["d"])
        self.assertEqual(report["counts"]["evaluation/retained"],1)

    def test_near_historical_sentence_and_author_closure_exclude_entire_author(self):
        records=[row("old","historical","abcdefghijklmnopqrst"),
                 row("a","train","abcdefghijklmnopqrstU"),
                 row("b","train","全く別の日本語文章です。")]
        for r in records[1:]:r["source"]["template_cluster_id"]="author-1"
        excluded,_,_=isolate(records)
        self.assertEqual(excluded,{"a":"historical_relation","b":"historical_relation"})
        self.assertEqual(isolate(list(reversed(records)))[0],excluded)

    def test_input_metadata_does_not_deserialize_labels_candidates_or_whole_rows(self):
        source=dict(corpus="jawiki",snapshot_date="2026-08-01",article_id="jawiki-page-1",page_id="1",revision_id="2",paragraph_hash="a"*64,sentence_hash="b"*64,sentence_shingle_hashes=["c"*64],template_cluster_id=None)
        original=json.loads
        data=dict(stable_id="old-1",source=source,reading="よみ",record_type="dataset",session=dict(left_context="前文",left_context_policy="synthetic",session_id="s1"),gold_surface="DO_NOT_DECODE",candidate_snapshots={"private":"DO_NOT_DECODE"})
        def guarded(raw):
            self.assertNotIn(b"DO_NOT_DECODE",raw)
            return original(raw)
        with patch("json.loads",side_effect=guarded):
            result=historical_input_metadata(canonical_json_bytes(data))
        self.assertEqual(result["input_hash"],canonical_json_hash(["前文","よみ"]))
        self.assertNotIn("session",result)

    def test_duplicate_ids_or_invalid_shingles_rejected(self):
        a=row("a","train","abcdef")
        with self.assertRaises(ValueError):isolate([a,a])
        b=deepcopy(a);b["source"]["sentence_shingle_hashes"]=[]
        with self.assertRaises(ValueError):isolate([b])


if __name__ == "__main__": unittest.main()
