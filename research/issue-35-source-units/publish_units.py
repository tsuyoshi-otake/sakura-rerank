"""Aggregate-only publication requires complete request accounting, not exit0 alone."""
import ast
import json

from unit35_common import ROOT,HERE,authenticate,read,save,sha


def run():
    authenticate('1226b2dbc1e6bdbd59ec629619a8011736403f67')
    reports={name:read(ROOT/path) for name,path in (
        ('preparation','preparation.json'),('ownership','owner-diagnostic.json'),
        ('first_native_attempt','native-report.json'),('native','native-report-v2.json'),
        ('verification','verification.json'),('tests','full-unit-tests-r2.json'))}
    native=reports['native'];tests=reports['tests'];verification=reports['verification']
    if (native['status']!='complete_with_explicit_rejections' or native['not_attempted']
            or native['stop_reason'] is not None or sum(native['outcomes'].values())!=426
            or native['native_calls_first_attempt']+native['native_calls_continuation']!=426
            or native['native_requests_retried'] or verification['status']!='passed'
            or not tests['successful'] or tests['failures'] or tests['errors'] or tests['skipped']):
        raise ValueError('unit35_complete_verified_population_required')
    for stage in ('prepare','owners','native','continuation','full-tests-r2','verify-r2'):
        if read(ROOT/(stage+'-runner.json'))['status']!='complete':
            raise ValueError('unit35_terminal_runner_required')
    for path in HERE.glob('*.py'):compile(ast.parse(path.read_bytes()),str(path),'exec')
    result=dict(kind='source_unit_and_owner_diagnostic_v1',status='research_diagnostic_complete',
        source_snapshot='tatoeba-jpn-weekly-20261031',exposure='Same100 source-pilot sentences; not new evaluation or calibration.',
        plan_sha256=sha(HERE/'plan-v1.json'),native_binding_sha256=sha(HERE/'native-binding-v1.json'),
        continuation_binding_sha256=sha(HERE/'native-continuation-v1.json'),reports=reports,
        adopted_accuracy_percent=90.72,safety_harm_fraction=.0025,gold_point_minimum=.995,
        gold_wilson_lower_minimum=.99,final_holdout_valid_minimum=3000,
        model_fits=0,model_inference=0,source_acquisition=0,old_exclusions_restored=0,
        gold_admission=0,calibration_admission=0,final_test_used=False,production_changed=False,
        old_converter_segment_bound=18,release_complete=False,raw_text_in_report=False)
    path='reports/issue-35-source-units-v1.json';save(path,result)
    save(ROOT/'publication.json',dict(report_sha256=sha(path),status='published_aggregate',
         tests=tests['tests'],native_requests_accounted=426,output_contract_rejections=native['outcomes']['output_contract_rejected']))
    print(json.dumps(dict(status=result['status'],report_sha256=sha(path),tests=tests['tests'])))


if __name__=='__main__':run()
