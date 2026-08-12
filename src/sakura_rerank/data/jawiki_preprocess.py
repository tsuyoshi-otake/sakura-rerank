"""Streaming, conservative jawiki extraction for Tier A source spans."""

from __future__ import annotations

import bz2
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

from ..atomic_io import commit_staged_file_and_bytes_atomic
from .contracts import (
    MAX_READING_CHARS,
    MIN_READING_CHARS,
    ContractError,
    _require_identifier,
    canonical_json_bytes,
    sentence_shingle_hashes,
    text_sha256,
)
from .manifest import LOCAL_ARTIFACT_VERIFIED
from .tier_a import (
    SOURCE_SPAN_RECORD_TYPE,
    SOURCE_SPAN_CLEANER_VERSION,
    SOURCE_SPAN_MANIFEST_KIND,
    SOURCE_SPAN_MANIFEST_SCHEMA_VERSION,
    SOURCE_SPAN_SCHEMA_VERSION,
    MAX_STABLE_ID_EXCLUSIONS,
    STABLE_ID_EXCLUSION_CANONICALIZATION,
    STABLE_ID_EXCLUSION_FORMAT_VERSION,
    TierAError,
    ensure_distinct_tier_a_paths,
    read_dictionary_index,
    read_dictionary_index_manifest,
    validate_dictionary_index_manifest,
)


PREPROCESSING_SCHEMA_VERSION = SOURCE_SPAN_MANIFEST_SCHEMA_VERSION
PREPROCESSING_MANIFEST_KIND = SOURCE_SPAN_MANIFEST_KIND
CLEANER_VERSION = SOURCE_SPAN_CLEANER_VERSION
MAX_PAGE_TEXT_CHARS = 10_000_000
MAX_PARAGRAPH_CHARS = 16_384
MAX_SENTENCE_CHARS = 512
MAX_COMMITTED_PREFIX_CHARS = 4_096
MAX_GOLD_SURFACE_CHARS = 64
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_STABLE_ID_EXCLUSION_BYTES = 16 * 1024 * 1024

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_REF_RE = re.compile(r"<ref\b[^>]*>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
_REF_SELF_RE = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
_TABLE_RE = re.compile(r"\{\|.*?\|\}", re.DOTALL)
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_EXTERNAL_LINK_RE = re.compile(r"\[(https?://[^\s\]]+)(?:\s+([^\]]+))?\]")
_HEADING_RE = re.compile(r"^\s*=+\s*(.*?)\s*=+\s*$")
_LIST_PREFIX_RE = re.compile(r"^\s*[*#;:]+\s*")
_SENTENCE_RE = re.compile(r".*?[。！？]+|.+$", re.DOTALL)
_RESIDUAL_MARKUP = (
    "{{",
    "}}",
    "[[",
    "]]",
    "{|",
    "|}",
    "http://",
    "https://",
    "''",
)
_RESIDUAL_DECORATIVE_CORRUPTION = frozenset("\u25bd\u25ef")
_DROP_LINK_NAMESPACES = frozenset(
    {
        "file",
        "image",
        "category",
        "template",
        "help",
        "portal",
        "wikipedia",
        "media",
        "ファイル",
        "画像",
        "カテゴリ",
        "テンプレート",
        "ヘルプ",
        "ポータル",
        "ウィキペディア",
        "メディア",
    }
)
_RESIDUAL_NAMESPACE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:file|image|category|template|help|portal|wikipedia|media|"
    r"ファイル|画像|カテゴリ|テンプレート|ヘルプ|ポータル|ウィキペディア|メディア):",
    re.IGNORECASE,
)


class PreprocessingError(ValueError):
    """The source-span pipeline could not produce a trusted terminal state."""


def contains_v4_decorative_corruption(text: str) -> bool:
    return any(marker in text for marker in _RESIDUAL_DECORATIVE_CORRUPTION)


def contains_v4_bare_pipe(text: str) -> bool:
    return "|" in text


