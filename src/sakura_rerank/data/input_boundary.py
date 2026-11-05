"""Exact literal/input-extent hypotheses for research; never edits or certifies labels.

The annotation reader owns token boundaries. This module owns classification,
bounded conversion requests and component presence. Candidate authentication is
the caller's responsibility. A component oracle is not a whole-input N-best list.
"""
from collections import Counter
import unicodedata

from .contracts import canonical_json_hash

VIEWS = ("whole", "literal_split", "morpheme_diagnostic")
TOP_K = (1, 5, 6, 10, 32)


def token_class(token):
    if token.get("alternative"):
        return "unresolved"
    surface, reading = token["surface"], token["reading"]
    if not surface or not reading:
        return "unresolved"
    if all("\u3041" <= c <= "\u3096" or c == "\u30fc" for c in reading):
        return "phonetic"
    if surface == reading and all(unicodedata.category(c)[0] in "PS" for c in reading):
        return "literal"
    return "unresolved"


def request_id(reading):
    return "boundary-reading-" + canonical_json_hash(reading)


def _convert(reading, target):
    return dict(kind="convert", reading=reading, target=target, request_id=request_id(reading))


def build_views(tokens):
    """Preserve original strings; unsupported annotation has no executable view."""
    classes = [token_class(t) for t in tokens]
    counts = dict(Counter(classes))
    target = "".join(t["surface"] for t in tokens)
    reading = "".join(t["reading"] for t in tokens)
    if not 1 <= len(reading) <= 128 or not 1 <= len(target) <= 256:
        status = "outside_input_bounds"
    elif "unresolved" in classes:
        status = "unsupported_annotation"
    elif "phonetic" not in classes:
        status = "no_phonetic_input"
    else:
        status = "ready"
    result = dict(status=status, token_classes=counts, target=target, reading=reading, views={})
    if status != "ready":
        result["views"] = {name: dict(status=status, parts=[]) for name in VIEWS}
        return result
    split, morphemes = [], []
    run_reading, run_target = "", ""
    for token, kind in zip(tokens, classes):
        if kind == "literal":
            if run_reading:
                split.append(_convert(run_reading, run_target))
                run_reading, run_target = "", ""
            literal = dict(kind="literal", text=token["surface"])
            split.append(literal)
            morphemes.append(literal.copy())
        else:
            run_reading += token["reading"]
            run_target += token["surface"]
            morphemes.append(_convert(token["reading"], token["surface"]))
    if run_reading:
        split.append(_convert(run_reading, run_target))
    for name, parts in zip(VIEWS, ([_convert(reading, target)], split, morphemes)):
        count = sum(p["kind"] == "convert" for p in parts)
        state = "ready" if 1 <= count <= 32 else "outside_part_bounds"
        if "".join(p["text"] if p["kind"] == "literal" else p["target"] for p in parts) != target:
            raise ValueError("composition_does_not_preserve_source")
        result["views"][name] = dict(status=state, parts=parts if state == "ready" else [],
                                     conversion_parts=count)
    return result


def collect_requests(rows):
    requests = {}
    for row in rows:
        for view in row["views"].values():
            if view["status"] != "ready":
                continue
            for part in view["parts"]:
                if part["kind"] == "convert":
                    key = part["request_id"]
                    if key != request_id(part["reading"]):
                        raise ValueError("request_identity_differs")
                    requests[key] = dict(stable_id=key, reading=part["reading"])
    if len(requests) > 16000:
        raise ValueError("request_population_outside_bound")
    return [requests[key] for key in sorted(requests)]


def score_view(view, snapshots):
    """Return all-parts source-presence; do not construct Cartesian candidates."""
    if view["status"] != "ready":
        return dict(status=view["status"])
    parts = [p for p in view["parts"] if p["kind"] == "convert"]
    if not 1 <= len(parts) <= 32:
        raise ValueError("invalid_ready_parts")
    if any(p["request_id"] not in snapshots for p in parts):
        return dict(status="unmeasured")
    positions = []
    for part in parts:
        matches = [i+1 for i, candidate in enumerate(snapshots[part["request_id"]])
                   if candidate["surface"] == part["target"]]
        positions.append(min(matches) if matches else None)
    # None denotes a measured source-exact miss, not a failed conversion.
    return dict(status="measured", parts=len(parts), ranks=positions,
                all_parts_present={str(k): all(rank is not None and rank <= k for rank in positions)
                                   for k in TOP_K})


def aggregate(rows, snapshots):
    if not rows or len({row["stable_id"] for row in rows}) != len(rows):
        raise ValueError("empty_or_duplicate_population")
    counts, cross = {}, Counter()
    for row in rows:
        scores = {}
        for name in VIEWS:
            score = scores[name] = score_view(row["views"][name], snapshots)
            key = row["policy"] + "/" + name
            c = counts.setdefault(key, Counter())
            c["slots"] += 1
            c[score["status"]] += 1
            c["original_ready"] += row["original_status"] == "ready_for_forward_check"
            if score["status"] == "measured":
                c["conversion_parts"] += score["parts"]
                for k, present in score["all_parts_present"].items():
                    c["source_supported_at_" + k] += present
                    if row["original_status"] == "ready_for_forward_check":
                        c["original_ready_supported_at_" + k] += present
        whole = scores["whole"]
        if whole["status"] != "measured" or whole["all_parts_present"]["32"]:
            continue
        cross["whole_top32_missing"] += 1
        if row["original_status"] == "ready_for_forward_check":
            cross["original_ready_whole_top32_missing"] += 1
        for name in ("literal_split", "morpheme_diagnostic"):
            part = scores[name]
            outcome = "unmeasured" if part["status"] != "measured" else (
                "all_supported" if part["all_parts_present"]["32"] else "component_missing")
            cross[name + "/" + outcome] += 1
            if row["original_status"] == "ready_for_forward_check":
                cross["original_ready/" + name + "/" + outcome] += 1
    return dict(slots=len(rows), by_policy_view={k: dict(v) for k, v in counts.items()},
                whole_miss_component_support=dict(cross), gold_certified=False,
                split_metric="All conversion parts contain their source-exact target at k. This is a composition oracle, not whole-reading Top-k.")
