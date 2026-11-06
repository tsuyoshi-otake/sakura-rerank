"""Frozen synthetic native-function/tensor/CPU-model parity; no corpus or Gold."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import time

from sakura_rerank import current_tiny as current
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_worker import Adapter, _WindowsJob, execute_model, runtime_identity
from current_tiny_reference_adapter import reference_factory

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE_PATHS = (
    'crates/sakura-neural-worker/src/sakura_scorer.rs', 'crates/sakura-neural-worker/src/sakura_runtime.rs',
    'crates/sakura-neural-worker/src/protocol.rs', 'crates/sakura-core/src/conversion/evidence.rs',
    'crates/sakura-core/src/input_repair.rs', 'crates/sakura-engine/src/long_conversion.rs',
    'crates/sakura-engine/src/dispatch.rs', 'models/sakura-rerank-tiny-v1/model.onnx',
    'models/sakura-rerank-tiny-v1/research-manifest.json', 'LICENSE')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def command(*args):
    return subprocess.check_output(list(args), timeout=30).decode('utf-8').strip()


def native_item(source, marker):
    if source.count(marker) != 1:
        raise ValueError('native item identity changed')
    start = source.index(marker)
    depth = 0
    for i in range(source.index('{', start), len(source)):
        if source[i] == '{': depth += 1
        if source[i] == '}': depth -= 1
        if not depth:
            return source[start:i+1]
    raise ValueError('native item incomplete')


def source_identity(root):
    if command('git', '-C', str(root), 'rev-parse', 'HEAD') != current.HEAD or command('git', '-C', str(root), 'status', '--porcelain=v1'):
        raise ValueError('current product checkout is not the pinned clean HEAD')
    result = {p: {'sha256': sha(root/p), 'bytes': (root/p).stat().st_size} for p in SOURCE_PATHS}
    for i, name in ((0, 'scorer_source_sha256'), (1, 'runtime_source_sha256'), (3, 'selection_source_sha256')):
        if result[SOURCE_PATHS[i]]['sha256'] != current.FEATURES[name]:
            raise ValueError('pinned product implementation differs')
    if result[SOURCE_PATHS[7]] != {'sha256': current.MODEL_SHA256, 'bytes': current.MODEL_BYTES}:
        raise ValueError('current model pin differs')
    return result


def compiler_identity():
    profile = json.loads((REPO/'manifests/reference-probe-build-profile-v1.json').read_bytes())
    rustc = Path(command('rustup', 'which', '--toolchain', profile['rust_toolchain'], 'rustc'))
    if sha(rustc) != profile['tools']['rustc']['sha256']:
        raise ValueError('compiler differs from existing verified profile')
    msvc = Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC')/profile['msvc_toolset']
    sdk = Path('C:/Program Files (x86)/Windows Kits/10/Lib')/profile['windows_sdk']
    linker = msvc/'bin/Hostx64/x64/link.exe'
    if sha(linker) != profile['linker_sha256']:
        raise ValueError('linker differs from existing verified profile')
    roots = [msvc/'lib/x64', sdk/'um/x64', sdk/'ucrt/x64']
    sysroot = Path(command(str(rustc), '--print', 'sysroot'))
    libraries = {f'{i}/{p.name}': sha(p) for i, root in enumerate(roots) for p in sorted(root.glob('*.lib'))}
    standard = {p.name: sha(p) for p in sorted((sysroot/'lib/rustlib/x86_64-pc-windows-msvc/lib').glob('*.rlib'))}
    if not libraries or not standard:
        raise ValueError('compiler libraries missing')
    return {'toolchain': profile['rust_toolchain'], 'rustc': str(rustc), 'rustc_sha256': sha(rustc),
            'version': command(str(rustc), '--version'), 'linker': str(linker), 'linker_sha256': sha(linker),
            'library_roots': [str(p) for p in roots], 'libraries_sha256': hashlib.sha256(canonical_json_bytes(libraries)).hexdigest(),
            'stdlib_sha256': hashlib.sha256(canonical_json_bytes(standard)).hexdigest()}


def vectors():
    rng = random.Random(20261106)
    surfaces = ['A', '東', '😀', 'か\u3099', 'A'*31, '東'*32, '東'*33, '😀'*64, 'A'*256, '\U0010ffff']
    costs = [-(2**63), -(2**31)-1, -(2**31), -1, 0, 1, 2**31-1, 2**31, 2**63-1]
    projection = [[{'surface': rng.choice(surfaces), 'local_cost': rng.choice(costs)} for _ in range(2+i%5)] for i in range(64)]
    projection += [[], projection[0][:1], projection[4]+projection[0][:1]]
    choices = []
    tags = sorted(current.EVIDENCE_TAGS)
    score_patterns = [[0., 0.], [10., -3.], [-3., 10.], [float('nan'), 1.], [1., float('inf')]]
    for a in tags:
        choices.append(([1.], [a]))
        for b in tags:
            choices.extend((scores, [a, b]) for scores in score_patterns)
    for i in range(1024):
        size = 2+i%5
        choices.append(([float(rng.randrange(-10, 11)) for _ in range(size)], [rng.choice(tags) for _ in range(size)]))
    return projection, choices


def projection_wire(rows):
    raw = bytearray(struct.pack('<BI', 0, len(rows)))
    for row in rows:
        raw += struct.pack('<B', len(row))
        for item in row:
            text = item['surface'].encode()
            raw += struct.pack('<qI', item['local_cost'], len(text))+text
    return bytes(raw)


def choice_wire(rows):
    raw = bytearray(struct.pack('<BI', 1, len(rows)))
    for scores, tags in rows:
        raw += struct.pack('<B', len(scores))
        for score, tag in zip(scores, tags, strict=True): raw += struct.pack('<fB', score, tag)
    return bytes(raw)


def harness(root):
    texts = {p: (root/p).read_text(encoding='utf-8') for p in SOURCE_PATHS[:7]}
    protocol, runtime, evidence = texts[SOURCE_PATHS[2]], texts[SOURCE_PATHS[1]], texts[SOURCE_PATHS[3]]
    mapping = {'CANDIDATE': native_item(protocol, 'pub(crate) struct Candidate'),
        'REQUEST': native_item(protocol, 'pub(crate) struct Request'),
        'CONSTANTS': '\n'.join(line for line in runtime.splitlines() if line.startswith('pub const ')),
        'INPUTS': native_item(runtime, 'pub struct Inputs'), 'SCORER_PATH': json.dumps((root/SOURCE_PATHS[0]).as_posix()),
        'REPAIR_KIND': native_item(texts[SOURCE_PATHS[4]], 'pub enum RepairKind'),
        'REPAIR_TIER': native_item(evidence, 'pub enum RepairTier'),
        'EVIDENCE': native_item(evidence, 'pub enum CandidateEvidence {'),
        'NEURAL_GROUP': native_item(evidence, 'pub const fn neural_group'),
        'FINGERPRINT_TAG': native_item(evidence, 'pub const fn fingerprint_tag'),
        'CHOICE': native_item(evidence, 'pub fn neural_listwise_choice')}
    text = (HERE/'native_harness.rs.in').read_text()
    for name, value in mapping.items(): text = text.replace('@@'+name+'@@', value)
    if '@@' in text: raise ValueError('harness substitution incomplete')
    return text.encode()


def implementation():
    return {p.name: sha(p) for p in (Path(__file__), HERE/'native_harness.rs.in', HERE/'current_tiny_reference_adapter.py')}


def prepare(root, work):
    if (Path.home()/'tmp').resolve() not in work.parents or work.exists():
        raise ValueError('fresh task-owned work directory required')
    source = source_identity(root)
    compiler = compiler_identity()
    rows, choices = vectors()
    plan = {'kind': 'current_tiny_synthetic_parity_plan', 'version': 1, 'source_head': current.HEAD,
        'sources': source, 'runtime': runtime_identity(), 'implementation': implementation(), 'compiler': compiler,
        'harness_sha256': hashlib.sha256(harness(root)).hexdigest(),
        'projection_wire_sha256': hashlib.sha256(projection_wire(rows)).hexdigest(),
        'choice_wire_sha256': hashlib.sha256(choice_wire(choices)).hexdigest(),
        'projection_count': len(rows), 'choice_count': len(choices), 'valid_projection_count': 64,
        'cpu_model_requests': 128, 'limits': {'startup_seconds': 20., 'request_seconds': .4,
        'model_seconds': 60., 'shutdown_seconds': 2.}, 'corpus_reads': 0, 'real_test': False,
        'native_ort_execution': False, 'production_edits': False}
    work.mkdir()
    save(work/'plan.json', plan)
    return {'status': 'prepared', 'plan_sha256': sha(work/'plan.json')}


def owned_command(args, work, label, payload=None, env=None):
    process = job = None
    try:
        process = subprocess.Popen(args, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        job = _WindowsJob(process.pid)
        output, error = process.communicate(payload, timeout=120)
        receipt = {'pid': process.pid, 'exit_code': process.returncode, 'job': job.close(2.), 'exited': process.poll() is not None}
        (work/(label+'.stderr')).write_bytes(error)
        save(work/(label+'-terminal.json'), receipt)
        if process.returncode: raise ValueError('native diagnostic command failed')
        return output, receipt
    finally:
        if job is not None: job.close(2.)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def decode_feeds(raw, cases):
    import numpy as np
    layout = [('context_ids', (1, 64), '<i8'), ('context_lengths', (1,), '<i8'),
        ('reading_ids', (1, 32), '<i8'), ('reading_lengths', (1,), '<i8'),
        ('candidate_ids', (1, 6, 32), '<i8'), ('candidate_lengths', (1, 6), '<i8'),
        ('features', (1, 6, 6), '<f4'), ('candidate_mask', (1, 6), '?')]
    offset, elements, rejected, feeds = 0, 0, 0, []
    for case in cases:
        accepted = raw[offset]; offset += 1
        if not accepted:
            try: current.protocol_feed(case)
            except current.ProductContractError: rejected += 1
            else: raise ValueError('native rejection differs')
            continue
        expected = current.protocol_feed(case)
        feed = {}
        for name, shape, dtype in layout:
            size = int(np.prod(shape))*np.dtype(dtype).itemsize
            array = np.frombuffer(raw[offset:offset+size], dtype=dtype).reshape(shape)
            if array.tobytes() != expected[name].tobytes(): raise ValueError('native tensor bytes differ')
            feed[name] = array.tolist(); offset += size; elements += array.size
        feeds.append(feed)
    if offset != len(raw) or len(feeds) != 64 or rejected != 3: raise ValueError('native frame denominator differs')
    return feeds, elements, rejected


def run(root, work, expected):
    if sha(work/'plan.json') != expected: raise ValueError('plan hash differs')
    plan = json.loads((work/'plan.json').read_bytes())
    if (plan['sources'] != source_identity(root) or plan['compiler'] != compiler_identity()
            or plan['implementation'] != implementation() or plan['runtime'] != runtime_identity()):
        raise ValueError('frozen implementation differs')
    attempt = work/'attempt-01'; attempt.mkdir()
    save(attempt/'started.json', {'plan_sha256': expected, 'owner_pid': os.getpid()})
    result = {'status': 'failed', 'plan_sha256': expected}
    try:
        rows, choices = vectors(); source = harness(root)
        if (hashlib.sha256(source).hexdigest() != plan['harness_sha256']
                or hashlib.sha256(projection_wire(rows)).hexdigest() != plan['projection_wire_sha256']
                or hashlib.sha256(choice_wire(choices)).hexdigest() != plan['choice_wire_sha256']):
            raise ValueError('synthetic recipe differs')
        source_path, binary = attempt/'native.rs', attempt/'native.exe'
        source_path.write_bytes(source)
        compiler = plan['compiler']
        env = {**os.environ, 'LIB': ';'.join(compiler['library_roots']), 'TEMP': str(work), 'TMP': str(work)}
        _, compiled = owned_command([compiler['rustc'], '--edition=2021', '-A', 'dead_code', '-Copt-level=1',
            '-Clinker='+compiler['linker'], '-Clink-arg=/Brepro', str(source_path), '-o', str(binary)], attempt, 'compile', env=env)
        raw, projected = owned_command([str(binary)], attempt, 'projection', projection_wire(rows), env)
        feeds, elements, rejected = decode_feeds(raw, rows)
        selected, chosen = owned_command([str(binary)], attempt, 'choice', choice_wire(choices), env)
        expected_choices = bytes(255 if (v := current.protected_choice(scores, tags)) is None else v for scores, tags in choices)
        if selected != expected_choices: raise ValueError('native protected choices differ')
        artifacts = {'weights': (root/SOURCE_PATHS[7]).read_bytes(), 'tokenizer': canonical_json_bytes(current.TOKENIZER),
                     'features': canonical_json_bytes(current.FEATURES), 'gate': b'{}'}
        requests = [{'reading': 'synthetic-unused', 'left_context': 'synthetic-unused', 'candidates': case} for case in rows[:64]]
        python = execute_model(requests, artifacts, Adapter(current.current_factory, current.validate_current),
            6, plan['limits'], deadline=time.monotonic()+90)
        native = execute_model([{'feed': value} for value in feeds], artifacts, Adapter(reference_factory, current.validate_current),
            6, plan['limits'], deadline=time.monotonic()+90)
        if not python['complete'] or not native['complete'] or python['scores'] != native['scores']:
            raise ValueError('CPU model score parity failed')
        result.update(status='passed', projection_cases=len(rows), rejected_candidate_counts=rejected,
            tensor_scalar_elements=elements, tensor_byte_equal=True, protected_choices=len(choices),
            native_choice_equal=True, actual_model_requests=128, output_scores_compared=64*6,
            cpu_score_equal=True, model_sha256=current.MODEL_SHA256, binary_sha256=sha(binary),
            processes=[compiled, projected, chosen, python['process'], native['process']],
            native_ort_execution=False, session_capture_verified=False, final_test=False,
            accuracy_claim=False, production_benchmark=False, release_eligible=False)
    finally:
        save(attempt/'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=('prepare', 'run'))
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--work-root', type=Path, required=True)
    p.add_argument('--plan-sha256')
    a = p.parse_args()
    root, work = a.source_root.resolve(strict=True), a.work_root.resolve()
    value = prepare(root, work) if a.stage == 'prepare' else run(root, work, a.plan_sha256)
    print(json.dumps({k: v for k, v in value.items() if k in {'status', 'plan_sha256', 'projection_cases', 'protected_choices', 'actual_model_requests'}}, sort_keys=True))
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception:
        print(json.dumps({'status': 'failed', 'automatic_retry': False}))
        raise SystemExit(1) from None
