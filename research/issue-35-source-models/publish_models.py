"""Publish aggregate, verified source-reconstruction evidence only."""
import ast
import json
from pathlib import Path

from model35_common import HERE,ROOT,read,save,sha


def publish():
    verification=read(ROOT/'verification.json');evaluation=read(ROOT/'evaluation.json')
    inference=read(ROOT/'inference-report.json');tests=read(ROOT/'full-tests.json');plan=read(HERE/'plan-v2.json')
    if (verification['status']!='passed' or verification['evaluation_sha256']!=sha(ROOT/'evaluation.json')
            or tests!={'errors':0,'failures':0,'skipped':0,'successful':True,'tests':769}
            or any(read(ROOT/(stage+'-runner.json'))['status']!='complete' for stage in ('preparation-v2','inference','evaluation','verification','full-tests'))):
        raise ValueError('source_models_publication_verification')
    files=sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/source_model_inputs.py'),
        Path('tests/test_source_model_inputs.py'),Path('tests/test_source_model_decisions.py')]
    code=[]
    for path in files:
        raw=path.read_bytes();tree=ast.parse(raw);compile(raw,str(path),'exec')
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        unused=[alias.asname or alias.name.split('.')[0] for node in ast.walk(tree)
            if isinstance(node,(ast.Import,ast.ImportFrom)) and getattr(node,'module',None)!='__future__'
            for alias in node.names if (alias.asname or alias.name.split('.')[0]) not in names]
        if unused:raise ValueError('source_models_unused_import')
        code.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    metrics=evaluation['parts']['all'];oracle=metrics['observed_candidate_oracle'];models=metrics['models']
    headroom=oracle['6']['numerator']-oracle['1']['numerator']
    diagnosis=dict(observed_parts=metrics['record_count'],baseline_mismatches=metrics['baseline_errors'],
        source_available_ranks2_to6=headroom,source_available_ranks7_to32=oracle['32']['numerator']-oracle['6']['numerator'],
        source_absent_top32=metrics['record_count']-oracle['32']['numerator'],
        models={name:dict(source_available_but_not_selected=oracle['6']['numerator']-value['accuracy']['numerator'],
            rescued_available_baseline_mismatches=value['correction_success'],available_rescue_fraction=value['correction_success']/headroom)
            for name,value in models.items()},
        published_gates={name:dict(source_matching_losses_prevented=models[name+'-ungated']['baseline_correct_destroyed']-models[name+'-published-gate']['baseline_correct_destroyed'],
            source_matching_gains_suppressed=models[name+'-ungated']['correction_success']-models[name+'-published-gate']['correction_success']) for name in ('r2','issue29')},
        inference='The frozen rankers recover few available source matches on this population; the prefix limit alone cannot account for the gap. Training-distribution, intended-output ambiguity and absent session context remain distinct unproven causal hypotheses.')
    retained=['plan-v1.json','plan-v2.json','inference-binding-v1.json']
    report=dict(kind='fixed_three_model_source_reconstruction_report',status='verified_research_only',issues=[35,33,32],parent_issue=1,
        source_commit=plan['source_commit'],label_scope=plan['label_task'],plan_hashes={name:sha(HERE/name) for name in retained},
        first_preparation_failure_preserved=plan['preserved_first_attempt'],preparation=read(ROOT/'preparation.json'),
        model_artifacts=plan['models'],environment=plan['environment'],inference=inference,evaluation=evaluation,diagnosis=diagnosis,
        verification=verification,tests=tests,static_checks=code,
        artifact_hashes={name:sha(ROOT/name) for name in ['preparation.json','outputs-seal.json','inference-report.json','evaluation.json','verification.json','full-tests.json']},
        current_sakura_input_head=plan['current_sakura_input_head'],production_equivalence_certified=False,
        adopted_accuracy_record=0.9072,new_model_adopted=False,safety_requirement=0.0025,
        gold_requirements=dict(point_precision=.995,wilson95_lower=.990,final_valid_minimum=3000),
        gold_admission=0,calibration_admission=0,final_test_used=False,new_fits=0,native_regeneration=0,production_changes=0,
        model_distribution_authorized=False,release_eligible=False,
        limitations=['Source-surface reconstruction is not unique intended Japanese conversion.',
            'All1000 reserved sentences remain:34 source failures and9 native-unmeasured sentences are not scored as observed failures or silently removed.',
            'Related-history and provisionally unconnected slices remain distinct; unknown authorship and translation lineage preclude independent Gold certification.',
            'Component intervals are conditional on the recorded relation graph; seven overlapping slices are descriptive, not a new confirmatory selection family.',
            'Zero empirical match losses and a degenerate bootstrap interval cannot certify zero population risk.',
            'Latency covers prebuilt-feed CPU session.run only, not encoding, IPC, startup, scheduling or end-to-end IME latency.'])
    target=Path('reports/issue-35-source-models-v1.json');save(target,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(target),tests=tests['tests'],syntax_checked=len(code),new_fits=0,adopted_accuracy_record=.9072)))


if __name__=='__main__':publish()
