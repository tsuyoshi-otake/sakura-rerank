"""Causal next-character windows from admitted source fragments, not IME labels."""
from .contracts import canonical_json_hash,text_sha256


def fragment_windows(text,maximum_positions=6):
    if not isinstance(text,str) or not 1<=maximum_positions<=6 or not 9<=len(text)<=128:
        raise ValueError("language_fragment_bounds")
    identity=text_sha256(text)
    positions=sorted(range(8,len(text)),key=lambda p:(canonical_json_hash([20261105,"lm-position",identity,p]),p))[:maximum_positions]
    return [dict(window_id=canonical_json_hash([text[max(0,p-64):p],text[p]]),
                 context=text[max(0,p-64):p],next_character=text[p],position=p,fragment_sha256=identity) for p in positions]
