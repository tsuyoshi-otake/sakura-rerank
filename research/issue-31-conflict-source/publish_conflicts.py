"""Publish verified aggregates and hash-only repair proposals, never labels."""
import ast
import json
from pathlib import Path
import subprocess
import sys

from conflict_common import HERE, ROOT, read, require, save, sha


def publish():
    audit, proof, tests = (read(ROOT/name) for name in ('audit.json','verification.json','full-tests.json'))
    require(proof['status']=='passed' and proof['audit_sha256']==sha(ROOT/'audit.json'), 'publication_verification')
    require(tests==dict(tests=821, successful=True, failures=0, errors=0, skipped=0), 'publication_tests')
    for stage in ('audit','verify','tests'):
        require(read(ROOT/(stage+'-terminal.json'))['status']=='complete', 'publication_terminal')
    plan = read(HERE/'plan-v1.json')
    require(sha(HERE/'plan-v1.json')==audit['plan_sha256'], 'publication_plan')
    for path, digest in {**plan['inputs'], **plan['code'], **audit['artifacts']}.items():
        require(sha(path)==digest, 'publication_immutable_artifact')
    old_audit = read(ROOT.parent/'attempt-01/audit.json')
    require(all(audit['summary'][k]==v for k,v in old_audit['summary'].items()), 'original_conflict_aggregate_parity')
    static = []
    for path in sorted(HERE.glob('*.py'))+[Path('tests/test_conflict_source.py')]:
        tree=ast.parse(path.read_bytes()); compile(tree,str(path),'exec')
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
                for a in n.names if (a.asname or a.name.split('.')[0]) not in names]
        require(not unused,'unused_import')
        static.append(dict(path=path.as_posix(),sha256=sha(path),syntax_valid=True,unused_imports=[]))
    original=subprocess.run([sys.executable,'-B','research/issue-33-data-growth/verify_integrity.py'],
        capture_output=True,text=True,timeout=120,check=True)
    integrity=json.loads(original.stdout.strip().splitlines()[-1])
    require(integrity['status']=='passed','original_integrity')
    checkpoints=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in checkpoints: require(sha(model['path'])==model['sha256'],'old_checkpoint')
    proposals=[]
    for row in read(ROOT/'rows.json'):
        if row['reading_evidence']=='exact_ruby_reading_disagreement':
            require(row['stratum']=='dictionary_aozora','repair_stratum')
            proposals.append({k:row[k] for k in ('index','input_key','original_row_sha256','consumption_sha256','source_revision_sha256')})
    require(len(proposals)==335,'repair_proposal_count')
    repair=dict(kind='source_reading_consistency_repair_proposals',status='proposed_not_applied',
        audit_sha256=sha(ROOT/'audit.json'),rows=proposals,reason='frozen_dictionary_reading_disagrees_with_exact_original_ruby_span',
        next_action='Rebuild new source-reconstruction examples from authenticated full original annotations, or quarantine when source evidence conflicts. Preserve originals and history; do not auto-correct IME/Gold labels.',
        labels_changed=0,training_rows_removed=0,gold_admission=False)
    save(ROOT/'repair-proposals.json',repair)
    report=dict(kind='source_conflict_diagnosis_report',status='verified_source_evidence_no_label_admission',
        issues=[31,32,33,34,35],parent_issue=1,plan_sha256=sha(HERE/'plan-v1.json'),
        execution_commit=audit['code_commit'],analysis=audit['summary'],verification=proof,tests=tests,static_checks=static,
        audit_sha256=sha(ROOT/'audit.json'),original_conflict_results_unchanged=True,
        prior_plan_code_commit=plan['supersedes_plan_code_commit'],
        source_extension_reason=plan['amendment'],original_integrity=integrity,old_checkpoints_unchanged=len(checkpoints),
        repair_proposal_count=len(proposals),repair_proposals_sha256=sha(ROOT/'repair-proposals.json'),repair_proposals_applied=False,
        conclusions=[
            'All21459 empty numeric inputs map to one literal reading/candidate input: zero whole-input aliases, surface encoding collisions or truncations in this population.',
            'Only27/2114 conflicting groups collapse under the declared mechanical notation folds;2087 remain distinct. Even the27 are not semantic equivalence or allowed-label findings.',
            'All75000 targets and bounded source prefixes match their original source extents. Exact original ruby contradicts335/25000 dictionary Aozora readings;234 of these are outside the initially diagnosed conflicts. Source presence does not validate intended reading.',
            'The25000 annotation-first rows all retain their original ruby reading, but this does not certify morphology, IME intent, meaning, Gold quality or superiority of the failed annotation training recipe.',
            'One/two/four source suffix characters reduce empirical minimum mismatches from5658 to1835/300/32; eight makes the consumed census conflict-free with74548 unique inputs. This is an information/uniqueness diagnostic, not held-out accuracy or a selected production context length.',
            'Combining the three source distributions adds1831 source mismatches beyond their3827 separate-stratum minimum. Source identity must not become an unauthorized production feature.',
            'The335 proposed repairs are not applied. All75000 rows and original labels remain; the adopted model accuracy and safety evidence are unchanged.'],
        priorities=[
            dict(priority=1,issue=31,action='Make original annotation versus dictionary-reading consistency explicit before new source-reconstruction admission; rebuild or quarantine contradictions with append-only provenance.',
                expected_effect='Addresses335 demonstrated reading inconsistencies in this fixed pool; no promised accuracy lift.',cost='Bounded source joins and new native candidate requests only for separately bound rebuilt examples; no GPU training needed for the integrity fix.'),
            dict(priority=2,issue=33,action='Evaluate local context and explicit ambiguity handling only after binding genuine same-session context availability and an unused research evaluation source.',
                expected_effect='Tests distinctions unavailable in empty inputs; current fixed model remains13271 source matches below the empty-input census ceiling.',cost='Small prespecified representation/ranking comparison with fresh source isolation; never select eight characters from this census as an optimum.'),
            dict(priority=3,issue=32,action='Preserve source strata and actual-projection equality in new reservations; do not discard difficult sources or break giant components.',
                expected_effect='Prevents distribution mixing and numeric projection changes from masquerading as independent improvement.',cost='Linear hash/group audit using existing contracts; new source acquisition is separately bounded.'),
            dict(priority=4,issue=35,action='Establish independently valid labels and calibration/Test separation before safety claims; retain single-use final Test and fixed0.25% requirement.',
                expected_effect='Makes any future gain and safety assessment interpretable. Current source annotations and AI cannot certify Gold.',cost='Independent evidence remains unavailable; no final evaluation or release claim is authorized by this diagnosis.')],
        adopted_accuracy_record=0.9072,accuracy_improvement_demonstrated=False,safety_limit=0.0025,
        gold_requirements=plan['gold_requirements'],gold_certified=False,release_eligible=False,
        new_fits=0,model_inferences=0,threshold_selection=False,calibration=False,final_test=False,production_change=False)
    path=Path('reports/issue-31-conflict-source-v1.json')
    save(path,report)
    print(json.dumps(dict(status=report['status'],report_sha256=sha(path),repair_proposals=335,tests=821,python_files=len(static))))


if __name__=='__main__':
    publish()
