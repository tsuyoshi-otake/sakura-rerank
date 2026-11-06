"""Construct every reserved source view before candidate outcomes exist."""
import argparse
from collections import Counter
import json

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.input_boundary import collect_requests
from sakura_rerank.data.tatoeba_input_units import VIEWS,build_source_units
from unit35_common import ROOT,PAST,authenticate,save,read,sha


def build():
    decoded=read(PAST/'decoded-pilot.json');rows=[]
    for slot in decoded['slots']:
        result=build_source_units(slot['sentence'],slot['transcription'])
        result.update(stable_id='tatoeba-source-unit-'+canonical_json_hash(['tatoeba-jpn-weekly-20261031',slot['sentence_id']]),
                      sentence_id=slot['sentence_id'],slot=slot['slot'],stratum=slot['stratum'])
        rows.append(result)
    return rows,collect_requests(rows)


def run(commit):
    plan=authenticate(commit)
    save(ROOT/'preparation-reservation.json',dict(plan_commit=commit,slots=100,source='previously_consumed_pilot',
        model_inference=0,gold_admitted=0))
    rows,requests=build()
    if (rows,requests)!=build():raise ValueError('unit35_source_views_replay_differs')
    if len(rows)!=100 or len(requests)>plan['native']['maximum_unique_requests']:
        raise ValueError('unit35_population_bound')
    save(ROOT/'source-units.json',dict(rows=rows))
    save(ROOT/'requests.json',dict(requests=requests))
    stats={name:dict(Counter(row['views'][name]['status'] for row in rows)) for name in VIEWS}
    report=dict(kind='source_unit_preparation',status='prepared_not_admitted',plan_commit=commit,
        slots=len(rows),source_statuses=dict(Counter(row['status'] for row in rows)),view_statuses=stats,
        strata=dict(Counter(row['stratum'] for row in rows)),requests=len(requests),
        projected_source_slots=sum(row.get('projected_units',0)>0 for row in rows),
        deterministic_replay=True,source_units_sha256=sha(ROOT/'source-units.json'),requests_sha256=sha(ROOT/'requests.json'),
        native_executed=False,new_fits=0,model_inference=0,gold_certified=False,final_test_used=False)
    save(ROOT/'preparation.json',report)
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan-commit',required=True)
    run(parser.parse_args().plan_commit)
