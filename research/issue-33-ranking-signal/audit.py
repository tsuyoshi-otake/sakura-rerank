"""Inspect only frozen training supervision and previously exposed research IDs."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.ranking_signal import conflicts,describe,coverage
from sakura_rerank.research_tiny import character_ids

sys.path.insert(0,"research/issue-41-language-pretraining")
try:
    from language_common import TRAIN_ROOT,context_model,boundary,read_json,rows,save,sha
finally:sys.path.pop(0)

ROOT=Path("data/generated/issue-33-ranking-signal-v1")
PLAN=Path("research/issue-33-ranking-signal/plan-v1.json")
PLAN_COMMIT="8dc17ab8d6a8d8877b604cb93366d45fe781d116"


def run():
    plan=json.loads(boundary.committed(PLAN,PLAN_COMMIT))
    binding=json.loads(boundary.committed(plan["training_binding"],plan["training_binding_commit"]))
    expected={r["path"]:r["sha256"] for r in binding["artifacts"]}
    paths=[TRAIN_ROOT/("cache/"+name) for name in ("train.npz","train-metadata.jsonl","cohorts.json")]
    for path in paths:
        if sha(path)!=expected[path.as_posix()]:raise ValueError("frozen_training_input_changed")
    selection=read_json(TRAIN_ROOT/"isolation/execution.json")
    if sha(TRAIN_ROOT/"isolation/selected.jsonl")!=selection["selected_sha256"]:raise ValueError("raw_training_join_source_changed")
    by_id={r["stable_id"]:r for r in rows(TRAIN_ROOT/"isolation/selected.jsonl") if r["population"]=="train"}
    metadata=list(rows(TRAIN_ROOT/"cache/train-metadata.jsonl"));indexes=read_json(TRAIN_ROOT/"cache/cohorts.json")["mixed"]
    with np.load(TRAIN_ROOT/"cache/train.npz",allow_pickle=False) as saved:arrays={k:np.array(saved[k])[indexes] for k in saved.files}
    selected=[by_id[metadata[i]["stable_id"]] for i in indexes]
    if len(selected)!=50000 or len({r["stable_id"] for r in selected})!=50000:raise ValueError("mixed_training_population_differs")
    harness=context_model.reference();input_names=tuple(harness.INPUT_NAMES)
    numeric_keys=[];ranks=Counter();characters=Counter();alias_rows=0;aliased_positive_rows=0
    for i,row in enumerate(selected):
        target=int(arrays["gold"][i]);valid=np.flatnonzero(arrays["candidate_mask"][i])
        if target not in valid or arrays["correct_mask"][i].sum()!=1:raise ValueError("training_positive_not_unique")
        for text,prefix,width in ((row["left_context"],"context",64),(row["reading"],"reading",32)):
            ids,length=character_ids(text,width)
            if arrays[prefix+"_lengths"][i]!=length or arrays[prefix+"_ids"][i].tolist()!=ids:raise ValueError("raw_numeric_input_join_differs")
        positive,length=character_ids(row["target"],32)
        if arrays["candidate_lengths"][i,target]!=length or arrays["candidate_ids"][i,target].tolist()!=positive:raise ValueError("raw_numeric_target_join_differs")
        if not np.isfinite(arrays["features"][i]).all():raise ValueError("nonfinite_training_features")
        digest=hashlib.sha256()
        for name in input_names:
            value=np.asarray(arrays[name][i]);digest.update(canonical_json_bytes([name,str(value.dtype),list(value.shape)]));digest.update(value.tobytes(order="C"))
        numeric_keys.append(digest.hexdigest());ranks[target+1]+=1
        encoded=[(int(arrays["candidate_lengths"][i,j]),tuple(int(v) for v in arrays["candidate_ids"][i,j])) for j in valid]
        aliases=Counter(encoded);alias_rows+=int(any(c>1 for c in aliases.values()))
        positive_encoded=(int(arrays["candidate_lengths"][i,target]),tuple(int(v) for v in arrays["candidate_ids"][i,target]))
        aliased_positive_rows+=int(aliases[positive_encoded]>1)
        characters.update(row["left_context"]+row["reading"]+row["target"])
    summary,forms,witnesses=describe(selected);reverse=describe(list(reversed(selected)))
    if (summary,forms,witnesses)!=reverse:raise ValueError("ranking_signal_order_dependence")
    # Independent literal Counter checks for headline counts/majority bound.
    independent=defaultdict(Counter)
    for row in selected:independent[row["reading"]][row["target"]]+=1
    single_rows=sum(sum(v.values()) for v in independent.values() if len(v)==1)
    majority=sum(max(v.values()) for v in independent.values())
    if single_rows!=summary["single_form_rows"] or majority!=summary["reading_majority_agreement_rows"]:raise ValueError("headline_recount_differs")
    encoded_groups=defaultdict(Counter)
    for char,count in characters.items():encoded_groups[(ord(char)*2654435761)%13311+1][char]+=count
    collisions=[g for g in encoded_groups.values() if len(g)>1]
    character_summary=dict(unique_literal_characters=len(characters),distinct_hash_ids=len(encoded_groups),aliased_hash_ids=len(collisions),
        characters_in_aliased_ids=sum(len(g) for g in collisions),character_occurrences=sum(characters.values()),
        minority_character_occurrences_in_aliased_ids=sum(sum(g.values())-max(g.values()) for g in collisions),
        scope="Positive training context/reading/target characters only. Aliasing is not itself a demonstrated ranking error.")
    exposed={}
    for name,directory,receipt_name in (("context40",Path("data/generated/issue-40-context-contrast-v1"),"cohort-binding.json"),
                                       ("language41",Path("data/generated/issue-41-language-pretraining-v1"),"cohort.json")):
        receipt=read_json(directory/receipt_name)
        if sha(directory/"selected.jsonl")!=receipt["artifacts"]["selected"]:raise ValueError("exposed_research_targets_changed")
        targets=list(rows(directory/"selected.jsonl"))
        exposed[name]={role:coverage([r for r in targets if role in r["roles"]],forms) for role in ("main","contrast")}
    result=dict(kind="ranking_supervision_signal_audit",plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),summary=summary,
        baseline_source_correct=ranks[1],baseline_source_errors=50000-ranks[1],gold_rank_counts={str(k):v for k,v in sorted(ranks.items())},
        numeric_input_conflicts=conflicts(zip(numeric_keys,(int(v) for v in arrays["gold"]))),character_encoding=character_summary,
        candidate_token_aliases=dict(rows=alias_rows,positive_candidate_rows=aliased_positive_rows,
            scope="Identical length and hashed candidate character sequence within a row; may include identical literal surfaces. Features/order can still differ, so this is not a full-input ambiguity count."),
        exposed_research_coverage=exposed,corpus_counts=dict(Counter(r["corpus"] for r in selected)),
        source_documents=len({r["source"]["article_id"] for r in selected}),source_components=len({r["component_id"] for r in selected}),
        input_artifacts={p.as_posix():sha(p) for p in paths+[TRAIN_ROOT/"isolation/selected.jsonl"]},
        implementation={p:sha(p) for p in ("research/issue-33-ranking-signal/audit.py","src/sakura_rerank/data/ranking_signal.py","src/sakura_rerank/data/context_contrasts.py")},
        raw_numeric_rows_verified=50000,reverse_order_replay=True,independent_majority_recount=True,
        model_fits=0,model_inferences=0,old_dev_or_final_test_decoded=False,gold_certified=False,safety_threshold=.0025)
    ROOT.mkdir(exist_ok=True)
    save(ROOT/"witness-identities.json",witnesses);result["witness_id_sha256"]=sha(ROOT/"witness-identities.json")
    save(ROOT/"report.json",result);save("reports/issue-33-ranking-signal-v1.json",result)
    return {k:result[k] for k in ("summary","baseline_source_correct","gold_rank_counts","numeric_input_conflicts","candidate_token_aliases","character_encoding","exposed_research_coverage")}


if __name__=="__main__":print(json.dumps(run()))
