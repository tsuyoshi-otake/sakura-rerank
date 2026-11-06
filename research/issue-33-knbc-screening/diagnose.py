"""Recount direct input matches separately from complete-component exclusion."""
import argparse
from collections import Counter
import json

from history import historical_aliases
from prepare import ROOT, authenticate, read, require


def diagnose(commit):
    authenticate(commit)
    aliases = historical_aliases()
    rows = read(ROOT/'source-slots.private.json')['rows']
    relations = read(ROOT/'relations.private.json')
    counts = Counter(relations['components'].values())
    inputs = [r['input'] for r in rows if r['input'] is not None]
    require(len(inputs) == sum(counts.values()), 'knbc_diagnostic_input_extent')
    direct = [r for r in inputs if r['input_hash'] in aliases]
    touched = {relations['components'][r['stable_id']] for r in direct}
    propagated = sum(n for key, n in counts.items() if key in touched)
    value = dict(kind='direct_versus_transitive_known_input_exposure', input_hypotheses=len(inputs),
        direct_actual_or_projected_history_matches=len(direct),
        distinct_direct_input_hashes=len({r['input_hash'] for r in direct}),
        components_touched_by_direct_matches=len(touched),
        all_recorded_component_sizes=sorted(counts.values(), reverse=True),
        component_propagated_inputs=propagated,
        non_direct_inputs_in_touched_components=propagated-len(direct),
        new_predictions=0, new_fits=0, exclusions_restored=0,
        interpretation='Counts of source relations and known inputs, not evidence that every excluded sentence is a duplicate or that new models fitted these examples.')
    require(value == read(ROOT/'direct-exposure-diagnostic.json'), 'knbc_diagnostic_replay')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.commit)))
