"""Pinned protocol-v1 projection and offline product choice, never a session oracle.

The caller must supply native policy facts from an authenticated producer. Legacy
source categories cannot establish eligibility, local preference or evidence tags.
"""
from __future__ import annotations

import hashlib
import math

HEAD = "bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88"
MODEL_SHA256 = "b3fe1e0aa7229edfd0760162d648f10328b0d75224a9cd49f2ba986b7db2ccbd"
MODEL_BYTES = 7_466_707
POLICY = "current_product_snapshot_v1"
TOKENIZER = {"kind": "current_tiny_protocol_v1", "version": 1,
             "character_hash": "unicode_scalar_multiplicative_modulo_v1", "vocab_size": 13312,
             "context": "empty", "reading": "empty", "surface_length": 32, "truncation": "prefix"}
FEATURES = {"kind": "current_tiny_protocol_v1", "version": 1, "width": 6,
            "source_head": HEAD, "model_sha256": MODEL_SHA256,
            "scorer_source_sha256": "212c065bfbf73ac9663dbd7b80e5eacb2526685cc1a2119b62151597c4b9c9e3",
            "selection_source_sha256": "d1c3ceebc62a52e110b3925644427412cb85c5bc194a8c4edbf7b10c84f6c37f",
            "runtime_source_sha256": "f479d67378476bc66c24f863dae6c936332fb66968bcce93225985558b806ccf"}
EVIDENCE_TAGS = frozenset({1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 30, 31})
MAX_NATIVE_CANDIDATES = 768
MAX_NATIVE_TEXT_BYTES = 1536


def snapshot_policy(provenance_sha256):
    """Distinct policy binding prevents silent reuse of legacy gate metadata."""
    return {"kind": "current_product_evaluation_policy", "version": 1, "source_head": HEAD,
            "population": "pre_display_native_candidate_snapshot", "baseline": "authenticated_native_local_selection",
            "scope_and_priorities": "native_snapshot_facts", "selection": "strongest_native_evidence_group",
            "tail_order": "unchanged_local_indices", "provenance_sha256": provenance_sha256,
            "safety_references": ["converter_top1", "native_local_selection"]}


class ProductContractError(ValueError):
    """Sanitized product contract error, without record fragments."""


def _require(condition, message):
    if not condition:
        raise ProductContractError(message)


def validate_current(artifacts, feature_width):
    from .data.contracts import canonical_json_bytes
    from .evaluation_payload import document
    _require(type(feature_width) is int and feature_width == 6, "current model width differs")
    for name, expected in (("tokenizer", TOKENIZER), ("features", FEATURES)):
        # Canonical bytes also distinguish JSON booleans/floats from integers.
        _require(canonical_json_bytes(document(artifacts[name])) == canonical_json_bytes(expected),
                 "current model metadata differs")
    _require(len(artifacts["weights"]) == MODEL_BYTES
             and hashlib.sha256(artifacts["weights"]).hexdigest() == MODEL_SHA256,
             "current model bytes differ")


