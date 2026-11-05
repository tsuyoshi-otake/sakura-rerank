"""Train-only contrast capacity; source forms and flags never certify Gold."""
from collections import Counter, defaultdict
import unicodedata

from .context_contrasts import select_contrasts
from .contracts import canonical_json_hash
from .growth_numeric import eligible_target
from .ranking_signal import conflicts

MAX_ROWS = 200_000
QUALITY_AXES = ("contextual_reading", "exact_source_span", "ime_input_boundary",
                "meaning_and_usage", "orthographic_intent")


def validate_population(rows, components):
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("contrast_capacity_population_bound")
    seen = set()
    for row in rows:
        stable = row["stable_id"]
        if (stable in seen or row["population"] != "train"
                or row["corpus"] not in ("jawiki", "aozora")
                or row["independent_gold_eligible"] is not False
                or row["label_kind"] != "source_exact_weak_supervision"
                or not 8 <= len(row["left_context"]) <= 64
                or not 1 <= len(row["reading"]) <= 32
                or not 1 <= len(row["target"]) <= 64
                or not row["source"]["article_id"] or not components.get(stable)):
            raise ValueError("contrast_capacity_train_contract")
        seen.add(stable)


def candidate_evidence(target, snapshot):
    """Authenticated snapshot in, exact-source proof out; no guessed fallback."""
    if snapshot is None:
        return dict(status="acquisition_missing", eligible=False,
                    presence={str(k): False for k in (1, 5, 6, 10, 32)},
                    unique_target_rank=None, candidate_count=0, truncated_candidates=0)
    candidates = snapshot["candidate_snapshots"]["training_top32"]["candidates"]
    top = snapshot["candidate_snapshots"]["production_top6"]["candidates"]
    if top != candidates[:6]:
        raise ValueError("contrast_candidate_prefix_differs")
    valid, reason = eligible_target(target, top)
    truncated = sum(len(c["surface"]) > 32 for c in top)
    if valid and (len(target) > 32 or truncated):
        valid, reason = False, "target_or_candidate_truncation"
    matches = [i + 1 for i, c in enumerate(candidates) if c["surface"] == target]
    return dict(status=reason, eligible=valid,
                presence={str(k): any(i <= k for i in matches) for k in (1, 5, 6, 10, 32)},
                unique_target_rank=matches[0] if len(matches) == 1 else None,
                candidate_count=len(candidates), truncated_candidates=truncated)


def _char_kind(char):
    value = ord(char)
    if 0x3400 <= value <= 0x9FFF or 0x20000 <= value <= 0x3134F:
        return "kanji"
    if 0x3040 <= value <= 0x30FF or 0xFF66 <= value <= 0xFF9D:
        return "kana"
    return "other"


def review_flags(row):
    """Non-exclusive prompts for evidence recovery, never rejection/validity."""
    left, target = row["left_context"], row["target"]
    kinds = (_char_kind(left[-1]), _char_kind(target[0]))
    return tuple(name for name, present in (
        ("kanji_adjacency", kinds == ("kanji", "kanji")),
        ("kanji_kana_adjacency", set(kinds) == {"kanji", "kana"}),
        ("quote_delimiter_visible", any(c in left + target for c in "「」『』“”")),
        ("ascii_letter_in_target", any("a" <= c.lower() <= "z" for c in target)),
        ("nfkc_changes_target", unicodedata.normalize("NFKC", target) != target),
    ) if present)


def _fold_for_warning(text):
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in normalized)


