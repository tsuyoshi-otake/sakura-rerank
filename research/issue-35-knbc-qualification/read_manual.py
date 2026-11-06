"""Read the separately reserved provider manual, never corpus members."""
import argparse
import bz2
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time

import pypdf

from qualify_knbc import HERE, REPO, ROOT, PREVIOUS, digest, git, require, save

PLAN = HERE/'manual-plan-v1.json'
MEMBER = 'KNBC_v1.0_090925_utf8/manual.pdf'


def freeze():
    inventory = json.loads((ROOT/'member-inventory.json').read_bytes())
    matches = [r for r in inventory if r['name'] == MEMBER]
    require(len(matches) == 1 and matches[0]['kind'] == 'file' and matches[0]['bytes'] == 770764, 'manual_metadata')
    save(PLAN, dict(kind='documentation_exposure_reservation', version=1, issue=35,
        archive_sha256=digest((PREVIOUS/'archive.quarantine.tar.bz2').read_bytes()),
        inventory_sha256=digest((ROOT/'member-inventory.json').read_bytes()),
        qualification_commit='c62444e191ec7e9057a8fd19375b2610900b0438',
        manual_member=MEMBER, manual_bytes=770764, max_pages=100, max_page_chars=50000,
        max_total_chars=1000000, seconds=120, python=platform.python_version(), pypdf=pypdf.__version__,
        pypdf_init_sha256=digest(Path(pypdf.__file__).read_bytes()),
        script_sha256=digest(Path(__file__).read_bytes()),
        document_exposure='The complete manual, including all examples, is documentation exposure; exclude matching corpus material from any later independent reservation.',
        corpus_member_semantic_decodes=0, network_requests=0, dependencies_installed=0,
        gold_admission=False, training_admission=False, final_test=False))
    return dict(status='complete', manual_plan_sha256=digest(PLAN.read_bytes()))


def read(commit):
    plan = json.loads(PLAN.read_bytes())
    require(PLAN.read_bytes() == git('show',commit+':'+PLAN.relative_to(REPO).as_posix()), 'manual_plan_not_committed')
    require(digest(Path(__file__).read_bytes()) == plan['script_sha256']
            == digest(git('show',commit+':'+Path(__file__).relative_to(REPO).as_posix())), 'manual_script_changed')
    require(platform.python_version() == plan['python'] and pypdf.__version__ == plan['pypdf']
            and digest(Path(pypdf.__file__).read_bytes()) == plan['pypdf_init_sha256'], 'manual_tool_changed')
    require(digest((ROOT/'member-inventory.json').read_bytes()) == plan['inventory_sha256'], 'manual_inventory_changed')
    raw = (PREVIOUS/'archive.quarantine.tar.bz2').read_bytes()
    require(digest(raw) == plan['archive_sha256'], 'manual_archive_changed')
    dec = bz2.BZ2Decompressor()
    expanded = dec.decompress(raw,max_length=128*1024*1024+1)
    require(len(expanded)<=128*1024*1024 and dec.eof and not dec.unused_data, 'manual_archive_bound')
    with tarfile.open(fileobj=io.BytesIO(expanded),mode='r:') as archive:
        member = archive.getmember(MEMBER)
        require(member.isfile() and member.size == plan['manual_bytes'], 'manual_member')
        with archive.extractfile(member) as source:
            body = source.read(plan['manual_bytes']+1)
    require(len(body) == plan['manual_bytes'] and body.startswith(b'%PDF-'), 'manual_bytes')
    with (ROOT/'manual.pdf').open('xb') as output:
        output.write(body)
    reader = pypdf.PdfReader(io.BytesIO(body),strict=True)
    require(not reader.is_encrypted and 0 < len(reader.pages) <= plan['max_pages'], 'manual_pages')
    pages=[]
    for page in reader.pages:
        text=page.extract_text()
        require(len(text)<=plan['max_page_chars'] and sum(len(t) for t in pages)+len(text)<=plan['max_total_chars'], 'manual_text_bound')
        pages.append(text)
    save(ROOT/'manual-pages.private.json',pages)
    result=dict(status='complete',manual_sha256=digest(body),pages=len(pages),text_characters=sum(map(len,pages)),
        text_sha256=digest((ROOT/'manual-pages.private.json').read_bytes()),plan_sha256=digest(PLAN.read_bytes()),
        plan_commit=commit,pypdf=pypdf.__version__,python=platform.python_version(),
        corpus_member_semantic_decodes=0,visual_layout_verified=False,documentation_examples_exposed=True)
    save(ROOT/'manual-evidence.json',result)
    return result


def run(commit):
    save(ROOT/'manual-reservation.json',dict(owner_pid=os.getpid(),commit=commit,seconds=120))
    started=time.monotonic()
    with (ROOT/'manual.log').open('xb') as log:
        child=subprocess.Popen([sys.executable,'-B',str(Path(__file__)),'read','--commit',commit],
            stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        result=dict(status='failed',child_pid=child.pid)
        try:
            result['exit_code']=child.wait(timeout=120)
            result['status']='complete' if child.returncode==0 else 'failed'
        except subprocess.TimeoutExpired:
            result['status']='timed_out'
            child.kill()
            result['exit_code']=child.wait(timeout=30)
    result['elapsed_seconds']=round(time.monotonic()-started,3)
    save(ROOT/'manual-terminal.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('stage',choices=('freeze','read','run')); parser.add_argument('--commit',default='')
    args=parser.parse_args()
    try:
        result=freeze() if args.stage=='freeze' else read(args.commit) if args.stage=='read' else run(args.commit)
        print(json.dumps(result),flush=True)
        raise SystemExit(0 if result['status']=='complete' else 1)
    except Exception as error:
        print(json.dumps(dict(status='failed',error_type=type(error).__name__)),flush=True)
        raise SystemExit(1)
