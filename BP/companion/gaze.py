# -*- coding: utf-8 -*-
"""Bounded head-only attention with continuous angles and a quiet return to rest."""
from __future__ import division
import math


def wrap(angle):return (angle+180)%360-180


class Gaze(object):
    def __init__(self):self.pitch=0.;self.yaw=0.

    def step(self,origin,body_yaw,target,enabled=True,reset=False):
        if reset:self.pitch=0.;self.yaw=0.
        pitch=yaw=0.
        if enabled and target:
            dx,dy,dz=[target[i]-origin[i] for i in range(3)]
            flat=math.hypot(dx,dz)
            if flat>.15:
                angle=wrap(math.degrees(math.atan2(-dx,dz))-body_yaw)
                if abs(angle)<105:
                    yaw=max(-35,min(35,angle))
                    pitch=max(-24,min(16,-math.degrees(math.atan2(dy,flat))))
        for key,value in (('pitch',pitch),('yaw',yaw)):
            current=getattr(self,key);delta=(value-current)*.14
            setattr(self,key,current+max(-2.2,min(2.2,delta)))
        return self.pitch,self.yaw
