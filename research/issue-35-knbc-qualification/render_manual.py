"""Bounded visual fallback for the already reserved, legacy-encoded manual."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pymupdf

ROOT=Path('data/generated/issue-35-knbc-qualification-v1/attempt-02')
TEMP=Path('C:/Users/developer/tmp/issue35-source-qualification-20261106')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path,value):
    with path.open('xb') as stream:
        stream.write(json.dumps(value,ensure_ascii=True,sort_keys=True).encode()+b'\n')


def render():
    raw=(ROOT/'manual.pdf').read_bytes()
    assert len(raw)==770764 and sha(raw)=='e8b42f07b5aefe1a1b5a737feb2f8d8ce4aa8621e56b148ecb4fb387905fbc59'
    assert pymupdf.VersionBind=='1.26.6'
    document=pymupdf.open(stream=raw,filetype='pdf')
    assert len(document)==13 and not document.is_encrypted
    pages=[]; images=[]
    for i,page in enumerate(document):
        text=page.get_text()
        assert len(text)<=50000 and sum(len(s) for s in pages)+len(text)<=1000000
        pages.append(text)
        assert 0<page.rect.width<=900 and 0<page.rect.height<=1200
        image=page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).tobytes('png')
        path=TEMP/f'manual-{i+1:02d}.png'
        with path.open('xb') as stream: stream.write(image)
        images.append(dict(page=i+1,sha256=sha(image),bytes=len(image)))
    save(ROOT/'manual-readable-pages.private.json',pages)
    result=dict(status='complete',pages=len(pages),manual_sha256=sha(raw),pymupdf=pymupdf.VersionBind,
        text_sha256=sha((ROOT/'manual-readable-pages.private.json').read_bytes()),images=images,
        corpus_member_semantic_decodes=0,exposure='existing whole-manual documentation reservation')
    save(ROOT/'manual-render-evidence.json',result)


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='child':
        render()
    else:
        save(ROOT/'manual-render-reservation.json',dict(owner_pid=os.getpid(),script_sha256=sha(Path(__file__).read_bytes()),seconds=120,pages=13,corpus_member_semantic_decodes=0))
        with (ROOT/'manual-render.log').open('xb') as log:
            child=subprocess.Popen([sys.executable,'-B',__file__,'child'],stdout=log,stderr=subprocess.STDOUT)
            try: code=child.wait(timeout=120)
            except subprocess.TimeoutExpired: child.kill(); code=child.wait(timeout=30)
        result=dict(status='complete' if code==0 else 'failed',child_pid=child.pid,exit_code=code)
        save(ROOT/'manual-render-terminal.json',result)
        print(json.dumps(result))
        raise SystemExit(code)
