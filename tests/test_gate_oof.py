"""Synthetic OOF boundaries: no real source strings, labels or model execution."""
import hashlib
import unittest

from sakura_rerank.gate_oof import component_folds,nested_schedule,score_exposure


def h(value):return hashlib.sha256(str(value).encode()).hexdigest()


def identity(i,component=None,original=None,numeric=None,group='source'):
    return dict(row_key=h(('row',i)),component_key=h(('component',i if component is None else component)),
        original_input_key=h(('original',i if original is None else original)),numeric_input_key=h(('numeric',i if numeric is None else numeric)),group=group)


def model(fit=(),selection=(),parents=(),complete=True):
    return dict(fit_components=[h(x) for x in fit],selection_components=[h(x) for x in selection],parents=[h(x) for x in parents],lineage_complete=complete)


class ComponentFoldTests(unittest.TestCase):
    def test_transitive_component_original_and_numeric_links(self):
        rows=[identity(0,component=0),identity(1,component=0,original=1),identity(2,original=1,numeric=2),identity(3,numeric=2),identity(4)]
        result=component_folds(rows)
        self.assertEqual(sorted(result['component_sizes'].values()),[1,4])
        self.assertEqual(len({result['row_fold'][r['row_key']] for r in rows[:4]}),1)

    def test_order_and_field_order_do_not_change_partition(self):
        rows=[identity(i,component=i//3) for i in range(23)]
        self.assertEqual(component_folds(rows),component_folds([dict(reversed(list(r.items()))) for r in reversed(rows)]))

    def test_duplicate_rows_rejected(self):
        with self.assertRaises(ValueError):component_folds([identity(1),identity(1)])

    def test_label_or_unbound_fields_rejected(self):
        with self.assertRaises(ValueError):component_folds([{**identity(0),'label':'fixture'}])

    def test_hash_group_and_fold_bounds(self):
        for field in ('row_key','component_key','original_input_key','numeric_input_key'):
            with self.assertRaises(ValueError):component_folds([{**identity(0),field:'not-a-hash'}])
        for count in (True,1,11):
            with self.assertRaises(ValueError):component_folds([identity(0)],count)
        with self.assertRaises(ValueError):component_folds([])
        with self.assertRaises(ValueError):component_folds([{**identity(0),'group':'source / raw'}])

    def test_giant_component_preserved_with_empty_folds(self):
        result=component_folds([identity(i,component=0) for i in range(30)])
        self.assertEqual(result['fold_sizes'],[30,0,0,0,0])
        self.assertFalse(result['fit_permission']);self.assertFalse(result['independent_source_certified'])

    def test_source_counts_reconcile_without_stratifying_labels(self):
        rows=[identity(i,group='a' if i%2 else 'b') for i in range(17)]
        result=component_folds(rows)
        self.assertEqual(sum(result['fold_sizes']),17)
        self.assertEqual(sum(g.get('a',0) for g in result['fold_group_counts']),8)
        self.assertEqual(sum(g.get('b',0) for g in result['fold_group_counts']),9)


class ScoreExposureTests(unittest.TestCase):
    def check(self,models,excluded=('outer',)):
        return score_exposure(h('candidate'),{h(x) for x in excluded},{h(k):v for k,v in models.items()})

    def test_complete_disjoint_lineage(self):
        r=self.check({'candidate':model(fit=('train',),parents=('base',)),'base':model()})
        self.assertTrue(r['oof_eligible']);self.assertEqual(r['known_models_visited'],2)

    def test_direct_fit_overlap(self):
        r=self.check({'candidate':model(fit=('outer',))})
        self.assertEqual(r['status'],'overlap');self.assertEqual(r['fit_overlap_components'],1)

    def test_initialization_and_teacher_exposures_propagate(self):
        for name in ('initialization','teacher'):
            r=self.check({'candidate':model(parents=(name,)),name:model(fit=('outer',))})
            self.assertFalse(r['oof_eligible']);self.assertEqual(r['fit_overlap_components'],1)

    def test_selection_exposure_propagates(self):
        r=self.check({'candidate':model(parents=('selected',)),'selected':model(selection=('outer',))})
        self.assertFalse(r['oof_eligible']);self.assertEqual(r['selection_overlap_components'],1)

    def test_missing_and_incomplete_ancestry_are_not_clean_roots(self):
        for models in ({'candidate':model(parents=('missing',))},{'candidate':model(complete=False)}):
            r=self.check(models);self.assertEqual(r['status'],'unknown_lineage');self.assertFalse(r['lineage_complete'])

    def test_cycle_and_malformed_lineage_rejected(self):
        with self.assertRaises(ValueError):self.check({'candidate':model(parents=('base',)),'base':model(parents=('candidate',))})
        with self.assertRaises(ValueError):self.check({'candidate':{**model(),'lineage_complete':1}})
        with self.assertRaises(ValueError):self.check({'candidate':model(parents=('base','base'))})

    def test_nested_gate_leak_even_when_own_prediction_fold_absent(self):
        models={'candidate':model(fit=('outer','other'))}
        self.assertTrue(self.check(models,('inner',))['oof_eligible'])
        self.assertFalse(self.check(models,('outer','inner'))['oof_eligible'])

    def test_shared_ancestor_counted_once(self):
        r=self.check({'candidate':model(parents=('a','b')),'a':model(parents=('root',)),'b':model(parents=('root',)),'root':model()})
        self.assertEqual(r['known_models_visited'],4)


class NestedScheduleTests(unittest.TestCase):
    def test_outer_labels_absent_from_every_inner_generator(self):
        schedule=nested_schedule()
        for outer in schedule['outer_folds']:
            k=outer['gate_test_fold']
            self.assertNotIn(k,schedule['ranker_jobs'][outer['test_score_job']]['training_folds'])
            for inner in outer['gate_training_scores']:
                trained=schedule['ranker_jobs'][inner['score_job']]['training_folds']
                self.assertNotIn(k,trained);self.assertNotIn(inner['gate_training_fold'],trained)

    def test_exact_fit_count_and_conditional_symmetric_reuse(self):
        schedule=nested_schedule(5)
        self.assertEqual(schedule['ranker_fits_with_identical_pair_reuse'],16)
        self.assertEqual(schedule['ranker_fits_without_pair_reuse'],26)
        self.assertEqual(schedule['gate_fits'],6)
        self.assertTrue(schedule['pair_reuse_requires_complete_fit_identity'])
        self.assertFalse(schedule['fit_permission']);self.assertFalse(schedule['calibration_permission'])

    def test_final_gate_scores_exclude_own_fold(self):
        schedule=nested_schedule(3)
        for row in schedule['final_gate_training_scores']:
            self.assertNotIn(row['gate_training_fold'],schedule['ranker_jobs'][row['score_job']]['training_folds'])
        self.assertEqual(schedule['ranker_jobs'][schedule['final_ranker_job']]['training_folds'],[0,1,2])

    def test_deterministic_and_bounded_schedule(self):
        self.assertEqual(nested_schedule(),nested_schedule())
        for value in (True,2,11):
            with self.assertRaises(ValueError):nested_schedule(value)


if __name__=='__main__':unittest.main()
