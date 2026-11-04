from __future__ import annotations

import bz2
import copy
import hashlib
import io
import json
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.__main__ import _parser
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.jawiki_preprocess import (
    CLEANER_VERSION, PreprocessingError, SurfaceMatcher, extract_source_spans, iter_source_spans,
)
from sakura_rerank.data.source_quality import QUALITY_CLEANER_VERSION, QUALITY_POLICY, quality_flags
from sakura_rerank.data.source_quality_audit import audit_train
from sakura_rerank.data.tier_a import TierABlockedError, TierAError, validate_source_span_manifest
from test_jawiki_preprocess import (
    EXTRACTOR_SHA, INDEX_SHA, config, dictionary_manifest, dictionary_records, jawiki_manifest,
)


def fixture(text):
    return ('<mediawiki><page><ns>0</ns><id>10</id><revision><id>20</id><text>'
            + text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            + '</text></revision></page></mediawiki>').encode()


class SourceQualityTests(unittest.TestCase):
    def test_targeted_rules_and_joint_reason_accounting(self):
        self.assertEqual(quality_flags(r'式 \mbox{', 'Alpha'), ('tex_command_residue',))
        self.assertEqual(quality_flags('著作『 』の', 'Alpha'), ('empty_title_delimiters',))
        self.assertEqual(quality_flags(r'『』と\frac{1}{2}', 'Alpha'),
                         ('tex_command_residue', 'empty_title_delimiters'))
        self.assertEqual(quality_flags('書名『', '』'), ('empty_title_delimiters',))

    def test_legitimate_text_paths_titles_and_partial_input_are_preserved(self):
        for left, target in ((r'C:\data\input', 'Alpha'), (r'\\mboxes', 'Alpha'),
                             ('一般の{記号}と', 'Alpha'), ('著作『架空』と', 'Alpha'),
                             ('生', '物的'), ('聴', 'かれる'), ('得', 'られる'), ('「」と', 'Alpha')):
            with self.subTest(left=left):
                self.assertEqual(quality_flags(left, target), ())

    def test_bounds_rejected_without_implicit_truncation(self):
        for left, target in (('a'*65, 'x'), ('', ''), ('', 'x'*257), (None, 'x')):
            with self.subTest(left=left), self.assertRaises(ValueError):
                quality_flags(left, target)

    def extract(self, text, version=CLEANER_VERSION, chosen_config=None, excluded=frozenset()):
        cfg = chosen_config or config()
        counts = Counter()
        rows = list(iter_source_spans(io.BytesIO(fixture(text)), SurfaceMatcher(dictionary_records(), cfg),
                                     cfg, counts, cleaner_version=version, excluded_stable_ids=excluded))
        return rows, counts

    def test_v5_quarantines_defects_and_preserves_v4_coordinates(self):
        text = r'Before <math>\mbox{ for } x</math> Alpha.' + '\n\n' + '『{{title}}』 Alpha.\n\nGood Alpha.'
        old, old_counts = self.extract(text)
        new, counts = self.extract(text, QUALITY_CLEANER_VERSION)
        self.assertEqual(len(old), 3)
        self.assertEqual(new, [old[2]])
        self.assertEqual(counts['quality_examined'], 3)
        self.assertEqual(counts['quality_quarantined'], 2)
        self.assertEqual(counts['quality_tex_command_residue'], 1)
        self.assertEqual(counts['quality_empty_title_delimiters'], 1)
        self.assertEqual(counts['quality_retained'], 1)
        self.assertFalse(any(k.startswith('quality_') for k in old_counts))
        excluded, exclusion_counts = self.extract(text, QUALITY_CLEANER_VERSION,
                                                 excluded=frozenset({old[2]['stable_id']}))
        self.assertEqual(excluded, [])
        self.assertEqual(exclusion_counts['stable_id_exclusions'], 1)

    def test_no_right_context_or_distant_left_context_influence(self):
        plain, _ = self.extract('Good Alpha.', QUALITY_CLEANER_VERSION)
        future, counts = self.extract('Good Alpha. 『』', QUALITY_CLEANER_VERSION)
        self.assertEqual(len(future), 1)
        self.assertEqual(plain[0]['stable_id'], future[0]['stable_id'])
        self.assertEqual(counts['quality_quarantined'], 0)
        distant, _ = self.extract('『』' + 'x'*65 + ' Alpha.', QUALITY_CLEANER_VERSION)
        self.assertEqual(len(distant), 1)

    def test_unknown_cleaner_fails_and_legacy_cli_default_stays(self):
        with self.assertRaises(PreprocessingError):
            self.extract('Good Alpha.', 'invented-version')
        args = ['jawiki-preprocess', 'dump', 'output', '--jawiki-manifest', 'jawiki',
                '--allowed-root', '.', '--dictionary-index', 'index', '--dictionary-manifest', 'dictionary',
                '--report', 'report', '--extractor-git-sha', EXTRACTOR_SHA]
        self.assertEqual(_parser().parse_args(args).cleaner_version, CLEANER_VERSION)
        self.assertEqual(_parser().parse_args(args + ['--cleaner-version', QUALITY_CLEANER_VERSION]).cleaner_version,
                         QUALITY_CLEANER_VERSION)

    def publish(self, directory, text, cfg=None):
        dump, output, report = [directory/name for name in ('fixture.bz2', 'source.jsonl', 'manifest.json')]
        dump.write_bytes(bz2.compress(fixture(text)))
        with patch('sakura_rerank.data.jawiki_preprocess.validate_dictionary_index_manifest',
                   return_value={'content_sha256': INDEX_SHA}):
            extract_source_spans(dump, output, report, jawiki_manifest=jawiki_manifest(),
                                 dictionary_records=dictionary_records(), dictionary_manifest=dictionary_manifest(),
                                 extractor_git_sha=EXTRACTOR_SHA, config=cfg or config(),
                                 cleaner_version=QUALITY_CLEANER_VERSION)
        return json.loads(report.read_bytes()), [json.loads(line) for line in output.read_bytes().splitlines()]

    def validate(self, manifest, rows, **kwargs):
        return validate_source_span_manifest(manifest, rows, jawiki_manifest=jawiki_manifest(),
                                             dictionary_manifest=dictionary_manifest(), **kwargs)

    def test_v5_manifest_binds_policy_and_cannot_promote_itself_to_verified(self):
        with tempfile.TemporaryDirectory() as d:
            manifest, rows = self.publish(Path(d), 'Good Alpha.\n\n『』 Alpha.')
            self.assertEqual(manifest['schema_version'], 5)
            self.assertEqual(manifest['candidate_quality_policy'], QUALITY_POLICY)
            self.assertEqual(self.validate(manifest, rows, require_verified=False), manifest)
            with self.assertRaises(TierABlockedError):
                self.validate(manifest, rows)
            for change in (dict(verification_status='verified'), dict(cleaner_version=CLEANER_VERSION),
                           dict(schema_version=4), dict(candidate_quality_policy='invented')):
                with self.subTest(change=change), self.assertRaises(TierAError):
                    self.validate(dict(manifest, **change), rows, require_verified=False)
            for key in ('quality_examined', 'quality_retained', 'quality_empty_title_delimiters'):
                bad = copy.deepcopy(manifest)
                bad['counts'][key] += 1
                with self.assertRaises(TierAError):
                    self.validate(bad, rows, require_verified=False)
            schema = json.loads(Path('manifests/jawiki-tier-a-source-spans-manifest.schema.json').read_bytes())
            self.assertEqual(schema['properties']['candidate_quality_policy']['const'], QUALITY_POLICY)
            self.assertIn(5, schema['properties']['schema_version']['enum'])

    def test_all_quarantined_has_explicit_failure_and_preserves_previous_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path/'source.jsonl').write_bytes(b'old-source')
            (path/'manifest.json').write_bytes(b'old-manifest')
            with self.assertRaisesRegex(PreprocessingError, 'no source spans'):
                self.publish(path, '『{{title}}』 Alpha.')
            self.assertEqual((path/'source.jsonl').read_bytes(), b'old-source')
            self.assertEqual((path/'manifest.json').read_bytes(), b'old-manifest')
            self.assertFalse(list(path.glob('*.tmp')))

    def test_output_byte_bound_is_in_the_v5_denominator(self):
        text = 'First Alpha.\n\nSecond Alpha.'
        rows, _ = self.extract(text, QUALITY_CLEANER_VERSION)
        size = len(canonical_json_bytes(rows[0])) + 1
        with tempfile.TemporaryDirectory() as d:
            manifest, saved = self.publish(Path(d), text, replace(config(), max_output_bytes=size))
            self.assertEqual(len(saved), 1)
            self.assertEqual(manifest['counts']['quality_output_byte_skipped'], 1)
            self.assertEqual(manifest['counts']['quality_examined'], 2)
            self.validate(manifest, saved, require_verified=False)


