"""Own one bounded lexical stage, including timeout and terminal receipt."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from lexical_common import HERE,ROOT,save


def execute(stage,commit):
    ROOT.mkdir(parents=True,exist_ok=True)
    save(ROOT/(stage+'-reservation.json'),dict(stage=stage,code_commit=commit,owner_pid=os.getpid(),timeout_seconds=1800))
    script='analyze_lexical.py' if stage=='analyze' else 'verify_lexical.py'
    command=[sys.executable,'-B','-u',str(HERE/script),stage]
    if commit:command+=['--commit',commit]
    started=time.monotonic();child=None;terminal=dict(stage=stage,status='failed')
    try:
        with (ROOT/(stage+'.log')).open('xb') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':os.pathsep.join((str(Path.cwd()/'src'),str(Path.cwd())))})
            terminal['child_pid']=child.pid;print(json.dumps(dict(stage=stage,status='running',child_pid=child.pid)),flush=True)
            try:
                code=child.wait(timeout=1800);terminal.update(status='complete' if code==0 else 'failed',exit_code=code)
            except subprocess.TimeoutExpired:terminal['status']='timed_out'
    except Exception as error:terminal['error_type']=type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            save(ROOT/(stage+'-termination-intent.json'),dict(child_pid=child.pid,reason=terminal['status']))
            killed=subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=30);child.wait(timeout=30)
            terminal.update(termination_exit=killed.returncode,exit_code=child.returncode)
        terminal['elapsed_seconds']=round(time.monotonic()-started,3)
        save(ROOT/(stage+'-terminal.json'),terminal);print(json.dumps(terminal),flush=True)
    return terminal['status']=='complete'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('analyze','verify','tests'));parser.add_argument('--commit');args=parser.parse_args()
    raise SystemExit(0 if execute(args.stage,args.commit) else 1)
