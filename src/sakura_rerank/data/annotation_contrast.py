"""Descriptive original-annotation observations and conservative contrast counts.

Neither character adjacency nor source-form disagreement is a linguistic verdict.
Original annotations remain weak evidence and are never admitted by this module.
"""
from collections import Counter, defaultdict
import unicodedata

from .contrast_capacity import review_flags, witnesses
from .contracts import canonical_json_hash
from .ranking_signal import conflicts


def char_class(char):
    if not char:
        return "paragraph_boundary"
    if len(char) != 1:
        raise ValueError("annotation_observation_character_bound")
    point = ord(char)
    if 0x3400 <= point <= 0x9FFF or 0x20000 <= point <= 0x3134F:
        return "kanji_range"
    if 0x3041 <= point <= 0x3096:
        return "hiragana"
    if 0x30A1 <= point <= 0x30FA or 0xFF66 <= point <= 0xFF9D:
        return "katakana"
    if char.isspace():
        return "whitespace"
    if unicodedata.category(char).startswith("P"):
        return "punctuation"
    return "other"


def boundary_observation(row, paragraph):
    """Audit-only adjacent character classes; no right-context model feature."""
    start, end = row["paragraph_start"], row["paragraph_end"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(paragraph)
            or paragraph[start:end] != row["target"]
            or paragraph[max(0, start - 64):start] != row["left_context"]):
        raise ValueError("annotation_boundary_source_mismatch")
    classes = dict(left=char_class(paragraph[start-1:start] if start else ""),
                   first=char_class(paragraph[start]), last=char_class(paragraph[end-1]),
                   right=char_class(paragraph[end:end+1]))
    flags = set(review_flags(row))
    if classes["last"] == "kanji_range" and classes["right"] == "hiragana":
        flags.add("right_hiragana_after_kanji")
    if classes["last"] == classes["right"] == "kanji_range":
        flags.add("right_kanji_adjacency")
    if any(char in row["raw_annotation_reading"] for char in "ゐゑヰヱ"):
        flags.add("explicit_historical_kana_marker")
    return dict(stable_id=row["stable_id"], annotation_kind=row["annotation_kind"],
                classes=classes, flags=sorted(flags), ime_input_unit="unresolved")


def profile(rows, components, observations):
    """All supplied rows remain in denominators; witnesses are lower bounds."""
    if len(rows) > 100_000 or len({r["stable_id"] for r in rows}) != len(rows):
        raise ValueError("annotation_contrast_population_bound")
    grouped, flags, adjacency = defaultdict(Counter), Counter(), Counter()
    for row in rows:
        stable = row["stable_id"]
        if (row["population"] != "train" or row["corpus"] != "aozora"
                or row["label_kind"] != "source_annotated_weak_supervision"
                or row["training_eligible"] is not False or row["independent_gold_eligible"] is not False
                or not components.get(stable) or stable not in observations
                or observations[stable]["ime_input_unit"] != "unresolved"
                or not 8 <= len(row["left_context"]) <= 64
                or not 2 <= len(row["reading"]) <= 32 or not 1 <= len(row["target"]) <= 32):
            raise ValueError("annotation_contrast_provisional_contract")
        grouped[row["reading"]][row["target"]] += 1
        flags.update(observations[stable]["flags"])
        classes = observations[stable]["classes"]
        adjacency["/".join(classes[k] for k in ("left", "first", "last", "right"))] += 1
    document, dc = witnesses(rows, components, independent_components=False)
    component, cc = witnesses(rows, components, independent_components=True)
    witnessed = {r["reading_sha256"] for r in component}
    result = dict(rows=len(rows), readings=len(grouped),
        source_works=len({r["source_id"] for r in rows}), source_authors=len({r["author_id"] for r in rows}),
        source_components=len({components[r["stable_id"]] for r in rows}),
        single_form_readings=sum(len(c) == 1 for c in grouped.values()),
        multiple_form_readings=sum(len(c) > 1 for c in grouped.values()),
        multiple_form_rows=sum(sum(c.values()) for c in grouped.values() if len(c) > 1),
        in_sample_reading_majority_rows=sum(max(c.values()) for c in grouped.values()),
        four_document_witnessed_readings=len(document), four_component_witnessed_readings=len(component),
        component_witness_rows=4*len(component),
        rows_in_component_witnessed_readings=sum(sum(c.values()) for k, c in grouped.items() if canonical_json_hash(k) in witnessed),
        component_witness_normalized_form_warnings=sum(r["normalized_form_collision_warning"] for r in component),
        selector_counts=dict(document=dc, component=cc), review_flags=dict(flags), adjacency_classes=dict(adjacency),
        annotation_kinds=dict(Counter(r["annotation_kind"] for r in rows)),
        input_conflicts=conflicts((canonical_json_hash([r["left_context"], r["reading"]]), r["target"]) for r in rows),
        ime_input_unit_unresolved=len(rows), meaning_usage_and_spelling_unresolved=len(rows))
    return result, dict(document=document, component=component)
