"""Complete neutral-source relations with separately bounded metadata.

The frozen legacy validator and graph remain unchanged. Only source-only nodes
may carry up to 1,024 signature hashes; real input metadata keeps its old limit.
All typed relation generation uses the same pinned splitter and recorder core.
"""
from collections import Counter,defaultdict
import re

from .contracts import canonical_json_hash
from .growth_isolation import validate_metadata
from .relation_witnesses import KINDS,MAX_EDGES,WitnessGraph,_Recorder,component_labels
from .splitter import MAX_COMPONENT_INPUT_RECORDS,_group_by_value,_union_groups,_union_near_duplicates

MAX_NEUTRAL_SIGNATURES=1024
SOURCE_FIELDS={'article_id','paragraph_hash','sentence_hash','sentence_shingle_hashes','template_cluster_id'}


def validate_source_record(row):
    if row.get('population')!='source_coverage':
        validate_metadata(row)
        return
    if (set(row)!={'stable_id','population','source'} or not isinstance(row['stable_id'],str)
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',row['stable_id'])):
        raise ValueError('complete_source_node_schema')
    source=row['source']
    if not isinstance(source,dict) or set(source)!=SOURCE_FIELDS:
        raise ValueError('complete_source_metadata_schema')
    if not isinstance(source['article_id'],str) or not 1<=len(source['article_id'])<=256:
        raise ValueError('complete_source_article_identity')
    cluster=source['template_cluster_id']
    if cluster is not None and (not isinstance(cluster,str) or not 1<=len(cluster)<=256):
        raise ValueError('complete_source_author_identity')
    values=source['sentence_shingle_hashes']
    if not isinstance(values,list) or not 1<=len(values)<=MAX_NEUTRAL_SIGNATURES:
        raise ValueError('complete_source_signature_bound')
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{64}',v) for v in [source['paragraph_hash'],source['sentence_hash'],*values]):
        raise ValueError('complete_source_hash_format')
    if values!=sorted(set(values)):
        raise ValueError('complete_source_signature_order')


def build_source_graph(records):
    """Same typed edges as the frozen builder, after versioned validation."""
    if not 1<=len(records)<=MAX_COMPONENT_INPUT_RECORDS:
        raise ValueError('complete_source_node_bound')
    ordered=sorted(records,key=lambda row:row['stable_id']);previous=None
    for row in ordered:
        if row['stable_id']==previous: raise ValueError('complete_source_duplicate_id')
        previous=row['stable_id'];validate_source_record(row)
    graph=WitnessGraph(ordered);recorder=_Recorder(graph,MAX_EDGES);groups={}
    for kind,field in ((0,'article_id'),(1,'template_cluster_id'),(3,'paragraph_hash')):
        recorder.kind=kind
        groups[KINDS[kind]]=_union_groups(recorder,_group_by_value(ordered,field,skip_none=kind==1))
    inputs=defaultdict(list)
    for index,row in enumerate(ordered):
        if 'input_hash' in row: inputs[row['input_hash']].append(index)
    recorder.kind=2;groups['input']=_union_groups(recorder,inputs)
    recorder.kind=4;pairs,signatures,comparisons,_=_union_near_duplicates(ordered,recorder,threshold=.8)
    graph.audit=dict(nodes=len(ordered),representative_edges=len(graph.left),
        edge_kinds={KINDS[k]:count for k,count in sorted(Counter(graph.kinds).items())},duplicate_key_groups=groups,
        conceptual_near_record_pairs=pairs,distinct_signatures=signatures,actual_signature_comparisons=comparisons,
        distinct_near_signature_pairs=recorder.near_signature_pairs)
    return graph


def isolate_source_scope(records):
    graph=build_source_graph(records);labels=component_labels(graph)
    members=defaultdict(list)
    for i,label in enumerate(labels): members[label].append(i)
    excluded={};components={};counts=Counter();population_components=Counter();sizes=[];paragraph_roles=defaultdict(set)
    for row in graph.records: paragraph_roles[row['source']['paragraph_hash']].add(row['population'])
    for group in members.values():
        populations={graph.records[i]['population'] for i in group}-{'source_coverage'}
        reason='historical_relation' if 'historical' in populations else ('cross_partition_relation' if {'train','evaluation'}<=populations else None)
        key=canonical_json_hash(sorted(graph.records[i]['stable_id'] for i in group));sizes.append(len(group))
        population_components['+'.join(sorted(populations)) or 'source_only']+=1
        for i in group:
            row=graph.records[i]
            if row['population'] in ('historical','source_coverage'): continue
            components[row['stable_id']]=key
            if reason: excluded[row['stable_id']]=reason
            counts[row['population']+'/'+(reason or 'retained')]+=1
    return excluded,components,dict(counts=dict(counts),components=len(sizes),largest_component=max(sizes),
        source_only_nodes=sum(r['population']=='source_coverage' for r in graph.records),source_only_input_edges=0,
        exact_input_duplicate_groups=graph.audit['duplicate_key_groups']['input'],near_pairs=graph.audit['conceptual_near_record_pairs'],
        near_signature_comparisons=graph.audit['actual_signature_comparisons'],records=len(records),
        population_component_counts=dict(population_components),historical_coverage_shared_paragraph_groups=sum(
            {'historical','source_coverage'}<=roles for roles in paragraph_roles.values()))
