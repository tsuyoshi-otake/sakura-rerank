"""One fixed development inference pass, followed by reproducible score reporting."""
import argparse
import json
from pathlib import Path
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.growth_metrics import observe,summarize
from sakura_rerank.evaluation_statistics import paired_component_bootstrap,mcnemar_exact,holm_adjust
from extend_wiki import ROOT
from prepare_sources import sha
from train import authenticate_fit,harness


def infer(commit):
    import numpy as np
    import torch
    binding,plan=authenticate_fit(commit)
    if dict(torch=torch.__version__,numpy=np.__version__,python=__import__("sys").version.split()[0])!=binding["environment"]:
        raise ValueError("evaluation_environment_changed")
    training=json.loads((ROOT/"training/execution.json").read_bytes())
    if training["status"]!="complete" or len(training["models"])!=9 or training["fit_commit"]!=commit:
        raise ValueError("all_nine_fixed_fits_required_before_evaluation")
    output=ROOT/"evaluation";output.mkdir(exist_ok=False)
    receipt=dict(kind="growth_development_inference",status="failed",fit_commit=commit,
        training_execution_sha256=sha(ROOT/"training/execution.json"),gold_certified=False,
        new_final_test_used=False,rows=4000,model_runs=[])
    start=time.monotonic()
    try:
        torch.set_num_threads(4);torch.set_num_interop_threads(1)
        h21=harness()
        with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as stored:arrays={k:np.array(stored[k]) for k in stored.files}
        if len(arrays["gold"])!=4000:raise ValueError("fixed_evaluation_count_differs")
        models=[dict(name="reference",path=Path(plan["training"]["initial_checkpoint"]),sha256=plan["training"]["initial_checkpoint_sha256"])]
        for fit in training["models"]:
            path=ROOT/"training"/fit["name"]
            if sha(path/"execution.json")!=fit["execution_sha256"]:raise ValueError("fit_receipt_changed")
            models.append(dict(name=fit["name"],path=path/"model.pt",sha256=fit["checkpoint_sha256"]))
        results={}
        for item in models:
            if sha(item["path"])!=item["sha256"]:raise ValueError("evaluated_checkpoint_changed")
            state=torch.load(item["path"],map_location="cpu",weights_only=True)["state_dict"]
            model=h21.build_model("C2");model.load_state_dict(state,strict=True);model=model.to("cuda:0")
            scores=h21.score_rows(model,arrays,arrays["features"],np.arange(4000))
            results[item["name"]]=scores
            receipt["model_runs"].append(dict(name=item["name"],checkpoint_sha256=item["sha256"],nonfinite_score_rows=int((~np.isfinite(scores).all(axis=1)).sum())))
            print(json.dumps(dict(stage="evaluation_inference",completed=len(results),total=10)),flush=True)
            del model,state;torch.cuda.empty_cache()
        with (output/"scores.npz").open("xb") as stream:np.savez_compressed(stream,**results)
        receipt.update(status="complete",scores_sha256=sha(output/"scores.npz"))
        return receipt
    except Exception as error:
        receipt["error_type"]=type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(output/"execution.json",canonical_json_bytes(receipt)+b"\n")


