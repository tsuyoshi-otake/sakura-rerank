"""Publish aggregate results only, after source/native and integrity verification."""
import json

from consume35_common import HERE, ROOT, read, save, sha


def run():
    verification=read(ROOT/'verification.json')
    if verification['status']!='passed':raise ValueError('consumption_verified_report_required')
    reports={name:read(ROOT/filename) for name,filename in (
        ('selection','selection-report.json'),('preparation','preparation.json'),
        ('history','history-report.json'),('native','native-report.json'),('verification','verification.json'))}
    if (reports['native']['status']!='complete_with_explicit_rejections'
            or reports['native']['not_attempted'] or reports['preparation']['slots']!=1000):
        raise ValueError('consumption_full_population_required')
    plan=read(HERE/'plan-v1.json')
    report=dict(kind='prospective_continuous_source_consumption_v1',status='complete_research_not_admitted',
        reports=reports,**plan['unchanged'],source_snapshot=plan['source_snapshot'],
        exposure='Prospective metadata-selected cohort in previously acquired exports; not independent Gold/Test.',
        plan_sha256=sha(HERE/'plan-v1.json'),contract_sha256=sha(HERE/'contract-v1.md'),
        selection_binding_sha256=sha(HERE/'selection-binding-v1.json'),
        native_binding_sha256=sha(HERE/'native-binding-v1.json'),
        raw_text_in_report=False,model_fits=0,model_inference=0,source_acquisition=0,
        gold_admission=0,calibration_admission=0,final_test_used=False,production_changed=False,release_complete=False)
    target='reports/issue-35-source-consumption-v1.json'
    save(target,report)
    print(json.dumps(dict(status=report['status'],report=target,sha256=sha(target))))


if __name__=='__main__':run()
