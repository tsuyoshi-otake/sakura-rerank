"""Synthetic provider-boundary contracts; fixtures are not corpus evidence."""
import bz2
from pathlib import Path
import tempfile
import unittest

from sakura_rerank.data.tatoeba_source import (
    SourceFormatError, audit_pair, decode_export_field, is_kana_reading,
    parse_transcription, raw_export_rows,
)


class TatoebaSourceTests(unittest.TestCase):
    def test_utf8_and_mysql_escaping(self):
        self.assertEqual(decode_export_field('文字'.encode() + b'\\t\\n\\r\\0\\b\\Z\\\\'), '文字\t\n\r\0\b\x1a\\')

    def test_null_and_literal_backslash_n_are_distinct(self):
        self.assertIsNone(decode_export_field(b'\\N'))
        self.assertEqual(decode_export_field(b'\\\\N'), '\\N')

    def test_unknown_escape_and_bad_utf8_fail_without_text(self):
        for raw in (b'secret\\q', b'private\\', b'private\xff'):
            with self.assertRaises(SourceFormatError) as caught:
                decode_export_field(raw)
            self.assertNotIn('secret', str(caught.exception))
            self.assertNotIn('private', str(caught.exception))

    def test_exact_whole_base_positions_and_multiple_readings(self):
        parsed = parse_transcription('前[日本|に|ほん]へ。')
        self.assertEqual(parsed.surface, '前日本へ。')
        self.assertEqual(parsed.phonetic_projection, '前にほんへ。')
        self.assertEqual((parsed.spans[0].start, parsed.spans[0].end), (1, 3))
        self.assertEqual(parsed.spans[0].base, '日本')

    def test_empty_per_character_piece_preserves_whole_base(self):
        parsed = parse_transcription('[今日|きょう|]')
        self.assertEqual(parsed.spans[0].reading, 'きょう')
        self.assertEqual(parsed.spans[0].reading_parts, ('きょう', ''))

    def test_unsupported_markup_is_pending_not_repaired(self):
        for value in ('[字]', '[|じ]', '[字|]', '[字|じ', '字]', 'a|b', '[[字|じ]|x]'):
            result, parsed = audit_pair('字', value)
            self.assertFalse(result['source_exact'])
            self.assertIsNone(parsed)

    def test_source_match_does_not_certify_context_or_ime(self):
        result, _ = audit_pair('今日。', '[今日|あした]。')
        self.assertTrue(result['source_exact'])
        self.assertFalse(result['intended_reading_verified'])
        self.assertFalse(result['input_unit_verified'])
        self.assertFalse(result['independent_ime_gold'])

    def test_surface_mismatch_is_not_normalized(self):
        result, _ = audit_pair('Ａ', 'A')
        self.assertEqual(result['status'], 'source_mismatch')

    def test_literal_han_and_controls_are_separate(self):
        result, _ = audit_pair('日月\t', '[日|にち]月\t')
        self.assertEqual(result['unannotated_han'], 1)
        self.assertGreater(result['control_characters'], 0)

    def test_reading_character_check_is_conservative(self):
        self.assertTrue(is_kana_reading('キョー'))
        for value in ('', 'abc', '漢字', 'ｶﾅ', 'か\u3099'):
            self.assertFalse(is_kana_reading(value))

    def test_supplementary_han_offsets_remain_codepoints(self):
        parsed = parse_transcription('あ[𠮷|よし]')
        self.assertEqual((parsed.spans[0].start, parsed.spans[0].end), (1, 2))

    def test_field_and_transcription_bounds(self):
        for call in (lambda: decode_export_field(b'x' * 65_537),
                     lambda: decode_export_field(b'x' * 10_001),
                     lambda: parse_transcription('x' * 10_001)):
            with self.assertRaises(SourceFormatError):
                call()

    def scan(self, raw, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.bz2'
            path.write_bytes(bz2.compress(raw))
            return list(raw_export_rows(path, 2, **kwargs))

    def test_metadata_scan_never_decodes_body_utf8(self):
        self.assertEqual(self.scan(b'1\t\xff\n')[0][2][1], b'\xff')

    def test_escaped_physical_tab_and_newline_preserve_record(self):
        rows = self.scan(b'1\tx\\\ty\\\nz\n2\tend\n')
        self.assertEqual(len(rows), 2)
        self.assertEqual(decode_export_field(rows[0][2][1]), 'x\ty\nz')

    def test_even_backslashes_do_not_escape_record_delimiter(self):
        rows = self.scan(b'1\tx\\\\\n2\ty\n')
        self.assertEqual(len(rows), 2)
        self.assertEqual(decode_export_field(rows[0][2][1]), 'x\\')

    def test_metadata_schema_rejects_incomplete_or_extra_fields(self):
        for raw in (b'0\tx\n', b'-1\tx\n', b'1\tx\ty\n', b'1\tx', b'x\ty\n'):
            with self.assertRaises(SourceFormatError):
                self.scan(raw)

    def test_expansion_line_and_row_limits(self):
        for options in ({'max_rows': 1}, {'max_bytes': 7}, {'max_line': 3}):
            with self.assertRaises(SourceFormatError):
                self.scan(b'1\tx\n2\ty\n', **options)

    def test_exact_limit_accepts_complete_export(self):
        self.assertEqual(len(self.scan(b'1\tx\n', max_rows=1, max_bytes=4, max_line=4)), 1)

    def test_invalid_bzip2_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.bz2'
            path.write_bytes(b'invalid')
            with self.assertRaises(OSError):
                list(raw_export_rows(path, 2))


if __name__ == '__main__':
    unittest.main()
