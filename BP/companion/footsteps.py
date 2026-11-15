# -*- coding: utf-8 -*-
"""Contact events share the rendered gait clock; held dolls never emit steps."""
from __future__ import division


class Footsteps(object):
    def __init__(self):
        self.previous = None
        self.style = None
        self.events = 0
        self.last_phase = None

    def step(self, phase, eligible, q_style=False, run=0):
        phase = phase % 1.0
        previous = self.previous
        self.previous = phase
        if not eligible or previous is None or self.style != q_style:
            self.style = q_style
            return []
        advance = (phase-previous) % 1.0
        if advance <= 0 or advance > .2:
            return []
        offset = (.3889 + .0278*max(0, min(1, run))) if q_style else 0.0
        result = []
        for marker, side in ((offset, 'left'), ((offset+.5) % 1, 'right')):
            crossed = (marker-previous) % 1.0
            if 0 < crossed <= advance + .000001:
                result.append(side)
                self.events += 1
                self.last_phase = phase
        return result
