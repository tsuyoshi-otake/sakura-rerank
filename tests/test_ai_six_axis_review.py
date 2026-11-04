from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.ai_six_axis_review import (
    MACHINE_CHECKS, POLICY_SHA, VALUES, load_inputs, ordered_cases, summarize,
    validate_batch, validate_decision,
)
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash


class AISixAxisReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Synthetic fixtures exercise the contract; they are not review decisions.
        cls.queue = {f'synthetic-{i}': {'case_id': f'synthetic-{i}', 'source_gold_surface': '架空'}
                     for i in range(1000)}
        cls.manifest = {'queue_sha256': 'a' * 64}
        cls.machine = {case: dict(case_id=case, packet_case_sha256=canonical_json_hash(row),
                                 source_target_comparison='exact',
                                 checks={key: True for key in MACHINE_CHECKS})
                       for case, row in cls.queue.items()}
        cls.machine_sha = 'b' * 64
        cls.axes = dict(reading='compatible', input_unit='whole_plausible', context='usable',
                        meaning='supported', spelling='ordinary_plausible')
        cls.batches = []
        ordered = ordered_cases(cls.queue)
        for i in range(20):
            cls.batches.append(dict(
                batch=i+1, queue_sha256=cls.manifest['queue_sha256'], policy_sha256=POLICY_SHA,
                machine_report_sha256=cls.machine_sha, reviewer_kind='ai_teacher',
                reviewer_id='codex-primary', reviewed_at='2026-11-04T02:00:00Z',
                decisions=[dict(case_id=case, axes=cls.axes, reason='Synthetic evidence only',
                                machine_evidence_sha256=canonical_json_hash(cls.machine[case]))
                           for case in ordered[i*50:(i+1)*50]],
            ))

    def summary(self, path, previous=None, baseline=None):
        return summarize(path, self.queue, self.manifest, self.machine, self.machine_sha,
                         previous, baseline, 'c'*64 if baseline is not None else None)

    def write(self, path, count=1):
        for batch in self.batches[:count]:
            (path/f"batch-{batch['batch']:03}.json").write_bytes(canonical_json_bytes(batch)+b'\n')

    def amendment(self, previous=None):
        initial = self.batches[0]['decisions'][0]
        return dict(queue_sha256=self.manifest['queue_sha256'], policy_sha256=POLICY_SHA,
                    machine_report_sha256=self.machine_sha, reviewer_kind='ai_teacher',
                    reviewer_id='codex-primary', reviewed_at='2026-11-04T03:00:00Z',
                    previous_event_sha256=canonical_json_hash(previous or initial),
                    previous_log_sha256=canonical_json_hash(previous) if previous else None,
                    decision=dict(initial, axes=dict(self.axes, meaning='unknown'), reason='Synthetic correction'))

    def test_complete_plausible_review_never_certifies_gold(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path, 20)
            report = self.summary(path)
            self.assertEqual((report['reviewed'], report['pending']), (1000, 0))
            self.assertEqual(report['status'], 'ai_review_complete_no_gold')
            for axis, value in self.axes.items():
                self.assertEqual(report['counts'][axis][value], 1000)
                self.assertEqual(sum(report['counts'][axis].values()), 1000)
            for field in ('independent_review', 'independent_test', 'blinded_to_source_gold',
                          'canonical_labels_changed', 'unique_intended_output_certified',
                          'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass'):
                self.assertFalse(report[field])
            self.assertTrue(report['prior_case_exposure'])
            self.assertEqual(report['human_review_count'], 0)
            self.assertIsNone(report['certified_accuracy'])
            public = json.dumps(report)
            for value in ('synthetic-', '架空', 'Synthetic evidence only'):
                self.assertNotIn(value, public)

    def test_missing_incomplete_and_complete_have_explicit_states(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.assertEqual(self.summary(path)['pending'], 1000)
            self.write(path)
            self.assertEqual(self.summary(path)['pending'], 950)
            self.write(path, 20)
            (path/'batch-012.json').unlink()
            self.assertEqual(self.summary(path)['pending'], 50)
            with self.assertRaises(ValueError):
                self.summary(path/'missing')

    def test_identity_policy_time_and_machine_binding_required(self):
        mutations = [dict(reviewer_kind='human'), dict(reviewer_id='second-reviewer'),
                     dict(batch=True), dict(batch=21), dict(queue_sha256='x'*64),
                     dict(policy_sha256='x'*64), dict(machine_report_sha256='x'*64),
                     dict(reviewed_at='2026-11-04'), dict(extra='not-allowed')]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_batch(dict(self.batches[0], **mutation), self.queue, self.manifest,
                               self.machine, self.machine_sha)

    def test_order_completeness_duplicates_and_explicit_axes_required(self):
        mutations = [lambda b: b['decisions'].pop(), lambda b: b['decisions'].reverse(),
                     lambda b: b['decisions'].__setitem__(1, b['decisions'][0]),
                     lambda b: b['decisions'][0]['axes'].pop('reading'),
                     lambda b: b['decisions'][0]['axes'].update(reading='valid'),
                     lambda b: b['decisions'][0].update(reason=' '),
                     lambda b: b['decisions'][0].update(reason='x'*2001),
                     lambda b: b['decisions'][0].update(machine_evidence_sha256='x'*64),
                     lambda b: b['decisions'][0].update(accepted_surfaces=['架空']),
                     lambda b: b['decisions'][0]['axes'].update(context='defect_blocking')]
        for mutate in mutations:
            value = copy.deepcopy(self.batches[0])
            mutate(value)
            with self.assertRaises(ValueError):
                validate_batch(value, self.queue, self.manifest, self.machine, self.machine_sha)

    def test_blocking_context_with_unknown_meaning_remains_unresolved(self):
        value = copy.deepcopy(self.batches[0]['decisions'][0])
        value['axes'].update(context='defect_blocking', meaning='unknown')
        validate_decision(value, value['case_id'], self.machine)

    def test_source_binding_checks_cannot_be_replaced_by_empty_or_generic_pass(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            evidence, report = path/'evidence.jsonl', path/'report.json'
            rows = list(copy.deepcopy(self.machine).values())
            metadata = dict(kind='machine_pilot_evidence_not_gold', checked=1000,
                            queue_sha256=self.manifest['queue_sha256'], canonical_labels_changed=False,
                            independent_source_correctness_verified=False, certified_accuracy=None,
                            human_review_count=0, final_holdout_valid_count=0)
            metadata.update({k: False for k in (
                'semantic_reading_validity_verified', 'real_user_input_boundary_verified',
                'intended_spelling_verified', 'independent_label_review', 'independent_test',
                'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass')})

            def invoke(candidate_rows, extra=None):
                raw = b''.join(canonical_json_bytes(row)+b'\n' for row in candidate_rows)
                evidence.write_bytes(raw)
                report.write_bytes(canonical_json_bytes(dict(metadata,
                    evidence_sha256=hashlib.sha256(raw).hexdigest(), **(extra or {}))))
                with patch('sakura_rerank.data.ai_six_axis_review.load_packet',
                           return_value=(self.manifest, self.queue, {})):
                    return load_inputs(path, report, evidence)

            self.assertEqual(len(invoke(rows)[2]), 1000)
            for changes in ({'checks': {}}, {'checks': {'generic_pass': True}},
                            {'packet_case_sha256': 'x'*64}, {'source_target_comparison': 'nfkc'},
                            {'checks': dict.fromkeys(MACHINE_CHECKS, 1)}):
                changed = copy.deepcopy(rows)
                changed[0].update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    invoke(changed)
            for changed in (rows[:-1], rows[:-1]+[rows[0]]):
                with self.assertRaises(ValueError):
                    invoke(changed)
            with self.assertRaises(ValueError):
                invoke(rows, {'independent_label_review': True})

    def test_source_file_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path/'evidence').write_bytes(b'{}\n')
            (path/'report').write_bytes(canonical_json_bytes(dict(
                kind='machine_pilot_evidence_not_gold', checked=1000,
                queue_sha256=self.manifest['queue_sha256'], evidence_sha256='x'*64)))
            with patch('sakura_rerank.data.ai_six_axis_review.load_packet',
                       return_value=(self.manifest, self.queue, {})), self.assertRaises(ValueError):
                load_inputs(path, path/'report', path/'evidence')

    def test_corrections_preserve_initial_counts_and_chain(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            before = self.summary(path)
            first = self.amendment()
            second = self.amendment(first)
            second['decision']['axes'] = self.axes
            journal = path/'amendments.jsonl'
            journal.write_bytes(canonical_json_bytes(first)+b'\n')
            one = self.summary(path, before)
            self.assertEqual(one['counts']['meaning']['unknown'], 1)
            self.assertEqual(one['initial_counts']['meaning']['supported'], 50)
            with journal.open('ab') as out:
                out.write(canonical_json_bytes(second)+b'\n')
            two = self.summary(path, one)
            self.assertEqual(two['counts']['meaning']['supported'], 50)
            self.assertEqual(two['self_correction_count'], 2)
            self.assertEqual(two['batch_sha256'], before['batch_sha256'])
            journal.write_bytes(canonical_json_bytes(first)+b'\n')
            with self.assertRaisesRegex(ValueError, 'rewritten or truncated'):
                self.summary(path, two)

    def test_stale_backdated_and_human_amendments_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            first = self.amendment()
            mutations = [dict(previous_event_sha256='x'*64), dict(previous_log_sha256='x'*64),
                         dict(reviewed_at='2026-11-03T00:00:00Z'), dict(reviewer_kind='human'),
                         dict(decision=dict(first['decision'], case_id='unreviewed'))]
            for mutation in mutations:
                (path/'amendments.jsonl').write_bytes(canonical_json_bytes(dict(first, **mutation))+b'\n')
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    self.summary(path)

    def test_filename_bound_and_prior_batch_rewrite_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            before = self.summary(path)
            file = path/'batch-001.json'
            file.write_bytes(file.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'rewritten'):
                self.summary(path, before)
            file.rename(path/'batch-wrong.json')
            with self.assertRaisesRegex(ValueError, 'filename'):
                self.summary(path)
            (path/'batch-wrong.json').write_bytes(b' '*(1024*1024+1))
            with self.assertRaisesRegex(ValueError, 'bound'):
                self.summary(path)

    def test_baseline_conditional_counts_cover_all_cases_without_labels(self):
        baseline = {case: (dict(verdict='unique_correct' if i < 807 else 'context_insufficient'),
                           'x'*64, '2026-11-04T01:00:00Z')
                    for i, case in enumerate(self.queue)}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path, 20)
            report = self.summary(path, baseline=baseline)
            cohorts = report['baseline_comparison']['cohorts']
            self.assertEqual(cohorts['old_unique']['reviewed'], 807)
            self.assertEqual(cohorts['old_flagged']['reviewed'], 193)
            for axis in VALUES:
                self.assertEqual(sum(sum(c['counts'][axis].values()) for c in cohorts.values()), 1000)
            self.assertFalse(report['unique_intended_output_certified'])
            baseline.pop(next(iter(baseline)))
            with self.assertRaisesRegex(ValueError, 'baseline population'):
                self.summary(path, baseline=baseline)

    def test_cli_policy_failure_does_not_echo_raw_input(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'policy'
            path.write_text('private synthetic raw evidence', encoding='utf-8')
            args = [sys.executable, '-m', 'sakura_rerank.data.ai_six_axis_review']
            for name in ('packet', 'machine-report', 'machine-evidence', 'policy', 'reviews'):
                args += ['--'+name, str(path)]
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertIn('no result authorized', result.stderr)
            self.assertNotIn('private synthetic', result.stderr)


if __name__ == '__main__':
    unittest.main()