def protocol_feed(candidates, *, full_population=False):
    """Match pinned sakura_scorer::prepare_inputs after engine int32 clipping."""
    import numpy as np
    _require(isinstance(candidates, list) and 2 <= len(candidates) <= 6, "current candidate count outside bound")
    for item in candidates:
        _require(isinstance(item, dict) and type(item.get("local_cost")) is int
                 and -(2**63) <= item["local_cost"] < 2**63
                 and isinstance(item.get("surface"), str)
                 and 1 <= len(item["surface"]) <= (MAX_NATIVE_TEXT_BYTES if full_population else 256),
                 "current candidate fields outside bound")
        try:
            raw = item["surface"].encode("utf-8", errors="strict")
        except UnicodeError:
            raise ProductContractError("invalid candidate encoding") from None
        _require(not full_population or len(raw) <= MAX_NATIVE_TEXT_BYTES, "native candidate bytes outside bound")
    costs = [max(-(2**31), min(2**31-1, item["local_cost"])) for item in candidates]
    low, high = min(costs), max(costs)
    span = float(max(1, high-low))
    values = dict(context_ids=np.zeros((1, 64), dtype=np.int64), context_lengths=np.zeros(1, dtype=np.int64),
        reading_ids=np.zeros((1, 32), dtype=np.int64), reading_lengths=np.zeros(1, dtype=np.int64),
        candidate_ids=np.zeros((1, 6, 32), dtype=np.int64), candidate_lengths=np.zeros((1, 6), dtype=np.int64),
        features=np.zeros((1, 6, 6), dtype=np.float32), candidate_mask=np.zeros((1, 6), dtype=np.bool_))
    for i, (item, cost) in enumerate(zip(candidates, costs, strict=True)):
        text = item["surface"]
        size = min(32, len(text))
        values["candidate_ids"][0, i, :size] = [(ord(c)*2654435761) % 13311 + 1 for c in text[:size]]
        values["candidate_lengths"][0, i] = size
        values["candidate_mask"][0, i] = True
        values["features"][0, i, 0] = -float(cost-low)/span
        values["features"][0, i, 1] = -np.float32(i)/np.float32(5)
        values["features"][0, i, 3] = np.float32(len(text))/np.float32(32)
    return values


def current_factory(artifacts, feature_width):
    return _current_scorer(artifacts, feature_width, full_population=False)


def native_current_factory(artifacts, feature_width):
    """Schema4 adapter: full native text extent, unchanged shipped model feed."""
    return _current_scorer(artifacts, feature_width, full_population=True)


def _current_scorer(artifacts, feature_width, *, full_population):
    from .evaluation_worker import cpu_session, cpu_scores
    validate_current(artifacts, feature_width)
    session = cpu_session(artifacts["weights"], 6)

    class Scorer:
        def score(self, request):
            return cpu_scores(session, protocol_feed(request["candidates"], full_population=full_population))

        def close(self):
            pass  # The contained process owns the native ORT session.
    return Scorer()


def validate_policy_facts(value, candidate_count):
    """Validate producer attestations, not infer their truth from raw candidates.

    schedule_eligible includes native scope/host/preedit/cursor and build checks;
    selection_allowed includes local learning/cache/literal/bridge protections.
    The provenance certificate must bind the producer and both facts to this row.
    The native local selection (baseline_index) is always a direct candidate,
    matching native capture; a retained non-direct tail never holds it.
    """
    keys = {"source_head", "baseline_index", "direct_count", "evidence_tags", "schedule_eligible", "selection_allowed"}
    _require(isinstance(value, dict) and value.keys() == keys and value["source_head"] == HEAD,
             "native policy facts missing or from another source")
    _require(type(value["direct_count"]) is int and 1 <= value["direct_count"] <= candidate_count
             and type(value["baseline_index"]) is int and 0 <= value["baseline_index"] < value["direct_count"],
             "native policy indices outside cohort")
    _require(type(value["schedule_eligible"]) is bool and type(value["selection_allowed"]) is bool,
             "native policy booleans missing")
    tags = value["evidence_tags"]
    _require(isinstance(tags, list) and len(tags) == candidate_count
             and all(type(v) is int and v in EVIDENCE_TAGS for v in tags), "native candidate evidence missing")
    return dict(value, evidence_tags=list(tags))


def eligible(facts):
    return facts["schedule_eligible"] and facts["selection_allowed"] and facts["direct_count"] >= 2


def protected_choice(scores, evidence_tags):
    """The native strongest-group choice; no local-cost fusion or margin gate."""
    _require(1 <= len(evidence_tags) <= 6 and len(scores) >= len(evidence_tags), "protected choice shape differs")
    _require(all(type(t) is int and t in EVIDENCE_TAGS for t in evidence_tags), "unknown native evidence")
    if len(evidence_tags) < 2:
        return None
    groups = [{2: 3, 1: 2, 3: 1}.get(tag) for tag in evidence_tags]
    target = max((g for g in groups if g is not None), default=None)
    if target is None:
        return None
    selected = None
    for i, group in enumerate(groups):
        if group != target:
            continue
        if not math.isfinite(scores[i]):
            return None
        if selected is None or scores[i] > scores[selected]:
            selected = i
    return selected
