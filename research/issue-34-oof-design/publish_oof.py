"""Publish aggregate feasibility and verification, without private row identities."""
import ast
import json
from pathlib import Path

from oof_common import HERE,ROOT,read,save,sha


def publish():
    audit=read(ROOT/'audit.json');proof=read(ROOT/'verification.json');tests=read(ROOT/'full-tests.json')
    if (proof['status']!='passed' or proof['audit_sha256']!=sha(ROOT/'audit.json')
            or tests!={'tests':788,'successful':True,'failures':0,'errors':0,'skipped':0}
            or any(read(ROOT/(stage+'-runner.json'))['status']!='complete' for stage in ('audit','verification','full-tests'))):
        raise ValueError('oof_publication_without_verification')
    paths=sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/gate_oof.py'),Path('tests/test_gate_oof.py')];static=[]
    for path in paths:
        raw=path.read_bytes();tree=ast.parse(raw);compile(raw,str(path),'exec')
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        unused=[alias.asname or alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))
            and getattr(node,'module',None)!='__future__' for alias in node.names if (alias.asname or alias.name.split('.')[0]) not in names]
        if unused:raise ValueError('oof_static_unused_import')
        static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    times=audit['observed_prior_fit_seconds']
    report=dict(kind='nested_gate_oof_design_report',status='verified_metadata_audit_no_fit_permission',issues=[34,33,32,35],parent_issue=1,
        plan_sha256=sha(HERE/'plan-v1.json'),audit=audit,verification=proof,tests=tests,static_checks=static,
        artifact_hashes={name:sha(ROOT/name) for name in ('audit.json','verification.json','full-tests.json','nested-schedule.json')},
        cost_context=dict(prior_six_500_update_fit_seconds=[min(times),max(times)],
            conditional16_fit_arithmetic_seconds=[16*min(times),16*max(times)],unshared26_fit_arithmetic_seconds=[26*min(times),26*max(times)],
            scope='Arithmetic only using prior CUDA fits; not a measured nested run or wall-time guarantee. Excludes source/lineage audit, inference, gates, calibration, CPU parity/export and verification.'),
        conclusions=['Saved fitted-training scores cannot be relabeled as OOF by attaching new fold IDs.',
            'Recorded component dependence and checkpoint ancestry are separate proof requirements; source-disjoint rows with unknown ancestry remain uncertified.',
            'Five folds are constructible, but the giant Aozora component prevents equal row counts and source-balanced folds without splitting recorded relations.',
            'Outer gate evaluation requires nested proposal-model exclusion; ordinary one-layer OOF proposals can retain outer-fold dependence.'],
        pending=['Complete initialization, teacher, model-selection and preprocessing exposure identities before fit permission.',
            'Prespecify interpretation of severe source imbalance, or add diverse permitted training sources while preserving old components and all evaluation exclusions.',
            'Freeze candidate/gate recipes, features, optimizer/order/seed and output contracts in a separate fit binding.',
            'Establish independent calibration and Gold evidence; consumed source evaluations cannot be reused as training, calibration or fresh Test.'],
        new_fits=0,new_inference=0,threshold_selection=False,calibration=False,final_test=False,
        adopted_accuracy_record=.9072,safety_limit=.0025,gold_requirements=dict(point=.995,wilson95_lower=.99,final_valid=3000),
        gold_certified=False,release_eligible=False)
    target=Path('reports/issue-34-oof-design-v1.json');save(target,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(target),tests=tests['tests'],python_files=len(static),new_fits=0)))


if __name__=='__main__':publish()
