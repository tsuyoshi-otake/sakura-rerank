"""Bounded documentation-only KNBC acquisition; never admits a dataset."""
import argparse
import bz2
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import tarfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ROOT = REPO / 'data/generated/issue-35-knbc-qualification-v1/attempt-01'
PLAN = HERE / 'plan-v1.json'
LIMITS = dict(compressed_bytes=16*1024*1024, expanded_bytes=128*1024*1024,
              members=20000, member_bytes=4*1024*1024, name_chars=512,
              document_bytes=1024*1024, document_total_bytes=4*1024*1024,
              documents=16, document_depth=3, socket_seconds=30,
              transfer_seconds=120, stage_seconds=300, retries=0, concurrency=1)
DOCUMENTS = frozenset(('readme', 'readme.txt', 'readme.md', 'readme.ja', 'readme.en',
                      'readme-ja.txt', 'readme_ja.txt', 'copying', 'copying.txt',
                      'license', 'license.txt', 'license.md', 'licence', 'licence.txt'))


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def git(*args):
    return subprocess.run(['git', *args], cwd=REPO, check=True, capture_output=True, timeout=30).stdout


def normalized_name(name):
    require(len(name) <= LIMITS['name_chars'] and not any(ord(c) < 32 for c in name), 'member_name')
    require(not name.startswith('/') and '\\' not in name and ':' not in name, 'member_path')
    while name.startswith('./'):
        name = name[2:]
    parts = name.rstrip('/').split('/')
    require(all(p and p not in ('.', '..') for p in parts), 'member_path')
    return '/'.join(parts)


def inspect_archive(raw, limits=None):
    """Decode archive headers and allowlisted documentation, never corpus bodies."""
    bounds = LIMITS if limits is None else {**LIMITS, **limits}
    require(0 < len(raw) <= bounds['compressed_bytes'], 'compressed_bound')
    decompressor = bz2.BZ2Decompressor()
    expanded = decompressor.decompress(raw, max_length=bounds['expanded_bytes']+1)
    require(len(expanded) <= bounds['expanded_bytes'], 'expanded_bound')
    require(decompressor.eof and not decompressor.unused_data, 'compressed_stream')
    inventory, documents, seen = [], [], set()
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for member in archive:
            require(len(inventory) < bounds['members'], 'member_count')
            name = normalized_name(member.name)
            key = name.casefold()
            require(key not in seen, 'duplicate_path')
            seen.add(key)
            require(member.isfile() or member.isdir(), 'member_type')
            require(not member.issparse(), 'sparse_member')
            require(0 <= member.size <= bounds['member_bytes'], 'member_size')
            require(not member.isdir() or member.size == 0, 'directory_size')
            path = PurePosixPath(name)
            selected = (member.isfile() and len(path.parts) <= bounds['document_depth']
                        and path.name.lower() in DOCUMENTS)
            inventory.append(dict(name=name, archive_name=member.name,
                                  kind='file' if member.isfile() else 'directory',
                                  bytes=member.size, documentation_selected=selected))
            if selected:
                require(member.size <= bounds['document_bytes'], 'document_size')
                require(len(documents) < bounds['documents'], 'document_count')
                require(sum(len(d['raw']) for d in documents)+member.size <= bounds['document_total_bytes'], 'document_total')
                with archive.extractfile(member) as stream:
                    body = stream.read(bounds['document_bytes']+1)
                require(len(body) == member.size, 'document_read')
                documents.append(dict(name=name, archive_name=member.name, raw=body))
    require(inventory, 'empty_archive')
    return inventory, documents, len(expanded)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def freeze():
    header = json.loads((ROOT/'headers.json').read_bytes())
    require(header['status'] == 'complete' and header['method'] == 'HEAD', 'header_proof')
    code = [HERE/'qualify_knbc.py', HERE/'run_owned.py', HERE/'probe_headers.py',
            REPO/'tests/test_knbc_documentation.py']
    plan = dict(kind='quarantine_documentation_qualification', version=1, issue=35, parent_issue=1,
                parent_commit=git('rev-parse', 'HEAD').decode().strip(), python=platform.python_version(),
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                source_url=header['url'], expected_bytes=header['bytes'], etag=header['etag'],
                last_modified=header['last_modified'], content_type=header['content_type'],
                official_cryptographic_digest=None, official_hash_status='not_found_in_inspected_provider_metadata',
                header_sha256=digest((ROOT/'headers.json').read_bytes()), limits=LIMITS,
                document_basenames=sorted(DOCUMENTS), redirects=False,
                code={p.relative_to(REPO).as_posix():digest(p.read_bytes()) for p in code},
                corpus_semantic_decode=False, corpus_member_extraction=False,
                documentation_exposure='All selected documents, including any examples, are exposed documentation. A later reservation must exclude matching corpus material.',
                new_fits=0, model_inferences=0, native_requests=0, original_labels_changed=0,
                training_admission=False, gold_admission=False, calibration=False, final_test=False,
                safety_limit=0.0025, gold_point_minimum=0.995, gold_wilson95_lower_minimum=0.990,
                gold_final_valid_minimum=3000,
                expected_effect='Resolve source license and annotation scope before reserving any research sample; no accuracy gain assumed.',
                expected_cost='One <=16MiB download, <=128MiB in-memory decompression, <=16 documentation files, no corpus decoding or model execution.')
    save(PLAN, plan)
    return dict(status='complete', plan_sha256=digest(PLAN.read_bytes()))


