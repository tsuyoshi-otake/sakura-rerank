"""Reserve and inspect KNBC source annotations without creating IME labels.

Metadata selection precedes text access. Provider surface, reading, lemma and
notes remain separate; absence of a detected marker is never Gold admission.
"""
from collections import Counter, defaultdict
import re
import unicodedata

from .contracts import canonical_json_hash

ARCHIVE_ROOT = 'KNBC_v1.0_090925_utf8'
MAX_BYTES = 65536
MAX_LINES = 6000
MAX_TOKENS = 4096
SID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
STRUCTURE = re.compile(r'^[*+] (?:[0-9]+ )?-?[0-9]+[DPIA](?: |$)')


def require(condition, code):
    if not condition:
        raise ValueError(code)


def reserve_slots(inventory, archive_sha256, *, seed=20261106, articles=20, slots_per_article=5):
    """Keep unclassified file cases explicitly; never select on corpus text."""
    require(re.fullmatch(r'[0-9a-f]{64}', archive_sha256) is not None, 'knbc_archive_identity')
    require(type(articles) is int and 1 <= articles <= 20
            and type(slots_per_article) is int and 1 <= slots_per_article <= 5, 'knbc_selection_bound')
    require(type(inventory) is list and len(inventory) <= 20000, 'knbc_inventory_bound')
    groups, unclassified, seen, metadata = defaultdict(list), defaultdict(list), set(), 0
    for row in inventory:
        name = row['name']
        require(isinstance(name,str) and len(name)<=512 and '\\' not in name
                and ':' not in name and not any(ord(c)<32 for c in name), 'knbc_member_name')
        parts = name.split('/')
        if parts[:2] != [ARCHIVE_ROOT, 'corpus1'] or row['kind'] != 'file':
            continue
        require(len(parts)==4 and all(p and p not in ('.','..') for p in parts), 'knbc_member_path')
        require(name not in seen, 'knbc_duplicate_path')
        seen.add(name)
        if parts[3]=='fileinfos':
            metadata += 1
            continue
        require(type(row['bytes']) is int and 0 < row['bytes'] <= MAX_BYTES, 'knbc_member_size')
        article, base = parts[2:]
        require(SID.fullmatch(article) is not None, 'knbc_article_identity')
        matching = re.fullmatch(re.escape(article)+r'(?:-[0-9]+)+', base) is not None
        selected = dict(path=name,archive_name=row.get('archive_name',name),bytes=row['bytes'],
                        article=article,family=article.split('_')[0],
                        role='sentence_candidate' if matching else 'unclassified_member')
        groups[article].append(selected)
        if not matching:
            unclassified[article].append(selected)
    require(len(groups)>=articles and len(unclassified)<=articles, 'knbc_article_capacity')
    require(all(len(v)<=slots_per_article for v in unclassified.values()), 'knbc_unknown_capacity')
    rank = lambda value: (canonical_json_hash(['knbc-format-v1',seed,archive_sha256,value]),value)
    forced = sorted(unclassified,key=rank)
    chosen = forced + sorted(set(groups)-set(forced),key=rank)[:articles-len(forced)]
    slots=[]
    for article in chosen:
        known_unknown = sorted(unclassified[article],key=lambda r:rank(r['path']))
        ordinary = sorted((r for r in groups[article] if r['role']=='sentence_candidate'),key=lambda r:rank(r['path']))
        selected = (known_unknown+ordinary)[:slots_per_article]
        for offset in range(slots_per_article):
            row = selected[offset] if offset<len(selected) else dict(path=None,archive_name=None,bytes=0,
                    article=article,family=article.split('_')[0],role='missing_metadata_slot')
            slots.append(dict(row,index=len(slots),selection_reason='metadata_exception_article' if article in forced else 'hash_selected_article'))
    census = dict(article_groups=len(groups),prefix_families=len({a.split('_')[0] for a in groups}),
        candidate_files=sum(r['role']=='sentence_candidate' for v in groups.values() for r in v),
        unclassified_files=sum(map(len,unclassified.values())),fileinfos_files=metadata,
        selected_articles=len(chosen),selected_prefix_families=len({a.split('_')[0] for a in chosen}),
        forced_exception_articles=len(forced),slots=len(slots),roles=dict(Counter(r['role'] for r in slots)))
    return dict(kind='knbc_source_format_reservation',seed=seed,archive_sha256=archive_sha256,
                census=census,slots=slots,selection_sha256=canonical_json_hash(slots),
                author_mapping_verified=False,training_admission=False,gold_admission=False,final_test=False)