def witnesses(rows, components, *, independent_components):
    """One conservative quartet per reading, with document or component units."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["reading"]].append(row)
    result, counts = [], Counter()
    for reading in sorted(grouped, key=canonical_json_hash):
        group = grouped[reading]
        if len({r["target"] for r in group}) < 2:
            continue
        adapted = [dict(row, document_id=(components[row["stable_id"]] if independent_components
                                         else row["source"]["article_id"]),
                        pos="unspecified", lexical_basis="literal_source_surface", lexical_key=row["target"])
                   for row in group]
        chosen, observed = select_contrasts(adapted, maximum_groups=1)
        counts.update(observed)
        if chosen:
            forms = {r["target"] for r in chosen}
            result.append(dict(reading_sha256=canonical_json_hash(reading),
                stable_ids=sorted(r["stable_id"] for r in chosen),
                normalized_form_collision_warning=len({_fold_for_warning(t) for t in forms}) != len(forms)))
    return result, dict(counts)


def profile(rows, components):
    validate_population(rows, components)
    grouped = defaultdict(Counter)
    flags = Counter()
    for row in rows:
        grouped[row["reading"]][row["target"]] += 1
        flags.update(review_flags(row))
    documents, document_counts = witnesses(rows, components, independent_components=False)
    independent, component_counts = witnesses(rows, components, independent_components=True)
    witnessed = {w["reading_sha256"] for w in independent}
    summary = dict(rows=len(rows), corpus_counts=dict(Counter(r["corpus"] for r in rows)),
        source_documents=len({r["source"]["article_id"] for r in rows}),
        source_components=len({components[r["stable_id"]] for r in rows}),
        readings=len(grouped), single_form_readings=sum(len(c) == 1 for c in grouped.values()),
        single_form_rows=sum(sum(c.values()) for c in grouped.values() if len(c) == 1),
        multiple_form_readings=sum(len(c) > 1 for c in grouped.values()),
        multiple_form_rows=sum(sum(c.values()) for c in grouped.values() if len(c) > 1),
        in_sample_reading_majority_rows=sum(max(c.values()) for c in grouped.values()),
        four_document_witnessed_readings=len(documents), four_component_witnessed_readings=len(independent),
        rows_in_component_witnessed_readings=sum(sum(c.values()) for k, c in grouped.items()
                                                if canonical_json_hash(k) in witnessed),
        component_witness_rows=4 * len(independent),
        component_witness_normalized_form_warnings=sum(w["normalized_form_collision_warning"] for w in independent),
        selector_counts=dict(document=document_counts, component=component_counts),
        input_conflicts=conflicts((canonical_json_hash([r["left_context"], r["reading"]]), r["target"]) for r in rows),
        review_flags=dict(flags),
        quality_evidence={axis: {"unresolved": len(rows)} for axis in QUALITY_AXES})
    return summary, dict(document=documents, component=independent)


def balanced_selections(rows, components, quotas):
    """Return planning IDs, not admitted training data. Whole quartets are atomic."""
    validate_population(rows, components)
    if (set(quotas) != {"jawiki", "aozora"}
            or any(type(n) is not int or not 1 <= n <= 25_000 for n in quotas.values())):
        raise ValueError("contrast_capacity_quota_bound")
    ordered = sorted(rows, key=lambda r: r["stable_id"])
    available = Counter(r["corpus"] for r in ordered)
    if any(available[c] < n for c, n in quotas.items()):
        return [], [], [], dict(status="insufficient_quantity", available=dict(available), quotas=quotas)
    control, counts = [], Counter()
    for row in ordered:
        if counts[row["corpus"]] < quotas[row["corpus"]]:
            control.append(row["stable_id"])
            counts[row["corpus"]] += 1
    by_id = {r["stable_id"]: r for r in rows}
    groups, _ = witnesses(rows, components, independent_components=True)
    selected, reserved, counts, skipped = set(), [], Counter(), 0
    for group in groups:
        needed = Counter(by_id[s]["corpus"] for s in group["stable_ids"])
        if any(counts[c] + n > quotas[c] for c, n in needed.items()):
            skipped += 1
            continue
        selected.update(group["stable_ids"])
        reserved.append(group)
        counts.update(needed)
    for row in ordered:
        if row["stable_id"] not in selected and counts[row["corpus"]] < quotas[row["corpus"]]:
            selected.add(row["stable_id"])
            counts[row["corpus"]] += 1
    if dict(counts) != quotas or len(selected) != sum(quotas.values()):
        raise ValueError("contrast_capacity_quota_accounting")
    return control, sorted(selected), reserved, dict(status="quantity_available", available=dict(available),
        quotas=quotas, reserved_groups=len(reserved), reserved_rows=4 * len(reserved), groups_over_quota=skipped)