def authenticate(commit):
    require(len(commit) == 40 and all(c in '0123456789abcdef' for c in commit), 'commit_identity')
    raw = PLAN.read_bytes()
    require(raw == git('show', commit+':'+PLAN.relative_to(REPO).as_posix()), 'plan_not_committed')
    plan = json.loads(raw)
    require(plan['limits'] == LIMITS and plan['document_basenames'] == sorted(DOCUMENTS), 'plan_contract')
    require(digest((ROOT/'headers.json').read_bytes()) == plan['header_sha256'], 'headers_changed')
    for name, expected in plan['code'].items():
        require(digest((REPO/name).read_bytes()) == expected, 'code_changed')
        require(digest(git('show', commit+':'+name)) == expected, 'code_not_committed')
    return plan


def acquire(commit):
    plan = authenticate(commit)
    save(ROOT/'acquisition-reservation.json', dict(commit=commit, plan_sha256=digest(PLAN.read_bytes()),
         owner_pid=os.getpid(), time_utc=datetime.now(timezone.utc).isoformat(), corpus_semantic_decode=False))
    request = urllib.request.Request(plan['source_url'], headers={
        'User-Agent':'Sakura-Rerank-source-qualification/1', 'Accept-Encoding':'identity',
        'If-Match':plan['etag'], 'If-Unmodified-Since':plan['last_modified']})
    started = time.monotonic()
    opener = urllib.request.build_opener(NoRedirect())
    archive_path = ROOT/'archive.quarantine.tar.bz2'
    with opener.open(request, timeout=LIMITS['socket_seconds']) as response:
        require(response.status == 200 and response.geturl() == plan['source_url'], 'http_response')
        require(response.headers.get('Content-Length') == str(plan['expected_bytes'])
                and response.headers.get('ETag') == plan['etag']
                and response.headers.get('Last-Modified') == plan['last_modified']
                and response.headers.get_content_type() == plan['content_type']
                and response.headers.get('Content-Encoding', 'identity') == 'identity', 'http_identity')
        total = 0
        with archive_path.open('xb') as output:
            while True:
                require(time.monotonic()-started < LIMITS['transfer_seconds'], 'transfer_time')
                chunk = response.read(min(65536, plan['expected_bytes']+1-total))
                if not chunk:
                    break
                total += len(chunk)
                require(total <= plan['expected_bytes'] <= LIMITS['compressed_bytes'], 'transfer_bytes')
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        require(total == plan['expected_bytes'], 'transfer_incomplete')
    raw = archive_path.read_bytes()
    inventory, documents, expanded = inspect_archive(raw)
    save(ROOT/'member-inventory.json', inventory)
    exposure = []
    for i, document in enumerate(documents):
        body = document['raw']
        with (ROOT/f'document-{i:02d}.raw').open('xb') as output:
            output.write(body)
        try:
            body.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            encoding = 'unresolved_not_semantically_decoded'
        exposure.append(dict(name=document['name'], bytes=len(body), sha256=digest(body),
                             local_name=f'document-{i:02d}.raw', encoding=encoding,
                             includes_possible_corpus_examples=True))
    save(ROOT/'documentation-exposure.json', exposure)
    result = dict(status='complete', fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                  source_url=plan['source_url'], local_sha256=digest(raw), compressed_bytes=len(raw),
                  expanded_bytes=expanded, members=len(inventory), files=sum(r['kind']=='file' for r in inventory),
                  documentation_files=len(documents), documentation_bytes=sum(d['bytes'] for d in exposure),
                  corpus_member_semantic_decodes=0, corpus_member_files_extracted=0,
                  official_cryptographic_digest=None, trusted_dataset_published=False,
                  acquisition_level='official_https_quarantine_only', plan_commit=commit,
                  plan_sha256=digest(PLAN.read_bytes()), python=platform.python_version(),
                  artifacts={p.name:digest(p.read_bytes()) for p in [ROOT/'member-inventory.json', ROOT/'documentation-exposure.json']})
    save(ROOT/'acquisition.json', result)
    return result