def contains_v4_residual_corruption(text: str) -> bool:
    """Return whether either zero-false-fire dev-supported v4 rule fires.

    Keeping the predicate public lets the corpus partition commit the exact
    same deterministic rule that source preprocessing applies at Stage 4.
    """

    return contains_v4_decorative_corruption(text) or contains_v4_bare_pipe(text)


def _empty_stable_id_exclusion_commitment() -> dict[str, Any]:
    return {
        "format_version": STABLE_ID_EXCLUSION_FORMAT_VERSION,
        "canonicalization": STABLE_ID_EXCLUSION_CANONICALIZATION,
        "count": 0,
        "content_sha256": hashlib.sha256(b"").hexdigest(),
        "raw_stable_ids_in_report": False,
    }


def load_stable_id_exclusion(
    path: str | Path | None,
) -> tuple[frozenset[str], dict[str, Any]]:
    """Read the bounded, canonical Stage 4 stable-ID exclusion input.

    The input is deliberately accepted only in its canonical JSONL encoding so
    the manifest commitment proves the exact ordered exclusion set without
    disclosing any identifiers in a tracked report.
    """

    if path is None:
        return frozenset(), _empty_stable_id_exclusion_commitment()
    source = Path(path)
    try:
        size = source.stat().st_size
        payload = source.read_bytes()
    except OSError as error:
        raise PreprocessingError(
            f"stable-ID exclusion input cannot be read ({type(error).__name__})"
        ) from error
    if size > MAX_STABLE_ID_EXCLUSION_BYTES or len(payload) != size:
        raise PreprocessingError("stable-ID exclusion input exceeds or changed during bounded read")
    if not payload:
        return frozenset(), _empty_stable_id_exclusion_commitment()
    if b"\r" in payload or not payload.endswith(b"\n"):
        raise PreprocessingError("stable-ID exclusion input must use canonical JSONL with UTF-8 LF")
    lines = payload[:-1].split(b"\n")
    if not lines or len(lines) > MAX_STABLE_ID_EXCLUSIONS or any(not line for line in lines):
        raise PreprocessingError("stable-ID exclusion input count is outside the bound")
    stable_ids: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PreprocessingError(
                f"stable-ID exclusion input line {line_number} is not UTF-8 JSON"
            ) from error
        if not isinstance(record, Mapping) or set(record) != {"stable_id"}:
            raise PreprocessingError(
                f"stable-ID exclusion input line {line_number} must contain only stable_id"
            )
        try:
            stable_id = _require_identifier(record["stable_id"], "stable-ID exclusion stable_id")
        except ContractError as error:
            raise PreprocessingError(str(error)) from error
        if line != canonical_json_bytes({"stable_id": stable_id}):
            raise PreprocessingError("stable-ID exclusion input must be canonical JSONL")
        stable_ids.append(stable_id)
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise PreprocessingError("stable-ID exclusion input stable_id values must be sorted and unique")
    return frozenset(stable_ids), {
        "format_version": STABLE_ID_EXCLUSION_FORMAT_VERSION,
        "canonicalization": STABLE_ID_EXCLUSION_CANONICALIZATION,
        "count": len(stable_ids),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "raw_stable_ids_in_report": False,
    }


@dataclass(frozen=True)
class ExtractorConfig:
    sample_modulus: int = 1_000
    sample_slots: int = 10
    max_records: int = 200_000
    max_records_per_page: int = 32
    max_output_bytes: int = 240 * 1024 * 1024
    min_sentence_chars: int = 4
    max_sentence_chars: int = MAX_SENTENCE_CHARS
    min_surface_chars: int = 1
    max_surface_chars: int = MAX_GOLD_SURFACE_CHARS
    min_reading_chars: int = MIN_READING_CHARS
    max_reading_chars: int = MAX_READING_CHARS

    def validate(self) -> None:
        if not 1 <= self.sample_modulus <= 1_000_000:
            raise PreprocessingError("sample_modulus is outside the bound")
        if not 1 <= self.sample_slots <= self.sample_modulus:
            raise PreprocessingError("sample_slots is outside the modulus")
        if not 1 <= self.max_records <= 1_000_000:
            raise PreprocessingError("max_records is outside the bound")
        if not 1 <= self.max_records_per_page <= 1_000:
            raise PreprocessingError("max_records_per_page is outside the bound")
        if not 1 <= self.max_output_bytes <= MAX_OUTPUT_BYTES:
            raise PreprocessingError("max_output_bytes is outside the Tier A input bound")
        if not 1 <= self.min_sentence_chars <= self.max_sentence_chars <= 4_096:
            raise PreprocessingError("sentence bounds are invalid")
        if not 1 <= self.min_surface_chars <= self.max_surface_chars <= 256:
            raise PreprocessingError("surface bounds are invalid")
        if not (
            MIN_READING_CHARS
            <= self.min_reading_chars
            <= self.max_reading_chars
            <= MAX_READING_CHARS
        ):
            raise PreprocessingError("reading bounds are invalid")


