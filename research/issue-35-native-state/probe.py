"""Build/run instrumented pinned native dispatcher privately; no production edits.

The unchanged workspace lock is used offline. Instrumentation observes the actual
selection callback and injects declared synthetic worker responses, not model or
Gold evidence. A new immutable plan is required after any instrumentation change.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

from sakura_rerank.current_tiny import HEAD
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_worker import _WindowsJob

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NATIVE = 'crates/sakura-engine/src/'
TEST = 'dispatch::tests::research_native_state::research_native_snapshot_probe'
FILES = ('probe.py', 'dispatch_probe.rs.in', 'long_conversion_probe.rs.in')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def command(*args):
    return subprocess.check_output(list(args), timeout=60, stderr=subprocess.PIPE).decode().strip()


def compiler():
    # Reuse the existing pinned compiler/library contract, not a second profile.
    parent = HERE.parent/'issue-35-current-tiny-parity'
    sys.path.insert(0, str(parent))
    try:
        spec = importlib.util.spec_from_file_location('native_state_parity_contract', parent/'parity.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.compiler_identity()
    finally:
        sys.path.pop(0)
    cargo = Path(command('rustup', 'which', '--toolchain', result['toolchain'], 'cargo'))
    profile = json.loads((REPO/'manifests/reference-probe-build-profile-v1.json').read_bytes())
    if sha(cargo) != profile['tools']['cargo']['sha256']:
        raise ValueError('cargo identity differs')
    return dict(result, cargo=str(cargo), cargo_sha256=sha(cargo))


def replace_once(raw, before, after):
    if raw.count(before) != 1:
        raise ValueError('native instrumentation boundary changed')
    return raw.replace(before, after)


def instrument(source):
    path = source/NATIVE
    changed = {}
    dispatch = (path/'dispatch.rs').read_text(encoding='utf-8')
    marker = '                let (visible_selected, raw_selected) = match project_conversion_candidates('
    insert = '''                #[cfg(test)]
                tests::research_native_state::capture(long_conversion_owner, session_id,
                    session, candidates, direct_limit,
                    if preserve_exact_initial || preferred >= direct_limit { 0 } else { preferred }, selected);
'''
    changed['dispatch.rs'] = replace_once(dispatch, marker, insert+marker).encode()
    tests = (path/'dispatch_tests.rs').read_text(encoding='utf-8')
    changed['dispatch_tests.rs'] = (tests+'\n#[path = "research_native_state.rs"]\npub(super) mod research_native_state;\n').encode()
    long = (path/'long_conversion.rs').read_text(encoding='utf-8')
    marker = '        let expected_key = RequestKey {'
    long = replace_once(long, marker, '        #[cfg(test)] research_state::note_call();\n'+marker)
    changed['long_conversion.rs'] = (long+'\n'+(HERE/'long_conversion_probe.rs.in').read_text()).encode()
    changed['research_native_state.rs'] = (HERE/'dispatch_probe.rs.in').read_bytes()
    for name, raw in changed.items():
        (path/name).write_bytes(raw)
    return {NATIVE+name:hashlib.sha256(raw).hexdigest() for name, raw in changed.items()}


def prepare(source, work):
    if (Path.home()/'tmp').resolve() not in work.parents or work.exists():
        raise ValueError('fresh private task directory required')
    if command('git','-C',str(source),'rev-parse','HEAD') != HEAD or command('git','-C',str(source),'status','--porcelain=v1'):
        raise ValueError('pinned clean source required')
    build = compiler()
    work.mkdir()
    packed = work/'source.tar'
    command('git','-C',str(source),'archive','--format=tar','--output='+str(packed),HEAD,
            '--','Cargo.toml','Cargo.lock','.cargo','crates','tools','data',
            'corpus/session-replay/phase3-editing.snap')
    workspace=work/'source'
    workspace.mkdir()
    with tarfile.open(packed) as stream:
        members=stream.getmembers()
        if sum(m.size for m in members)>128*1024*1024 or any(not(m.isfile() or m.isdir()) for m in members):
            raise ValueError('archive outside bounded source contract')
        stream.extractall(workspace,filter='data')
    original={p.relative_to(workspace).as_posix():sha(p) for p in workspace.rglob('*') if p.is_file()}
    changed=instrument(workspace)
    plan={'kind':'native_state_probe_plan','version':1,'source_head':HEAD,
        'source_tree':command('git','-C',str(source),'rev-parse','HEAD^{tree}'),
        'source_archive_sha256':sha(packed),'original_source_files':original,'instrumented_files':changed,
        'implementation':{name:sha(HERE/name) for name in FILES},'compiler':build,
        'lock_sha256':sha(workspace/'Cargo.lock'),'test':TEST,'build_jobs':1,
        'build_timeout_seconds':600,'run_timeout_seconds':120,'synthetic_response_injection':True,
        'real_test':False,'model_inference':False,'gold_evidence':False,'production_edits':False}
    save(work/'plan.json',plan)
    print(json.dumps({'status':'prepared','source_files':len(original),'plan_sha256':sha(work/'plan.json')}))


def owned(args, cwd, work, label, env, timeout):
    process=job=None
    receipt={'status':'failed','label':label,'timeout_seconds':timeout}
    started=time.monotonic()
    try:
        with (work/(label+'.stdout')).open('xb') as out, (work/(label+'.stderr')).open('xb') as err:
            process=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            receipt['pid']=process.pid
            job=_WindowsJob(process.pid)
            process.wait(timeout=timeout)
            receipt.update(exit_code=process.returncode,status='passed' if process.returncode==0 else 'failed')
    except subprocess.TimeoutExpired:
        receipt['status']='timeout'
    finally:
        if job is not None:
            receipt['job']=job.close(2.)
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait(timeout=10)
            receipt['exited']=process.poll() is not None
        receipt['elapsed_seconds']=round(time.monotonic()-started,3)
        save(work/(label+'-terminal.json'),receipt)
    if receipt['status']!='passed':
        raise ValueError('native command did not complete successfully')
    return receipt


def run(work, plan_sha):
    if sha(work/'plan.json')!=plan_sha:
        raise ValueError('plan differs')
    plan=json.loads((work/'plan.json').read_bytes())
    if {name:sha(HERE/name) for name in FILES}!=plan['implementation']:
        raise ValueError('probe implementation changed')
    if compiler()!=plan['compiler']:
        raise ValueError('compiler environment changed')
    source=work/'source'
    expected=dict(plan['original_source_files'],**plan['instrumented_files'])
    actual={p.relative_to(source).as_posix():sha(p) for p in source.rglob('*') if p.is_file()}
    if actual!=expected:
        raise ValueError('private instrumented source differs')
    save(work/'started.json',{'owner_pid':os.getpid(),'plan_sha256':plan_sha})
    result={'kind':'native_state_probe_result','version':1,'plan_sha256':plan_sha,'status':'failed','processes':[]}
    try:
        (work/'temp').mkdir()
        c=plan['compiler']
        env=dict(os.environ,LIB=';'.join(c['library_roots']),RUSTC=c['rustc'],RUSTUP_TOOLCHAIN=c['toolchain'],
            CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=c['linker'],CARGO_NET_OFFLINE='true',CARGO_INCREMENTAL='0',
            CARGO_TARGET_DIR=str(work/'target'),CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',
            TEMP=str(work/'temp'),TMP=str(work/'temp'))
        args=[c['cargo'],'test','-p','sakura-engine','--features','dev-fixtures','--lib','--no-run',
              '--offline','--locked','--jobs','1','--message-format=json']
        result['processes'].append(owned(args,source,work,'build',env,600))
        if sha(source/'Cargo.lock')!=plan['lock_sha256']:
            raise ValueError('source lock changed')
        messages=[json.loads(line) for line in (work/'build.stdout').read_text(encoding='utf-8').splitlines() if line.startswith('{')]
        binaries=[Path(v['executable']) for v in messages if v.get('reason')=='compiler-artifact' and v.get('executable')
                  and v.get('target',{}).get('name')=='sakura_engine' and v.get('profile',{}).get('test')]
        if len(binaries)!=1 or work not in binaries[0].resolve().parents:
            raise ValueError('native test binary ambiguous')
        result['binary_sha256']=sha(binaries[0])
        env['SAKURA_RESEARCH_NATIVE_OUTPUT']=str(work/'capture.jsonl')
        result['processes'].append(owned([str(binaries[0]),TEST,'--exact','--test-threads=1'],source,work,'native',env,120))
        raw=(work/'capture.jsonl').read_bytes()
        if len(raw)>2*1024*1024:
            raise ValueError('native capture exceeds bound')
        rows=[json.loads(line) for line in raw.splitlines()]
        if not rows or [v['fixture'] for v in rows]!=list(range(len(rows))):
            raise ValueError('native capture coverage differs')
        result.update(status='passed',capture_sha256=hashlib.sha256(raw).hexdigest(),fixture_count=len(rows),
            capture_count=sum(len(v['captures']) for v in rows),applied=sum(v['terminal']=='Applied' for v in rows),
            model_inference=False,production_edits=False,real_test=False,gold_evidence=False)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        result['error_type']=type(error).__name__
    finally:
        save(work/'result.json',result)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--plan-sha256')
    options=parser.parse_args()
    if options.stage=='prepare':
        prepare(options.source_root.resolve(),options.work_root.resolve())
    else:
        sys.exit(run(options.work_root.resolve(),options.plan_sha256))
