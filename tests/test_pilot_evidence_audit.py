from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.pilot_evidence_audit import inspect_cases, selected_rows
from sakura_rerank.data.tier_a import SOURCE_SPAN_RECORD_TYPE, SOURCE_SPAN_SCHEMA_VERSION
from tests.test_frozen_diagnostics import verified_synthetic_record


class PilotEvidenceAuditTests(unittest.TestCase):
    def test_only_selected_records_are_parsed_and_holdout_is_skipped(self):
        row=verified_synthetic_record()
        data=canonical_json_bytes(row)+b'\n'
        data+=b'{"broken":,"split":"final-holdout","stable_id":"protected"}\n'
        data+=b'{"broken":,"stable_id":"not-selected"}\n'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.jsonl'
            path.write_bytes(data)
            rows,info=selected_rows(path,hashlib.sha256(data).hexdigest(),{row['stable_id']},frozen=True)
            self.assertEqual(len(rows),1)
            self.assertEqual(info['holdout_skipped_before_json'],1)
            self.assertEqual(info['nonselected_parsed'],0)

    def test_hash_duplicate_missing_and_wrong_split_fail(self):
        row=verified_synthetic_record()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.jsonl'
            data=canonical_json_bytes(row)+b'\n'
            path.write_bytes(data)
            for wanted,sha in (({row['stable_id']},'f'*64),({'missing'},hashlib.sha256(data).hexdigest())):
                with self.assertRaises(ValueError):
                    selected_rows(path,sha,wanted,frozen=True)
            path.write_bytes(data*2)
            with self.assertRaisesRegex(ValueError,'duplicate'):
                selected_rows(path,hashlib.sha256(data*2).hexdigest(),{row['stable_id']},frozen=True)
            row['split']='dev'
            data=canonical_json_bytes(row)+b'\n'
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                selected_rows(path,hashlib.sha256(data).hexdigest(),{row['stable_id']},frozen=True)

    def test_source_projection_uses_only_bounded_left_and_no_future(self):
        row=verified_synthetic_record()
        span=dict(schema_version=SOURCE_SPAN_SCHEMA_VERSION,record_type=SOURCE_SPAN_RECORD_TYPE,
                  stable_id=row['stable_id'],source=row['source'],gold_surface=row['gold_surface'],
                  committed_prefix='X'*200+row['gold_surface'])
        raw=canonical_json_bytes(span)+b'\n'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'span.jsonl'
            path.write_bytes(raw)
            rows,_=selected_rows(path,hashlib.sha256(raw).hexdigest(),{row['stable_id']},frozen=False)
            evidence=rows[row['stable_id']][0]
            self.assertEqual(evidence['left_context'],'X'*64)
            self.assertNotIn('committed_prefix',evidence)
            self.assertNotIn('right_context',evidence)
            span['committed_prefix']+='not-the-target'
            raw=canonical_json_bytes(span)+b'\n'
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                selected_rows(path,hashlib.sha256(raw).hexdigest(),{row['stable_id']},frozen=False)

    def test_reader_resource_bound(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'large'
            path.write_bytes(b'xx')
            with patch('sakura_rerank.data.pilot_evidence_audit.MAX_BYTES',1),self.assertRaises(ValueError):
                selected_rows(path,'a'*64,set(),frozen=False)

    @staticmethod
    def cohort():
        base=verified_synthetic_record()
        queue,bindings,spans,frozen={},{},{},{}
        for i in range(1000):
            case=f'case-{i}'
            stable=f'synthetic-{i}'
            row=copy.deepcopy(base)
            row['stable_id']=stable
            sha=hashlib.sha256(canonical_json_bytes(row)+b'\n').hexdigest()
            candidates=row['candidate_snapshots']['training_top32']['candidates']
            queue[case]=dict(case_id=case,reading=row['reading'],source_gold_surface=row['gold_surface'],
                left_context=row['session']['left_context'],candidate_surfaces=sorted({c['surface'] for c in candidates}),
                gold_segment_surfaces=[row['gold_surface']])
            bindings[case]=dict(stable_id=stable,old_gold_surface=row['gold_surface'],source_row_sha256=sha,
                               source=row['source'],converter_provenance=row['converter_provenance'])
            spans[stable]=(dict(source=copy.deepcopy(row['source']),gold_surface=row['gold_surface'],
                                left_context=row['session']['left_context']),'b'*64)
            frozen[stable]=(row,sha)
        return queue,bindings,spans,frozen

    def test_all_cases_consistent_never_certifies_japanese_or_gold(self):
        inputs=self.cohort()
        report,evidence=inspect_cases(*inputs)
        self.assertEqual(report['checked'],1000)
        self.assertEqual(len(evidence),1000)
        self.assertEqual(report['counts']['source_target_exact'],1000)
        self.assertEqual(report['status'],'evidence_consistent_no_semantic_claim')
        for field in ('semantic_reading_validity_verified','intended_spelling_verified','new_converter_execution',
                      'independent_source_correctness_verified','independent_label_review','gate_a_human_audit_pass',
                      'gate_a_owner_authorized_audit_pass','independent_test','canonical_labels_changed'):
            self.assertIs(report[field],False)
        self.assertIsNone(report['certified_accuracy'])
        public=json.dumps(report)
        for sensitive in ('synthetic-','case-','fixture_surface','source_span_row_sha256'):
            self.assertNotIn(sensitive,public)

    def test_exact_nfkc_and_real_mismatch_stay_distinct(self):
        queue,bindings,spans,frozen=self.cohort()
        original=spans['synthetic-0'][0]['gold_surface']
        spans['synthetic-0'][0]['gold_surface']=chr(ord(original[0])+0xFEE0)+original[1:]
        spans['synthetic-1'][0]['gold_surface']='different'
        spans['synthetic-2'][0]['left_context']='changed'
        spans['synthetic-3'][0]['source']['article_id']='different-article'
        bindings['case-4']['source_row_sha256']='f'*64
        queue['case-5']['reading']='changed'
        report,_=inspect_cases(queue,bindings,spans,frozen)
        self.assertEqual(report['counts']['source_target_exact'],998)
        self.assertEqual(report['counts']['source_target_nfkc_only'],1)
        self.assertEqual(report['counts']['source_target_different'],1)
        for key in ('source_left_context_exact_fail','provenance_exact_fail','frozen_row_binding_exact_fail','packet_frozen_exact_fail'):
            self.assertEqual(report['counts'][key],1)
        self.assertEqual(report['status'],'evidence_discrepancies_require_investigation')

    def test_missing_cases_and_invalid_captured_paths_rejected(self):
        queue,bindings,spans,frozen=self.cohort()
        missing=dict(spans)
        missing.pop('synthetic-0')
        with self.assertRaises(ValueError):
            inspect_cases(queue,bindings,missing,frozen)
        frozen['synthetic-0'][0]['candidate_snapshots']['training_top32']['candidates'][0]['segments'][0]['reading_end']=1
        with self.assertRaises(ValueError):
            inspect_cases(queue,bindings,spans,frozen)


if __name__=='__main__':
    unittest.main()
