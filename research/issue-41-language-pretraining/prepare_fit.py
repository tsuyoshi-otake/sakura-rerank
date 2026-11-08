"""Bind every comparison condition before any #41 model update."""
from collections import defaultdict
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_hash
from language_common import ROOT,PRIOR_ROOT,TRAIN_ROOT,PLAN,context_model,read_json,rows,save,sha
from acquire_sources import PLAN_COMMIT
from forward_candidates import verify as verify_forward
from fit_contract import BINDING


def run():
    import numpy as np
    import torch
    plan=read_json(PLAN);candidate=read_json(ROOT/"candidate-report.json");language=read_json(ROOT/"language-preparation.json")
    if candidate["status"]!="ready" or language["status"]!="ready":raise ValueError("ready_candidates_and_language_data_required")
    verify_forward(candidate["input_commit"])
    if read_json(ROOT/"language-verification.json")["data_manifest_sha256"]!=sha(ROOT/"language-preparation.json"):
        raise ValueError("language_verification_missing")
    targets=list(rows(ROOT/"forward-targets.jsonl"));metadata=read_json(ROOT/"cache/metadata.json")
    if [r["stable_id"] for r in targets]!=[r["stable_id"] for r in metadata]:raise ValueError("evaluation_order_changed")
    groups=defaultdict(list);strata=defaultdict(list)
    for i,(row,meta) in enumerate(zip(targets,metadata)):
        if "contrast" in row["roles"]:groups[row["contrast_group"]].append(i)
        bucket=0 if meta["context_chars"]<16 else (1 if meta["context_chars"]<32 else 2)
        strata[("main" in row["roles"],bucket)].append(i)
    supported={g for g,indexes in groups.items() if all(metadata[i]["source_exact_presence"]["6"] for i in indexes)}
    shuffle=list(range(len(targets)));singletons=0
    for indexes in strata.values():
        ordered=sorted(indexes,key=lambda i:canonical_json_hash([20261105,"language-shuffle",targets[i]["stable_id"]]))
        if len(ordered)==1:singletons+=1
        for j,i in enumerate(ordered):shuffle[i]=ordered[(j+1)%len(ordered)]
    conditions=dict(contexts=["intact","empty","shuffled"],shuffle=shuffle,singleton_strata=singletons,
        populations=dict(main=[i for i,r in enumerate(targets) if "main" in r["roles"]],
            contrast_all=[i for i,r in enumerate(targets) if "contrast" in r["roles"]],
            contrast_supported=[i for i,r in enumerate(targets) if r["contrast_group"] in supported]),
        target_ids_sha256=canonical_json_hash([r["stable_id"] for r in targets]),gate_margin=1.7,source_form_only=True)
    save(ROOT/"conditions.json",conditions)
    training_paths=[ROOT/"language-windows.npz",TRAIN_ROOT/"cache/train.npz",TRAIN_ROOT/"cache/cohorts.json",Path(plan["downstream"]["initial_checkpoint"])]
    training_paths.extend(PRIOR_ROOT/"models"/f"c2-s{s}"/"model.pt" for s in plan["downstream"]["seeds"])
    evaluation_paths=[ROOT/name for name in ("cache/evaluation.npz","cache/metadata.json","conditions.json","forward-targets.jsonl","candidate-report.json","cohort.json")]
    code=["research/issue-41-language-pretraining/fit_language.py","research/issue-41-language-pretraining/fit_contract.py",
          "research/issue-41-language-pretraining/language_common.py","src/sakura_rerank/language_pretraining.py",
          "research/issue-33-data-growth/train.py","research/issue-40-context-contrast/model_common.py",
          "src/sakura_rerank/research_tiny.py","research/issue-21-retrain/run.py"]
    prior,_=context_model.growth_training().authenticate_fit("ad976a7f4515a80ff2602e8153b3decb35e37f6f")
    environment=dict(python=__import__("sys").version.split()[0],torch=torch.__version__,numpy=np.__version__)
    if environment!=prior["environment"]:raise ValueError("training_environment_changed")
    bound=dict(kind="paired_language_fit_binding",plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),
        environment=environment,training_artifacts={p.as_posix():sha(p) for p in training_paths},
        evaluation_artifacts={p.as_posix():sha(p) for p in evaluation_paths},code={p:sha(p) for p in code},
        language_verification_sha256=sha(ROOT/"language-verification.json"),language_manifest_sha256=sha(ROOT/"language-preparation.json"),
        evaluation_conditions_sha256=sha(ROOT/"conditions.json"),fits=6,pretraining_runs=3,
        evaluation_arrays_in_training_process=False,gold_certified=False,final_test_used=False)
    save(ROOT/"fit-binding.json",bound);save(BINDING,bound)
    return dict(fits=6,pretraining_runs=3,language_windows=language["selected_windows"],populations={k:len(v) for k,v in conditions["populations"].items()})


if __name__=="__main__":print(json.dumps(run()))
