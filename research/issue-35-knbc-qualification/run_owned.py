"""Own one finite qualification/check process, including failed terminal states."""
import argparse
import json
import os
import subprocess
import sys
import time

from qualify_knbc import HERE, REPO, ROOT, save


def run(stage, commit):
    timeout = 1800 if stage == 'tests' else 300
    save(ROOT/(stage+'-owner-reservation.json'), dict(owner_pid=os.getpid(), stage=stage, timeout_seconds=timeout, commit=commit))
    child = None
    result = dict(status='failed', stage=stage)
    started = time.monotonic()
    try:
        with (ROOT/(stage+'.log')).open('xb') as log:
            child = subprocess.Popen([sys.executable, '-B', '-u', str(HERE/'qualify_knbc.py'), stage, '--commit', commit],
                cwd=REPO, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':os.pathsep.join((str(REPO/'src'), str(REPO)))})
            result['child_pid'] = child.pid
            print(json.dumps(dict(status='running', stage=stage, child_pid=child.pid)), flush=True)
            try:
                result['exit_code'] = child.wait(timeout=timeout)
                result['status'] = 'complete' if child.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                result['status'] = 'timed_out'
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            save(ROOT/(stage+'-termination-intent.json'), dict(child_pid=child.pid, reason=result['status']))
            killed = subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'], capture_output=True, timeout=30)
            child.wait(timeout=30)
            result.update(termination_exit=killed.returncode, exit_code=child.returncode)
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(ROOT/(stage+'-terminal.json'), result)
        print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('inspect','verify','targeted','tests'))
    parser.add_argument('--commit', default='')
    args = parser.parse_args()
    raise SystemExit(0 if run(args.stage, args.commit) else 1)
