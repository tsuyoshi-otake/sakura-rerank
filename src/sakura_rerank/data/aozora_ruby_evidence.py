"""Recover source notation evidence for existing targets; never create labels."""
from collections import Counter, defaultdict
import hashlib
import re

from .contracts import canonical_json_hash, text_sha256
from .growth_corpus import SEED, aozora_paragraphs
from .jawiki_preprocess import _sentences


def _kanji(char):
    code = ord(char)
    return (0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
            or 0x20000 <= code <= 0x3134F or char in "仝々〆〇ヶ")


def parse_line(line):
    """Explicit bases and implicit kanji only; preserve unsupported scope."""
    if (not isinstance(line, str) or len(line) > 100_000
            or line.count("《") != line.count("》") or re.search(r"《[^》]*《", line)):
        raise ValueError("ruby_line_not_supported")
    plain, spans = [], []
    marker, floor, index, duplicate_marker = None, 0, 0, False
    while index < len(line):
        char = line[index]
        if char == "｜":
            duplicate_marker = duplicate_marker or marker is not None
            marker = len(plain)
            index += 1
            continue
        if char == "《":
            close = line.find("》", index + 1)
            if close < 0:
                raise ValueError("ruby_line_not_supported")
            reading = line[index + 1:close]
            end = len(plain)
            start = marker
            kind = "explicit" if marker is not None else "implicit_kanji"
            if marker is None:
                start = end
                while start > floor and _kanji(plain[start - 1]):
                    start -= 1
            if duplicate_marker or start == end:
                kind, start = "unresolved_base", floor
            spans.append(dict(start=start, end=end, reading=reading, kind=kind,
                              base_sha256=text_sha256("".join(plain[start:end]))))
            floor, marker, duplicate_marker = end, None, False
            index = close + 1
            continue
        if char == "》":
            raise ValueError("ruby_line_not_supported")
        plain.append(char)
        index += 1
    return "".join(plain), spans, dict(orphan_marker=marker is not None)


def paragraphs_with_ruby(raw):
    """Index the frozen cleaner's exact retained lines, proving byte parity."""
    expected, original_counts = aozora_paragraphs(raw)
    lines = raw.decode("cp932", errors="strict").splitlines()
    rules = [i for i, line in enumerate(lines) if re.fullmatch(r"-{20,}", line.strip())]
    annotated = []
    counts = Counter()
    # Retention is owned by the frozen cleaner. These predicates only recover
    # its original line mapping; exact paragraph parity below is mandatory.
    for line_number in range(rules[1] + 1, len(lines)):
        source_line = lines[line_number]
        if source_line.startswith("底本："):
            break
        line = source_line.strip()
        if (not line or len(line) > 100_000 or "※" in line or "［＃" in line or "］" in line
                or line.count("《") != line.count("》") or re.search(r"《[^》]*《", line)):
            continue
        cleaned = re.sub(r"《[^《》]*》", "", line).replace("｜", "")
        if "《" in cleaned or "》" in cleaned:
            continue
        plain, spans, flags = parse_line(line)
        if plain != cleaned:
            raise ValueError("ruby_stripped_line_parity_differs")
        counts.update(s["kind"] for s in spans)
        counts["orphan_marker_lines"] += flags["orphan_marker"]
        annotated.append(dict(text=plain, spans=spans, line_number=line_number,
                              source_line_sha256=text_sha256(source_line), flags=flags))
    if [p["text"] for p in annotated] != expected:
        raise ValueError("ruby_frozen_paragraph_parity_differs")
    return annotated, dict(paragraphs=len(expected), ruby_counts=dict(counts), original_cleaner_counts=original_counts)


def ruby_state(paragraph, start, end, reading):
    overlaps = [s for s in paragraph["spans"] if s["start"] < end and start < s["end"]]
    if any(s["kind"] == "unresolved_base" for s in overlaps):
        return "ruby_parse_unresolved", overlaps
    if not overlaps:
        return ("ruby_parse_unresolved" if paragraph["flags"]["orphan_marker"] else "no_ruby_overlap"), []
    if len(overlaps) != 1 or overlaps[0]["start"] != start or overlaps[0]["end"] != end:
        return "ruby_scope_differs", overlaps
    observed = overlaps[0]["reading"]
    if not re.fullmatch(r"[ぁ-ゖァ-ヶー]{1,32}", observed) or observed in ("ママ", "まま"):
        return "exact_ruby_nonphonetic_or_out_of_bounds", overlaps
    phonetic = "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in observed)
    return ("exact_ruby_reading_match" if phonetic == reading else "exact_ruby_reading_disagreement"), overlaps


def recover_rows(raw, targets):
    """Recover each immutable stable-ID preimage with bounded sentence scans."""
    if (not targets or len(targets) > 200 or len({r["stable_id"] for r in targets}) != len(targets)
            or len({r["source_id"] for r in targets}) != 1):
        raise ValueError("ruby_work_target_bound")
    revision = hashlib.sha256(raw).hexdigest()
    if any(r["corpus"] != "aozora" or r["population"] != "train" or r["source_revision"] != revision for r in targets):
        raise ValueError("ruby_train_source_provenance_differs")
    paragraphs, counts = paragraphs_with_ruby(raw)
    by_hash = defaultdict(list)
    for pi, paragraph in enumerate(paragraphs):
        by_hash[text_sha256(paragraph["text"])].append((pi, paragraph))
    recovered = []
    for row in sorted(targets, key=lambda r: r["stable_id"]):
        matches = []
        for pi, paragraph in by_hash.get(row["source"]["paragraph_hash"], []):
            for si, (offset, sentence) in enumerate(_sentences(paragraph["text"])):
                if text_sha256(sentence) != row["source"]["sentence_hash"]:
                    continue
                start = sentence.find(row["target"])
                while start >= 0:
                    end = start + len(row["target"])
                    key = canonical_json_hash([SEED, "aozora", row["source_id"], revision, pi, si, start, end, row["target"]])
                    if "growth-" + key == row["stable_id"]:
                        absolute_start, absolute_end = offset + start, offset + end
                        if paragraph["text"][max(0, absolute_start - 64):absolute_start] != row["left_context"]:
                            raise ValueError("ruby_source_context_differs")
                        state, overlaps = ruby_state(paragraph, absolute_start, absolute_end, row["reading"])
                        matches.append(dict(state=state, paragraph_index=pi, sentence_index=si,
                            sentence_start=start, sentence_end=end, paragraph_start=absolute_start,
                            paragraph_end=absolute_end, source_line_number=paragraph["line_number"],
                            source_line_sha256=paragraph["source_line_sha256"],
                            annotations=[dict(start=s["start"], end=s["end"], kind=s["kind"],
                                base_sha256=s["base_sha256"], reading_sha256=text_sha256(s["reading"])) for s in overlaps]))
                    start = sentence.find(row["target"], start + 1)
        if len(matches) > 1:
            raise ValueError("ruby_source_span_not_unique")
        recovered.append(dict(stable_id=row["stable_id"], source_row_sha256=canonical_json_hash(row),
            **(matches[0] if matches else dict(state="span_not_recovered"))))
    return recovered, counts
