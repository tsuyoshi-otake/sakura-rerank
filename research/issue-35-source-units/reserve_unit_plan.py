"""Fix transformations, diagnostic views and resource permissions before execution."""
import platform
import subprocess
import sys

from unit35_common import ROOT,HERE,PAST,PLAN,read,save,sha


def run():
    observed=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True).strip()
    if subprocess.check_output(['git','-C','../sakura-input','status','--porcelain']):
        raise ValueError('unit35_clean_sakura_input_required')
    inputs=[PAST/name for name in ('decoded-pilot.json','selection.json','alignment-audit.json','isolation-audit.json',
        'source-relations.json','acquisition.json','metadata-profile.json','relation-diagnostic.json')]
    inputs += ['research/issue-35-source-pilot/plan-v1.json','research/issue-35-source-pilot/selection-binding-v1.json',
        'research/issue-35-source-pilot/history-binding-v1.json','reports/issue-35-external-source-pilot-v1.json',
        'manifests/reference-probe-identity-v1.json']
    code=list(HERE.glob('*.py'))+['src/sakura_rerank/data/tatoeba_input_units.py',
        'src/sakura_rerank/data/source_owner_diagnostic.py','src/sakura_rerank/data/tatoeba_source.py',
        'src/sakura_rerank/data/input_boundary.py','src/sakura_rerank/data/reconstruction_graph.py',
        'src/sakura_rerank/data/relation_witnesses.py','research/issue-35-source-pilot/isolate_pilot.py',
        'research/issue-35-source-pilot/pilot35_common.py','tests/test_tatoeba_input_units.py','tests/test_source_owner_diagnostic.py']
    binding=read('manifests/reference-probe-identity-v1.json')
    plan=dict(kind='source_units_and_owner_diagnostic_plan_v1',parent_issue=1,issues=[31,32,35],
        source_snapshot='tatoeba-jpn-weekly-20261031',pilot_commit='50a6991490fd7c053ccc7afadb5ad1cafdc47d44',
        population=dict(slots=100,prior_exposure='All100 source slots already consumed by PR60. This is research diagnostics only.',
                        replacements=0,source_acquisition=0,final_test_used=False),
        hypotheses=['Source-specific administrative ownership propagates input matches without proving shared authorship.',
                    'Whole-source or punctuation-delimited inputs avoid treating each ruby base as a complete word; native source presence may differ.'],
        ownership=dict(official_help='https://tatoeba.org/en/help',
            official_guide='https://en.wiki.tatoeba.org/articles/show/what-you-can-do-and-how-to-do-it',
            selected='Exactly the100 prior source nodes plus all312 prior input nodes; authenticate owner namespace and full group coverage.',
            comparison='Full graph versus only selected Tatoeba owner-edge omissions; independent null-owner rebuild.',
            unchanged='Old author, input, paragraph and near/exact text relations; original exclusions and partitions.',
            production_policy_change=False),
        units=dict(views=['whole_source','literal_runs','ruby_fragments'],
            rules='Preserve all original surface codepoints; ruby parts concatenate; plain kana has literal phonetic evidence; punctuation/symbols retained as literals.',
            input_projection='Only one-to-one U+30A1..U+30F6 to U+3041..U+3096; preserve original surfaces/raw reading and long-vowel mark. No Unicode normalization or vowel expansion.',
            unsupported='Unannotated Han, Latin, digits, whitespace, unsupported reading/control/markup remain explicit; no guesses.',
            caveat='Neither punctuation boundaries nor ruby are certified grammatical/IME input boundaries. Whole source is a hypothetical conversion event.',
            reading_max=128,target_max=256,conversion_parts_max=32),
        native=dict(permission='Preparation only until a separate committed exact-request binding.',
            maximum_unique_requests=1000,concurrency=2,request_timeout_seconds=30,total_timeout_seconds=900,retries=0,
            executable='data/generated/issue-31-reference-exporter-v1/probe-exporter.exe',
            dictionary='data/generated/issue-31-exporter-restoration-v1/system.dic',
            runtime_identity_sha256=sha('manifests/reference-probe-identity-v1.json'),
            exporter_sha256=binding['runtime_manifest']['exporter_binary_sha256'],
            dictionary_sha256=binding['runtime_manifest']['dictionary_sha256'],
            exporter_source_head=binding['runtime_manifest']['sakura_input_head'],
            current_sakura_input_head=observed,current_sakura_input_clean=True,
            interpretation='Pinned research reference exporter; not equivalence to current production HEAD.'),
        metrics=dict(k=[1,5,6,10,32],denominator='All100 slots and both80/20 strata; report measured/failure/unsupported separately.',
            whole='Whole-reading exact source Top-k',runs='All parts source-supported at k, not joint Top-k',
            label_quality='Unmeasured; no independent Gold precision or accuracy claim.'),
        bounds=dict(historical_nodes=988073,previous_diagnostic_nodes=988485,maximum_nodes=1000000,stage_timeout_seconds=1200),
        unchanged=dict(adopted_accuracy_percent=90.72,safety_harm_fraction=.0025,gold_point_minimum=.995,
            gold_wilson_lower_minimum=.99,final_holdout_valid_minimum=3000),
        forbidden=dict(training=True,model_inference=True,gold_admission=True,calibration_admission=True,
            final_test=True,production_edits=True,restore_old_exclusions=True),
        environment=dict(python=sys.version,platform=platform.platform(),new_dependencies=0),
        inputs={str(p).replace('\\','/'):sha(p) for p in inputs},code={str(p).replace('\\','/'):sha(p) for p in code})
    save(PLAN,plan)
    return dict(slots=100,old_nodes=988073,sakura_input_head=observed,plan_sha256=sha(PLAN))


if __name__=='__main__':print(run())