def reading_kind(surface, reading):
    if reading in ('*','NIL'):
        return 'missing'
    if all('\u3041'<=c<='\u3096' or c=='ー' for c in reading):
        return 'hiragana'
    if all('\u3041'<=c<='\u3096' or '\u30a1'<=c<='\u30f6' or c=='ー' for c in reading):
        return 'kana_projection_possible'
    if reading==surface and all(unicodedata.category(c)[0] in 'PS' for c in reading):
        return 'literal_symbol'
    return 'unsupported_for_kana_input'


def flags(text):
    result=[]
    if 'ER:' in text or 'ER：' in text:
        result.append('provider_correction_marker')
    if any(s in text for s in ('原形曖昧','読み曖昧','品詞曖昧')):
        result.append('provider_ambiguity_marker')
    if any(s in text for s in ('スラング:','スラング：','言い淀み','言い直し')):
        result.append('provider_style_marker')
    return result


def morpheme(line):
    fields=line.split(maxsplit=11)
    require(len(fields)>=11 and all(re.fullmatch(r'[0-9]+',fields[i]) for i in (4,6,8,10)), 'knbc_morpheme_columns')
    notes=fields[11] if len(fields)==12 else ''
    return dict(annotated_surface=fields[0],annotated_reading=fields[1],lemma=fields[2],
                grammatical_fields=fields[3:11],notes=notes,flags=flags(notes),
                reading_kind=reading_kind(fields[0],fields[1]),alternatives=[])


def parse_member(raw, *, expected_sid=None):
    """Parse one complete annotation unit; keep corrected/source identity unknown."""
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_BYTES, 'knbc_document_bound')
    require(expected_sid is None or (isinstance(expected_sid,str) and SID.fullmatch(expected_sid)), 'knbc_expected_identity')
    text=raw.decode('utf-8',errors='strict')
    require('\0' not in text, 'knbc_nul')
    lines=text.splitlines()
    require(len(lines)<=MAX_LINES and all(len(line.encode('utf-8'))<=16384 for line in lines), 'knbc_line_bound')
    state='before_header'; sid=None; tokens=[]; structures=[]; header=None; alternatives=0
    for line in lines:
        if not line:
            continue
        if state=='before_header':
            match=re.fullmatch(r'# S-ID:\s*([A-Za-z0-9_-]{1,128})(?: .*)?',line)
            require(match is not None, 'knbc_header')
            sid=match[1]
            require(expected_sid is None or sid==expected_sid, 'knbc_foreign_sid')
            header=line;state='morphemes';continue
        require(state=='morphemes', 'knbc_after_eos')
        if line=='EOS':
            require(tokens, 'knbc_empty_sentence')
            state='complete';continue
        if STRUCTURE.match(line):
            structures.append(line);continue
        if line.startswith('@ '):
            require(tokens and alternatives<MAX_TOKENS, 'knbc_orphan_or_bound_alternative')
            tokens[-1]['alternatives'].append(morpheme(line[2:]));alternatives+=1;continue
        require(not line.startswith(('#','* ','+ ')), 'knbc_unknown_structure')
        require(len(tokens)<MAX_TOKENS, 'knbc_token_bound')
        tokens.append(morpheme(line))
    require(state=='complete', 'knbc_missing_eos')
    document_flags=set(flags(header))
    for line in structures:
        document_flags.update(flags(line))
    for token in tokens:
        document_flags.update(token['flags'])
        for alternative in token['alternatives']:
            document_flags.update(alternative['flags'])
    if alternatives:
        document_flags.add('alternative_annotation')
    return dict(kind='knbc_annotation_not_gold',sid=sid,header=header,structures=structures,tokens=tokens,
        annotation_surface=''.join(t['annotated_surface'] for t in tokens),
        annotation_reading=''.join(t['annotated_reading'] for t in tokens),
        flags=sorted(document_flags),alternative_rows=alternatives,
        original_source_surface_verified=False,author_mapping_verified=False,
        ime_input_boundary_verified=False,training_admission=False,gold_admission=False,final_test=False)
