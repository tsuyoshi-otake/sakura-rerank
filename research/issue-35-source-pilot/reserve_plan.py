"""Bind provider metadata and sampling before downloading source text."""
import platform
import sys

from pilot35_common import ROOT, HERE, PLAN, read, save, sha


def run():
    probe = read(ROOT/'header-probe.json')
    if probe['status'] != 'complete' or probe['body_bytes_read'] or probe['not_attempted']:
        raise ValueError('pilot35_successful_header_probe_required')
    code = sorted(HERE.glob('*.py')) + [
        HERE.parent.parent/'src/sakura_rerank/data/tatoeba_source.py',
        HERE.parent.parent/'tests/test_tatoeba_source.py',
    ]
    plan = dict(kind='source_only_pilot_plan_v1', issues=[35, 32, 31], parent_issue=1,
        snapshot='tatoeba-jpn-weekly-20261031', seed=20261106,
        header_probe_sha256=sha(ROOT/'header-probe.json'),
        authority='Authorized autonomous source/data-quality research; no model or trusted-label admission.',
        source=dict(provider='Tatoeba', license='CC BY 2.0 FR for distributed exports; retain original attribution privately',
            documentation='https://tatoeba.org/ca/downloads',
            index='https://downloads.tatoeba.org/exports/per_language/jpn/',
            format_repository='https://github.com/Tatoeba/tatoeba2',
            inspected_commit='f2c80b81032630648f7896182174a9f5784ccde2',
            inspected_blobs={
                'docs/database/scripts/weekly_exports.sql':'44ca5b9164e8b74d2ac2f1b1ffa628fd06f3919a',
                'src/Model/Entity/FuriganaTrait.php':'795315612fc681555e05fef9f0fa60461c7cf8fa',
                'src/Model/Entity/Transcription.php':'edc197bcbc6431ffc5972599acfec80e3e52f0e9',
                'src/Model/Table/TranscriptionsTable.php':'637e31316f24541a20fd8fedbf3a3c0e6a59846d',
                'src/Model/Behavior/TranscriptableBehavior.php':'d0dc1932fa94a81ff380b5f7ed2e8b14c2396592',
                'docs/cron/export.sh':'a2dd67b19833f34f95bdaba98ea7e8683c3c48ff'},
            official_cryptographic_digest=None,
            digest_limit='No digest in inspected official index/headers; ETag is not a cryptographic digest. Provisional acquisition only.',
            provenance_limit='Editor is source provenance, not our independent A/B reviewer; export omits needsReview and transcription modification time.',
            license_membership='Require each selected transcription ID to occur in licensed detailed-sentences export.'),
        acquisition=dict(files=[dict(name=r['file'],url=r['final_url'],bytes=int(r['headers']['content-length']),
            etag=r['headers']['etag'],last_modified=r['headers']['last-modified']) for r in probe['requests']],
            request_timeout_seconds=30,total_timeout_seconds=180,minimum_request_interval_seconds=1,
            maximum_concurrency=1,automatic_retries=0,redirects=False,
            on_429_or_403='Stop entire acquisition; record Retry-After, keep failed reservation; no automatic retry.',
            decompressed_bytes_per_file=128*1024*1024,maximum_rows_per_file=500000,maximum_record_bytes=65536),
        selection=dict(domain='tatoeba-source-pilot-v1',strata={'named_editor':80,'no_editor':20},
            method='Take smallest canonical SHA256(seed,domain,sentence_id) within metadata-only strata.',
            selection_before_semantic_decode=True,insufficient_capacity='stop; do not replace stratum',
            replacement_allowed=False,binding_commit_before_semantic_decode=True),
        audit=dict(slots=100,source_and_annotation_only=True,exact_codepoints=True,
            guessed_readings=False,spelling_normalization=False,independent_human_reviews=0,
            outcomes='Each selected slot retains decode/markup/source-match/coverage status; no replacement.',
            hypotheses=['Named-editor provenance may provide source-exact whole ruby readings.',
                'Source-exact readings alone cannot establish intended IME output or Gold quality.'],
            denominator='Report all 100 and both metadata strata; these are deliberately stratified and not a corpus accuracy estimate.'),
        isolation=dict(previous_nodes=988073,maximum_nodes=1100000,
            method='Any proposed inputs require complete previous source/input history, all 100 source units, and every proposed span; forward and reverse closure must agree.',
            future_splits='Disjoint components for research, calibration and one-use final Test must be frozen before use. This exposed pilot is research only.',
            unselected_scope='Binary acquired and metadata scanned; no semantic decode. Future admission still needs exposure and source-lineage audit.'),
        forbidden=dict(fits=True,model_inference=True,native_candidate_execution=True,final_test_access=True,
            gold_certification=True,training_admission=True,calibration_admission=True,production_changes=True),
        unchanged=dict(adopted_accuracy_percent=90.72,safety_harm_fraction=0.0025,
            gold_point_minimum=0.995,gold_wilson_lower_minimum=0.99,final_holdout_valid_minimum=3000),
        environment=dict(python=sys.version,platform=platform.platform(),new_dependencies=0),
        code={p.as_posix():sha(p) for p in code})
    save(PLAN,plan)
    return dict(plan=str(PLAN),sha256=sha(PLAN),slots=100,total_compressed_bytes=sum(f['bytes'] for f in plan['acquisition']['files']))


if __name__ == '__main__':
    print(run())
