"""Descriptive supervision evidence, without certifying source labels as Gold."""
from collections import Counter,defaultdict

from .context_contrasts import select_contrasts
from .contracts import canonical_json_hash


def conflicts(items):
    grouped=defaultdict(Counter)
    for key,label in items:grouped[key][label]+=1
    contradictory=[counts for counts in grouped.values() if len(counts)>1]
    n=sum(sum(c.values()) for c in grouped.values())
    unavoidable=sum(sum(c.values())-max(c.values()) for c in contradictory)
    return dict(rows=n,unique_inputs=len(grouped),duplicate_groups=sum(sum(c.values())>1 for c in grouped.values()),
        contradictory_groups=len(contradictory),contradictory_rows=sum(sum(c.values()) for c in contradictory),
        unavoidable_source_disagreements=unavoidable,empirical_deterministic_source_ceiling=(n-unavoidable)/n if n else None)


def describe(rows):
    if not 1<=len(rows)<=100000 or len({r["stable_id"] for r in rows})!=len(rows):raise ValueError("ranking_audit_population")
    grouped=defaultdict(list)
    for row in rows:grouped[row["reading"]].append(row)
    form_counts={reading:Counter(r["target"] for r in group) for reading,group in grouped.items()}
    single=[reading for reading,c in form_counts.items() if len(c)==1]
    multiple=[reading for reading,c in form_counts.items() if len(c)>1]
    witnesses=[];witness_readings=set();selector_counts=Counter()
    for reading in sorted(multiple,key=canonical_json_hash):
        adapted=[dict(row,document_id=row["source"]["article_id"],pos="unspecified",
                      lexical_basis="literal_source_surface",lexical_key=row["target"]) for row in grouped[reading]]
        selected,count=select_contrasts(adapted,maximum_groups=1);selector_counts.update(count)
        if selected:
            witness_readings.add(reading)
            witnesses.append(dict(reading_sha256=canonical_json_hash(reading),stable_ids=sorted(r["stable_id"] for r in selected),
                                  source_ids_sha256=canonical_json_hash(sorted(r["document_id"] for r in selected))))
    raw=conflicts((canonical_json_hash([r["left_context"],r["reading"]]),r["target"]) for r in rows)
    result=dict(rows=len(rows),readings=len(grouped),single_form_readings=len(single),single_form_rows=sum(len(grouped[k]) for k in single),
        multiple_form_readings=len(multiple),multiple_form_rows=sum(len(grouped[k]) for k in multiple),
        reading_majority_agreement_rows=sum(max(c.values()) for c in form_counts.values()),
        reading_majority_disagreement_rows=sum(sum(c.values())-max(c.values()) for c in form_counts.values()),
        witnessed_four_source_context_readings=len(witness_readings),
        rows_in_witnessed_reading_groups=sum(len(grouped[k]) for k in witness_readings),
        witness_rows=4*len(witnesses),witness_selector_counts=dict(selector_counts),raw_input_conflicts=raw,
        witness_scope="Conservative deterministic four-example witness: two literal target forms, two contexts each, four distinct source IDs/contexts. Not a complete combinatorial count or semantic certification.",
        majority_scope="In-sample oracle using source-label frequencies per reading, not a deployable score or held-out performance estimate.")
    return result,form_counts,witnesses


def coverage(targets,form_counts):
    counts=Counter();groups=defaultdict(list)
    for row in targets:
        forms=form_counts.get(row["reading"])
        state=("reading_unseen" if forms is None else ("target_form_unseen" if row["target"] not in forms else
               ("target_seen_single_form_reading" if len(forms)==1 else "target_seen_multiple_form_reading")))
        counts[state]+=1
        if row.get("contrast_group"):groups[row["contrast_group"]].append(row)
    complete=[group for group in groups.values() if len(group)==4]
    pair_states=Counter()
    for group in complete:
        forms=form_counts.get(group[0]["reading"],{})
        target_types={r["target"] for r in group}
        state="both_forms_at_least_two_train_rows" if all(forms.get(t,0)>=2 for t in target_types) else (
            "both_forms_seen" if all(forms.get(t,0)>0 for t in target_types) else "one_or_both_forms_unseen")
        pair_states[state]+=1
    return dict(rows=len(targets),row_states=dict(counts),complete_contrast_groups=len(complete),contrast_states=dict(pair_states))
