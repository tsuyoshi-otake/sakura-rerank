"""Source support retains failed slots and distinguishes partial observations."""
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]/'research/issue-35-source-consumption'
sys.path.insert(0, str(HERE))
try:
    spec = importlib.util.spec_from_file_location('consumption_metric_contract', HERE/'native_consumption.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
finally:
    sys.path.pop(0)


def row(parts, *, status='ready', stratum='named_editor'):
    return dict(stratum=stratum,status='ready_source_hypothesis',
                inputs=[dict(p,stable_id='input-'+str(i)) for i,p in enumerate(parts)],
                view=dict(status=status,parts=[dict(p,kind='convert') for p in parts]))


class SourceConsumptionMetricTests(unittest.TestCase):
    def test_partial_native_failure_keeps_slot_unmeasured_but_counts_observed_parts(self):
        value=row([dict(request_id='a',target='橋'),dict(request_id='b',target='道')])
        result=module.aggregate([value],{'a':[dict(surface='橋')]},{})['all']
        self.assertEqual(result['slots'],1)
        self.assertEqual(result['unmeasured'],1)
        self.assertEqual(result['measured_parts'],1)
        self.assertEqual(result['unmeasured_parts'],1)
        self.assertNotIn('all_parts_at_32',result)

    def test_full_observation_can_be_source_miss(self):
        value=row([dict(request_id='a',target='橋')])
        result=module.aggregate([value],{'a':[dict(surface='箸')]},{})['all']
        self.assertEqual(result['measured'],1)
        self.assertEqual(result['all_parts_at_32'],0)
        self.assertNotIn('unmeasured',result)

    def test_failure_is_not_removed_from_editor_or_total_denominator(self):
        failed=dict(stratum='no_editor',status='invalid_source_fields',view=None,inputs=[])
        result=module.aggregate([failed],{}, {})
        for group in ('all','no_editor','no_input_hypothesis'):
            self.assertEqual(result[group]['slots'],1)
            self.assertEqual(result[group]['invalid_source_fields'],1)

    def test_history_slice_does_not_remove_full_population(self):
        value=row([dict(request_id='a',target='橋')])
        result=module.aggregate([value],{'a':[dict(surface='箸'),dict(surface='橋')]},{'input-0':'historical_relation'})
        for group in ('all','historically_related','named_editor'):
            self.assertEqual(result[group]['slots'],1)
            self.assertEqual(result[group]['all_parts_at_1'],0)
            self.assertEqual(result[group]['all_parts_at_5'],1)


if __name__=='__main__':unittest.main()
