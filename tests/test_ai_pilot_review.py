from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.ai_pilot_review import summarize, validate_batch
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash


class AIPilotReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = {f'synthetic-{i}': {'case_id': f'synthetic-{i}', 'source_gold_surface': '日本',
                     'candidate_surfaces': ['にほん', '日本']} for i in range(1000)}
        cls.manifest = {'queue_sha256': 'a' * 64}
        cls.policy = 'b' * 64
        ordered = sorted(cls.queue.values(), key=lambda r: canonical_json_hash(['A', r['case_id']]))
        cls.batches = []
        for i in range(40):
            cls.batches.append(dict(batch=i + 1, queue_sha256=cls.manifest['queue_sha256'],
                policy_sha256=cls.policy, reviewer_kind='ai_teacher', reviewer_id='codex-primary',
                reviewed_at='2026-11-04T01:00:00+00:00', decisions=[dict(case_id=r['case_id'],
                verdict='unique_correct', accepted_surfaces=['日本'], reason='Synthetic test evidence')
                for r in ordered[i*25:(i+1)*25]]))

    def write(self, path, count=1):
        for b in self.batches[:count]:
            (path / f"batch-{b['batch']:03d}.json").write_bytes(canonical_json_bytes(b) + b'\n')

    def summary(self, path, previous=None):
        return summarize(path, self.queue, self.manifest, self.policy, previous)

    def amendment(self, previous=None):
        initial = self.batches[0]['decisions'][0]
        return dict(queue_sha256=self.manifest['queue_sha256'], policy_sha256=self.policy,
                    reviewer_kind='ai_teacher', reviewer_id='codex-primary',
                    reviewed_at='2026-11-04T02:00:00+00:00', previous_event_sha256=canonical_json_hash(previous or initial),
                    previous_log_sha256=canonical_json_hash(previous) if previous else None,
                    decision=dict(initial, verdict='context_insufficient', accepted_surfaces=[], reason='Self correction'))

    def test_perfect_complete_single_ai_review_never_passes_gate(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path, 40)
            report = self.summary(path)
            self.assertEqual(report['reviewed'], 1000)
            self.assertEqual(report['pending'], 0)
            self.assertEqual(report['status'], 'ai_review_complete_no_gate')
            self.assertEqual(report['human_review_count'], 0)
            for field in ['independent_double_review', 'independent_test', 'canonical_labels_changed',
                          'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass']:
                self.assertFalse(report[field])
            self.assertIsNone(report['certified_accuracy'])
            public = json.dumps(report)
            self.assertNotIn('synthetic-', public)
            self.assertNotIn('日本', public)

    def test_incomplete_and_missing_directory_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.assertEqual(self.summary(path)['pending'], 1000)
            self.write(path)
            self.assertEqual(self.summary(path)['pending'], 975)
            with self.assertRaises(ValueError):
                self.summary(path / 'missing')

    def test_identity_policy_human_and_time_mutations_rejected(self):
        mutations = [{'reviewer_kind': 'human'}, {'reviewer_id': 'human-A'}, {'batch': True},
                     {'batch': 41}, {'queue_sha256': 'c'*64}, {'policy_sha256': 'c'*64},
                     {'reviewed_at': None}, {'reviewed_at': '2026-11-04'}, {'extra': 'unsupported'}]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_batch(dict(self.batches[0], **mutation), self.queue, self.manifest, self.policy)

    def test_explicit_complete_decisions_and_frozen_alternatives_required(self):
        for mutate in [lambda b: b['decisions'].pop(),
                       lambda b: b['decisions'].reverse(),
                       lambda b: b['decisions'].__setitem__(1, b['decisions'][0]),
                       lambda b: b['decisions'][0].update(reason=' '),
                       lambda b: b['decisions'][0].update(accepted_surfaces=['outside']),
                       lambda b: b['decisions'][0].update(verdict='context_insufficient'),
                       lambda b: b['decisions'][0].update(verdict='orthographic_equivalent'),
                       lambda b: b['decisions'][0].update(verdict='wrong_gold_surface')]:
            value = copy.deepcopy(self.batches[0])
            mutate(value)
            with self.assertRaises(ValueError):
                validate_batch(value, self.queue, self.manifest, self.policy)

    def test_chained_self_correction_changes_counts_not_original_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            before = self.summary(path)
            first = self.amendment()
            second = self.amendment(first)
            second['decision'] = dict(second['decision'], verdict='unique_correct', accepted_surfaces=['日本'])
            journal = path / 'amendments.jsonl'
            journal.write_bytes(canonical_json_bytes(first) + b'\n')
            one = self.summary(path, before)
            self.assertEqual(one['counts']['context_insufficient'], 1)
            self.assertEqual(one['initial_counts']['unique_correct'], 25)
            with journal.open('ab') as f:
                f.write(canonical_json_bytes(second) + b'\n')
            two = self.summary(path, one)
            self.assertEqual(two['counts']['unique_correct'], 25)
            self.assertEqual(two['self_correction_count'], 2)
            self.assertEqual(before['batch_sha256'], two['batch_sha256'])
            journal.write_bytes(canonical_json_bytes(first) + b'\n')
            with self.assertRaisesRegex(ValueError, 'rewritten or truncated'):
                self.summary(path, two)

    def test_stale_reordered_unbound_and_backdated_amendments_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            original = self.amendment()
            mutations = [{'previous_event_sha256': 'f'*64}, {'previous_log_sha256': 'f'*64},
                         {'reviewed_at': '2026-11-03T00:00:00Z'}, {'reviewer_kind': 'human'},
                         {'decision': dict(original['decision'], case_id='unreviewed')},
                         {'decision': dict(original['decision'], accepted_surfaces=['日本'])}]
            for update in mutations:
                (path/'amendments.jsonl').write_bytes(canonical_json_bytes(dict(original, **update)) + b'\n')
                with self.subTest(update=update), self.assertRaises(ValueError):
                    self.summary(path)

    def test_filename_rewrite_and_size_bound_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.write(path)
            before = self.summary(path)
            file = path/'batch-001.json'
            file.write_bytes(file.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'rewritten'):
                self.summary(path, before)
            file.rename(path/'batch-wrong.json')
            with self.assertRaisesRegex(ValueError, 'filename'):
                self.summary(path)
            (path/'batch-wrong.json').write_bytes(b' ' * (256*1024+1))
            with self.assertRaisesRegex(ValueError, 'bound'):
                self.summary(path)


if __name__ == '__main__':
    unittest.main()
