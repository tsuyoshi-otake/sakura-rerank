"""Reading-controlled research contrasts from original morphological evidence.

Different source lexical keys are a proxy for contrast, not human
certification of semantic intent. Source admission/isolation remains external.
"""
from collections import Counter, defaultdict
import re
import unicodedata

from .context_pilot import annotation_units
from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .kwdlc_probe import COMMIT, STRUCTURE

REPRESENTATIVE = re.compile(r'代表表記:([^\s"]+)')
SEED = 20261105


def extract_pool(document_id, raw, *, lexical_basis="representative"):
    if lexical_basis not in ("representative", "original_lemma"):
        raise ValueError("unsupported_lexical_evidence")
    units = annotation_units(document_id, raw)
    metadata, current = [], []
    for line in raw.decode("utf8").splitlines():
        if line.startswith("# S-ID:"):
            current = []
        elif line == "EOS":
            metadata.append(current)
        elif line and not line.startswith("@ ") and not STRUCTURE.match(line):
            fields = line.split()
            representatives = REPRESENTATIVE.findall(" ".join(fields[11:]))
            current.append(dict(pos=fields[3], lemma=fields[2], representatives=representatives))
    if len(metadata) != len(units) or any(len(m) != len(u) for m, u in zip(metadata, units)):
        raise ValueError("annotation_sidecar_alignment_differs")
    rows, counts = [], Counter()
    for unit_index, (unit, sidecar) in enumerate(zip(units, metadata)):
        sentence = "".join(t["surface"] for t in unit)
        source = dict(article_id="kwdlc:"+document_id, paragraph_hash=text_sha256(sentence),
                      sentence_hash=text_sha256(sentence), sentence_shingle_hashes=sentence_shingle_hashes(sentence),
                      template_cluster_id=None)
        prefix = ""
        for token_index, (token, meta) in enumerate(zip(unit, sidecar)):
            context, prefix = prefix[-64:], prefix+token["surface"]
            target, reading = token["surface"], token["reading"]
            reps = meta["representatives"]
            if token["alternative"]:
                status = "alternative_annotation"
            elif token["named_entity"]:
                status = "annotated_named_entity"
            elif not 2 <= len(reading) <= 32 or not 1 <= len(target) <= 32:
                status = "outside_model_bounds"
            elif not all("\u3041" <= c <= "\u3096" or c == "ー" for c in reading):
                status = "unsupported_reading"
            elif not any(unicodedata.name(c, "").startswith("CJK UNIFIED IDEOGRAPH-") for c in target):
                status = "no_kanji_target"
            elif len(context) < 8:
                status = "insufficient_left_context"
            elif lexical_basis == "representative" and (len(reps) != 1 or reps[0].count("/") != 1 or "?" in reps[0] or len(reps[0]) > 128):
                status = "unresolved_representative_annotation"
            elif lexical_basis == "original_lemma" and not 1 <= len(meta["lemma"]) <= 128:
                status = "unresolved_original_lemma"
            else:
                status = "eligible_research_pool"
            counts[status] += 1
            if status != "eligible_research_pool":
                continue
            rows.append(dict(stable_id="context-contrast-"+canonical_json_hash([COMMIT, document_id, unit_index, token_index]),
                             document_id=document_id, annotation_unit=unit_index, morpheme=token_index,
                             reading=reading, target=target, left_context=context,
                             lexical_key=reps[0] if lexical_basis == "representative" else meta["lemma"],
                             lexical_basis=lexical_basis, pos=meta["pos"], source=source,
                             context_origin="synthetic_source_prefix_not_observed_session",
                             gold_certified=False, training_eligible=False))
    return rows, dict(counts)


def select_contrasts(rows, maximum_groups=100):
    """Four distinct documents/contexts: two surfaces, two examples per surface.

    Selection uses only original annotations. Up to 32 lexical-key/surface types
per reading/POS group are examined; larger groups remain explicitly unresolved.
The caller supplies only source-admitted rows and retains its exclusion ledger.
"""
    if not 1 <= maximum_groups <= 1000 or len(rows) > 100000:
        raise ValueError("contrast_selection_bound")
    if len({r["stable_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate_contrast_input")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["lexical_basis"], row["reading"], row["pos"])].append(row)
    selected, counts = [], Counter()
    for group in sorted(groups, key=lambda key: canonical_json_hash([SEED, *key])):
        by_type = defaultdict(list)
        for row in groups[group]:
            by_type[(row["lexical_key"], row["target"])].append(row)
        if len(by_type) > 32:
            counts["too_many_types"] += 1
            continue
        types = sorted(by_type, key=lambda key: canonical_json_hash([SEED, *group, *key]))
        chosen = None
        for first in types:
            left = sorted(by_type[first], key=lambda r: canonical_json_hash([SEED, r["stable_id"]]))
            first_pair = []
            for row in left:
                if all(row["document_id"] != r["document_id"] and row["left_context"] != r["left_context"] for r in first_pair):
                    first_pair.append(row)
                if len(first_pair) == 2:
                    break
            if len(first_pair) != 2:
                continue
            for second in types:
                if first[0] == second[0] or first[1] == second[1]:
                    continue
                right = sorted(by_type[second], key=lambda r: canonical_json_hash([SEED, r["stable_id"]]))
                quartet = first_pair.copy()
                for row in right:
                    if all(row["document_id"] != r["document_id"] and row["left_context"] != r["left_context"] for r in quartet):
                        quartet.append(row)
                    if len(quartet) == 4:
                        break
                if len(quartet) == 4:
                    chosen = quartet
                    break
            if chosen is not None:
                break
        if chosen is None:
            counts["no_supported_lexical_quartet"] += 1
            continue
        counts["eligible_groups"] += 1
        if len(selected)//4 >= maximum_groups:
            counts["outside_group_cap"] += 1
            continue
        group_id = "contrast-group-"+canonical_json_hash(list(group))
        selected.extend(dict(row, contrast_group=group_id) for row in chosen)
    counts.update(selected_groups=len(selected)//4, selected_rows=len(selected), reading_pos_groups=len(groups))
    return selected, dict(counts)
