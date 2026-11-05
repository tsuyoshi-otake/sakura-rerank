import unittest

from sakura_rerank.data.context_source_isolation import isolate_with_source_coverage
from sakura_rerank.data.contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.growth_isolation import isolate


def row(key, population, article, sentence, input_key=None):
    result=dict(stable_id=key,population=population,source=dict(article_id=article,
        paragraph_hash=text_sha256(sentence),sentence_hash=text_sha256(sentence),
        sentence_shingle_hashes=sentence_shingle_hashes(sentence),template_cluster_id=None))
    if input_key is not None:result["input_hash"]=canonical_json_hash(input_key)
    return result


class ContextSourceIsolationTests(unittest.TestCase):
    def test_unselected_source_unit_can_quarantine_target_elsewhere_in_document(self):
        records=[row("history","historical","old","共通する文章を含む出典です"),
                 row("source","source_coverage","new","共通する文章を含む出典です"),
                 row("target","evaluation","new","別の文から対象を取りました","input")]
        excluded,components,counts=isolate_with_source_coverage(records)
        self.assertEqual(excluded,{"target":"historical_relation"})
        self.assertEqual(set(components),{"target"})
        self.assertEqual(counts["source_only_nodes"],1)

    def test_neutral_source_is_not_history_and_does_not_invent_input_edges(self):
        records=[row("s1","source_coverage","one","第一の独立資料について説明"),
                 row("s2","source_coverage","two","海の潮流と気象を観測した"),
                 row("a","evaluation","one","第一の独立資料について説明","a"),
                 row("b","evaluation","two","海の潮流と気象を観測した","b")]
        excluded,components,counts=isolate_with_source_coverage(records)
        self.assertEqual(excluded,{})
        self.assertNotEqual(components["a"],components["b"])
        self.assertEqual(counts["source_only_input_edges"],0)
        self.assertEqual(counts["exact_input_duplicate_groups"],0)

    def test_source_only_node_with_an_input_hash_is_rejected(self):
        with self.assertRaises(ValueError):
            isolate_with_source_coverage([row("s","source_coverage","one","元の文章","fake-input")])

    def test_real_new_input_still_requires_its_input_identity(self):
        with self.assertRaises(ValueError):
            isolate_with_source_coverage([row("s","evaluation","one","元の文章")])

    def test_input_edges_and_train_evaluation_quarantine_are_preserved(self):
        records=[row("a","train","one","学習用の独立した資料です","same-input"),
                 row("b","evaluation","two","外部の評価資料から取得","same-input")]
        expected=isolate(records)
        actual=isolate_with_source_coverage(records)
        self.assertEqual(actual[:2],expected[:2])
        self.assertEqual(actual[0],{"a":"cross_partition_relation","b":"cross_partition_relation"})


if __name__=="__main__":unittest.main()