class SurfaceMatcher:
    """Exact prefix-bucket matcher over unique-reading dictionary surfaces."""

    def __init__(self, records: Sequence[Mapping[str, Any]], config: ExtractorConfig):
        buckets: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
        boundary_metadata: dict[str, tuple[str | None, str | None, bool]] = {}
        accepted = 0
        for record in records:
            surface = record["surface"]
            readings = record["readings"]
            if (
                len(readings) != 1
                or not config.min_surface_chars <= len(surface) <= config.max_surface_chars
                or not config.min_reading_chars
                <= len(readings[0])
                <= config.max_reading_chars
            ):
                continue
            key = surface if len(surface) == 1 else surface[:2]
            buckets[key][len(surface)].add(surface)
            boundary_metadata[surface] = (
                _character_class(surface[0]),
                _character_class(surface[-1]),
                all(
                    _character_class(character) in {"hiragana", "katakana"}
                    for character in surface
                ),
            )
            accepted += 1
        self._buckets = {
            key: tuple((length, frozenset(values)) for length, values in sorted(groups.items(), reverse=True))
            for key, groups in buckets.items()
        }
        self._boundary_metadata = boundary_metadata
        self.surface_count = accepted

    def matches(
        self, text: str, counts: Counter[str] | None = None
    ) -> Iterator[tuple[int, int, str]]:
        position = 0
        parenthesis_depth = 0
        while position < len(text):
            groups = []
            if position + 1 < len(text):
                groups.extend(self._buckets.get(text[position : position + 2], ()))
            groups.extend(self._buckets.get(text[position], ()))
            match: tuple[int, int, str] | None = None
            for length, surfaces in groups:
                end = position + length
                if end <= len(text):
                    candidate = text[position:end]
                    if candidate in surfaces and (match is None or length > len(match[2])):
                        match = (position, end, candidate)
            if match is None:
                next_position = position + 1
            elif not _safe_match_boundaries(
                text,
                *match,
                self._boundary_metadata[match[2]],
                inside_parentheses=parenthesis_depth > 0,
            ):
                if counts is not None:
                    counts["matches_unsafe_boundary"] += 1
                next_position = position + 1
            else:
                yield match
                next_position = match[1]

            if next_position == position + 1:
                character = text[position]
                if character == "(":
                    parenthesis_depth += 1
                elif character == ")" and parenthesis_depth:
                    parenthesis_depth -= 1
            else:
                for character in text[position:next_position]:
                    if character == "(":
                        parenthesis_depth += 1
                    elif character == ")" and parenthesis_depth:
                        parenthesis_depth -= 1
            position = next_position


def _character_class(character: str) -> str | None:
    if character.isascii() and character.isalnum():
        return "ascii_alnum"
    codepoint = ord(character)
    if 0x3040 <= codepoint <= 0x309F:
        return "hiragana"
    if 0x30A0 <= codepoint <= 0x30FF:
        return "katakana"
    return None


