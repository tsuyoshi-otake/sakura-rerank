"""Propagate explicit semantic exposure of source-only nodes without fake inputs.

Neutral source coverage is intentionally not historical consumption. Consumers
must separately declare which source-only nodes they actually decoded or used.
This overlay can only add historical relations; it never admits a source.
"""
from .relation_witnesses import component_labels


def exposed_source_inputs(graph, exposed_source_ids):
    """Return research input IDs connected to declared, existing neutral sources."""
    ids = list(exposed_source_ids)
    if len(ids) > 10000 or len(ids) != len(set(ids)):
        raise ValueError('source_exposure_identity_bound')
    chosen = set(ids)
    found = {row['stable_id']: row for row in graph.records if row['stable_id'] in chosen}
    if set(found) != chosen or any(row['population'] != 'source_coverage' for row in found.values()):
        raise ValueError('source_exposure_requires_existing_neutral_sources')
    labels = component_labels(graph)
    exposed_components = {labels[i] for i, row in enumerate(graph.records) if row['stable_id'] in chosen}
    return {row['stable_id'] for i, row in enumerate(graph.records)
            if row['population'] not in ('historical', 'source_coverage') and labels[i] in exposed_components}
