"""Reconcile documentation evidence and publish aggregate source qualification."""
import ast
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from qualify_knbc import HERE, REPO, ROOT, PREVIOUS, authenticate, digest, require, save


def read(path):
    return json.loads(path.read_bytes())


def publish():
    plan=authenticate('c62444e191ec7e9057a8fd19375b2610900b0438')
    result=read(ROOT/'acquisition.json'); verified=read(ROOT/'verification.json')
    require(result['status']==verified['status']=='complete', 'qualification_evidence')
    require(digest((REPO/result['archive_path']).read_bytes())==result['local_sha256'], 'archive_integrity')
    inventory=read(ROOT/'member-inventory.json')
    files=[r for r in inventory if r['kind']=='file' and r['name'].split('/')[1:2]==['corpus1']]
    metadata=[r for r in files if Path(r['name']).name=='fileinfos']
    sentence_candidates=[r for r in files if Path(r['name']).name!='fileinfos']
    articles={str(Path(r['name']).parent) for r in files}
    require(len(files)==4436 and len(metadata)==249 and len(sentence_candidates)==4187 and len(articles)==249, 'metadata_census')
    require(len(inventory)==verified['independently_reconciled_members']==13589, 'independent_count')
    documentation=read(ROOT/'documentation-exposure.json')
    for item in documentation:
        require(digest((ROOT/item['local_name']).read_bytes())==item['sha256'], 'documentation_integrity')
    manual=read(ROOT/'manual-evidence.json'); rendered=read(ROOT/'manual-render-evidence.json')
    require(digest((ROOT/'manual.pdf').read_bytes())==manual['manual_sha256']==rendered['manual_sha256'], 'manual_integrity')
    require(digest((ROOT/'manual-readable-pages.private.json').read_bytes())==rendered['text_sha256'], 'manual_text_integrity')
    readable=read(ROOT/'manual-readable-pages.private.json')
    require('ER:' in readable[4] and 'ヨミ:' in readable[8], 'manual_section_evidence')
    require(read(ROOT/'manual-render-terminal.json')['status']=='complete', 'manual_render_terminal')
    for stage in ('targeted','inspect','verify','tests'):
        require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','stage_terminal')
    tests=read(ROOT/'full-tests.json'); targeted=read(ROOT/'targeted-tests.json')
    require(tests['successful'] and tests['tests']==954 and targeted['tests']==13
            and not (tests['failures'] or tests['errors'] or tests['skipped']), 'test_evidence')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[REPO/'tests/test_knbc_documentation.py']:
        tree=ast.parse(path.read_bytes()); compile(tree,str(path),'exec')
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
                for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import')
        static.append(dict(path=path.relative_to(REPO).as_posix(),sha256=digest(path.read_bytes()),syntax_valid=True,unused_imports=[]))
    checked=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(checked.stdout.strip().splitlines()[-1])
    models=read(REPO/'research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:
        require(digest((REPO/model['path']).read_bytes())==model['sha256'], 'historical_model_integrity')
    report=dict(kind='external_source_documentation_qualification',version=1,issue=35,parent_issue=1,related_issues=[31,32,33],
        status='candidate_for_reserved_research_pilot_not_gold',source='KNBC_v1.0_090925_utf8',
        official_page='https://nlp.ist.i.kyoto-u.ac.jp/kuntt/',source_url=plan['source_url'],
        source_archive_sha256=result['local_sha256'],official_cryptographic_digest=None,
        acquisition_level=result['acquisition_level'],compressed_bytes=result['compressed_bytes'],expanded_bytes=result['expanded_bytes'],
        acquisition_plan_sha256=digest((HERE/'plan-v1.json').read_bytes()),inspection_plan_sha256=digest((HERE/'plan-v2.json').read_bytes()),
        manual_plan_sha256=digest((HERE/'manual-plan-v1.json').read_bytes()),
        previous_attempt=dict(status='failed_before_documentation_publication',reason=read(PREVIOUS/'acquire-failure.json')['error_code'],
                              preserved=True,archive_reused_without_second_get=True),
        metadata=dict(members=len(inventory),types=dict(Counter(r['kind'] for r in inventory)),
            corpus1_files=len(files),fileinfos_metadata_files=len(metadata),sentence_candidate_files=len(sentence_candidates),
            article_directories=len(articles),provider_sentence_claim=4186,claim_difference=1,
            interpretation='Metadata-only file census; no corpus sentence/parse count is certified and the extra file is not dropped.'),
        provider_description=dict(articles=249,sentences=4186,commissioned_writers=81,human_annotated=True,
            themes={'mobile_phones':dict(articles=79,sentences=1278),'kyoto_tourism':dict(articles=91,sentences=1498),
                    'sports':dict(articles=22,sentences=522),'food':dict(articles=57,sentences=888)},
            denominator_type='provider_documentation_claims_not_new_measurements'),
        documentation=[dict(sha256=d['sha256'],bytes=d['bytes'],kind='provider_readme') for d in documentation],
        manual=dict(sha256=manual['manual_sha256'],pages=13,pypdf_extraction_retained_but_unreadable=True,
            readable_text_sha256=rendered['text_sha256'],rendered_pages=13,visually_inspected_pdf_pages=[1,5,9],
            renderer='PyMuPDF 1.26.6',renderer_wheel_sha256=read(HERE/'pdf-tool-v1.json')['sha256'],
            all_documentation_examples_exposed=True,corpus_members_semantically_decoded=0),
        source_policy=dict(license='Package README contains three-clause BSD-style use/redistribution terms; preserve copyright, conditions and disclaimer; no endorsement.',
            human_annotation_scope='Provider human-analyzed morphology/syntax; no imported project A/B verdict or measured IME-label error rate.',
            important_contract='Manual 4.1 preserves original misspellings while annotating corrected forms and ER notes. Source spelling and corrected annotation are separate evidence.',
            reading_contract='Manual 4.4.1 distinguishes contextual surface reading from lemma; morphology boundaries still do not establish intended IME input boundaries.',
            context_contract='Corpus document adjacency and extracted bracket sentences are not observed Sakura session context.',
            unknowns=['Individual contextual reading error rate and IME intent','Writer-to-article mapping and author-level split feasibility',
                      'One-file discrepancy against provider sentence count','Source/input/history and documentation-example overlaps',
                      'Independent Gold valid count and confidence interval']),
        comparison=dict(tatoeba='Previously acquired and 1100 sentences consumed; provenance and exposure limits remain; not a new untouched source.',
            gsd='Pinned README distinguishes annotation licensing from original text; lexeme reading is not surface reading. No corpus acquired in this qualification.',
            kwdlc='Existing public-train reservation exhausted; no reuse as fresh evaluation.',
            mozc='Focused metadata search returned no results; no corpus inspected or qualified.'),
        next_step=dict(priority=1,action='Freeze a <=100-sentence, <=20-article source-format pilot before corpus decoding; preserve every selected slot, group exclusions by article and inherited relations.',
            prerequisites=['Resolve metadata file roles and documentation-example exclusion','Bind KNP reading/surface/ER semantics and preserve original source separately','Join complete source/input/history exposure before later evaluation use'],
            expected_effect='Test whether provider readings and correction notes avoid dictionary-derived or source-exact mislabels; not an expected accuracy percentage.',
            cost='At most100 fixed sentence slots and20 article groups; no fitting, threshold selection or final Test. Larger sampling requires a new reservation.'),
        tests=tests,targeted_tests=targeted,static_checks=static,independent_metadata_verification=verified,
        original_integrity=integrity,old_checkpoints_unchanged=len(models),
        scope=dict(owner='research/issue-35-knbc-qualification',state='Immutable quarantined source and documentation exposure receipts',
            files='Six research scripts, three frozen documentation plans, tool lock/manifest, one test module, aggregate report and README',
            expansion='Provider archive contains a symbolic link; its manual uses a legacy PDF encoding; provider sentence claim differs from file inventory. Separate documentation access, rendering and census were necessary.',
            architecture='No production/data-consumer API changed. Documentation qualification grants no training, Gold, calibration or Test admission.',
            future_reading='Next source pilot can use pinned archive/documentation hashes, known ER/reading caveats and metadata census without rediscovering acquisition or licensing. It must still understand KNP field semantics and complete exposure lineage.'),
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,
        gold_requirements=dict(point=.995,wilson95_lower=.990,final_valid_minimum=3000),
        new_fits=0,model_inferences=0,native_requests=0,original_labels_changed=0,human_reviews=0,ai_linguistic_reviews=0,
        corpus_member_semantic_decodes=0,training_admission=False,gold_admission=False,calibration=False,final_test=False,production_change=False,release_eligible=False)
    destination=REPO/'reports/issue-35-knbc-qualification-v1.json'
    save(destination,report)
    print(json.dumps(dict(status=report['status'],report_sha256=digest(destination.read_bytes()),members=len(inventory),sentence_candidate_files=len(sentence_candidates),tests=tests['tests'],static_files=len(static))))


if __name__=='__main__':
    publish()
