"""Publish complete aggregate experiment evidence and a readable interpretation."""
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from extend_wiki import ROOT
from prepare_sources import sha


def persist(path,raw):
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError("published_experiment_differs")
    else:write_once(path,raw)


def run():
    report_path=Path("reports/issue-33-data-growth-model-v2.json")
    report=json.loads(report_path.read_bytes())
    paths={"source_extension":"wiki-extra/execution.json","isolation":"isolation/execution.json",
        "candidate_acquisition":"candidates/execution.json","numeric_cohorts":"cache/manifest.json",
        "training":"training/execution.json","inference":"evaluation/execution.json",
        "historical_integrity":"original-integrity.json","result_verification":"evaluation/verification.json"}
    evidence={name:json.loads((ROOT/path).read_bytes()) for name,path in paths.items()}
    if evidence["result_verification"]["status"]!="passed" or evidence["result_verification"]["report_sha256"]!=sha(report_path):
        raise ValueError("verified_results_required")
    candidate=evidence["candidate_acquisition"]
    candidate["batch_count"]=len(candidate.pop("batches"))
    execution=dict(kind="growth_execution_evidence",status="completed_research_no_promotion",issue=33,parent_issue=1,
        evidence=evidence,artifacts={name:dict(path=(ROOT/path).as_posix(),sha256=sha(ROOT/path)) for name,path in paths.items()},
        model_report_sha256=sha(report_path),gold_certified=False,new_final_test_used=False)
    persist(Path("reports/issue-33-data-growth-execution-v2.json"),canonical_json_bytes(execution)+b"\n")
    lines=["# Wikipedia/Aozora growth experiment: measured model results", "",
        "The mixed-source cohort improved source-exact ranking more than increasing Wikipedia examples alone under the fixed update budget. This is conditional development evidence, not a new overall IME accuracy estimate or release approval.", "",
        "All nine fixed adaptations completed before development inference. Each used the same frozen Issue-29 checkpoint, C2 architecture, features, masked label-smoothed loss, AdamW recipe, and 500 updates of 256 examples. Seeds change batch order/dropout; initial weights are common. The 12,516-row Wiki subset and 25,000-row mixed Wiki subset are nested in the 50,000-row Wiki cohort. The mixed cohort adds 25,000 Aozora rows.", "",
        "The evaluation has 2,000 Wikipedia and 2,000 Aozora targets, all with 8–64 characters of synthetic left context. It retains target misses and one-candidate cases. Its converter Top-1 is **79.350% (3,174/4,000)**, so its results cannot be compared directly with the historical dev's 90.72%. No old dev tuning, new final Test consumption, source-label rewriting or model replacement occurred.", "",
        "## Complete point results", "",
        "Success = baseline-wrong to source-exact; failure = harm + wrong-to-wrong among changed surfaces. Same-surface rank changes are not corrections. Accuracy gain is relative to the converter baseline in percentage points. Every seed is shown.", ""]
    for mode in ("gated","ungated"):
        lines += [f"### {mode}","", "The gated mode preserves the existing strict `L > 1.7` rule; it was not recalibrated." if mode=="gated" else "Ungated results diagnose ranking headroom and are not safe deployment candidates.","",
            "| Model / seed | Exact accuracy | Gain pp | Success | Failure | Harm | Wrong→wrong | Changed |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
        keys=[mode+"/reference"]+[f"{mode}/{cohort}-s{seed}" for cohort in ("wiki_small","wiki_large","mixed") for seed in (20260814,20261103,20261104)]
        for key in keys:
            m=report["models"][key]
            lines.append(f"| {key.split('/')[1]} | {100*m['accuracy']['value']:.3f}% | {100*m['baseline_gain']:+.3f} | {m['rescue']} | {m['correction_failure']} | {m['harm']} | {m['wrong_to_wrong']} | {m['changed']} |")
        lines += ["", "| Model / seed | Precision | Recall | All-row application | Application to baseline errors | Harm rate | Exact harm 95% upper |",
            "|---|---:|---:|---:|---:|---:|---:|"]
        for key in keys:
            m=report["models"][key]
            values=[m[field]["value"] for field in ("precision","recall","application","application_to_error","harm_rate")]
            values.append(m["harm_exact95_row_assumption"]["two_sided"][1])
            lines.append("| "+key.split('/')[1]+" | "+" | ".join(f"{100*v:.3f}%" if v is not None else "undefined" for v in values)+" |")
        lines.append("")
    lines += ["## Quantity, source diversity and uncertainty", "",
        "Under the matched 128,000-example update budget, Wiki 50k minus Wiki 12,516 is −0.275, +0.175 and −0.250 pp ungated across the three seeds; every paired component interval includes zero. This does not establish that larger Wikipedia training is ineffective under a larger compute budget.", "",
        "Mixed 50k minus Wiki 50k is +1.700, +1.375 and +1.750 pp ungated, and +0.575, +0.600 and +0.700 pp gated. Thus source diversity helped this balanced Wiki/Aozora population more consistently than the tested quantity increase.", "",
        "For seed 20260814 (the first listed seed, displayed consistently rather than selecting the best outcome):", "",
        "| Contrast | Gain pp | Paired component 95% interval, pp | Holm-adjusted McNemar p |",
        "|---|---:|---:|---:|"]
    names=["ungated/mixed-s20260814 minus ungated/reference","ungated/mixed-s20260814 minus ungated/wiki_large-s20260814",
        "gated/mixed-s20260814 minus gated/reference","gated/mixed-s20260814 minus gated/wiki_large-s20260814"]
    for key in names:
        c=report["contrasts"][key];lo,hi=c["paired_component_ci95"]["ci95"]
        lines.append(f"| {key} | {100*c['gain']:+.3f} | [{100*lo:+.3f}, {100*hi:+.3f}] | {c['holm_p']:.6g} |")
    lines += ["", "Intervals use 10,000 shared source/input-component bootstrap draws over 1,285 components. The 50 prespecified accuracy contrasts receive Holm correction for exact McNemar p-values; those p-values assume exchangeable rows. Component intervals are not simultaneous familywise intervals. Neither method certifies weak-label truth or population representativeness. All model-specific Wilson, component and exact harm intervals, including undefined-denominator accounting, are in the JSON report.", "",
        "## Safety and remaining headroom", "",
        "The mixed seed-20260814 gated model changes 113 surfaces: 95 successes, four harms and 14 wrong-to-wrong changes. Precision rises from the frozen reference's 69.531% to 84.071%; recall is 11.501%. Its source-exact harm rate is 4/3,174 = 0.126%, but the two-sided exact 95% upper bound is **0.322%**, above the unchanged **0.25%** criterion. The component upper bound is also above it (0.278%). Two of the three mixed seeds exceed the exact upper-bound criterion; selecting only the favorable seed is not permitted. Independent Gold is also absent. No model is adopted and no safety criterion is relaxed.", "",
        "Source-exact candidate presence is Top-1 3,174/4,000; Top-5 3,910; Top-6 3,939; Top-10 3,978; Top-32 4,000. The mixed seed-20260814 ungated model gets 3,383 right, leaving 556 Top-6-present targets incorrectly ranked and 61 targets outside Top-6. Its gate suppresses 209 successful corrections while avoiding 91 harms, compared with its own ungated output. Those are research source-exact counts, not independently adjudicated Japanese conversion judgments.", "",
        "The ungated mixed/reference difference is larger on Aozora (80.550% vs 76.500%) than Wikipedia (88.600% vs 87.350%). With the fixed gate, Wikipedia is slightly lower (86.550% vs 86.800%) while Aozora rises (76.700% vs 75.750%). Generalization to business writing, dialogue or real IME input is unmeasured. Only 21 evaluation readings exceed nine characters, so long-input performance is not established.", "",
        "## Priority and validation cost", "",
        "1. Broaden independently sourced modern-domain reading/surface evidence and document spelling intent. The observed mixed-source gain supports diversity; literary-source gains do not establish everyday-domain gains. Cost is new source/rights/annotation/isolation work, not another architecture search; gain outside this domain is unknown.",
        "2. Fix the extraction/label task's concentration on short dictionary surfaces. Preserve real reading annotations and verify whole input units through the converter. Current Wiki/Aozora targets remain approximately 98.3%/99.94% at most nine reading characters. Expected benefit is coverage of missing input types; it needs a separately registered extraction/quality pilot before fitting.",
        "3. Keep these model results fixed and evaluate confidence separation on a fresh, independently isolated calibration population. The gate's blocked rescues show headroom, but this development population must not become a threshold-tuning set. Do not merely relax 0.25%; quality-certified final evaluation remains separate.", "",
        "Measured compute: nine adaptations took 152.265 seconds; the final ten-model inference pass took 2.056 seconds excluding process startup and input authentication. Source work dominated: the two Wikipedia passes took 535.788 and 553.446 seconds; the 750 sequential Aozora requests took 810.825 seconds (the first Wikipedia pass ran concurrently). These are observed research timings, not production latency benchmarks.", "",
        "## Evidence and reproduction", "",
        "- [Full metrics and all 50 contrasts](../../reports/issue-33-data-growth-model-v2.json).",
        "- [Execution, source/cohort/model hashes and historical integrity](../../reports/issue-33-data-growth-execution-v2.json).",
        "- [Direct surface-based recount](../../reports/issue-33-data-growth-verification-v2.json): all 20 point reports, all 50 paired contrasts and Top-k counts match, with zero extra inference or fitting.",
        "- [V1 source failure and diagnosis](results-source-v1.md), [v2 plan](plan-v2.json), [evaluation specification](evaluation-v2.json), [fit binding](../../manifests/data-growth-fit-binding-v2.json).",
        "",
        "The fit binding was committed as `ad976a7f4515a80ff2602e8153b3decb35e37f6f` before fitting. Every fit read only the training tensor file. All 32,237 unique converter readings validated; all ten model runs produced finite scores. Six historical source generations, their checkout manifests, the old frozen dataset, dictionary index, original dump and Issue-29 checkpoint remained byte-identical (16 original artifact checks); all 25 fit-bound artifacts authenticated. Local source bodies, numeric caches and checkpoints remain ignored under `data/generated/issue-33-data-growth-v1/` and `data/generated/issue-33-data-growth-v2/`.", "",
        "Verify: run `verify_integrity.py` with `PYTHONPATH=src`; expect the same 16/25 hash checks. `verify_results.py` records its one-time recount without repeat inference; preserve its existing receipt. Reconstruct experiments in fresh output directories only, using the preregistered commits and `env/uv.lock`; never overwrite these runs or train on their exposed development cases.", "",
        "## Responsibility and reading scope (IRV)", "",
        "A. Actual scope: corpus selection/acquisition/extraction, metadata-only historical isolation, the weak-label numeric adapter, fixed C2 adaptation and aggregate statistics, plus their synthetic and actual-artifact checks. B. Scope expanded because source/input graph closure made the first cohort infeasible; a preserved v1 diagnosis and separately registered conditional v2 were necessary. C. Each stage owns its append-only output directory and manifest; old Gold admission, old datasets and Sakura Input production behavior have no changed owner or contract. D. Future source-growth work can start from this experiment's plan, stage receipts and adapter tests instead of rediscovering source reservations, shared-reading acquisition, cohort nesting and denominator rules. New sources, label intent and independent evaluation still require explicit evidence.", ""]
    destination=Path("research/issue-33-data-growth/results-model-v2.md")
    persist(destination,"\n".join(lines).encode("utf-8"))
    print(json.dumps(dict(report=destination.as_posix(),sha256=sha(destination),model_report_sha256=sha(report_path))))


if __name__=="__main__":run()
