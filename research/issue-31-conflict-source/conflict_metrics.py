"""Descriptive conflicts, never normalization-based label admission."""
from collections import Counter, defaultdict
import unicodedata

TRANSFORMS = ('literal', 'nfc', 'nfkc', 'kana', 'case', 'kana_case')
CONTEXT_LENGTHS = (0, 1, 2, 4, 8, 16, 32, 64)


def transformed(text, rule):
    if not isinstance(text, str) or not text or rule not in TRANSFORMS:
        raise ValueError('conflict_notation_contract')
    if rule == 'literal':
        return text
    value = unicodedata.normalize('NFC' if rule == 'nfc' else 'NFKC', text)
    if rule in ('case', 'kana_case'):
        value = value.casefold()
    if rule in ('kana', 'kana_case'):
        value = ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in value)
    return value


def notation_class(targets):
    """First whole-group collapse in the fixed order; not semantic equivalence."""
    values = set(targets)
    if not values:
        raise ValueError('conflict_empty_targets')
    for rule in TRANSFORMS:
        if len({transformed(t, rule) for t in values}) == 1:
            return rule
    return 'distinct_after_all_mechanical_folds'


def census(keys, labels):
    """Single-source-label empirical bound for a deterministic input selector."""
    if not keys or len(keys) != len(labels) or len(keys) > 100000:
        raise ValueError('conflict_census_population')
    groups = defaultdict(Counter)
    for key, label in zip(keys, labels, strict=True):
        if type(label) is not int or not 0 <= label < 6:
            raise ValueError('conflict_census_label')
        groups[key][label] += 1
    conflicts = [counts for counts in groups.values() if len(counts) > 1]
    loss = sum(sum(c.values()) - max(c.values()) for c in conflicts)
    return dict(rows=len(keys), unique_inputs=len(groups),
                conflicting_groups=len(conflicts), conflicting_rows=sum(sum(c.values()) for c in conflicts),
                minimum_source_mismatches=loss, maximum_source_matches=len(keys)-loss,
                empirical_source_match_ceiling=(len(keys)-loss)/len(keys))


def mixture(keys, labels, strata):
    if len(strata) != len(keys) or any(s not in ('common_wikipedia', 'dictionary_aozora', 'annotation_aozora') for s in strata):
        raise ValueError('conflict_stratum_contract')
    groups = {}
    for stratum in sorted(set(strata)):
        positions = [i for i, s in enumerate(strata) if s == stratum]
        groups[stratum] = census([keys[i] for i in positions], [labels[i] for i in positions])
    overall = census(keys, labels)
    separate = sum(v['minimum_source_mismatches'] for v in groups.values())
    return dict(union=overall, strata=groups, separate_source_minimum_mismatches=separate,
                additional_mixture_mismatches=overall['minimum_source_mismatches']-separate)


def source_observation(text, start, end, target, left):
    """Exact source extents and character classes only; right side never a feature."""
    from sakura_rerank.data.annotation_contrast import char_class
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
            or text[start:end] != target or text[max(0, start-64):start] != left):
        raise ValueError('conflict_source_span_or_context')
    classes = dict(left=char_class(text[start-1:start] if start else ''),
                   first=char_class(text[start]), last=char_class(text[end-1]), right=char_class(text[end:end+1]))
    return dict(classes=classes, exact_source_span=True, exact_left_prefix=True,
                ime_input_unit='unresolved', meaning='not_reviewed', spelling_intent='not_reviewed')
