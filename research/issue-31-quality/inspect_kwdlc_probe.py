"""Read-only replay and dictionary comparison of the fixed external annotation probe.

Run from the repository root with PYTHONPATH=src. Prints only aggregate evidence.
This is neither an independent Gold assessment nor execution of the converter.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from sakura_rerank.data import kwdlc_probe as probe
from sakura_rerank.data.pilot_doubt_evidence import dictionary_evidence

ROOT = Path("data/generated/issue-31-kwdlc-probe-v1")
PINS = {
    "selection.json": "1d281e81f5da380e1834a415a5660ce0de716b5717d3ab1c5a29bf60cfc1e5e3",
    "extraction.json": "82862d649180cc9292511ba806e29f109b5a170abc822e99b8255828e7505b40",
    "extraction-r2.json": "688bb44abe9719ab6c90980ec231f36218cd4e9d82edbb4e752f9e571192fa38",
}
DICTIONARY_MANIFEST = Path("manifests/system-dictionary-index-verified.json")
DICTIONARY_MANIFEST_SHA = "f9c4b5b4c3e0ce518dc86b61092d81debfe14be802ef94e4b42ef0d9f9faf22d"


def bound_json(path: Path, expected: str):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("pinned input changed")
    return json.loads(raw)


def run() -> dict:
    selection = bound_json(ROOT / "selection.json", PINS["selection.json"])
    initial = bound_json(ROOT / "extraction.json", PINS["extraction.json"])
    revised = bound_json(ROOT / "extraction-r2.json", PINS["extraction-r2.json"])
    if hashlib.sha256(Path("research/issue-31-quality/external-annotation-probe-v1.json").read_bytes()).hexdigest() != probe.PLAN_SHA256:
        raise ValueError("preregistered plan changed")
    rows_by_revision = []
    for suffix, report in (("", initial), ("-r2", revised)):
        for prefix in ("targets", "requests"):
            raw = (ROOT / f"{prefix}{suffix}.jsonl").read_bytes()
            if hashlib.sha256(raw).hexdigest() != report[f"{prefix}_sha256"]:
                raise ValueError("derived artifact changed")
            if prefix == "targets":
                rows_by_revision.append([json.loads(line) for line in raw.splitlines()])
    before, after = rows_by_revision
    docs = selection["selected_documents"]
    if len(docs) != 50 or [d["document_id"] for d in docs] != [r["document_id"] for r in after]:
        raise ValueError("selected population changed")
    if [r["document_id"] for r in before] != [r["document_id"] for r in after]:
        raise ValueError("initial population changed")
    preserved = 0
    for doc, old, row in zip(docs, before, after):
        raw = (ROOT / "source" / (doc["document_id"] + ".knp")).read_bytes()
        probe.authenticate_blob(raw.decode("utf-8"), doc["git_blob_sha1"], doc["bytes"])
        if probe.extract_target(doc["document_id"], raw) != row:
            raise ValueError("extraction replay differs")
        if old["status"] != "parse_failure":
            if old != row:
                raise ValueError("previously successful target changed")
            preserved += 1
    manifest = bound_json(DICTIONARY_MANIFEST, DICTIONARY_MANIFEST_SHA)
    queue = {row["stable_id"]: dict(left_context=row["left_context"], source_gold_surface=row["surface"])
             for row in after}
    # This consumer uses the exact target only; prefix combinations from the
    # shared streaming API are not evidence about the source morpheme's reading.
    found = dictionary_evidence(queue, list(queue), Path("data/generated/system-dictionary-index.jsonl"), manifest)
    counts = Counter()
    for row in after:
        readings = found[row["stable_id"]].get(row["surface"])
        if readings is None:
            outcome = "surface_absent_from_index"
        elif row["reading"] not in readings:
            outcome = "annotated_reading_absent_from_indexed_readings"
        elif len(readings) == 1:
            outcome = "annotation_matches_unique_dictionary_reading"
        else:
            outcome = "annotation_matches_one_of_multiple_dictionary_readings"
        counts[outcome] += 1
    return dict(
        kind="kwdlc_external_annotation_development_probe", schema_version=1,
        corpus_commit=probe.COMMIT, plan_sha256=probe.PLAN_SHA256,
        selection_commit="c55a30a", initial_implementation_commit="0348a45ffa9e5668fa08acbca36dfb6ecaaa6392",
        input_sha256=PINS, initial_extraction=initial, revised_extraction=revised,
        source_annotation_origin="Third-party human-corrected morphology; not IME-task certification",
        annotation_column_used="original KNP morpheme reading; no Sakura reading inference",
        authenticated_sources=50, replayed_targets=50, initial_successes_unchanged=preserved,
        dictionary_comparison=dict(denominator=50, counts=dict(sorted(counts.items())),
            manifest_sha256=DICTIONARY_MANIFEST_SHA, content_sha256=manifest["content_sha256"],
            normalization="exact_unicode_v1", actual_converter_execution=False,
            interpretation="Index disagreement or absence is neither a label error nor an N-best oracle miss"),
        forward_check_at_acquisition=dict(status="not_run", measured_denominator=0,
            reason="Authenticated exporter not located; found dictionary binary differs from pinned identity",
            expected_exporter_sha256="0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf",
            expected_dictionary_sha256="6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad",
            observed_dictionary_sha256="d83e571d41d1e2f804810493b0a7987372800f449ddddf540c94e6d40c675f73",
            oracle_at_1=None, oracle_at_5=None, oracle_at_6=None, oracle_at_10=None, oracle_at_32=None),
        human_ime_adjudication_count=0, independently_certified_labels=0,
        label_accuracy=None, label_accuracy_95ci=None, gate_a_pass=False,
        new_final_test_used=False, labels_changed=False, models_trained=0,
        safety_threshold=0.0025,
    )


if __name__ == "__main__":
    sys.stdout.buffer.write(probe.canonical_json_bytes(run()) + b"\n")