def _safe_match_boundaries(
    text: str,
    start: int,
    end: int,
    surface: str,
    metadata: tuple[str | None, str | None, bool],
    *,
    inside_parentheses: bool,
) -> bool:
    """Reject dictionary substrings that cut through a lexical token or reading note."""

    first_class, last_class, pure_kana = metadata
    if start and first_class is not None and _character_class(text[start - 1]) == first_class:
        return False
    if end < len(text) and last_class is not None and _character_class(text[end]) == last_class:
        return False
    if pure_kana and inside_parentheses:
        return False
    return True


def _remove_balanced(text: str, opening: str, closing: str) -> str | None:
    output: list[str] = []
    depth = 0
    index = 0
    while index < len(text):
        if text.startswith(opening, index):
            depth += 1
            index += len(opening)
        elif text.startswith(closing, index):
            if depth == 0:
                return None
            depth -= 1
            index += len(closing)
        else:
            if depth == 0:
                output.append(text[index])
            index += 1
    return "".join(output) if depth == 0 else None


def _replace_internal_links(text: str) -> str | None:
    output: list[str] = []
    index = 0
    while index < len(text):
        start = text.find("[[", index)
        if start < 0:
            output.append(text[index:])
            break
        output.append(text[index:start])
        end = text.find("]]", start + 2)
        if end < 0:
            return None
        content = text[start + 2 : end]
        if "[[" in content:
            return None
        target = content.split("|", 1)[0].strip()
        namespace_target = target.lstrip(":").strip()
        namespace = (
            namespace_target.split(":", 1)[0].casefold()
            if ":" in namespace_target
            else ""
        )
        if namespace not in _DROP_LINK_NAMESPACES:
            display = content.rsplit("|", 1)[-1].strip()
            output.append(display.split("#", 1)[0])
        index = end + 2
    return "".join(output)


def clean_wikitext(raw: str) -> tuple[list[str], Counter[str]]:
    counts: Counter[str] = Counter()
    text = _COMMENT_RE.sub("", raw)
    text = _REF_RE.sub("", text)
    text = _REF_SELF_RE.sub("", text)
    text = _TABLE_RE.sub("\n\n", text)
    text = _remove_balanced(text, "{{", "}}")
    if text is None:
        return [], Counter({"unbalanced_template": 1})
    text = _replace_internal_links(text)
    if text is None:
        return [], Counter({"unbalanced_link": 1})
    text = _EXTERNAL_LINK_RE.sub(lambda match: match.group(2) or "", text)
    text = _TAG_RE.sub("", text)
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n+", text):
        for line in block.splitlines():
            heading = _HEADING_RE.fullmatch(line)
            line = heading.group(1) if heading else _LIST_PREFIX_RE.sub("", line)
            line = html.unescape(line)
            line = unicodedata.normalize("NFKC", " ".join(line.split()))
            paragraph = line.strip()
            if not paragraph:
                continue
            if len(paragraph) > MAX_PARAGRAPH_CHARS:
                counts["paragraph_too_long"] += 1
                continue
            if (
                any(marker in paragraph for marker in _RESIDUAL_MARKUP)
                or "<" in paragraph
                or ">" in paragraph
                or _RESIDUAL_NAMESPACE_RE.search(paragraph) is not None
            ):
                counts["residual_markup"] += 1
                continue
            if contains_v4_residual_corruption(paragraph):
                counts["residual_corruption"] += 1
                continue
            paragraphs.append(paragraph)
    return paragraphs, counts


def _sentences(paragraph: str) -> Iterator[tuple[int, str]]:
    for match in _SENTENCE_RE.finditer(paragraph):
        sentence = match.group(0).strip()
        if sentence:
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            yield match.start() + leading, sentence


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if child.tag.rsplit("}", 1)[-1] == name), None)


def _text(element: ET.Element, name: str) -> str | None:
    child = _child(element, name)
    return None if child is None else child.text


def _sampled(key: bytes, config: ExtractorConfig) -> bool:
    value = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return value % config.sample_modulus < config.sample_slots


