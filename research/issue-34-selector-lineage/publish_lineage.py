"""Aggregate publication only; no raw identities or label promotion."""
import ast
import json
from pathlib import Path
from lineage_common import HERE,ROOT,read,save,sha


def publish():
    audit=read(ROOT/'audit.json');verified=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    if (verified['status']!='passed' or verified['audit_sha256']!=sha(ROOT/'audit.json')
        or tests!={'tests':788,'successful':True,'failures':0,'errors':0,'skipped':0}
        or any(read(ROOT/(name+'-runner.json'))['status']!='complete' for name in ('audit','verification','full-tests'))):
        raise ValueError('lineage_publication_requires_complete_verification')
    checked=[]
    for path in sorted(HERE.glob('*.py')):
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec');names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        if unused:raise ValueError('lineage_publication_unused_import')
        checked.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    result=dict(kind='fixed_selector_lineage_report',status='verified_recorded_ancestry_no_fit_permission',issues=[34,33,32,35],parent_issue=1,
        plan_sha256=sha(HERE/'plan-v1.json'),audit=audit,verification=verified,tests=tests,static_checks=checked,
        conclusions=['The fixed #29 selector has no projected fit or selection overlap with the75000-row pool under the authenticated recorded history closure.',
            'Random C2 initialization and old-train teachers avoid inheriting the six new fitted models. The expanded22-node artifact graph has no missing parents.',
            'Keeping #29 fixed requires zero new ranker fits. Five outer gate fits plus one final fit are a conditional future budget, not execution permission.',
            'The pool was previously consumed for research and labels remain weak source reconstruction; source-disjointness is not independent evaluation or Gold.',
            'CPU score generation and a separate gate recipe/evaluation binding remain outstanding. Historical GPU scores are not recertified.'],
        next_action='Freeze CPU-only input/score generation for the fixed selector, preserving component folds and all75000 source rows. Establish separate gate and independent evaluation/calibration bindings before fitting or threshold selection.',
        expected_benefit='Avoid16/26 unnecessary ranker fits when the selector stays fixed; isolate application-decision learning from candidate ranking.',
        measured_audit_seconds=audit['elapsed_seconds'],measured_verification_seconds=read(ROOT/'verification-runner.json')['elapsed_seconds'],
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,
        gold_requirements=dict(point=.995,wilson95_lower=.99,final_valid=3000),gold_certified=False,release_eligible=False,
        new_fits=0,new_inference=0,threshold_selection=False,calibration=False,final_test=False,production_change=False)
    target=Path('reports/issue-34-selector-lineage-v1.json');save(target,result)
    print(json.dumps(dict(status=result['status'],report_sha256=sha(target),tests=tests['tests'],python_files=len(checked))))


if __name__=='__main__':publish()
