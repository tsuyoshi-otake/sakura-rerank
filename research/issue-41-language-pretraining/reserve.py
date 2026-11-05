"""Reserve an unused public-train cohort before fetching any of its text."""
from sakura_rerank.data.contracts import canonical_json_hash
from language_common import ROOT,PRIOR_ROOT,TRAIN_ROOT,boundary,sha,read_json,save,authenticate_prior


def run():
    authenticate_prior()
    previous=read_json("research/issue-40-context-contrast/plan-v1.json")
    tree=read_json(ROOT/"tree.json")
    if tree["sha"]!=previous["source_tree"] or tree["truncated"]:raise ValueError("fixed_tree_differs")
    old=boundary.pilot.ROOT.parent/"issue-31-kwdlc-probe-v1"
    if sha(old/"train.id")!=previous["membership_sha256"]:raise ValueError("membership_changed")
    available=set((old/"train.id").read_text(encoding="utf8").splitlines())
    exposed={r["document_id"] for root,key in ((old,"selected_documents"),(boundary.pilot.ROOT,"documents"),(PRIOR_ROOT,"documents"))
             for r in read_json(root/"selection.json")[key]}
    if len(available)!=3915 or len(exposed)!=1300:raise ValueError("known_exposure_count_differs")
    wanted=sorted(available-exposed,key=lambda d:(canonical_json_hash([20261105,"issue-41-language-pretraining-v1",d]),d))[:1000]
    entries={r["path"].rsplit("/",1)[-1][:-4]:r for r in tree["tree"] if r["path"].startswith("knp/") and r["path"].endswith(".knp")}
    docs=[dict(document_id=d,path=entries[d]["path"],git_blob_sha1=entries[d]["sha"],bytes=entries[d]["size"]) for d in wanted]
    selection=dict(kind="language_pretraining_research_evaluation_reservation",corpus_commit=previous["source_commit"],
        corpus_tree=tree["sha"],documents=docs,previous_documents=1300,body_accessed=False,final_test=False)
    save(ROOT/"selection.json",selection)
    plan=dict(kind="paired_c2_language_pretraining_plan",issue=41,parent=1,date="2026-11-05",
        source_commit=previous["source_commit"],source_tree=tree["sha"],selection_sha256=sha(ROOT/"selection.json"),
        expected_source_bytes=sum(d["bytes"] for d in docs),documents=1000,acquisition=previous["acquisition"],
        selection_rule="Bottom SHA256 canonical [20261105,'issue-41-language-pretraining-v1',document_id], exclude all 1300 exposed public-train documents. No public dev/test access or replacements.",
        source_rights_scope=previous["source_rights_scope"],
        evaluation=dict(eligibility=previous["eligibility"],main="One target per document, bottom SHA256 [20261105,'language-main',stable_id]; all 1000 slots retained as terminal states.",
            contrasts=previous["contrast_selection"],history="All #40 history plus every #40 source unit and eligible input, including excluded/unselected rows. Full source coverage for new cohort; same transitive source/near/input isolation.",
            readiness=dict(main_minimum=500,contrast_groups_minimum=25,supported_groups_minimum=25),
            runtime="CPU PyTorch FP32, one host thread; CPU ORT parity/latency for seed20260814; no GPU scores used to choose winners.",
            conditions=["intact","empty","fixed shuffled"],gate="Existing margin >1.7 unchanged; no calibration on this cohort.",
            metrics="All seeds, raw/gated R/H/W, correction failures, precision/recall, application, candidate/ranking failures, component paired 95% intervals; never omit failures.",
            primary="LM-on minus LM-off intact/ungated main per seed; all three paired 95% lower bounds >0, all point differences >=0 with positive mean, and supported contrasts improve in >=2 seeds to advance. Otherwise do not adopt. No best-seed or post-hoc budget search."),
        pretraining=dict(hypothesis="Learning next-character prediction from train-only source fragments improves candidate rescue with unchanged C2 ranking architecture and downstream supervision.",
            source_path=str(TRAIN_ROOT/"isolation/selected.jsonl").replace("\\","/"),source_sha256=sha(TRAIN_ROOT/"isolation/selected.jsonl"),
            source_scope="Only population=train Wikipedia/Aozora original left_context+target fragments from authenticated v2 source isolation. No reading label used by LM; not a full-article/general-language corpus.",
            source_licenses="Reuse pinned v1/v2 Wikipedia/Aozora source, license and acquisition manifests. KWDLC never used for training.",
            isolation="Recheck train fragments against six original source generations, frozen inputs, every growth evaluation source (including excluded rows), all 1300 old KWDLC documents and all 1000 reserved new documents. Quarantine whole connected components. Previously approved growth train targets are allowed, not mislabeled as evaluation history.",
            windows="At most six positions per unique literal fragment, bottom SHA256 [20261105,'lm-position',text_sha256,position], positions >=8. Each uses only previous <=64 characters to predict the next character. Deduplicate exact (context,next-char) pairs, preserve provenance, choose lowest window hashes up to 500000 per corpus/1000000 total; no replacement from eval.",
            minimum_windows=100000,maximum_windows=1000000,context_max=64,positions_per_fragment=6,
            architecture="Unchanged C2 character hash vocabulary, embedding and single-layer GRU. Tied embedding output matrix predicts one next-character hash class; PAD class excluded. Only embedding/encoder updated; ranking scorer stays unchanged during LM. No added inference parameters or vocabulary change.",
            updates=2000,batch_size=512,learning_rate=.0001,weight_decay=.01,gradient_clip_norm=1.0,
            maximum_seconds_per_seed=3600,maximum_total_gpu_seconds=14400,selection="Fixed final step only, no validation tuning. Record loss but never use it as adoption evidence."),
        downstream=dict(architecture="c2",cohort="mixed",rows=50000,initial_checkpoint="data/generated/issue-29-distill-gate/final/student-s20260814.pt",
            initial_checkpoint_sha256="cf20755918400ae4ab79bc800cd59ded888124a3c96b54197b6e3d7581aa132a",
            seeds=[20260814,20261103,20261104],updates=500,batch_size=256,learning_rate=.0001,weight_decay=.01,gradient_clip_norm=1.0,
            loss="Unchanged C2 listwise CE / smoothing .05",control="Authenticate #40 C2 controls and replay all three no-LM fits; require tensor equality. Reset RNG/optimizer before paired downstream adaptation.",
            model_selection="All six final checkpoints sealed before any new evaluation inference. Training process never opens evaluation arrays."),
        cpu_benchmark=dict(seed=20260814,warmup=200,runs=10000,batch=1,intra_op_threads=1,inter_op_threads=1,p95_ms_max=2,p99_ms_max=5,atol=1e-5,rtol=1e-5),
        safety_threshold=.0025,gold_certified=False,final_test_used=False,production_changes=False,
        verify_expect=[dict(Verify="Source/license/hash and full history closure before LM",Expect="Train-only fragments, all fixed cohort slots accounted, no test contamination"),
            dict(Verify="Causal windows, tied-head gradient and scorer freeze tests; identical downstream controls",Expect="Only pretraining presence changes, no right-context/label use in LM"),
            dict(Verify="All model/score bindings, independent count replay, CPU parity and 10000 runs",Expect="No omitted seeds/failures or numerical tolerance changes"),
            dict(Verify="Full tests, historical artifact hashes and process/temp cleanup",Expect="No original data/model changes; Gold and .25% limits preserved")])
    save("research/issue-41-language-pretraining/plan-v1.json",plan)
    return dict(documents=1000,previous_documents=1300,expected_source_bytes=plan["expected_source_bytes"],selection_sha256=plan["selection_sha256"])


if __name__=="__main__":
    import json
    print(json.dumps(run()))
