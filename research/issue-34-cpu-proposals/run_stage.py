"""Bounded process ownership, no retries, immutable terminal accounting."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from proposal_common import ROOT,HERE,save


def run(stage,script,seconds,arguments):
    if not re.fullmatch('[a-z][a-z0-9-]{0,50}',stage) or Path(script).name!=script or not (HERE/script).is_file() or not 1<=seconds<=2400:
        raise ValueError('proposal_runner_bound')
    ROOT.mkdir(exist_ok=True);save(ROOT/(stage+'-runner-reservation.json'),dict(stage=stage,parent_pid=os.getpid(),timeout_seconds=seconds))
    start=time.monotonic();child=None;terminal=dict(status='failed',stage=stage)
    try:
        with (ROOT/(stage+'.log')).open('xb') as log:
            child=subprocess.Popen([sys.executable,'-B','-u',str(HERE/script),*arguments],stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1',
                'PYTHONPATH':os.pathsep.join((str(Path.cwd()/'src'),str(Path.cwd())))})
            terminal['child_pid']=child.pid;print(json.dumps(dict(stage=stage,status='running',child_pid=child.pid)),flush=True)
            try:
                code=child.wait(timeout=seconds);terminal.update(status='complete' if code==0 else 'failed',exit_code=code)
            except subprocess.TimeoutExpired:terminal['status']='timed_out'
    except Exception as error:terminal['error_type']=type(error).__name__
    finally:
        if child is not None and child.poll() is None:
            save(ROOT/(stage+'-termination-intent.json'),dict(child_pid=child.pid,reason=terminal['status']))
            stopped=subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=30);child.wait(timeout=30)
            terminal.update(termination_exit=stopped.returncode,exit_code=child.returncode)
        terminal['elapsed_seconds']=round(time.monotonic()-start,3);save(ROOT/(stage+'-runner.json'),terminal);print(json.dumps(terminal),flush=True)
    return terminal


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage');parser.add_argument('script');parser.add_argument('seconds',type=int)
    parser.add_argument('arguments',nargs=argparse.REMAINDER);args=parser.parse_args()
    raise SystemExit(0 if run(args.stage,args.script,args.seconds,args.arguments)['status']=='complete' else 1)
