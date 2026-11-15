# -*- coding: utf-8 -*-
"""A size multiplier used only by the doll mounted on a player's back."""
DEFAULT_SCALE=1.
MIN_SCALE=.6
MAX_SCALE=1.5


def normalized_scale(value):
    if isinstance(value,bool):return DEFAULT_SCALE
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return DEFAULT_SCALE
    if not -float('inf')<value<float('inf'):return DEFAULT_SCALE
    return max(MIN_SCALE,min(MAX_SCALE,value))


def render_scale(settings,worn,is_player):
    if not is_player or not worn:return DEFAULT_SCALE
    return normalized_scale(settings.get('carry_scale',DEFAULT_SCALE))
