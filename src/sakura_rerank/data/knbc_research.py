"""One prospective KNBC source-reconstruction slot per complete sentence.

This owns metadata reservation and a fixed, whole-bunsetsu input hypothesis.
It grants no IME Gold, training, calibration or final-Test admission.
"""
from collections import Counter
import re
import unicodedata

from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .knbc_source import ARCHIVE_ROOT, STRUCTURE, parse_member, require
from .reconstruction_graph import build_source_graph
from .relation_witnesses import component_labels

POLICY = 'knbc-screened-dictionary-research-v1'
SEED = 20261107


def reserve_remaining(inventory, pilot, member_hashes):
    """Reserve all remaining prefix families without looking at new text."""
    require(isinstance(inventory, list) and len(inventory) <= 20000, 'knbc_research_inventory_bound')
    require(pilot['selection_sha256'] == canonical_json_hash(pilot['slots']), 'knbc_research_pilot_identity')
    require(len(pilot['slots']) == 100, 'knbc_research_pilot_extent')
    require(all(r['family'] == r['article'].split('_')[0] for r in pilot['slots']),
            'knbc_research_pilot_family_identity')
    families = {r['family'] for r in pilot['slots']}
    articles = {r['article'] for r in pilot['slots']}
    require(len(families) == 19 and len(articles) == 20, 'knbc_research_pilot_groups')
    seen, selected, excluded = set(), [], Counter()
    for item in inventory:
        name = item['name']
        if item['kind'] != 'file' or not name.startswith(ARCHIVE_ROOT+'/corpus1/'):
            continue
        parts = name.split('/')
        require(len(parts) == 4 and all(p and p not in ('.', '..') for p in parts)
                and '\\' not in name and ':' not in name and not any(ord(c) < 32 for c in name),
                'knbc_research_member_path')
        require(name not in seen, 'knbc_research_duplicate_path')
        seen.add(name)
        article, filename = parts[2:]
        if filename == 'fileinfos':
            excluded['metadata'] += 1
            continue
        family = article.split('_')[0]
        if family in families:
            excluded['previously_reserved_family'] += 1
            continue
        require(re.fullmatch(re.escape(article)+r'(?:-[0-9]+)+', filename) is not None,
                'knbc_research_unclassified_fresh_member')
        require(type(item['bytes']) is int and 0 < item['bytes'] <= 65536,
                'knbc_research_member_bound')
        require(item['archive_name'] in (name, './'+name), 'knbc_research_archive_alias')
        digest = member_hashes[name]
        require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None,
                'knbc_research_member_hash')
        selected.append(dict(path=name, archive_name=item['archive_name'], article=article,
            family=family, bytes=item['bytes'], source_raw_sha256=digest))
    selected.sort(key=lambda r: (canonical_json_hash([POLICY, SEED, r['path']]), r['path']))
    require(1 <= len(selected) <= 2786, 'knbc_research_reservation_bound')
    for index, row in enumerate(selected):
        row['index'] = index
    return dict(kind='knbc_research_reservation', policy=POLICY, seed=SEED,
        slots=selected, slots_sha256=canonical_json_hash(selected),
        census=dict(slots=len(selected), articles=len({r['article'] for r in selected}),
            families=len({r['family'] for r in selected}), excluded=dict(excluded)),
        training_admission=False, gold_admission=False, calibration=False, final_test=False)


def source_metadata(slot, sentence):
    require(bool(sentence) and len(sentence) <= 1024, 'knbc_research_source_extent')
    signature = sentence_shingle_hashes(sentence)
    require(len(signature) <= 512, 'knbc_research_source_signature_extent')
    return dict(article_id='knbc:'+slot['article'],
        template_cluster_id='knbc-prefix:'+slot['family'],
        paragraph_hash=text_sha256(sentence), sentence_hash=text_sha256(sentence),
        sentence_shingle_hashes=signature)


def whole_bunsetsu(raw, parsed):
    """Retain the provider's complete * units; never cut a token or trim text."""
    groups, current, token_index = [], None, 0
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith('#') or line == 'EOS' or line.startswith('@ '):
            continue
        if STRUCTURE.match(line):
            if line.startswith('*'):
                if current is not None:
                    groups.append((current, token_index))
                current = token_index
            continue
        require(current is not None, 'knbc_research_missing_bunsetsu')
        token_index += 1
    if current is not None:
        groups.append((current, token_index))
    require(token_index == len(parsed['tokens']) and groups
            and all(a < b for a, b in groups), 'knbc_research_bunsetsu_coverage')
    return groups