def _span_record(
    *,
    page_sequence: int,
    page_id: str,
    revision_id: str,
    paragraph_index: int,
    sentence_index: int,
    paragraph: str,
    sentence: str,
    sentence_offset: int,
    match_start: int,
    match_end: int,
    surface: str,
) -> dict[str, Any]:
    sentence_hash = text_sha256(sentence)
    identity = (
        f"{page_id}:{revision_id}:{paragraph_index}:{sentence_index}:"
        f"{match_start}:{match_end}:{surface}"
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    stable_id = (
        f"jawiki-20260801-{page_sequence:08d}-{paragraph_index:05d}-"
        f"{sentence_index:04d}-{match_start:04d}-{suffix}"
    )
    prefix_end = sentence_offset + match_end
    committed_prefix = paragraph[max(0, prefix_end - MAX_COMMITTED_PREFIX_CHARS) : prefix_end]
    return {
        "schema_version": SOURCE_SPAN_SCHEMA_VERSION,
        "record_type": SOURCE_SPAN_RECORD_TYPE,
        "stable_id": stable_id,
        "source": {
            "corpus": "jawiki",
            "snapshot_date": "2026-08-01",
            "article_id": f"jawiki-page-{page_id}",
            "page_id": page_id,
            "revision_id": revision_id,
            "paragraph_hash": text_sha256(paragraph),
            "sentence_hash": sentence_hash,
            "sentence_shingle_hashes": sentence_shingle_hashes(sentence),
            "template_cluster_id": None,
        },
        "committed_prefix": committed_prefix,
        "gold_surface": surface,
    }


def iter_source_spans(
    stream: BinaryIO,
    matcher: SurfaceMatcher,
    config: ExtractorConfig,
    counts: Counter[str],
    *,
    excluded_stable_ids: frozenset[str] = frozenset(),
) -> Iterator[dict[str, Any]]:
    context = ET.iterparse(stream, events=("start", "end"))
    _, root = next(context)
    page_sequence = 0
    emitted = 0
    for event, element in context:
        if event != "end" or element.tag.rsplit("}", 1)[-1] != "page":
            continue
        page_sequence += 1
        counts["pages_total"] += 1
        namespace = _text(element, "ns")
        redirect = _child(element, "redirect")
        revision = _child(element, "revision")
        if namespace != "0":
            counts["pages_non_main"] += 1
        elif redirect is not None:
            counts["pages_redirect"] += 1
        elif revision is None:
            counts["pages_missing_revision"] += 1
        else:
            page_id = _text(element, "id")
            revision_id = _text(revision, "id")
            raw = _text(revision, "text") or ""
            if not page_id or not revision_id or not page_id.isdigit() or not revision_id.isdigit():
                counts["pages_invalid_identity"] += 1
            elif len(raw) > MAX_PAGE_TEXT_CHARS:
                counts["pages_text_too_long"] += 1
            else:
                counts["pages_processed"] += 1
                paragraphs, cleaning = clean_wikitext(raw)
                counts.update(cleaning)
                per_page = 0
                for paragraph_index, paragraph in enumerate(paragraphs):
                    counts["paragraphs_accepted"] += 1
                    for sentence_index, (sentence_offset, sentence) in enumerate(
                        _sentences(paragraph)
                    ):
                        if not config.min_sentence_chars <= len(sentence) <= config.max_sentence_chars:
                            counts["sentences_outside_bounds"] += 1
                            continue
                        counts["sentences_accepted"] += 1
                        for start, end, surface in matcher.matches(sentence, counts):
                            counts["dictionary_matches"] += 1
                            sample_key = (
                                f"{page_id}:{revision_id}:{paragraph_index}:"
                                f"{sentence_index}:{start}:{end}:{surface}"
                            ).encode("utf-8")
                            if not _sampled(sample_key, config):
                                counts["matches_not_sampled"] += 1
                                continue
                            record = _span_record(
                                page_sequence=page_sequence,
                                page_id=page_id,
                                revision_id=revision_id,
                                paragraph_index=paragraph_index,
                                sentence_index=sentence_index,
                                paragraph=paragraph,
                                sentence=sentence,
                                sentence_offset=sentence_offset,
                                match_start=start,
                                match_end=end,
                                surface=surface,
                            )
                            if record["stable_id"] in excluded_stable_ids:
                                counts["stable_id_exclusions"] += 1
                                continue
                            yield record
                            emitted += 1
                            per_page += 1
                            if emitted >= config.max_records:
                                counts["stopped_at_global_bound"] = 1
                                return
                            if per_page >= config.max_records_per_page:
                                counts["pages_hit_record_bound"] += 1
                                break
                        if per_page >= config.max_records_per_page:
                            break
                    if per_page >= config.max_records_per_page:
                        break
        element.clear()
        root.clear()


def extract_source_spans(
    dump_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    *,
    jawiki_manifest: Mapping[str, Any],
    dictionary_records: Sequence[Mapping[str, Any]],
    dictionary_manifest: Mapping[str, Any],
    extractor_git_sha: str,
    config: ExtractorConfig,
    stable_id_exclusion_path: str | Path | None = None,
) -> tuple[str, str, int]:
    config.validate()
    if jawiki_manifest.get("status") != LOCAL_ARTIFACT_VERIFIED:
        raise PreprocessingError("a local_artifact_verified jawiki manifest is required")
    if not re.fullmatch(r"[0-9a-f]{40}", extractor_git_sha):
        raise PreprocessingError("extractor_git_sha must be a lowercase Git SHA-1")
    normalized_dictionary_manifest = validate_dictionary_index_manifest(
        dictionary_manifest, dictionary_records
    )
    excluded_stable_ids, stable_id_exclusion = load_stable_id_exclusion(
        stable_id_exclusion_path
    )
    matcher = SurfaceMatcher(dictionary_records, config)
    output = Path(output_path)
    report = Path(report_path)
    try:
        ensure_distinct_tier_a_paths(
            {
                "dump": dump_path,
                "output": output,
                "report": report,
                **(
                    {"stable_id_exclusion": stable_id_exclusion_path}
                    if stable_id_exclusion_path is not None
                    else {}
                ),
            }
        )
    except TierAError as error:
        raise PreprocessingError(str(error)) from error
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    count = 0
    counts: Counter[str] = Counter()
    try:
        with os.fdopen(descriptor, "wb") as destination, bz2.open(dump_path, "rb") as stream:
            for record in iter_source_spans(
                stream,
                matcher,
                config,
                counts,
                excluded_stable_ids=excluded_stable_ids,
            ):
                line = canonical_json_bytes(record) + b"\n"
                if destination.tell() + len(line) > config.max_output_bytes:
                    counts["stopped_at_output_byte_bound"] = 1
                    break
                destination.write(line)
                digest.update(line)
                count += 1
            destination.flush()
            os.fsync(destination.fileno())
        if count < 1:
            raise PreprocessingError("no source spans passed the configured boundary")
        output_sha = digest.hexdigest()
        manifest = {
            "schema_version": PREPROCESSING_SCHEMA_VERSION,
            "manifest_kind": PREPROCESSING_MANIFEST_KIND,
            "verification_status": "measured",
            "snapshot_date": jawiki_manifest["snapshot_date"],
            "jawiki_local_sha256": jawiki_manifest["local_sha256"],
            "dictionary_index_sha256": normalized_dictionary_manifest["content_sha256"],
            "extractor_git_sha": extractor_git_sha,
            "cleaner_version": CLEANER_VERSION,
            "config": asdict(config),
            "eligible_dictionary_surface_count": matcher.surface_count,
            "record_count": count,
            "content_sha256": output_sha,
            "counts": dict(sorted(counts.items())),
            "raw_text_in_report": False,
            "stage4_stable_id_exclusion": stable_id_exclusion,
        }
        report_payload = canonical_json_bytes(manifest) + b"\n"
        report_sha = hashlib.sha256(report_payload).hexdigest()
        commit_staged_file_and_bytes_atomic(output, temporary, report, report_payload)
        return output_sha, report_sha, count
    finally:
        temporary.unlink(missing_ok=True)


def load_dictionary_inputs(
    index_path: str | Path, manifest_path: str | Path
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    return read_dictionary_index(index_path), read_dictionary_index_manifest(manifest_path)
