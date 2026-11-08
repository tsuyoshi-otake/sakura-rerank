"""Annotated input-unit research slots; no Gold admission or model training.

The existing KWDLC reader owns document-format validation. This module owns
four span policies, deterministic selection, and explicit unresolved outcomes.
"""
from collections import Counter, defaultdict
import hashlib
import unicodedata

from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .kwdlc_probe import COMMIT, ProbeError, STRUCTURE, extract_target

POLICIES = ("morpheme", "basic_phrase", "two_basic_phrases", "three_basic_phrases")
SEED = 20261105


def annotation_units(document_id, raw):
    """Validate the frozen KNP contract, then retain phrase boundaries as evidence."""
    extract_target(document_id, raw)
    units = []
    current = None
    phrase = None
    named = False
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        if line.startswith("# S-ID:"):
            current = []
            phrase = None
            named = False
        elif line == "EOS":
            units.append(current)
            current = None
        elif STRUCTURE.match(line):
            if line.startswith("+"):
                phrase = 0 if phrase is None else phrase + 1
                named = "<NE:" in line
        elif line.startswith("@ "):
            current[-1]["alternative"] = True
        else:
            fields = line.split()
            current.append(dict(surface=fields[0], reading=fields[1], phrase=phrase,
                                named_entity=named, alternative=False))
    return units


def span_candidates(unit, policy):
    if policy not in POLICIES:
        raise ProbeError("unknown_input_policy")
    if policy == "morpheme":
        return [(i, i+1) for i in range(len(unit))]
    if any(token["phrase"] is None for token in unit):
        return []
    starts = [i for i, token in enumerate(unit) if i == 0 or token["phrase"] != unit[i-1]["phrase"]]
    ends = starts[1:] + [len(unit)]
    width = {"basic_phrase": 1, "two_basic_phrases": 2, "three_basic_phrases": 3}[policy]
    return [(starts[i], ends[i+width-1]) for i in range(len(starts)-width+1)]


def empty_slots(document_id, status, source_sha256=None):
    if status not in ("acquisition_failed", "acquisition_not_attempted", "parse_failure"):
        raise ProbeError("unknown_document_failure")
    return [dict(kind="context_pilot_slot_not_gold", stable_id="context-pilot-"+canonical_json_hash([COMMIT,document_id,policy]),
                 document_id=document_id, policy=policy, status=status, source_sha256=source_sha256,
                 gold_certified=False, training_eligible=False) for policy in POLICIES]


def extract_slots(document_id, raw):
    units = annotation_units(document_id,raw)
    source_sha = hashlib.sha256(raw).hexdigest()
    result = []
    for policy in POLICIES:
        base = dict(kind="context_pilot_slot_not_gold",stable_id="context-pilot-"+canonical_json_hash([COMMIT,document_id,policy]),
                    document_id=document_id,policy=policy,source_sha256=source_sha,gold_certified=False,training_eligible=False)
        candidates = []
        for index, unit in enumerate(units):
            for start,end in span_candidates(unit,policy):
                if any(unicodedata.name(c,"").startswith("CJK UNIFIED IDEOGRAPH-") for token in unit[start:end] for c in token["surface"]):
                    candidates.append((index,start,end))
        if not candidates:
            result.append(dict(base,status="no_target"))
            continue
        index,start,end = min(candidates,key=lambda span:canonical_json_hash([SEED,document_id,policy,*span]))
        unit=units[index]; span=unit[start:end]
        target="".join(t["surface"] for t in span)
        reading="".join(t["reading"] for t in span)
        left="".join(t["surface"] for t in unit[:start])[-64:]
        sentence="".join(t["surface"] for t in unit)
        if any(t["alternative"] for t in span):
            status="alternative_annotation"
        elif not 1<=len(reading)<=128 or not 1<=len(target)<=256:
            status="length_outside_converter_contract"
        elif not all("\u3041"<=c<="\u3096" or c=="\u30fc" for c in reading):
            status="special_reading_annotation"
        else:
            status="ready_for_forward_check"
        result.append(dict(base,status=status,target=target,reading=reading,left_context=left,
            annotation_unit=index,start_morpheme=start,end_morpheme=end,morphemes=end-start,
            named_entity=any(t["named_entity"] for t in span),
            existing_model_bounds=len(reading)<=32 and len(target)<=32,
            context_origin="synthetic_source_prefix_not_observed_session",
            source=dict(article_id="kwdlc:"+document_id,paragraph_hash=text_sha256(sentence),
                        sentence_hash=text_sha256(sentence),sentence_shingle_hashes=sentence_shingle_hashes(sentence),
                        template_cluster_id=None)))
    return result


