"""Publish aggregate evidence only; raw source/IDs remain in the private root."""
import ast
import json
from pathlib import Path

from pilot35_common import ROOT, HERE, committed, read, save, sha


def run():
    tests=read(ROOT/'full-unit-tests-r2.json')
    if not tests['successful'] or tests['failures'] or tests['errors'] or tests['skipped']:
        raise ValueError('pilot35_full_suite_required')
    for stage in ('acquire','metadata','alignment','isolation','full-tests-r2','verify','relation-diagnostic'):
        if read(ROOT/(stage+'-runner.json'))['status']!='complete':
            raise ValueError('pilot35_all_terminal_stages_required')
    binding_path=Path('research/issue-33-loss-balance/evaluation-binding-v1.json')
    bound=json.loads(committed(binding_path,'5fcbb79afcf109391f75e6e880228c259d11f4a4'))
    for model in bound['models']:
        if sha(model['path'])!=model['sha256']:
            raise ValueError('pilot35_previous_checkpoint_changed')
    reports={name:read(ROOT/filename) for name,filename in (
        ('acquisition','acquisition.json'),('metadata','metadata-profile.json'),('alignment','alignment-audit.json'),
        ('isolation','isolation-audit.json'),('diagnostic','relation-diagnostic.json'),
        ('verification','direct-verification.json'),('historical_integrity','historical-integrity.json'))}
    if reports['verification']['status']!='passed' or reports['historical_integrity']['status']!='passed':
        raise ValueError('pilot35_direct_verification_required')
    code=list(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/tatoeba_source.py'),Path('tests/test_tatoeba_source.py'),Path('tests/test_tatoeba_acquisition.py')]
    unused=[]
    for path in code:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec')
        used={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)) and getattr(node,'module',None)!='__future__':
                for alias in node.names:
                    key=alias.asname or alias.name.split('.')[0]
                    if key not in used:unused.append(dict(path=path.as_posix(),name=key))
    if unused:
        raise ValueError('pilot35_unused_import')
    result=dict(kind='external_source_pilot_v1',status='research_pilot_complete_not_gold',
        snapshot='tatoeba-jpn-weekly-20261031',source_plan_sha256=sha(HERE/'plan-v1.json'),
        selection_binding_sha256=sha(HERE/'selection-binding-v1.json'),
        history_binding_sha256=sha(HERE/'history-binding-v1.json'),reports=reports,tests=tests,
        static_checks=dict(python_files_compiled=len(code),unused_imports=0),
        unchanged_model_checkpoints=len(bound['models']),adopted_accuracy_percent=90.72,
        safety_harm_fraction=0.0025,gold_point_minimum=0.995,gold_wilson_lower_minimum=0.99,
        final_holdout_valid_minimum=3000,new_fits=0,model_inference=0,native_candidate_calls=0,
        human_verdicts=0,gold_certified=0,calibration_admitted=0,final_test_used=False,
        production_changed=False,release_complete=False,raw_text_in_public_report=False)
    save('reports/issue-35-external-source-pilot-v1.json',result)
    save(ROOT/'publication.json',dict(report_sha256=sha('reports/issue-35-external-source-pilot-v1.json'),
        tests=tests,static_checks=result['static_checks'],unchanged_model_checkpoints=len(bound['models'])))
    print(json.dumps(dict(status=result['status'],tests=tests,static_checks=result['static_checks'],unchanged_model_checkpoints=len(bound['models']))))


if __name__=='__main__':run()
