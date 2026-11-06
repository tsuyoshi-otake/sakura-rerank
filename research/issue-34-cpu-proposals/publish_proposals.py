"""Publish a verified training-proposal bundle and aggregate information limits."""
import ast
import json
from pathlib import Path
from proposal_common import CACHE,HERE,ROOT,read,save,sha


def publish():
    prep=read(ROOT/'preparation.json');inference=read(ROOT/'inference.json');analysis=read(ROOT/'analysis.json');proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    if (proof['status']!='passed' or any(proof[name+'_sha256']!=sha(ROOT/(name+'.json')) for name in ('preparation','inference','analysis'))
        or tests!={'tests':805,'successful':True,'errors':0,'failures':0,'skipped':0}
        or any(read(ROOT/(name+'-runner.json'))['status']!='complete' for name in ('preparation','inference','analysis','verification','full-tests'))):
        raise ValueError('proposal_publication_requires_verified_completion')
    paths=sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/gate_proposal_inputs.py'),Path('tests/test_gate_proposal_inputs.py'),Path('tests/test_gate_proposal_metrics.py')]
    static=[]
    for path in paths:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        if unused:raise ValueError('proposal_unused_import')
        static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    binding=read(HERE/'inference-binding-v1.json')
    bundle=dict(kind='fixed_selector_research_proposal_bundle',rows=75000,model=binding['model'],
        source_cache_manifest_sha256=sha(CACHE/'manifest.json'),source_cache_arrays_sha256=sha(CACHE/'arrays.npz'),
        source_row_receipts_sha256=sha(CACHE/'row-receipts.jsonl'),inputs=prep['artifacts'],
        scores={r['condition']:r['scores_sha256'] for r in inference['conditions']},
        preparation_sha256=sha(ROOT/'preparation.json'),outputs_seal_sha256=sha(ROOT/'outputs-seal.json'),verification_sha256=sha(ROOT/'verification.json'),
        label_kind='original_source_reconstruction_weak_labels',fit_permission=False,calibration_permission=False,final_test_permission=False,
        condition_scope={name:dict(recorded_provenance=r['recorded_provenance'],history_connected_rows=r['history_connected_rows'],
            independent_gold=False,independent_evaluation=False) for name,r in prep['conditions'].items()})
    save(ROOT/'proposal-bundle.json',bundle)
    results=dict(kind='fixed_cpu_proposal_report',status='verified_research_proposals_no_fit_permission',issues=[34,31,32,33,35],parent_issue=1,
        plan_sha256=sha(HERE/'plan-v1.json'),inference_binding_sha256=sha(HERE/'inference-binding-v1.json'),
        preparation=prep,inference=inference,analysis=analysis,verification=proof,tests=tests,static_checks=static,
        proposal_bundle_sha256=sha(ROOT/'proposal-bundle.json'),
        conclusions=['Both75000-row CPU output sets replay exactly. The fixed selector,8 input fields, masks, original component links and all source labels remain unchanged.',
            'Removing context changes the model input identity:21459 unique inputs remain,2114 have incompatible source labels, and at least5658/75000 source mismatches are unavoidable for any deterministic selector of these exact inputs.',
            'The92.456% ceiling is a census bound on this consumed weak-label pool, not the ceiling of the old dev set or Japanese IME accuracy.',
            'Empty-context inputs match1688 historical train and210 dev rows,1888 distinct current rows. Recorded component propagation connects73623/75000 rows to history; the remaining1377 are not independent Gold.',
            'The empty-context giant contains73608 rows; each50000-row arm has48608/348/348/348/348 folds. Removing these relations or dropping difficult rows would change the evaluation contract.',
            'A fixed gate suppresses both harms and successful corrections. CPU preparation does not improve adopted accuracy or establish the0.25% safety criterion.'],
        prioritized_next_steps=[
            dict(priority=1,issue=31,action='Decompose incompatible projected-input groups into source-intent ambiguity, extraction/label problems and encoding aliases; preserve all alternatives and histories without majority relabeling.',expected_effect='Identify whether extra context, explicit ambiguity handling or label correction is required.',cost='Metadata joins and bounded source review on2114 training-only groups; no fit or external evaluation.'),
            dict(priority=2,issue=32,action='Carry projected-input equality and ancestry overlays into any new source reservation or gate-fold contract.',expected_effect='Prevent the demonstrated context-removal leakage and expose effective source diversity.',cost='Linear hash/group joins; independent calibration remains a separate acquisition/quality task.'),
            dict(priority=3,issue=34,action='Freeze a gate recipe only after choosing a valid deployment context contract and independent calibration/evaluation source.',expected_effect='Separate correction application from candidate ranking without treating consumed training scores as safety evidence.',cost='Up to6 gate fits for a fixed selector, conditional on valid data and folds; zero new ranker fits in this run.')],
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,
        gold_requirements=dict(point=.995,wilson95_lower=.99,final_valid=3000),gold_certified=False,release_eligible=False,
        new_ranker_fits=0,new_gate_fits=0,threshold_selection=False,calibration=False,final_test=False,production_change=False)
    target=Path('reports/issue-34-cpu-proposals-v1.json');save(target,results)
    print(json.dumps(dict(status=results['status'],report_sha256=sha(target),bundle_sha256=sha(ROOT/'proposal-bundle.json'),tests=tests['tests'],python_files=len(static))))


if __name__=='__main__':publish()
