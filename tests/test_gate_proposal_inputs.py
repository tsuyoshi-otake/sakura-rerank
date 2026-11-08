"""Projection boundaries and dependency changes, not fitted model quality."""
import hashlib
import unittest
import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,tensor_hash
from sakura_rerank.gate_oof import component_folds
from sakura_rerank.gate_proposal_inputs import project_inputs,projected_folds,validate_source_inputs


def digest(value):return hashlib.sha256(str(value).encode()).hexdigest()


def fixture():
    values=dict(context_ids=np.zeros((2,64),np.int64),context_lengths=np.array([8,8],np.int64),
        reading_ids=np.zeros((2,32),np.int64),reading_lengths=np.array([2,2],np.int64),
        candidate_ids=np.zeros((2,6,32),np.int64),candidate_lengths=np.zeros((2,6),np.int64),
        features=np.zeros((2,6,7),np.float32),candidate_mask=np.zeros((2,6),np.bool_))
    values['context_ids'][:,:8]=1;values['context_ids'][1,0]=2
    values['reading_ids'][:,:2]=3;values['candidate_ids'][:,:2,0]=4
    values['candidate_lengths'][:,:2]=1;values['candidate_mask'][:,:2]=True
    return values


def records():
    return [dict(row_key=digest(i),component_key=digest('component'+str(i)),original_input_key=digest('original'+str(i)),
        numeric_input_key=digest('numeric'+str(i)),group='source') for i in range(2)]


class GateProposalInputTests(unittest.TestCase):
    def test_source_is_exact_and_read_only_without_freezing_original(self):
        original=fixture();projected=project_inputs(original,'source')
        for key in MODEL_FIELDS:
            np.testing.assert_array_equal(original[key],projected[key])
            self.assertTrue(original[key].flags.writeable);self.assertFalse(projected[key].flags.writeable)

    def test_empty_changes_only_context_and_preserves_original(self):
        original=fixture();before={k:v.copy() for k,v in original.items()};projected=project_inputs(original,'empty')
        for key in MODEL_FIELDS:
            np.testing.assert_array_equal(original[key],before[key])
            if key in ('context_ids','context_lengths'):self.assertFalse(projected[key].any())
            else:np.testing.assert_array_equal(original[key],projected[key])

    def test_labels_cannot_enter_projection(self):
        for name in ('gold','correct_mask','baseline_equivalent','target','source_id'):
            value=fixture();value[name]=np.zeros(2)
            with self.assertRaises(ValueError):project_inputs(value,'source')

    def test_missing_input_and_unknown_condition_rejected(self):
        value=fixture();del value['features']
        with self.assertRaises(ValueError):project_inputs(value,'source')
        with self.assertRaises(ValueError):project_inputs(fixture(),'observed')

    def test_schema_row_shape_dtype_and_contiguity(self):
        for name,replacement in (('reading_lengths',np.array([[2,2]],np.int64)),('context_ids',np.zeros((2,64),np.int32)),
            ('candidate_ids',np.zeros((2,5,32),np.int64)),('context_ids',np.ones((2,128),np.int64)[:,::2])):
            value=fixture();value[name]=replacement
            with self.assertRaises(ValueError):validate_source_inputs(value)

    def test_mask_requires_two_or_more_prefix_candidates(self):
        for active in ([],[0],[1,2],[0,2]):
            value=fixture();value['candidate_mask'][:]=False;value['candidate_mask'][:,active]=True
            with self.assertRaises(ValueError):validate_source_inputs(value)

    def test_nonfinite_and_padded_features_rejected(self):
        for index,value in (((0,0,0),np.nan),((0,2,0),1.0)):
            arrays=fixture();arrays['features'][index]=value
            with self.assertRaises(ValueError):validate_source_inputs(arrays)

    def test_length_bounds_and_padded_candidate_lengths(self):
        for name,index,value in (('context_lengths',0,7),('reading_lengths',0,33),('candidate_lengths',(0,0),0),('candidate_lengths',(0,2),1)):
            arrays=fixture();arrays[name][index]=value
            with self.assertRaises(ValueError):validate_source_inputs(arrays)

    def test_token_and_padding_bounds(self):
        for index,value in (((0,0),0),((0,0),13312),((0,8),1)):
            arrays=fixture();arrays['context_ids'][index]=value
            with self.assertRaises(ValueError):validate_source_inputs(arrays)

    def test_empty_context_equality_adds_a_fold_dependency(self):
        original=fixture();source=project_inputs(original,'source');empty=project_inputs(original,'empty')
        source_keys=[tensor_hash(source,i,MODEL_FIELDS) for i in range(2)]
        empty_keys=[tensor_hash(empty,i,MODEL_FIELDS) for i in range(2)]
        self.assertNotEqual(source_keys[0],source_keys[1]);self.assertEqual(empty_keys[0],empty_keys[1])
        metadata=records();base=component_folds(metadata,2)['row_component']
        separated=projected_folds(metadata,base,source_keys,2);joined=projected_folds(metadata,base,empty_keys,2)
        self.assertEqual(separated['fold_sizes'],[1,1]);self.assertEqual(joined['fold_sizes'],[2,0])
        self.assertFalse(joined['fit_permission'])

    def test_projection_cannot_split_existing_component_bridges(self):
        metadata=records();base={r['row_key']:digest('shared') for r in metadata}
        result=projected_folds(metadata,base,[digest('a'),digest('b')],2)
        self.assertEqual(result['fold_sizes'],[2,0])

    def test_projection_denominator_and_digest_validation(self):
        metadata=records();base=component_folds(metadata,2)['row_component']
        for supplied,keys in (({},[digest('a'),digest('b')]),(base,[digest('a')]),(base,['bad',digest('b')])):
            with self.assertRaises(ValueError):projected_folds(metadata,supplied,keys,2)


if __name__=='__main__':unittest.main()
