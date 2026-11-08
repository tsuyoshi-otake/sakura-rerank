"""Own a bounded recipe stage and its terminal/termination evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from recipe_common import HERE, ROOT, save


def run(stage, commit):
    ROOT.mkdir(parents=True, exist_ok=True)
    save(ROOT/(stage+'-reservation.json'), dict(stage=stage, owner_pid=os.getpid(), commit=commit, timeout_seconds=1800))
    command = [sys.executable, '-B', '-u', str(HERE/'execute_recipe.py'), stage]
    if commit: command += ['--commit', commit]
    started = time.monotonic(); child = None; result = dict(stage=stage, status='failed')
    try:
        with (ROOT/(stage+'.log')).open('xb') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':os.pathsep.join((str(Path.cwd()/'src'), str(Path.cwd())))})
            result['child_pid'] = child.pid
            print(json.dumps(dict(stage=stage, child_pid=child.pid, status='running')), flush=True)
            try:
                code = child.wait(timeout=1800); result.update(status='complete' if code == 0 else 'failed', exit_code=code)
            except subprocess.TimeoutExpired: result['status'] = 'timed_out'
    except Exception as error: result['error_type'] = type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            save(ROOT/(stage+'-termination-intent.json'), dict(child_pid=child.pid, reason=result['status']))
            killed = subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=30)
            child.wait(timeout=30); result.update(termination_exit=killed.returncode, exit_code=child.returncode)
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(ROOT/(stage+'-terminal.json'), result); print(json.dumps(result), flush=True)
    return result['status'] == 'complete'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=('targeted', 'prepare', 'verify', 'tests')); parser.add_argument('--commit')
    args = parser.parse_args(); raise SystemExit(0 if run(args.stage, args.commit) else 1)
