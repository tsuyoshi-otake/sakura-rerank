from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.gold_pilot import _publish
from sakura_rerank.data import human_six_axis_pilot as h

POLICY=Path(__file__).parents[1]/'research/gold-human-six-axis-policy-v1.json'
VALUES=dict(source='unverifiable',reading='compatible',input_unit='whole_unit_plausible',
            context='usable',meaning='identifiable',spelling='unique')


class HumanSixAxisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue={f'synthetic-{i:04d}':dict(case_id=f'synthetic-{i:04d}',left_context='SYNTHETIC_CONTEXT',
            reading='にほん',source_gold_surface='日本',candidate_surfaces=['にほん','日本'],gold_segment_surfaces=['日本'])
            for i in range(1000)}
        cls.raw_policy=POLICY.read_bytes()
        cls.payloads=h.build_packet(cls.queue,cls.raw_policy)
        cls.manifest=json.loads(cls.payloads['manifest.json'])
        cls.roster=json.loads(cls.payloads['coordinator/assignment.template.json'])
        cls.roster.update(coordinator_id='synthetic-coordinator',confirmed_at='2026-11-04T00:00:00Z')
        for role in ('A','B','C'):
            cls.roster['roles'][role].update(reviewer_id='synthetic-human-'+role,reviewer_kind='human',
                                          **{k:True for k in h.DECLARATIONS})
        cls.cases=sorted(cls.queue)

    def setUp(self):
        self.events=[]
        self.heads={}
        self.case_heads={}

    def add(self,case,role,changes=None,surfaces=None,seal=None,basis=None):
        e=h._form(self.manifest['packet_id'],role,case)
        vals=dict(VALUES,**(changes or {}))
        e.update(reviewer_id=self.roster['roles'][role]['reviewer_id'],reviewer_kind='human',
                 reviewed_at='2026-11-04T01:00:00Z',roster_sha256=canonical_json_hash(self.roster),
                 axes={a:dict(value=v,reason='Synthetic evidence only, not actual human work') for a,v in vals.items()},
                 accepted_surfaces=(['日本'] if vals['spelling']=='unique' else []) if surfaces is None else surfaces,
                 previous_log_sha256=self.heads.get(role),previous_event_sha256=self.case_heads.get((case,role)),
                 seal_sha256=canonical_json_hash(seal) if seal else None,basis_sha256=basis or [])
        self.events.append(e)
        self.heads[role]=self.case_heads[(case,role)]=canonical_json_hash(e)
        return e

    def complete_ab(self,disagree=False):
        for i,c in enumerate(self.cases):
            self.add(c,'A')
            self.add(c,'B',{'meaning':'unknown','spelling':'unknown'} if disagree and i==0 else None)

    def result(self,events=None,roster=True):
        return h.reconcile(self.manifest,self.queue,self.roster if roster else None,
                           self.events if events is None else events)

    def test_packet_same_population_and_blind_role_specific_ids(self):
        self.assertEqual(self.payloads,h.build_packet(dict(reversed(list(self.queue.items()))),self.raw_policy))
        orders={}
        for role in ('A','B'):
            cards=[]
            for i in range(1,41):
                cards.extend(json.loads(self.payloads[f'reviewer-{role}/batch-{i:03d}.json'])['cases'])
            self.assertEqual(len(cards),1000)
            orders[role]=[c['review_id'] for c in cards]
            self.assertEqual(len(set(orders[role])),1000)
            for c in cards:
                self.assertEqual(set(c),{'review_id','left_context','reading','source_gold_surface',
                    'candidate_surfaces','gold_segment_surfaces','source_evidence','input_provenance'})
                self.assertIsNone(c['source_evidence'])
        self.assertFalse(set(orders['A']) & set(orders['B']))
        case_orders={r:sorted(self.cases,key=lambda c:canonical_json_hash([h.VERSION,r,c])) for r in ('A','B')}
        self.assertNotEqual(case_orders['A'],case_orders['B'])

    def test_frozen_policy_changes_rejected(self):
        with self.assertRaisesRegex(ValueError,'hash'):
            h.build_packet(self.queue,self.raw_policy+b' ')
        with self.assertRaises(ValueError):
            h.build_packet({c:self.queue[c] for c in self.cases[:-1]},self.raw_policy)

    def test_blank_assignment_is_not_human_evidence(self):
        blank=json.loads(self.payloads['coordinator/assignment.template.json'])
        with self.assertRaises(ValueError):
            h.validate_roster(blank,self.manifest)
        report,*_=self.result(roster=False)
        self.assertEqual(report['status'],'awaiting_assignment')
        self.assertEqual(report['human_case_counts'],{'A':0,'B':0,'C':0})
        self.assertIsNone(report['initial_agreement']['joint_rate'])
        self.assertEqual(self.result()[0]['status'],'awaiting_dual_review')

    def test_ai_duplicate_people_and_missing_independence_rejected(self):
        for change in ({'reviewer_kind':'ai_teacher'},{'reviewer_id':'synthetic-human-A'},
                       {'no_prior_case_ai_exposure':False},{'human_identity_checked':None}):
            roster=copy.deepcopy(self.roster)
            roster['roles']['B'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                h.validate_roster(roster,self.manifest)

    def test_six_axes_reasons_source_evidence_and_candidate_constraints(self):
        e=self.add(self.cases[0],'A')
        mutations=[lambda x:x['axes'].pop('meaning'),lambda x:x['axes']['source'].update(value='matches'),
                   lambda x:x['axes']['reading'].update(reason=' '),lambda x:x['axes']['reading'].update(value='unknown'),
                   lambda x:x.update(accepted_surfaces=['outside']),lambda x:x.update(reviewer_kind='ai_teacher'),
                   lambda x:x.update(reviewed_at='2026-11-04'),lambda x:x.update(extra='AI advice')]
        for mutation in mutations:
            changed=copy.deepcopy(e)
            mutation(changed)
            with self.assertRaises(ValueError):
                self.result([changed])

    def test_history_chain_roster_binding_and_backdating_rejected(self):
        self.add(self.cases[0],'A')
        self.add(self.cases[1],'A')
        for changes in ({'previous_log_sha256':None},{'previous_event_sha256':'f'*64},
                        {'roster_sha256':'f'*64},{'reviewed_at':'2026-11-03T00:00:00Z'}):
            changed=copy.deepcopy(self.events)
            changed[-1].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.result(changed)

    def test_initial_agreement_is_not_replaced_by_corrections(self):
        c=self.cases[0]
        self.add(c,'A',{'meaning':'unknown','spelling':'unknown'})
        self.add(c,'B')
        self.add(c,'A')
        report,*_=self.result()
        self.assertEqual(report['initial_agreement']['joint_rate'],0)
        self.assertEqual(report['current_agreement']['joint_rate'],1)
        self.assertEqual(report['initial_agreement']['paired'],1)
        self.assertEqual(report['initial_agreement']['missing_pairs'],999)
        self.assertEqual(report['human_case_counts']['A'],1)

    def test_unknown_agreement_is_not_informative_accuracy(self):
        values={a:'unverifiable' if a=='source' else 'unknown' for a in h.AXES}
        for r in ('A','B'):
            self.add(self.cases[0],r,values)
        report,*_=self.result()
        self.assertEqual(report['initial_agreement']['joint_rate'],1)
        for axis in report['initial_agreement']['per_axis'].values():
            self.assertEqual(axis['both_unknown'],1)
            self.assertEqual(axis['informative_paired'],0)
            self.assertIsNone(axis['informative_rate'])
        self.assertIsNone(report['certified_accuracy'])

    def test_adjudication_hidden_until_all_ab_then_bound_to_seal(self):
        self.add(self.cases[0],'A')
        self.add(self.cases[0],'B',{'meaning':'unknown','spelling':'unknown'})
        report,_,tasks,seal=self.result()
        self.assertEqual(report['adjudication']['disagreement_count'],1)
        self.assertFalse(tasks)
        self.assertIsNone(seal)
        self.add(self.cases[0],'C',basis=[canonical_json_hash(e) for e in self.events[:2]])
        with self.assertRaises(ValueError):
            self.result()

    def test_complete_disagreement_and_third_party_unknown_terminal(self):
        self.complete_ab(disagree=True)
        report,findings,tasks,seal=self.result()
        self.assertEqual(report['status'],'awaiting_adjudication')
        self.assertEqual((len(findings),len(tasks)),(999,1))
        self.assertEqual(report['adjudication']['required_rate_on_paired'],0.001)
        self.assertNotIn('reviewer_id',tasks[0]['review_a'])
        self.add(self.cases[0],'C',{'meaning':'unknown','spelling':'unknown'},seal=seal,basis=tasks[0]['basis_sha256'])
        report,findings,tasks,_=self.result()
        self.assertEqual(report['status'],'pilot_findings_complete_no_gold')
        self.assertEqual(report['adjudication']['completion_rate'],1)
        self.assertEqual(report['initial_agreement']['joint_rate'],0.999)
        self.assertEqual(report['distributions']['final']['meaning']['unknown'],1)
        self.assertEqual(len(findings),1000)
        self.assertFalse(tasks)
        self.assertEqual(report['certified_gold_count'],0)

    def test_sealed_ab_and_wrong_c_basis_rejected(self):
        self.complete_ab(disagree=True)
        _,_,tasks,seal=self.result()
        before=list(self.events)
        self.add(self.cases[0],'A')
        with self.assertRaises(ValueError):
            self.result()
        self.events=before
        self.add(self.cases[0],'C',seal=seal,basis=['f'*64,'f'*64])
        with self.assertRaises(ValueError):
            self.result()

    def test_complete_perfect_pilot_never_passes_gold_gates(self):
        self.complete_ab()
        report,findings,tasks,_=self.result()
        self.assertEqual(report['initial_agreement']['joint_rate'],1)
        self.assertEqual(report['status'],'pilot_findings_complete_no_gold')
        self.assertEqual(len(findings),1000)
        self.assertFalse(tasks)
        for k in ('gate_a_human_audit_pass','gate_a_owner_authorized_audit_pass','independent_test','canonical_labels_changed'):
            self.assertIs(report[k],False)
        self.assertEqual(report['source_independently_verified'],0)
        text=json.dumps(report,ensure_ascii=False)
        for hidden in ('synthetic-', 'SYNTHETIC_CONTEXT','日本','Synthetic evidence'):
            self.assertNotIn(hidden,text)

    def test_packet_read_rejects_extra_files_tampering_and_wrong_cohort(self):
        with tempfile.TemporaryDirectory() as d:
            packet=Path(d)/'packet'
            _publish(packet,self.payloads)
            with self.assertRaisesRegex(ValueError,'cohort'):
                h.load_review_packet(packet)
            with patch.object(h,'SOURCE_QUEUE_SHA',self.manifest['queue_sha256']):
                self.assertEqual(h.load_review_packet(packet)[0],self.manifest)
                extra=packet/'reviewer-A/ai-advice.txt'
                extra.write_text('synthetic leak')
                with self.assertRaises(ValueError):
                    h.load_review_packet(packet)
                extra.unlink()
                target=packet/'reviewer-A/batch-001.json'
                target.write_bytes(target.read_bytes()+b' ')
                with self.assertRaises(ValueError):
                    h.load_review_packet(packet)

    def test_round_checkpoint_prefix_no_overwrite_and_assignment_binding(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            zero=root/'zero'
            h.publish_round(zero,self.manifest,self.queue,None,[])
            sha=h._sha((zero/'round.json').read_bytes())
            self.add(self.cases[0],'A')
            first=root/'first'
            h.publish_round(first,self.manifest,self.queue,self.roster,self.events,zero,sha)
            with self.assertRaises(ValueError):
                h.publish_round(first,self.manifest,self.queue,self.roster,self.events,zero,sha)
            for ev,checkpoint in (([],h._sha((first/'round.json').read_bytes())),(self.events,'f'*64)):
                with self.assertRaises(ValueError):
                    h.publish_round(root/'bad',self.manifest,self.queue,self.roster,ev,first,checkpoint)
                self.assertFalse((root/'bad').exists())
            changed=copy.deepcopy(self.roster)
            changed['coordinator_id']='replacement'
            with self.assertRaises(ValueError):
                h.publish_round(root/'bad',self.manifest,self.queue,changed,self.events,first,h._sha((first/'round.json').read_bytes()))
            with (first/'events.jsonl').open('ab') as f:
                f.write(b'\n')
            with self.assertRaises(ValueError):
                h.publish_round(root/'bad',self.manifest,self.queue,self.roster,self.events,first,h._sha((first/'round.json').read_bytes()))

    def test_bootstrap_cannot_smuggle_human_events_or_assignment(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                h.publish_round(Path(d)/'bad',self.manifest,self.queue,self.roster,[])

    def test_publication_failure_cleans_staging(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('sakura_rerank.data.gold_pilot.os.fsync',side_effect=OSError('synthetic fault')):
                with self.assertRaises(OSError):
                    h.publish_round(Path(d)/'bad',self.manifest,self.queue,None,[])
            self.assertEqual(list(Path(d).iterdir()),[])


if __name__=='__main__':
    unittest.main()
