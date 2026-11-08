"""Write-once stage owner with a wall deadline and descendant termination."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path('data/generated/issue-35-source-consumption-v1')
HERE = Path(__file__).resolve().parent


def save(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True)+'\n').encode())


def run(name, script, timeout, arguments):
    if (not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name)
            or Path(script).name != script or not script.endswith('.py')
            or not (HERE/script).is_file() or not 1<=timeout<=6000):
        raise ValueError('experiment_runner_bounds')
    ROOT.mkdir(exist_ok=True)
    save(ROOT/(name+'-runner-reservation.json'), dict(stage=name, script=script,
        parent_pid=os.getpid(), timeout_seconds=timeout))
    started=time.monotonic()
    result=dict(stage=name,status='failed',child_pid=None)
    try:
        with (ROOT/(name+'.log')).open('xb') as log:
            child=subprocess.Popen([sys.executable,'-u',str(HERE/script),*arguments],
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env={**os.environ,'PYTHONPATH':os.pathsep.join((str(Path.cwd()/'src'),str(Path.cwd())))})
            result['child_pid']=child.pid
            print(json.dumps(dict(stage=name,status='running',child_pid=child.pid)),flush=True)
            try:
                code=child.wait(timeout=timeout)
                result.update(status='complete' if code==0 else 'failed',exit_code=code)
            except subprocess.TimeoutExpired:
                save(ROOT/(name+'-termination-intent.json'),dict(child_pid=child.pid,reason='wall_deadline'))
                killed=subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=30)
                child.wait(timeout=30)
                result.update(status='timed_out',exit_code=child.returncode,termination_exit=killed.returncode)
    except Exception as error:
        result['error_type']=type(error).__name__
        raise
    finally:
        result['elapsed_seconds']=round(time.monotonic()-started,3)
        save(ROOT/(name+'-runner.json'),result)
        print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('name');parser.add_argument('script');parser.add_argument('timeout',type=int)
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    outcome=run(args.name,args.script,args.timeout,args.arguments)
    raise SystemExit(0 if outcome['status']=='complete' else 1)