def report(commit):
    import numpy as np
    _,plan=authenticate_fit(commit)
    execution=json.loads((ROOT/"evaluation/execution.json").read_bytes())
    if execution["status"]!="complete" or execution["fit_commit"]!=commit or sha(ROOT/"evaluation/scores.npz")!=execution["scores_sha256"]:
        raise ValueError("completed_bound_inference_required")
    with np.load(ROOT/"cache/evaluation.npz",allow_pickle=False) as stored:arrays={k:np.array(stored[k]) for k in stored.files}
    with np.load(ROOT/"evaluation/scores.npz",allow_pickle=False) as stored:scores={k:np.array(stored[k]) for k in stored.files}
    metadata=[json.loads(line) for line in (ROOT/"cache/evaluation-metadata.jsonl").read_bytes().splitlines()]
    components=[r["component_id"] for r in metadata]
    observations={mode+"/"+name:observe(arrays,value,mode) for mode in ("ungated","gated") for name,value in scores.items()}
    summaries={name:summarize(value) for name,value in observations.items()}
    base=arrays["correct_mask"][:,0]
    # Component intervals for each run; never discard undefined denominator draws.
    for offset in range(0,len(observations),4):
        names=sorted(observations)[offset:offset+4]
        columns=[np.ones(4000,dtype=int),base.astype(int),(~base).astype(int)]
        ratios={}
        for name in names:
            obs=observations[name];right=obs["correct"];changed=obs["changed"]
            begin=len(columns)
            columns.extend([right.astype(int),(~base & right).astype(int),(base & ~right).astype(int),changed.astype(int),(changed & ~base).astype(int)])
            for metric,numerator,denominator in (("accuracy",begin,0),("precision",begin+1,begin+3),("recall",begin+1,2),
                ("harm_rate",begin+2,1),("application",begin+3,0),("application_to_error",begin+4,2)):
                ratios[name+"/"+metric]=(numerator,denominator)
        bootstrap=paired_component_bootstrap(components,np.stack(columns,axis=1).tolist(),ratios,replicates=10000,seed=20261105)
        for name in names:
            summaries[name]["component_ci95"]={metric:bootstrap["ratios"][name+"/"+metric] for metric in ("accuracy","precision","recall","harm_rate","application","application_to_error")}
        print(json.dumps(dict(stage="component_intervals",completed=min(offset+4,len(observations)),total=len(observations))),flush=True)
    comparisons=[]
    for mode in ("ungated","gated"):
        keys=[key for key in observations if key.startswith(mode+"/")]
        comparisons.extend((key,"baseline") for key in keys)
        comparisons.extend((key,mode+"/reference") for key in keys if not key.endswith("/reference"))
        for seed in plan["training"]["seeds"]:
            comparisons.append((f"{mode}/wiki_large-s{seed}",f"{mode}/wiki_small-s{seed}"))
            comparisons.append((f"{mode}/mixed-s{seed}",f"{mode}/wiki_large-s{seed}"))
    if len(comparisons)!=50 or len(set(comparisons))!=50:raise ValueError("comparison_family_differs")
    contrasts={};columns=[np.ones(4000,dtype=int)];ratios={};p_values={}
    for left,right in comparisons:
        name=left+" minus "+right
        a=observations[left]["correct"];b=base if right=="baseline" else observations[right]["correct"]
        difference=a.astype(int)-b.astype(int)
        columns.append(difference);ratios[name]=(len(columns)-1,0)
        left_only=int((a & ~b).sum());right_only=int((b & ~a).sum())
        p_values[name]=mcnemar_exact(left_only,right_only)
        contrasts[name]=dict(gain=float(difference.mean()),left_only_correct=left_only,right_only_correct=right_only,
            mcnemar_p_row_assumption=p_values[name])
    adjusted=holm_adjust(p_values)
    paired=paired_component_bootstrap(components,np.stack(columns,axis=1).tolist(),ratios,replicates=10000,seed=20261105)
    for name in contrasts:contrasts[name].update(holm_p=adjusted[name],paired_component_ci95=paired["ratios"][name])
    slices={"jawiki":[i for i,r in enumerate(metadata) if r["corpus"]=="jawiki"],
            "aozora":[i for i,r in enumerate(metadata) if r["corpus"]=="aozora"],
            "reading_le_9":[i for i,r in enumerate(metadata) if r["reading_chars"]<=9],
            "reading_ge_10":[i for i,r in enumerate(metadata) if r["reading_chars"]>=10]}
    result=dict(kind="growth_model_comparison",status="research_only_no_promotion",fit_commit=commit,
        rows=4000,source_exact_presence={str(k):sum(r["source_exact_presence"][str(k)] for r in metadata) for k in (1,5,6,10,32)},
        models=summaries,contrasts=contrasts,slices={slice_name:{name:summarize(obs,indexes) for name,obs in observations.items()} for slice_name,indexes in slices.items() if indexes},
        bootstrap=dict(replicates=10000,seed=20261105,components=paired["component_count"],independence_certified=False),
        comparison_family_size=50,safety_threshold=0.0025,gold_certified=False,new_final_test_used=False,
        scope="Left context 8-64 characters; source-exact labels; acquisition-inclusive development denominator",
        execution_sha256=sha(ROOT/"evaluation/execution.json"),scores_sha256=execution["scores_sha256"],
        evaluation_spec_sha256=sha(Path("research/issue-33-data-growth/evaluation-v2.json")))
    raw=canonical_json_bytes(result)+b"\n"
    write_once(ROOT/"evaluation/report.json",raw)
    write_once(Path("reports/issue-33-data-growth-model-v2.json"),raw)
    print(json.dumps(dict(report_sha256=sha(ROOT/"evaluation/report.json"),rows=4000,models=len(summaries),contrasts=len(contrasts))))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--mode",choices=("infer","report"),required=True);parser.add_argument("--fit-commit",required=True)
    args=parser.parse_args()
    if args.mode=="infer":print(canonical_json_bytes(infer(args.fit_commit)).decode("utf-8"))
    else:report(args.fit_commit)
