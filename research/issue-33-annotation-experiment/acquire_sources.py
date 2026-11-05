"""Fetch exactly the already reserved research documents, with no replacement."""
import argparse
import json

from experiment_common import ROOT, HERE, EXECUTION_PLAN, authenticate, boundary, read, save, sha


def run(commit):
    plan, spec = authenticate(commit)
    for path in spec['acquisition_code']:
        boundary.committed(path, commit)
        if sha(path) != spec['acquisition_code'][path]:
            raise ValueError('experiment_acquisition_code_changed')
    selection = read(plan['evaluation']['selection_path'])
    save(ROOT/'source-reservation.json', dict(
        execution_plan_commit=commit, execution_plan_sha256=sha(EXECUTION_PLAN),
        selection_sha256=sha(plan['evaluation']['selection_path']), documents=1000,
        retries=0, replacements=0, final_test=False))
    executor = boundary.load_script('annotation_reserved_sources', 'research/reserved_source_acquisition.py')
    result = executor.acquire(ROOT, selection['documents'], plan['evaluation'], dict(
        execution_plan_commit=commit, execution_plan_sha256=sha(EXECUTION_PLAN),
        plan_sha256=sha('research/issue-33-annotation-comparison/plan-v2.json'),
        selection_sha256=sha(plan['evaluation']['selection_path']),
        script_sha256=sha(HERE/'acquire_sources.py'), executor_sha256=sha('research/reserved_source_acquisition.py')))
    return dict(status=result['status'], received=sum(r['status']=='received' for r in result['attempts']),
                slots=len(result['attempts']), elapsed_seconds=result['elapsed_seconds'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execution-commit', required=True)
    print(json.dumps(run(parser.parse_args().execution_commit)))
