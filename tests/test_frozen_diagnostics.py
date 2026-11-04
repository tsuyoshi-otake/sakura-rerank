import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes, validate_record
from sakura_rerank.data.frozen_diagnostics import audit, read_projection, main
from tests.test_data_contracts import production_record, _rehash_snapshots
from tests.test_tier_a import exporter_record
from tests.test_gold_pilot import projection


def verified_synthetic_record():
    row = production_record()
    row['candidate_snapshots']['training_top32']['exporter_run'] = exporter_record()['candidate_snapshots']['training_top32']['exporter_run']
    _rehash_snapshots(row)
    return row


class FrozenDiagnosticsTests(unittest.TestCase):
    def test_projection_pins_hash_and_discards_holdout_before_parsing(self):
        row = verified_synthetic_record()
        validate_record(row)
        # A deliberately unparsable holdout line proves its body is not parsed.
        content = canonical_json_bytes(row) + b'\n' + b'{"broken":,"split":"final-holdout","secret":"not inspected"}\n'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'source.jsonl'
            p.write_bytes(content)
            rows, evidence = read_projection(p, hashlib.sha256(content).hexdigest())
            self.assertEqual(len(rows), 1)
            self.assertEqual(evidence['holdout_rows_skipped_before_json'], 1)
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                read_projection(p, '0' * 64)

    def test_wrong_converter_and_bounds_fail(self):
        row = production_record()  # unverified exporter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'source.jsonl'
            content = canonical_json_bytes(row) + b'\n'
            p.write_bytes(content)
            with self.assertRaisesRegex(ValueError, 'invalid contract'):
                read_projection(p, hashlib.sha256(content).hexdigest())
            with patch('sakura_rerank.data.frozen_diagnostics.MAX_SOURCE_BYTES', 1):
                with self.assertRaisesRegex(ValueError, 'bound'):
                    read_projection(p, '0' * 64)

    def test_overlap_is_detected_despite_disjoint_provenance(self):
        a, b = projection(1), projection(2, 'dev')
        b['input_key'] = a['input_key']
        b['feature_input_key'] = a['feature_input_key']
        original = copy.deepcopy([a, b])
        report = audit([a, b], {})
        self.assertEqual(report['cross_split_exact_overlap']['article_id']['groups'], 0)
        self.assertEqual(report['cross_split_exact_overlap']['input_key']['groups'], 1)
        self.assertEqual([a, b], original)
        self.assertNotIn('synthetic context', str(report))

    def test_missing_top6_kept_in_denominator_and_conflicts_counted(self):
        a, b = projection(1), projection(2)
        b['input_key'] = a['input_key']
        b['gold_surface'] = 'other synthetic gold'
        b['gold_index'] = 8
        report = audit([a, b], {})['profiles']['train']
        self.assertEqual(report['n'], 2)
        self.assertEqual(report['top6'], 1)
        self.assertEqual(report['top10'], 2)
        self.assertEqual(report['conflicting_gold_groups'], 1)

    def test_output_failure_leaves_no_partial_report_or_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'report.json'
            argv = ['audit', '--source', 'unused', '--source-sha256', '0'*64, '--output', str(output)]
            with patch('sys.argv', argv), patch('sakura_rerank.data.frozen_diagnostics.read_projection', return_value=([projection(1)], {})):
                with patch('sakura_rerank.data.frozen_diagnostics.os.fsync', side_effect=OSError('injected')):
                    with self.assertRaises(SystemExit):
                        main()
                self.assertFalse(output.exists())
                output.write_bytes(b'earlier report')
                with self.assertRaises(SystemExit):
                    main()
                self.assertEqual(output.read_bytes(), b'earlier report')


if __name__ == '__main__':
    unittest.main()
