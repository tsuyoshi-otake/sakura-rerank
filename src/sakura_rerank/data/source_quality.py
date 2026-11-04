"""Versioned source-quality flags over exactly the model-visible left context.

Flags quarantine an automatic training example; they neither repair its label
nor prove that the Japanese is wrong. Literal TeX/empty-title discussions can
also trigger. The immutable source and the original evaluation denominator stay.
"""
from __future__ import annotations

import re

from .contracts import MAX_LEFT_CONTEXT_CHARS, MAX_SURFACE_CHARS

QUALITY_CLEANER_VERSION = 'conservative_wikitext_v5'
QUALITY_MANIFEST_SCHEMA_VERSION = 5
QUALITY_POLICY = 'bounded_left64_target_tex_empty_title_v1'
QUALITY_REASONS = ('tex_command_residue', 'empty_title_delimiters')

# Fixed, bounded command vocabulary, not an open-ended backslash-word detector.
# Ordinary braces, nonempty titles and kanji adjacency alone do not trigger.
# A path containing a listed command token can trigger; this is quarantine,
# not a claim that every flagged text is malformed or its label incorrect.
TEX_COMMANDS = (
    'mbox', 'hbox', 'text', 'textrm', 'textbf', 'textit', 'mathrm', 'mathbf',
    'mathit', 'mathbb', 'mathcal', 'mathsf', 'mathtt', 'frac', 'dfrac', 'tfrac',
    'sqrt', 'begin', 'end', 'left', 'right', 'over', 'underbrace', 'overbrace',
    'in', 'notin', 'subset', 'subseteq', 'supset', 'supseteq', 'leq', 'geq',
    'neq', 'equiv', 'forall', 'exists', 'sum', 'prod', 'int', 'lim', 'infty',
    'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta', 'lambda', 'mu',
    'pi', 'sigma', 'phi', 'omega', 'times', 'cdot', 'ldots', 'cdots',
)
_TEX_COMMAND = re.compile(r'\\(?:' + '|'.join(TEX_COMMANDS) + r')(?![A-Za-z])')
_EMPTY_TITLE = re.compile(r'『\s*』')


def quality_flags(left_context: str, target: str) -> tuple[str, ...]:
    """Return every matching rule in fixed order, using no unseen continuation.

    Callers must supply the already bounded, exact strings, not a full sentence.
    A rejected bound is an error rather than a silently truncated observation.
    """
    if (not isinstance(left_context, str) or not isinstance(target, str)
            or len(left_context) > MAX_LEFT_CONTEXT_CHARS
            or not 1 <= len(target) <= MAX_SURFACE_CHARS):
        raise ValueError('source-quality input exceeds left-context/target contract')
    text = left_context + target
    return tuple(reason for reason, matched in (
        (QUALITY_REASONS[0], _TEX_COMMAND.search(text) is not None),
        (QUALITY_REASONS[1], _EMPTY_TITLE.search(text) is not None),
    ) if matched)
