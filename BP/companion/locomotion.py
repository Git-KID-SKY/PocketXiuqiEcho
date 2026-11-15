# -*- coding: utf-8 -*-
"""Stable gait from 30 Hz script samples of 20 Hz entity movement."""
from __future__ import division


def continuous_angle(previous,value):
    return previous+(value-previous+180)%360-180


def is_teleport(delta, motion=None):
    # Native motion is blocks per physics tick. Fast falls legitimately move
    # over 1.5 blocks between samples; allow two ticks plus interpolation slack.
    motion = motion or (0, 0, 0)
    return any(abs(delta[i]) > max(1.5, abs(motion[i]) * 2.5 + .5) for i in range(3))


class Gait(object):
    def __init__(self):
        self.distances = [0.0, 0.0, 0.0]
        self.phase = 0.0
        self.speed = 0.0
        self.walk = 0.0
        self.run = 0.0
        self.moving = False

    def step(self, distance, teleported=False):
        if teleported:
            self.distances = [0.0, 0.0, 0.0]
            self.speed = self.walk = self.run = 0.0
            self.moving = False
            return
        self.distances.pop(0)
        self.distances.append(max(0.0, distance))
        self.speed = min(8.0, sum(self.distances) * 10.0)
        # Hysteresis prevents a repeated physics position from ending a stride.
        self.moving = self.speed > (0.06 if self.moving else 0.12)
        target = 1.0 if self.moving else 0.0
        self.walk += max(-0.2, min(0.2, target - self.walk))
        target_run = max(0.0, min(1.0, (self.speed - 2.4) / 1.2)) if self.moving else 0.0
        self.run += max(-0.15, min(0.15, target_run - self.run))
        # One full left/right stride per 0.8 blocks, capped for the short rig.
        # Always wrap: the native keyframe sampler must never see elapsed laps.
        if self.moving:
            self.phase = (self.phase + min(2.4, self.speed / 0.8) / 30.0) % 1.0
