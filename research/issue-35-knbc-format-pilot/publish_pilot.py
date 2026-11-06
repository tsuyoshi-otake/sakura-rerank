"""Reproduce aggregate field/capacity diagnostics and publish the fixed pilot."""
import ast
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

from pilot import HERE, REPO, ROOT, INVENTORY, PLAN, BINDING, binding, read, require, save, sha


def publish():
    _,selection=binding('ee9f945b357d64ba2991e0ee9dfae459068eb2a2')
    pilot=read(ROOT/'pilot-report.json');proof=read(ROOT/'verification.json')
    rows=read(ROOT/'parsed-slots.private.json');diag=read(ROOT/'field-diagnostic.json');structure=read(ROOT/'structure-diagnostic.json')
    capacity=read(ROOT/'capacity-diagnostic.json');tests=read(ROOT/'full-tests.json');targeted=read(ROOT/'targeted-tests.json')
    require(proof['status']=='passed' and sha(ROOT/'parsed-slots.private.json')==pilot['slots_sha256']==diag['slots_sha256'],'pilot_publication_proof')
    require(tests['successful'] and tests['tests']==972 and targeted['tests']==18
            and not(tests['failures'] or tests['errors'] or tests['skipped']),'pilot_publication_tests')
    for stage in ('targeted','select','decode','verify','tests'):
        require(read(ROOT/(stage+'-terminal.json'))['status']=='complete','pilot_publication_terminal')
    doc_markers=Counter();token_markers=Counter();locations=Counter();empty=0;grammar=0
    for row in rows:
        raw=(ROOT/'raw-members'/f"slot-{row['index']:03d}.raw").read_text(encoding='utf-8')
        lines=raw.splitlines()
        for marker in ('原形曖昧','読み曖昧','品詞曖昧'):
            doc_markers[marker]+=any(marker in line for line in lines)
        morphs=[line.split(maxsplit=11) for line in lines if line and line!='EOS' and not line.startswith(('#','* ','+ ','@ '))]
        for marker in ('原形曖昧','読み曖昧','品詞曖昧'):
            token_markers[marker]+=sum(len(fields)==12 and marker in fields[11] for fields in morphs)
        for line in lines:
            if line.startswith(('* ','+ ')) and ('ER:' in line or 'ER：' in line):
                locations['basic_phrase' if line.startswith('+ ') else 'bunsetsu']+=1
        if row['annotation']:
            for fields,token in zip(morphs,row['annotation']['tokens'],strict=True):
                require(fields[3:11]==token['grammatical_fields'],'pilot_grammar_field_replay');grammar+=1
        elif row['role']=='unclassified_member':
            require(not morphs and len(lines)==2 and lines[0].startswith('# S-ID:') and lines[1]=='EOS','pilot_unclassified_shape');empty+=1
    require(dict(doc_markers)==diag['document_marker_kinds'] and dict(token_markers)==diag['token_note_marker_kinds']
            and dict(locations)==structure['structure_marker_counts'] and empty==1,'pilot_independent_diagnostics')
    inventory=read(INVENTORY)
    candidate_paths=[r['name'] for r in inventory if r['kind']=='file' and r['name'].split('/')[1:2]==['corpus1']
                     and re.fullmatch(re.escape(r['name'].split('/')[2])+r'(?:-[0-9]+)+',Path(r['name']).name)]
    articles={r['article'] for r in rows};families={r['family'] for r in rows}
    article_used=sum(p.split('/')[2] in articles for p in candidate_paths)
    family_used=sum(p.split('/')[2].split('_')[0] in families for p in candidate_paths)
    require(len(candidate_paths)==capacity['all_sentence_candidates']==4186
        and article_used==capacity['candidate_files_in_selected_articles']==348
        and family_used==capacity['candidate_files_in_selected_prefix_families']==1400
        and len(candidate_paths)-family_used==capacity['remaining_after_conservative_family_exclusion']==2786,'pilot_capacity_replay')
    static=[]
    for path in sorted(HERE.glob('*.py'))+[REPO/'src/sakura_rerank/data/knbc_source.py',REPO/'tests/test_knbc_source.py']:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec')
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
                for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'pilot_unused_import')
        static.append(dict(path=path.relative_to(REPO).as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    checked=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(checked.stdout.strip().splitlines()[-1])
    models=read(REPO/'research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in models:require(sha(REPO/model['path'])==model['sha256'],'pilot_old_model_changed')
    report=dict(kind='knbc_fixed_source_format_pilot',version=1,issue=35,parent_issue=1,related_issues=[31,32,33],
        status='fixed_format_pilot_complete_not_gold',plan_sha256=sha(PLAN),decode_binding_sha256=sha(BINDING),
        plan_commit='6daa84cb923556da2d5df52f2237c3ec6a90de4e',binding_commit='ee9f945b357d64ba2991e0ee9dfae459068eb2a2',
        selection=read(ROOT/'selection-report.json'),pilot=pilot,field_diagnostic=diag,structure_diagnostic=structure,capacity_diagnostic=capacity,
        independent_verification={**proof,'grammar_field_rows':grammar,'field_and_capacity_diagnostics_reproduced':True},
        tests=tests,targeted_tests=targeted,static_checks=static,original_integrity=integrity,old_checkpoints_unchanged=len(models),
        data_contract=dict(owner='src/sakura_rerank/data/knbc_source.py',
            fields='Provider annotated surface, reading, lemma, grammar, structures, notes and alternatives remain distinct. Original source reconstruction and correction scope are not verified.',
            exposure='All100 attempted members,20 reserved articles,19 conservative prefix families and complete byte-alias census remain in immutable private records. Unknown author mapping is not independence.',
            permission='No training, Gold, calibration, final Test, model or native capability is granted.'),
        findings=['The one extra nonconforming file contains only a header and EOS. It stays as a failed diagnostic slot;4186 article-prefixed files remain sentence candidates, not4186 newly validated Gold sentences.',
            'All47 ambiguity-marker documents carry lemma-ambiguity annotations. Detected reading/POS ambiguity markers are zero; this does not measure actual reading or IME-label ambiguity.',
            'Five correction markers occur on three bunsetsu and two basic-phrase lines, with zero on token notes. Token-only correction scanning would miss all five; replacement scope is unresolved.',
            'No exact whole annotation-surface hit was detected in exposed documentation. Fragment, near-duplicate, source/input/history and author isolation remain unverified.',
            'A one-sentence/one-example final Test would have at most2786 metadata candidates under the reserved-family exclusions, before further quality/history exclusions. This cannot satisfy3000 valid examples by itself; do not change the statistical unit or restore exclusions to inflate capacity.'],
        next_priorities=[dict(priority=1,action='Reconcile the frozen Gold evaluation-unit contract and qualify an additional source before consuming more potential Test material.',
             expected_effect='Ensure enough independent, admissible candidates for final valid3000 and separate calibration without lowering quality or safety.',
             cost='Provider metadata/annotation-policy checks first; no additional corpus text or model inference until a separate reservation.'),
            dict(priority=2,action='On only the already consumed99 annotation units, bind source-original correspondence and phrase-level ER scope before deriving any input or target.',
             expected_effect='Prevent preserved source errors and phrase-scoped notes from becoming guessed per-token Gold labels.',
             cost='Reuse current99 units; any additional source representation requires a separately frozen identity/exposure binding.')],
        scope=dict(actual='One source-format module and its18 contracts; three research stage/report scripts; two frozen plans; metadata, documentation and all-slot ledger boundaries.',
            expansion='The single filename exception required a dedicated diagnostic slot. Actual ER location and remaining family-group capacity required explicit posthoc format/capacity checks; these do not change selection or labels.',
            architecture='Source adapter owns parsing/reservation; research stage owns immutable bytes and exposure ledger. Existing graph, model, training consumers and production contracts unchanged.',
            future_reading='Use the KNBC field contract and pinned consumption ledger without redoing acquisition/format discovery. Future work must resolve original-surface/ER scope and ingest all exposure before independent evaluation.'),
        adopted_accuracy_record=.9072,accuracy_improvement_demonstrated=False,safety_limit=.0025,
        gold_requirements=dict(point=.995,wilson95_lower=.990,final_valid_minimum=3000),
        new_fits=0,model_inferences=0,native_requests=0,original_labels_changed=0,human_reviews=0,ai_linguistic_reviews=0,
        training_admission=False,gold_admission=False,calibration=False,final_test=False,production_change=False,release_eligible=False)
    destination=REPO/'reports/issue-35-knbc-format-pilot-v1.json';save(destination,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(destination),summary=pilot['summary'],tests=tests['tests'],static_files=len(static),remaining_candidate_ceiling=2786)))


if __name__=='__main__':publish()
