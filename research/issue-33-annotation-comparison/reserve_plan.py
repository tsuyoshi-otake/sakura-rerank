"""Freeze the paired recipe and unused public-train membership before body access."""
import hashlib
import json
from pathlib import Path
import subprocess

from sakura_rerank.data.contracts import canonical_json_hash

ROOT=Path('data/generated/issue-33-annotation-comparison-v1')
HERE=Path('research/issue-33-annotation-comparison')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path): return json.loads(Path(path).read_bytes())


def save(path,value):
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')
    with Path(path).open('xb') as stream: stream.write(raw)


def run():
    previous=read('research/issue-40-context-contrast/plan-v1.json')
    old=Path('data/generated/issue-31-kwdlc-probe-v1')
    tree_path=Path('data/generated/issue-41-language-pretraining-v1/tree.json')
    tree=read(tree_path)
    if tree['sha']!=previous['source_tree'] or tree['truncated'] or sha(old/'train.id')!=previous['membership_sha256']:
        raise ValueError('comparison_reservation_metadata_changed')
    membership=set((old/'train.id').read_text(encoding='utf-8').splitlines())
    prior=[(old/'selection.json','selected_documents'),
        (Path('data/generated/issue-39-context-pilot-v1/selection.json'),'documents'),
        (Path('data/generated/issue-40-context-contrast-v1/selection.json'),'documents'),
        (Path('data/generated/issue-41-language-pretraining-v1/selection.json'),'documents')]
    exposed=set()
    for path,key in prior:
        documents={r['document_id'] for r in read(path)[key]}
        if exposed & documents: raise ValueError('comparison_prior_reservations_overlap')
        exposed.update(documents)
    if len(membership)!=3915 or len(exposed)!=2300 or not exposed<=membership:
        raise ValueError('comparison_prior_exposure_count')
    chosen=sorted(membership-exposed,key=lambda d:(canonical_json_hash([20261105,'annotation-recipe-v1',d]),d))[:1000]
    entries={r['path'].rsplit('/',1)[-1][:-4]:r for r in tree['tree'] if r['path'].startswith('knp/') and r['path'].endswith('.knp')}
    docs=[dict(document_id=d,path=entries[d]['path'],git_blob_sha1=entries[d]['sha'],bytes=entries[d]['size']) for d in chosen]
    if len(docs)!=1000: raise ValueError('comparison_reservation_shortfall')
    ROOT.mkdir(parents=True,exist_ok=False)
    selection=dict(kind='annotation_recipe_research_evaluation_reservation',corpus_commit=previous['source_commit'],corpus_tree=tree['sha'],
        documents=docs,previous_documents=2300,remaining_after_reservation=len(membership-exposed)-len(docs),body_accessed=False,final_test=False)
    save(ROOT/'selection.json',selection)
    paths=['reports/issue-33-consumed-numeric-v1.json','reports/issue-33-consumed-numeric-verification-v1.json',
        'data/generated/issue-33-consumed-numeric-v1/cache/manifest.json',
        'reports/issue-32-consumed-source-v1.json','reports/issue-32-consumed-source-verification-v1.json',
        'manifests/language-pretraining-data-v1.json','reports/issue-48-contrast-capacity-v1.json','reports/issue-48-contrast-verification-v1.json',
        'data/generated/issue-41-language-pretraining-v1/lm-admitted-fragments.jsonl',
        'research/issue-32-consumed-source/consumption_common.py','research/issue-49-annotation-first/annotation_common.py',
        'research/issue-49-consumed-contrast/verify_audit.py','research/issue-33-consumed-numeric/numeric_common.py',
        'src/sakura_rerank/data/growth_corpus.py','src/sakura_rerank/data/jawiki_preprocess.py',
        'src/sakura_rerank/data/growth_numeric.py','src/sakura_rerank/data/consumed_numeric.py',
        'src/sakura_rerank/data/consumed_source.py','src/sakura_rerank/data/relation_witnesses.py',
        'src/sakura_rerank/data/annotation_isolation.py','src/sakura_rerank/data/context_contrasts.py',
        'research/issue-33-annotation-comparison/policy-v1.md']
    source=read('research/issue-33-data-growth/plan-v1.json')['jawiki']
    head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=15).strip()
    clean=not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],text=True,timeout=15).strip()
    if not clean: raise ValueError('sakura_input_not_clean')
    plan=dict(kind='paired_annotation_extraction_recipe_comparison',schema_version=1,issue=33,parent=1,date='2026-11-05',
        baseline_commit='229e960ad91c6efb1f49fd9c3f2d448b6317711c',inputs={p:sha(p) for p in paths},
        hypothesis='Replacing dictionary-extracted Aozora weak labels with original-ruby-base/reading weak labels improves unseen source-form ranking under equal source counts and model budget. This is a joint extraction-recipe effect, not pure reading quality.',
        quality_policy='policy-v1.md',gold_certified=False,final_test_used=False,safety_threshold=.0025,
        original_artifacts_mutated=False,production_changes=False,
        sakura_input_observed=dict(head=head,worktree_clean=clean,used_for_behavior=False),
        source=dict(wikipedia_dump=source['path'],wikipedia_sha256=source['sha256'],
            dictionary_pool='data/generated/issue-41-language-pretraining-v1/lm-admitted-fragments.jsonl',dictionary_rows=162502,
            annotation_pool='data/generated/issue-33-consumed-numeric-v1/cache',annotation_rows=35592,
            original_inventory_nodes=833600,source_scope='All original permitted Aozora paragraphs plus complete original paragraphs used by candidate Wikipedia train fragments. Exact original source/positions required; no body pretraining.',
            history='Full #53 inventory/taint plus new Wikipedia paragraph coverage. Rebuild identity and content quarantine, preserve all old quarantine, then fresh full consumed-source/input closure.'),
        bounds=dict(nodes=1000000,rows=200000,artifact_bytes=536870912,source_stage_seconds=3600,other_stage_seconds=1800,
            wikipedia_page_chars=1000000,native_training_requests=0),
        cohorts=dict(rows_per_arm=50000,quotas=dict(jawiki=25000,aozora=25000),
            dictionary='Latest admitted source-exact dictionary-extracted rows, candidate-eligible and within current permitted paragraph scope.',
            annotation='Same Wikipedia rows/order, plus candidate-eligible original-ruby rows from #55 within current permitted paragraph scope.',
            selection='Lowest stable IDs per corpus after all source and candidate checks. No replacement, repetition, evaluation-word matching, reading/form rebalancing or model-outcome selection.',
            shortage='Preserve all terminal counts and stop before fitting. No quota or leakage-threshold relaxation.'),
        training=dict(architecture='C2',initial_checkpoint='data/generated/issue-29-distill-gate/final/student-s20260814.pt',
            initial_checkpoint_sha256='cf20755918400ae4ab79bc800cd59ded888124a3c96b54197b6e3d7581aa132a',
            seeds=[20260814,20261103,20261104],fits=6,updates_per_fit=500,batch_size=256,learning_rate=.0001,weight_decay=.01,gradient_clip_norm=1.,
            loss='Unchanged masked listwise CE with label smoothing .05',pretraining=False,feature_changes=False,
            threads=4,interop_threads=1,device='existing pinned CUDA environment',max_seconds_per_fit=1800,
            start_rule='Only after source/cohort/numeric verification, unused research evaluation readiness, separate committed fit binding and quality-policy validation. No evaluation arrays in fit process; all six final checkpoints fixed before any scores.',
            validation_during_fit=False,seed_or_step_selection=False),
        evaluation=dict(source_commit=previous['source_commit'],source_tree=tree['sha'],membership_sha256=previous['membership_sha256'],
            selection_path=(ROOT/'selection.json').as_posix(),selection_sha256=sha(ROOT/'selection.json'),documents=1000,
            expected_source_bytes=sum(d['bytes'] for d in docs),prior_exposed_documents=2300,
            reservation_metadata={path.as_posix():sha(path) for path,_ in prior},tree_sha256=sha(tree_path),
            selection='Bottom SHA256 [20261105, annotation-recipe-v1, document_id], excluding all 2300 exposed public-train documents; never public dev/test.',
            rights=previous['source_rights_scope'],acquisition=previous['acquisition'],eligibility=previous['eligibility'],
            main='One target per document, minimum canonical SHA256 [20261105, annotation-main, stable_id] before candidate/model outcomes. Retain all 1000 terminal document slots.',
            contrasts=previous['contrast_selection'],readiness=dict(main_minimum=500,contrast_minimum_for_primary=0),
            contrast_interpretation='Secondary descriptive evidence with actual group counts; no required semantic label or target support manufactured.',
            isolation='All historical/source/input metadata plus both prospective train pools and all their consumed paragraph coverage. No fresh evaluation rows or words enter training. All selected and unselected new annotation units contribute source isolation.',
            models='Initial #29 reference plus all six final fits; never pick a seed.',contexts=['intact','empty','fixed_shuffle'],
            shuffle='Same fixed role/context-length stratified cyclic permutation as #40, hash domain annotation-shuffle, seed20261105; singleton strata counted.',
            gate='Existing research margin >1.7 only; no calibration or threshold search.',
            metrics='Source-exact accuracy, rescue/harm/wrong-to-wrong, all failed corrections, error application/overall coverage, precision/recall, baseline gains, candidate presence/ranking failures, Wilson/exact 95% intervals and component paired bootstrap.',
            primary='One prespecified mean across three paired seed accuracy differences, annotation minus dictionary, intact/ungated main. Shared source-component bootstrap draws (2000, seed20261105).',
            advance_rule='All three point differences nonnegative and mean paired 95% lower bound above zero. Secondary per-seed intervals/context/contrast metrics descriptive; no multiple-comparison winner selection. Otherwise retain current model. This is research advancement, not production admission.'),
        cpu_benchmark=dict(seed=20260814,models=['dictionary','annotation'],warmup=200,runs=10000,batch=1,intra_op_threads=1,inter_op_threads=1,
            gpu=False,p95_ms_max=2,p99_ms_max=5,atol=1e-5,rtol=1e-5),
        expected_effect='Unknown; better source reading/span evidence may help, while literary distribution and unresolved IME intent may harm modern evaluation.',
        expected_cost='One bounded 4.8GB compressed Wikipedia pass plus source graph reconstruction and complete provenance/numeric verification; at most 3600s for source recovery and 1800s per other preparation stage. Later six 500-update fits cap at 1800s each, evaluation acquisition at 900s, CPU 10000 runs per prespecified arm.')
    save(HERE/'plan-v1.json',plan)
    return dict(status='reserved',documents=len(docs),previous_documents=len(exposed),remaining_documents=selection['remaining_after_reservation'],source_bytes=plan['evaluation']['expected_source_bytes'],selection_sha256=plan['evaluation']['selection_sha256'])


if __name__=='__main__': print(json.dumps(run()))
