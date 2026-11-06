"""Do not retry attempted native inputs or turn rejected output into a score."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

from sakura_rerank.data.contracts import ContractError

HERE=Path(__file__).resolve().parents[1]/'research/issue-35-source-units'
sys.path.insert(0,str(HERE))
try:
    spec=importlib.util.spec_from_file_location('unit35_continuation_contract',HERE/'resume_native.py')
    resume=importlib.util.module_from_spec(spec);spec.loader.exec_module(resume)
finally:sys.path.pop(0)


class SourceUnitContinuationTests(unittest.TestCase):
    def test_complete_and_failed_attempts_are_both_excluded_from_continuation(self):
        attempts=[dict(index=0,status='complete'),dict(index=2,status='failed')]
        self.assertEqual(resume.unattempted_indices(4,attempts),[1,3])

    def test_duplicate_or_out_of_range_attempts_fail_closed(self):
        for ids in ([0,0],[-1],[4],[True]):
            with self.assertRaises(ValueError):resume.unattempted_indices(4,[dict(index=i) for i in ids])

    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        directory=Path(temporary.name);request=dict(stable_id='fixture',reading='synthetic')
        (directory/'input.jsonl').write_text(json.dumps(request),encoding='utf8')
        (directory/'output.jsonl').write_text(json.dumps(dict(candidate_snapshots=dict(training_top32=dict(candidates=[dict(segments=[{}]*19)])))),encoding='utf8')
        receipt=dict(status='failed',exit_code=0,error_type='ContractError',input_sha256=resume.sha(directory/'input.jsonl'))
        (directory/'execution.json').write_text(json.dumps(receipt),encoding='utf8')
        terminal=dict(status='failed',execution_sha256=resume.sha(directory/'execution.json'))
        return directory,request,terminal

    def test_contract_rejection_is_unmeasured_with_existing_bound_preserved(self):
        directory,request,terminal=self.fixture()
        def reject(*args):raise ContractError('synthetic_segments_bound')
        result,record=resume.checked_result(directory,request,terminal,{},SimpleNamespace(validate_result=reject))
        self.assertEqual(result['status'],'output_contract_rejected')
        self.assertEqual(result['existing_segment_bound'],18)
        self.assertTrue(result['segments_exceed_existing_bound'])
        self.assertIsNone(record)

    def test_a_rejection_cannot_silently_become_success_on_replay(self):
        directory,request,terminal=self.fixture()
        with self.assertRaisesRegex(ValueError,'not_reproduced'):
            resume.checked_result(directory,request,terminal,{},SimpleNamespace(validate_result=lambda *args:[]))

    def test_non_contract_validator_failure_is_not_reclassified(self):
        directory,request,terminal=self.fixture()
        def reject(*args):raise ValueError('native_identity_mismatch')
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            resume.checked_result(directory,request,terminal,{},SimpleNamespace(validate_result=reject))

    def test_changed_terminal_receipt_fails_before_validation(self):
        directory,request,terminal=self.fixture()
        (directory/'execution.json').write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'receipt_changed'):
            resume.checked_result(directory,request,terminal,{},None)


if __name__=='__main__':unittest.main()