def aggregate(rows, snapshots):
    """Unmeasured slots remain distinct from measured source-surface misses."""
    if not rows or len({r["stable_id"] for r in rows})!=len(rows):
        raise ProbeError("empty_or_duplicate_pilot_slots")
    policies={p:Counter() for p in POLICIES}; groups=defaultdict(list)
    top_counts={p:Counter({str(k):0 for k in (1,5,6,10,32)}) for p in POLICIES}
    rank_distribution=Counter(); path_counts=Counter()
    for row in rows:
        c=policies[row["policy"]];c["slots"]+=1;c["status/"+row["status"]]+=1
        if "reading" in row:
            c["target_defined"]+=1;c["reading_over9"]+=len(row["reading"])>9
            c["reading_over32"]+=len(row["reading"])>32;c["context_empty"]+=not row["left_context"]
            c["context_under8"]+=len(row["left_context"])<8;c["multiple_morphemes"]+=row["morphemes"]>1
            c["named_entity"]+=row["named_entity"];c["within_existing_model_bounds"]+=row["existing_model_bounds"]
            groups[row["reading"]].append(row)
        candidates=snapshots.get(row.get("request_id"))
        if candidates is None:
            c["unmeasured"]+=1
            continue
        if row["status"]!="ready_for_forward_check":
            raise ProbeError("unresolved_slot_was_forwarded")
        c["measured"]+=1
        matches=[i for i,t in enumerate(candidates) if t["surface"]==row["target"]]
        for k in (1,5,6,10,32):top_counts[row["policy"]][str(k)]+=any(i<k for i in matches)
        if matches:
            index=matches[0];rank_distribution[str(index+1)]+=1
            c["top32_present"]+=1;c["top32_nonunique_surface"]+=len(matches)>1
            segments=candidates[index]["segments"]
            path_counts["all_dictionary" if all(s["source_category"]=="system_dictionary" for s in segments) else "includes_fallback_or_other"]+=1
            path_counts["single_segment" if len(segments)==1 else "multiple_segments"]+=1
        else:
            c["measured_top32_missing"]+=1
    contrasts=[g for g in groups.values() if len({r["target"] for r in g})>1 and len({r["left_context"] for r in g})>1]
    cross_document=[g for g in contrasts if len({r["document_id"] for r in g})>1]
    for c in policies.values():
        if c["slots"]!=c["measured"]+c["unmeasured"] or c["measured"]!=c["top32_present"]+c["measured_top32_missing"]:
            raise ProbeError("pilot_denominator_mismatch")
    return dict(slots=len(rows),by_policy={p:dict(c) for p,c in policies.items()},
        source_exact_presence_counts={p:dict(c) for p,c in top_counts.items()},
        target_rank_counts=dict(rank_distribution),matched_path_counts=dict(path_counts),
        same_reading_different_surface_context_groups=len(contrasts),contrast_group_slots=sum(map(len,contrasts)),
        cross_document_contrast_groups=len(cross_document),cross_document_contrast_slots=sum(map(len,cross_document)),
        contrast_labels_semantically_certified=False,independent_gold=False,
        denominator_note="Presence counts / all slots are verified-presence lower bounds. Conditional measured rates exclude explicitly reported unmeasured slots; measured misses are not unmeasured.")