def verify(commit):
    authenticate(commit)
    result = json.loads((ROOT/'acquisition.json').read_bytes())
    archive_path = ROOT/'archive.quarantine.tar.bz2'
    raw = archive_path.read_bytes()
    require(digest(raw) == result['local_sha256'], 'archive_changed')
    inventory, documents, expanded = inspect_archive(raw)
    require(inventory == json.loads((ROOT/'member-inventory.json').read_bytes()), 'inventory_changed')
    other = subprocess.run(['tar', '-tf', str(archive_path)], capture_output=True, check=True, timeout=60)
    paths = [normalized_name(n) for n in other.stdout.decode('utf-8').splitlines()]
    require(paths == [r['name'] for r in inventory], 'independent_inventory')
    for i, document in enumerate(documents):
        other = subprocess.run(['tar', '-xOf', str(archive_path), '--', document['archive_name']],
                               capture_output=True, check=True, timeout=60)
        require(other.stdout == document['raw'] == (ROOT/f'document-{i:02d}.raw').read_bytes(), 'independent_document')
    for name, sha in result['artifacts'].items():
        require(digest((ROOT/name).read_bytes()) == sha, 'artifact_changed')
    checked = dict(status='complete', independently_reconciled_members=len(paths),
                   independently_reconciled_documents=len(documents), expanded_bytes=expanded,
                   tar_version=subprocess.run(['tar','--version'], capture_output=True, check=True, timeout=10).stdout.decode().strip(),
                   corpus_member_semantic_decodes=0)
    save(ROOT/'verification.json', checked)
    return checked


def checks(targeted):
    import ast
    import unittest
    code = [HERE/'qualify_knbc.py', HERE/'run_owned.py', HERE/'probe_headers.py', REPO/'tests/test_knbc_documentation.py']
    for path in code:
        ast.parse(path.read_text(encoding='utf-8'))
    suite = unittest.defaultTestLoader.discover(str(REPO/'tests'), pattern='test_knbc_documentation.py' if targeted else 'test*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    value = dict(tests=result.testsRun, successful=result.wasSuccessful(), failures=len(result.failures),
                 errors=len(result.errors), skipped=len(result.skipped), static_files=len(code))
    save(ROOT/('targeted-tests.json' if targeted else 'full-tests.json'), value)
    require(result.wasSuccessful() and not result.skipped and result.testsRun >= (10 if targeted else 951), 'tests_failed')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'acquire', 'verify', 'targeted', 'tests'))
    parser.add_argument('--commit', default='')
    args = parser.parse_args()
    try:
        value = (freeze() if args.stage == 'freeze' else acquire(args.commit) if args.stage == 'acquire'
                 else verify(args.commit) if args.stage == 'verify' else checks(args.stage == 'targeted'))
        print(json.dumps(value), flush=True)
    except Exception as error:
        failure = dict(status='failed', stage=args.stage, error_type=type(error).__name__,
                       error_code=str(error) if isinstance(error, ValueError) and str(error).isidentifier() else None)
        save(ROOT/(args.stage+'-failure.json'), failure)
        print(json.dumps(failure), flush=True)
        raise SystemExit(1)
