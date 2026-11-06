"""Keep every source slot and distinguish whole ranks from compositional oracles."""
import importlib.util
from pathlib import Path
import sys
import unittest

from sakura_rerank.data.tatoeba_input_units import build_source_units

HERE=Path(__file__).resolve().parents[1]/'research/issue-35-source-units'
sys.path.insert(0,str(HERE))
try:
    spec=importlib.util.spec_from_file_location('unit35_metric_contract',HERE/'unit_native.py')
    metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
finally:sys.path.pop(0)


class SourceUnitMetricTests(unittest.TestCase):
    def test_unsupported_and_missing_slots_stay_in_all_denominators(self):
        rows=[dict(build_source_units('橋。','[橋|はし]。'),stratum='named_editor'),
              dict(build_source_units('字','[字|]'),stratum='no_editor')]
        result=metrics.aggregate_units(rows,{})
        for name in metrics.VIEWS:
            count=result['by_stratum_view']['all/'+name]
            self.assertEqual(count['slots'],2)
            self.assertEqual(count['unmeasured'],1)
            self.assertEqual(count['source_unresolved'],1)
            self.assertNotIn('source_supported_at_1',count)

    def test_ruby_support_does_not_become_whole_source_rank(self):
        row=dict(build_source_units('橋へ。','[橋|はし]へ。'),stratum='named_editor')
        snapshots={p['request_id']:[] for view in row['views'].values() for p in view['parts'] if p['kind']=='convert'}
        ruby=row['views']['ruby_fragments']['parts'][0]
        snapshots[ruby['request_id']]=[{'surface':'橋'}]
        result=metrics.aggregate_units([row],snapshots)
        self.assertEqual(result['by_stratum_view']['all/ruby_fragments']['source_supported_at_1'],1)
        self.assertEqual(result['by_stratum_view']['all/whole_source']['source_supported_at_32'],0)
        self.assertEqual(result['whole_miss_comparison']['ruby_fragments/all_parts_supported'],1)

    def test_missing_or_extra_view_is_rejected(self):
        row=dict(build_source_units('橋','[橋|はし]'),stratum='named_editor')
        del row['views']['ruby_fragments']
        with self.assertRaisesRegex(ValueError,'view_contract'):metrics.aggregate_units([row],{})


if __name__=='__main__':unittest.main()
