"""Exact source-unit hypotheses, not inferred words or verified IME labels.

Whole-source and maximal phonetic runs preserve every source character. Ruby
fragments remain a separately named diagnostic; they are never morphemes.
Only a fixed one-to-one katakana-to-hiragana input projection is allowed.
Unannotated Latin/digits/whitespace and unsupported readings remain explicit.
"""
from __future__ import annotations

from .input_boundary import request_id, score_view
from .tatoeba_source import SourceFormatError, parse_transcription
import unicodedata

VIEWS=('whole_source','literal_runs','ruby_fragments')
MAX_READING=128
MAX_TARGET=256
MAX_PARTS=32


def kana_projection(value: str) -> str | None:
    """One-to-one codepoint projection; do not expand vowels, guess or normalize."""
    projected=[]
    for char in value:
        if '\u3041'<=char<='\u3096' or char=='ー':projected.append(char)
        elif '\u30a1'<=char<='\u30f6':projected.append(chr(ord(char)-0x60))
        else:return None
    return ''.join(projected) if projected else None


def _part(reading,target,start,end):
    return dict(kind='convert',reading=reading,target=target,start=start,end=end,
                request_id=request_id(reading))


def _view(parts):
    convert=[p for p in parts if p['kind']=='convert']
    status=('no_phonetic_input' if not convert else 'part_bound' if len(convert)>MAX_PARTS else
            'input_bound' if any(not 1<=len(p['reading'])<=MAX_READING or not 1<=len(p['target'])<=MAX_TARGET for p in convert)
            else 'ready')
    return dict(status=status,conversion_parts=len(convert),parts=parts if status=='ready' else [])


def build_source_units(sentence: str, transcription: str) -> dict:
    """Return one terminal per view; source mismatch/unsupported data has no requests."""
    empty={name:dict(status='source_unresolved',parts=[]) for name in VIEWS}
    try:parsed=parse_transcription(transcription)
    except SourceFormatError as error:
        return dict(status=str(error),views=empty)
    if sentence!=parsed.surface:
        return dict(status='source_mismatch',views=empty)
    if not sentence or len(sentence)>10_000 or any(ord(c)<32 or ord(c)==127 for c in sentence):
        return dict(status='source_bound_or_control',views=empty)
    units=[];pos=0
    def literal_units(start,end):
        output=[]
        for index in range(start,end):
            char=sentence[index];projected=kana_projection(char)
            if projected is not None:
                output.append(dict(kind='phonetic',surface=char,reading=projected,start=index,end=index+1,
                                   origin='literal_kana',projected=projected!=char))
            elif unicodedata.category(char)[0] in 'PS':
                output.append(dict(kind='literal',surface=char,reading=char,start=index,end=index+1,origin='literal_symbol',projected=False))
            else:return None
        return output
    for span in parsed.spans:
        prefix=literal_units(pos,span.start);reading=kana_projection(span.reading)
        if prefix is None or reading is None:
            return dict(status='unsupported_source_or_reading',views=empty)
        units.extend(prefix)
        units.append(dict(kind='phonetic',surface=span.base,reading=reading,start=span.start,end=span.end,
                          origin='ruby',projected=reading!=span.reading))
        pos=span.end
    suffix=literal_units(pos,len(sentence))
    if suffix is None:return dict(status='unsupported_source_or_reading',views=empty)
    units.extend(suffix)
    transformed=sum(u['projected'] for u in units)
    if ''.join(u['surface'] for u in units)!=sentence:
        raise ValueError('unit35_units_do_not_reconstruct_source')
    reading=''.join(u['reading'] for u in units)
    runs=[];run=[];fragments=[]
    def flush():
        if run:
            runs.append(_part(''.join(u['reading'] for u in run),''.join(u['surface'] for u in run),run[0]['start'],run[-1]['end']))
            run.clear()
    for unit in units:
        if unit['kind']=='literal':
            flush();runs.append(dict(kind='literal',text=unit['surface'],start=unit['start'],end=unit['end']))
        else:run.append(unit)
        if unit['origin']=='ruby':fragments.append(_part(unit['reading'],unit['surface'],unit['start'],unit['end']))
    flush()
    views=dict(whole_source=_view([_part(reading,sentence,0,len(sentence))]) if any(u['kind']=='phonetic' for u in units)
               else dict(status='no_phonetic_input',parts=[]),literal_runs=_view(runs),ruby_fragments=_view(fragments))
    for name in ('whole_source','literal_runs'):
        view=views[name]
        if view['status']=='ready' and ''.join(p['text'] if p['kind']=='literal' else p['target'] for p in view['parts'])!=sentence:
            raise ValueError('unit35_view_does_not_reconstruct_source')
    return dict(status='source_projected_not_certified',target=sentence,reading=reading,units=units,
                projected_units=transformed,views=views,grammatical_boundary_verified=False,ime_gold=False)


def score_units(row,snapshots):
    """Whole rank and all-parts presence are separate denominators and claims."""
    return {name:score_view(row['views'][name],snapshots) for name in VIEWS}
