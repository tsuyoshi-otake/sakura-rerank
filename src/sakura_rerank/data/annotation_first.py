"""Whole original ruby bases as provisional research targets, never Gold."""
from bisect import bisect_right
from collections import Counter
import hashlib
import re

from .aozora_ruby_evidence import paragraphs_with_ruby
from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .jawiki_preprocess import _sentences


def source_metadata(work_id, author_id, paragraph, sentence):
    return dict(article_id="aozora-work-" + work_id, paragraph_hash=text_sha256(paragraph),
                sentence_hash=text_sha256(sentence), sentence_shingle_hashes=sentence_shingle_hashes(sentence),
                template_cluster_id="aozora-author-" + author_id)


def extract_work(raw, work_id, author_id, expected_revision):
    """One terminal per retained annotation; whole retained-source coverage."""
    if (not work_id.isdigit() or not author_id.isdigit()
            or hashlib.sha256(raw).hexdigest() != expected_revision):
        raise ValueError("annotation_source_identity_differs")
    paragraphs, original = paragraphs_with_ruby(raw)
    targets, terminals, coverage = [], [], {}
    reasons, flags, coverage_counts = Counter(), Counter(), Counter()
    for pi, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        sentences = list(_sentences(text))
        starts = [offset for offset, _ in sentences]
        for offset, sentence in sentences:
            pieces = [sentence] if len(sentence) <= 512 else [sentence[i:i + 512] for i in range(0, len(sentence), 256)]
            coverage_counts["long_sentences_windowed"] += len(sentence) > 512
            for piece in pieces:
                metadata = source_metadata(work_id, author_id, text, piece)
                if not metadata["sentence_shingle_hashes"]:
                    coverage_counts["empty_normalized_source_piece"] += 1
                    continue
                if len(metadata["sentence_shingle_hashes"]) > 512:
                    raise ValueError("annotation_source_signature_bound")
                key = "ruby-coverage-" + canonical_json_hash(metadata)
                coverage_counts["source_pieces_before_deduplication"] += 1
                coverage[key] = dict(stable_id=key, population="source_coverage", source=metadata)
        for ri, ruby in enumerate(paragraph["spans"]):
            start, end, observed = ruby["start"], ruby["end"], ruby["reading"]
            target = text[start:end]
            reading = "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in observed)
            stable = "ruby-first-" + canonical_json_hash([work_id, expected_revision, pi, ri, start, end, target, observed])
            index = bisect_right(starts, start) - 1
            sentence_ok = index >= 0 and end <= sentences[index][0] + len(sentences[index][1])
            left = text[max(0, start - 64):start]
            failures = tuple(name for name, failed in (
                ("ruby_base_unresolved", ruby["kind"] == "unresolved_base" or paragraph["flags"]["orphan_marker"]),
                ("editorial_or_nonphonetic", observed in ("ママ", "まま") or re.fullmatch(r"[ぁ-ゖァ-ヶー]+", observed) is None),
                ("reading_outside_bounds", not 2 <= len(reading) <= 32),
                ("target_outside_bounds", not 1 <= len(target) <= 32),
                ("insufficient_left_context", len(left) < 8),
                ("source_sentence_boundary", not sentence_ok),
                ("source_sentence_too_long", sentence_ok and len(sentences[index][1]) > 512),
            ) if failed)
            status = failures[0] if failures else "provisional"
            terminal = dict(stable_id=stable, work_id=work_id, paragraph_index=pi, annotation_index=ri,
                start=start, end=end, raw_reading_sha256=text_sha256(observed), target_sha256=text_sha256(target),
                source_line_sha256=paragraph["source_line_sha256"], status=status, flags=list(failures))
            terminals.append(terminal)
            reasons[status] += 1
            flags.update(failures)
            if failures:
                continue
            sentence = sentences[index][1]
            targets.append(dict(kind="original_ruby_provisional_target", stable_id=stable, population="train", corpus="aozora",
                source_id=work_id, source_revision=expected_revision, author_id=author_id,
                left_context=left, reading=reading, target=target, raw_annotation_reading=observed,
                annotation_kind=ruby["kind"], reading_mapping="fullwidth_katakana_to_hiragana_only",
                paragraph_index=pi, annotation_index=ri, paragraph_start=start, paragraph_end=end,
                sentence_index=index, source_line_number=paragraph["line_number"],
                source_line_sha256=paragraph["source_line_sha256"],
                context_origin="synthetic_source_prefix_not_observed_session",
                label_kind="source_annotated_weak_supervision", independent_gold_eligible=False, training_eligible=False,
                source=source_metadata(work_id, author_id, text, sentence)))
    return targets, terminals, [coverage[k] for k in sorted(coverage)], dict(
        annotation_slots=len(terminals), provisional_targets=len(targets), terminal_counts=dict(reasons),
        overlapping_exclusion_flags=dict(flags), source_coverage_nodes=len(coverage), coverage_counts=dict(coverage_counts),
        original_cleaner=original)