def project_member(raw, slot):
    """Choose by position hash before checking reading/length/annotation status."""
    parsed = parse_member(raw, expected_sid=slot['path'].rsplit('/', 1)[1])
    groups = whole_bunsetsu(raw, parsed)
    source = source_metadata(slot, parsed['annotation_surface'])
    sid = 'knbc-research-'+canonical_json_hash([POLICY, slot['path']])
    coverage = dict(stable_id=sid+'-source', population='source_coverage', source=source)
    index = min(range(len(groups)), key=lambda i: canonical_json_hash([POLICY, SEED, slot['path'], i]))
    start, end = groups[index]
    tokens = parsed['tokens'][start:end]
    surface = ''.join(t['annotated_surface'] for t in tokens)
    reading = ''.join(t['annotated_reading'] for t in tokens)
    annotations = [parsed['header'], *parsed['structures']]
    annotations.extend(t['notes'] for t in parsed['tokens'])
    annotations.extend(a['notes'] for t in parsed['tokens'] for a in t['alternatives'])
    status = 'ready_for_history'
    if 'provider_correction_marker' in parsed['flags']:
        status = 'pending_document_correction'
    elif any('読み曖昧' in value for value in annotations):
        status = 'pending_reading_ambiguity'
    elif 'provider_style_marker' in parsed['flags']:
        status = 'pending_style_annotation'
    elif any(a['annotated_surface'] != t['annotated_surface'] or a['annotated_reading'] != t['annotated_reading']
             for t in tokens for a in t['alternatives']):
        status = 'pending_alternative_reading_or_surface'
    elif not all(t['reading_kind'] == 'hiragana' for t in tokens):
        status = 'pending_non_kana_reading'
    elif not (1 <= len(reading) <= 128 and 1 <= len(surface) <= 256):
        status = 'pending_input_extent'
    elif not any(unicodedata.name(c, '').startswith('CJK UNIFIED IDEOGRAPH-') for c in surface):
        status = 'pending_no_kanji_target'
    hypothesis = None
    if status == 'ready_for_history':
        hypothesis = dict(stable_id=sid, population='evaluation', source=source,
            input_hash=canonical_json_hash(['', reading]), left_context='', reading=reading,
            source_surface=surface, bunsetsu_index=index, token_start=start, token_end=end,
            surface_start=sum(len(t['annotated_surface']) for t in parsed['tokens'][:start]),
            surface_end=sum(len(t['annotated_surface']) for t in parsed['tokens'][:end]))
    return dict(index=slot['index'], status=status, source_coverage=coverage, input=hypothesis,
        selected_bunsetsu=index, bunsetsu_count=len(groups), annotation_tokens=len(parsed['tokens']),
        original_source_surface_certified=False, ime_input_boundary_certified=False,
        author_mapping_verified=False, training_admission=False, gold_admission=False,
        calibration=False, final_test=False)


def exclude_alias_components(components, input_hashes, historical_aliases):
    """All aliases are already consumed inputs, so their touched components fail.

    No extra history node or fake input is needed. Old source relations remain in
    the full graph; this overlay can only exclude, never restore a component.
    """
    require(set(components) == set(input_hashes), 'knbc_alias_input_extent')
    touched = {components[key] for key, digest in input_hashes.items() if digest in historical_aliases}
    return {key for key, component in components.items() if component in touched}


def classify_frame(records, historical_aliases, exposed_sources):
    """Classify one complete graph without rebuilding it for each exposure view."""
    graph = build_source_graph(records)
    labels = component_labels(graph)
    exposed = set(exposed_sources)
    found = {r['stable_id'] for r in graph.records if r['population'] == 'source_coverage'}
    require(exposed <= found, 'knbc_frame_unknown_exposed_source')
    blocked = {labels[i] for i, r in enumerate(graph.records)
               if r['population'] == 'historical' or r['stable_id'] in exposed}
    input_rows = [(i, r) for i, r in enumerate(graph.records) if r['population'] == 'evaluation']
    require(not any(r['population'] == 'train' for r in graph.records), 'knbc_frame_train_role')
    wanted = {labels[i] for i, _ in input_rows}
    members = {label:[] for label in wanted}
    for i, row in enumerate(graph.records):
        if labels[i] in members:
            members[labels[i]].append(row['stable_id'])
    identities = {label:canonical_json_hash(ids) for label, ids in members.items()}
    components = {r['stable_id']:identities[labels[i]] for i, r in input_rows}
    hashes = {r['stable_id']:r['input_hash'] for _, r in input_rows}
    aliases = exclude_alias_components(components, hashes, historical_aliases)
    excluded = {r['stable_id']:'historical_or_consumed_source_relation'
                for i, r in input_rows if labels[i] in blocked}
    for key in aliases:
        excluded.setdefault(key, 'historical_input_alias_relation')
    return excluded, components, dict(graph.audit, exposed_source_nodes=len(exposed),
        historical_alias_hashes=len(historical_aliases), alias_connected_new_inputs=len(aliases))
