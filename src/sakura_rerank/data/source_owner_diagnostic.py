"""Omit only authenticated administrative-owner groups for diagnostic views.

The caller retains all original exclusions. This never assigns partitions or
author identities. Old author, source, input and text relations remain intact.
"""
from array import array
import re

from .relation_witnesses import KINDS


def administrative_owner_omissions(graph,selected_source_ids):
    selected=set(selected_source_ids)
    if not selected or len(selected)>10000:
        raise ValueError('administrative_owner_selection_bound')
    found={row['stable_id'] for row in graph.records if row['stable_id'] in selected}
    if found!=selected:raise ValueError('administrative_owner_selected_id_missing')
    selected_flags=[]
    for row in graph.records:
        active=row['stable_id'] in selected
        group=row['source']['template_cluster_id']
        if active and (not row['source']['article_id'].startswith('tatoeba:')
                       or group is not None and not re.fullmatch(r'tatoeba-owner:[0-9a-f]{64}',group)):
            raise ValueError('administrative_owner_source_identity')
        selected_flags.append(active)
    omitted=array('B',[0])*len(graph.left)
    for index,(left,right,kind) in enumerate(zip(graph.left,graph.right,graph.kinds)):
        if kind!=KINDS.index('author'):continue
        a,b=selected_flags[left],selected_flags[right]
        if not a and not b:continue
        if not a or not b:raise ValueError('administrative_owner_unselected_group_member')
        left_group=graph.records[left]['source']['template_cluster_id']
        if left_group is None or left_group!=graph.records[right]['source']['template_cluster_id']:
            raise ValueError('administrative_owner_edge_identity')
        omitted[index]=1
    return omitted
