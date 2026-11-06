"""Own one bounded, non-retrying preparation/test process and its terminal."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ROOT = REPO/'data/generated/issue-33-knbc-screening-v1/attempt-02'


def save(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def run(stage, commit):
    ROOT.mkdir(parents=True, exist_ok=True)
    limit = 900 if stage == 'history' else 600
    save(ROOT/(stage+'-owner.json'), dict(owner_pid=os.getpid(), stage=stage, seconds_limit=limit))
    child, result, started = None, dict(status='failed', stage=stage), time.monotonic()
    try:
        with (ROOT/(stage+'.log')).open('xb') as log:
            child = subprocess.Popen([sys.executable, '-B', '-u', str(HERE/'prepare.py'), stage, '--commit', commit],
                cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONPATH':os.pathsep.join((str(REPO/'src'), str(REPO))),
                     'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONIOENCODING':'utf-8'},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            result['child_pid'] = child.pid
            print(json.dumps(dict(status='running', stage=stage, child_pid=child.pid)), flush=True)
            try:
                code = child.wait(timeout=limit)
                result.update(status='complete' if code == 0 else 'failed', exit_code=code)
            except subprocess.TimeoutExpired:
                result['status'] = 'timed_out'
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            save(ROOT/(stage+'-termination-intent.json'), dict(child_pid=child.pid, reason=result['status']))
            killed = subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=30)
            child.wait(timeout=30)
            result.update(termination_exit=killed.returncode, exit_code=child.returncode)
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(ROOT/(stage+'-terminal.json'), result)
        print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('pilot', 'prepare', 'history', 'verify', 'targeted', 'tests'))
    parser.add_argument('--commit', default='')
    args = parser.parse_args()
    raise SystemExit(0 if run(args.stage, args.commit) else 1)
