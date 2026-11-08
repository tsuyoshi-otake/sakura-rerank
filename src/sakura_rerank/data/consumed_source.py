"""Prospective paragraph quarantine and exact dry-run consumption evidence.

This contract cannot admit training data or authorize model/cache/body consumers.
Source inventory and previously published exclusions remain separately immutable.
"""
from collections import Counter

from .annotation_first import source_metadata
from .contracts import canonical_json_hash, text_sha256
from .jawiki_preprocess import _sentences

PERMITTED = "isolated_for_source_verification"


def unit_key(source):
    return "consumed-unit-" + canonical_json_hash([source["article_id"], source["paragraph_hash"]])


def quarantine_units(records, identity, content):
    """Whole paragraphs fail closed if any source node touches historical roots."""
    size = len(records)
    for labels in (identity, content):
        if (len(labels) != size or any(type(label) is not int or not 0 <= label < size for label in labels)
                or any(labels[label] != label for label in labels)):
            raise ValueError("consumption_component_labels_invalid")
    history = [i for i, row in enumerate(records) if row["population"] == "historical"]
    identity_roots, content_roots = {identity[i] for i in history}, {content[i] for i in history}
    decisions = {}
    for index, row in enumerate(records):
        if row["population"] != "source_coverage":
            continue
        if set(row) != {"stable_id", "population", "source"}:
            raise ValueError("consumption_source_only_input_forbidden")
        source = row["source"]
        key = unit_key(source)
        decision = decisions.setdefault(key, dict(unit_id=key, article_id=source["article_id"],
            paragraph_hash=source["paragraph_hash"], source_nodes=0, identity_relation=False, content_or_input_relation=False))
        decision["source_nodes"] += 1
        decision["identity_relation"] |= identity[index] in identity_roots
        decision["content_or_input_relation"] |= content[index] in content_roots
    for decision in decisions.values():
        decision["status"] = ("quarantined_identity" if decision["identity_relation"] else
            "quarantined_content_or_input" if decision["content_or_input_relation"] else PERMITTED)
    return decisions, dict(Counter(d["status"] for d in decisions.values()))


def target_terminal(row, decisions):
    decision = decisions.get(unit_key(row["source"]))
    return "missing_full_source_coverage" if decision is None else decision["status"]


def verify_consumption(row, decision, paragraph, *, work_id, author_id, revision, paragraph_index, consumer):
    """Return hash-only evidence after checking an exact original paragraph.

    The caller authenticates the original work bytes and supplies its actual
    identity/position. This function checks every field that will identify the
    bounded input. No alternative consumer is enabled in this trial.
    """
    if consumer != "source_verification":
        raise ValueError("consumption_consumer_not_authorized")
    if decision is None or decision.get("status") != PERMITTED:
        raise ValueError("consumption_quarantined_or_missing_unit")
    if (row.get("training_eligible") is not False or row.get("independent_gold_eligible") is not False
            or row.get("label_kind") != "source_annotated_weak_supervision"
            or row.get("population") != "train" or row.get("corpus") != "aozora"):
        raise ValueError("consumption_provisional_label_contract")
    text = paragraph["text"]
    start, end, annotation = row["paragraph_start"], row["paragraph_end"], row["annotation_index"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
            or type(annotation) is not int or not 0 <= annotation < len(paragraph["spans"])):
        raise ValueError("consumption_source_position_invalid")
    ruby = paragraph["spans"][annotation]
    reading = "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in ruby["reading"])
    sentences = list(_sentences(text))
    si = row["sentence_index"]
    if type(si) is not int or not 0 <= si < len(sentences):
        raise ValueError("consumption_sentence_position_invalid")
    sentence_offset, sentence = sentences[si]
    expected_source = source_metadata(work_id, author_id, text, sentence)
    expected_id = "ruby-first-" + canonical_json_hash([work_id, revision, paragraph_index, annotation,
        start, end, text[start:end], ruby["reading"]])
    if (row["source_id"] != work_id or row["author_id"] != author_id or row["source_revision"] != revision
            or row["paragraph_index"] != paragraph_index or row["source"] != expected_source
            or decision["unit_id"] != unit_key(expected_source) or decision["article_id"] != expected_source["article_id"]
            or decision["paragraph_hash"] != text_sha256(text) or row["stable_id"] != expected_id
            or row["source_line_number"] != paragraph["line_number"]
            or row["source_line_sha256"] != paragraph["source_line_sha256"]
            or (ruby["start"], ruby["end"]) != (start, end)
            or row["raw_annotation_reading"] != ruby["reading"] or row["reading"] != reading
            or row["target"] != text[start:end] or row["left_context"] != text[max(0, start - 64):start]
            or not sentence_offset <= start < end <= sentence_offset + len(sentence)
            or not 8 <= len(row["left_context"]) <= 64 or not 1 <= len(row["target"]) <= 32
            or not 2 <= len(reading) <= 32 or len(sentence) > 512):
        raise ValueError("consumption_original_input_evidence_differs")
    return dict(stable_id=row["stable_id"], unit_id=decision["unit_id"], consumer=consumer,
        source_revision=revision, source_line_sha256=row["source_line_sha256"], paragraph_index=paragraph_index,
        context_start=max(0, start - 64), target_start=start, target_end=end,
        context_sha256=text_sha256(row["left_context"]), target_sha256=text_sha256(row["target"]),
        reading_sha256=text_sha256(row["reading"]),
        input_and_label_sha256=canonical_json_hash([row["left_context"], row["reading"], row["target"]]),
        training_eligible=False, independent_gold_eligible=False)