class SourceQualityTrainAuditTests(unittest.TestCase):
    def test_train_only_parse_union_counts_and_private_ledger(self):
        rows = [dict(stable_id=str(i), split='train', is_fixture=False, training_eligible=True,
                     session={'left_context': left}, gold_surface='Alpha')
                for i, left in enumerate(('Good ', '『』', r'\mbox{', r'『』\frac{'))]
        # These deliberately invalid non-train JSON lines must never reach the parser.
        raw = (b'{broken,"split":"dev",}\n' + b'{broken,"split":"final-holdout",}\n'
               + b''.join(canonical_json_bytes(row)+b'\n' for row in rows))
        with tempfile.TemporaryDirectory() as d, patch(
            'sakura_rerank.data.source_quality_audit.validate_record', side_effect=lambda r:r
        ) as validate:
            path = Path(d)/'frozen.jsonl'; path.write_bytes(raw)
            report, ledger = audit_train(path, hashlib.sha256(raw).hexdigest())
            self.assertEqual(validate.call_count, 4)
            self.assertEqual(report['original_train_denominator'], 4)
            self.assertEqual(report['proposed_quarantined'], 3)
            self.assertEqual(sum(report['reasons'].values()), 4)
            self.assertEqual(report['dev_skipped_before_json'], 1)
            self.assertEqual(report['holdout_skipped_before_json'], 1)
            self.assertEqual(report['evidence_rows'], 4)
            self.assertNotIn('stable_id', report)
            self.assertNotIn('Alpha', json.dumps(report))
            self.assertEqual(len(ledger.splitlines()), 4)
            self.assertFalse(report['canonical_labels_changed'])
            self.assertFalse(report['gate_a_pass'])
            self.assertEqual(audit_train(path, hashlib.sha256(raw).hexdigest()), (report, ledger))
            with self.assertRaises(ValueError):
                audit_train(path, '0'*64)

    def test_bad_split_duplicate_bounds_and_no_training_rows_fail_closed(self):
        train = dict(stable_id='id', split='train', is_fixture=False, training_eligible=True,
                     session={'left_context': ''}, gold_surface='Alpha')
        valid = canonical_json_bytes(train)+b'\n'
        for raw in (b'{"split":"unknown"}\n', valid+valid, b'{,"split":"dev",}\n', b'x'*(256*1024+1)):
            with self.subTest(length=len(raw)), tempfile.TemporaryDirectory() as d, patch(
                'sakura_rerank.data.source_quality_audit.validate_record', side_effect=lambda r:r
            ):
                path = Path(d)/'frozen.jsonl'; path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    audit_train(path, hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    unittest.main()
