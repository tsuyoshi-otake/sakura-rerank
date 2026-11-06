"""Bounded export decoding and exact ruby alignment; never IME Gold admission.

The provider exports MySQL-escaped UTF-8 TSV. Japanese transcriptions use
``[base|reading|reading]``. Empty per-character reading pieces are permitted,
but an empty complete base or reading is not. Bracket literals/unsupported
markup remain explicit failures rather than being repaired or normalized.
"""
from __future__ import annotations

import bz2
from dataclasses import dataclass
from pathlib import Path
import re


class SourceFormatError(ValueError):
    """A text-free terminal reason, safe for aggregate diagnostics."""


def raw_export_rows(path: Path, columns: int, *, max_rows: int = 500_000,
                    max_bytes: int = 128 * 1024 * 1024, max_line: int = 65_536):
    """Scan raw metadata fields without UTF-8 decoding sentence/reading fields."""
    if columns < 2 or min(max_rows, max_bytes, max_line) < 1:
        raise SourceFormatError('invalid_export_bounds')
    total = 0
    with bz2.open(path, 'rb') as stream:
        for number in range(1, max_rows + 2):
            raw = bytearray()
            while True:
                part = stream.readline(max_line + 1 - len(raw))
                raw.extend(part)
                if not part or len(raw) > max_line:
                    break
                backslashes = len(raw[:-1]) - len(raw[:-1].rstrip(b'\\'))
                if raw.endswith(b'\n') and backslashes % 2 == 0:
                    break
            if not raw:
                return
            raw = bytes(raw)
            total += len(raw)
            if number > max_rows or len(raw) > max_line or total > max_bytes or not raw.endswith(b'\n'):
                raise SourceFormatError('export_expansion_bound')
            fields, start = [], 0
            for match in re.finditer(rb'\\[\s\S]|\t', raw[:-1]):
                if match.group() == b'\t':
                    fields.append(raw[start:match.start()])
                    start = match.end()
            fields.append(raw[start:-1])
            if (len(fields) != columns or not fields[0].isdigit()
                    or not 0 < int(fields[0]) < 2**63):
                raise SourceFormatError('export_metadata_schema')
            yield number, raw, fields


def decode_export_field(raw: bytes) -> str | None:
    """Decode the fixed TSV contract; reject unknown escapes without text leaks."""
    if len(raw) > 65_536:
        raise SourceFormatError('field_byte_bound')
    if raw == b'\\N':
        return None
    escapes = {ord('0'): 0, ord('b'): 8, ord('n'): 10, ord('r'): 13,
               ord('t'): 9, ord('Z'): 26, ord('\\'): 92,
               0: 0, 9: 9, 10: 10, 13: 13}
    result = bytearray()
    pos = 0
    while pos < len(raw):
        byte = raw[pos]
        pos += 1
        if byte == 92:
            if pos == len(raw) or raw[pos] not in escapes:
                raise SourceFormatError('unsupported_export_escape')
            byte = escapes[raw[pos]]
            pos += 1
        result.append(byte)
    try:
        value = result.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise SourceFormatError('invalid_export_utf8') from None
    if len(value) > 10_000:
        raise SourceFormatError('field_character_bound')
    return value


@dataclass(frozen=True)
class RubySpan:
    start: int
    end: int
    base: str
    reading: str
    reading_parts: tuple[str, ...]


@dataclass(frozen=True)
class Transcription:
    surface: str
    phonetic_projection: str
    spans: tuple[RubySpan, ...]
    literal_segments: tuple[str, ...]


def parse_transcription(value: str) -> Transcription:
    """Preserve exact code points and whole ruby bases; do not split lexical units."""
    if not isinstance(value, str) or not value or len(value) > 10_000:
        raise SourceFormatError('transcription_character_bound')
    surface, projection, spans, literals = [], [], [], []
    pos = 0
    surface_length = 0
    while pos < len(value):
        if value[pos] != '[':
            end = value.find('[', pos)
            if end < 0:
                end = len(value)
            literal = value[pos:end]
            if ']' in literal or '|' in literal:
                raise SourceFormatError('unsupported_literal_markup')
            literals.append(literal)
            surface.append(literal)
            projection.append(literal)
            surface_length += len(literal)
            pos = end
            continue
        end = value.find(']', pos + 1)
        if end < 0:
            raise SourceFormatError('unclosed_ruby')
        body = value[pos + 1:end]
        if '[' in body:
            raise SourceFormatError('nested_ruby')
        parts = body.split('|')
        if len(parts) < 2 or not parts[0] or not ''.join(parts[1:]):
            raise SourceFormatError('empty_or_missing_ruby')
        base, reading = parts[0], ''.join(parts[1:])
        spans.append(RubySpan(surface_length, surface_length + len(base), base, reading, tuple(parts[1:])))
        surface.append(base)
        projection.append(reading)
        surface_length += len(base)
        pos = end + 1
    return Transcription(''.join(surface), ''.join(projection), tuple(spans), tuple(literals))


def is_han(char: str) -> bool:
    point = ord(char)
    return (0x3400 <= point <= 0x4DBF or 0x4E00 <= point <= 0x9FFF
            or 0xF900 <= point <= 0xFAFF or 0x20000 <= point <= 0x323AF
            or char in '々〆ヶ')


def is_kana_reading(value: str) -> bool:
    """A conservative character test, not a pronunciation or intended-reading verdict."""
    return bool(value) and all('\u3041' <= c <= '\u3096' or '\u30a1' <= c <= '\u30fa'
                               or c in 'ーゝゞヽヾ' for c in value)


def audit_pair(sentence: str, transcription: str) -> tuple[dict, Transcription | None]:
    if not isinstance(sentence, str) or not sentence or len(sentence) > 10_000:
        return {'status': 'invalid_sentence', 'source_exact': False}, None
    try:
        parsed = parse_transcription(transcription)
    except SourceFormatError as error:
        return {'status': str(error), 'source_exact': False}, None
    exact = sentence == parsed.surface
    result = dict(status='source_exact' if exact else 'source_mismatch', source_exact=exact,
                  ruby_spans=len(parsed.spans),
                  kana_reading_spans=sum(is_kana_reading(s.reading) for s in parsed.spans),
                  unannotated_han=sum(is_han(c) for part in parsed.literal_segments for c in part),
                  control_characters=sum(ord(c) < 32 or ord(c) == 127 for c in sentence + transcription),
                  independent_ime_gold=False, intended_reading_verified=False,
                  input_unit_verified=False)
    return result, parsed
