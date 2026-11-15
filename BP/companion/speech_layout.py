# -*- coding: utf-8 -*-
"""Bounded Chinese/Latin speech lines; every page retains the full message."""
import math

HEAD_OFFSET = (0., .85, 0.)
MAX_DISTANCE = 16.
SPEECH_DEFAULTS = {'speech_enabled': True, 'speech_offset_x': 0, 'speech_offset_y': 0}
SPEECH_OFFSET_LIMITS = {'speech_offset_x': (-60, 60), 'speech_offset_y': (-30, 100)}


def speech_preferences(values):
    """Read display-only owner preferences, with bounded safe legacy defaults."""
    values=values or {};result=dict(SPEECH_DEFAULTS)
    if type(values.get('speech_enabled')) is bool:result['speech_enabled']=values['speech_enabled']
    for key,(low,high) in SPEECH_OFFSET_LIMITS.items():
        value=values.get(key,0)
        if type(value) is bool:continue
        try:value=float(value)
        except (TypeError,ValueError,OverflowError):continue
        if math.isnan(value) or math.isinf(value):continue
        result[key]=max(low,min(high,int(round(value))))
    return result


def bubble_position(scale,offset_x=0,offset_y=0):
    """Translate the complete bubble relative to its native head projection.

    Positive vertical preference raises the bubble. Both axes follow the same
    distance scale as the panel and glyphs, so moving away cannot leave a large
    fixed screen-space gap between a tiny companion and its speech.
    """
    width,height=156*scale,78*scale
    return ((156-width)/2.+offset_x*scale,39-height-2-offset_y*scale)


def bubble_scale(foot, camera, forward):
    """World-bound tip; size only changes the panel extending above that tip."""
    if not foot or not camera or not forward:return None
    delta=tuple(foot[i]+HEAD_OFFSET[i]-camera[i] for i in range(3))
    if sum(delta[i]*forward[i] for i in range(3))<=0:return None
    distance=math.sqrt(sum(value*value for value in delta))
    if distance>MAX_DISTANCE:return None
    # Keep close speech readable; shrink the background AND glyphs together.
    return round(max(.6,min(1.,4./max(1.,distance))),2)


def units(char):
    code=ord(char)
    if 0x300<=code<=0x36f or code in (0x200d,0xfe0f):return 0
    return 2 if code>=0x1100 and not 0x2000<=code<0x2e80 else 1


def pages(message, width=26, rows=3):
    lines=[]
    for paragraph in message.replace(u'\r\n',u'\n').replace(u'\r',u'\n').split(u'\n'):
        total=sum(units(c) for c in paragraph)
        count=max(1,(total+width-1)//width)
        limit=min(width,max(2,(total+count-1)//count))
        line=u'';used=0
        for char in paragraph:
            amount=units(char)
            if line and used+amount>limit:
                # A punctuation mark belongs with the previous character.
                carry=u''
                if char in u'，。！？、；：）】》…' and len(line)>1:
                    carry=line[-1];line=line[:-1]
                lines.append(line.rstrip());line=carry;used=sum(units(c) for c in carry)
            if not line and char.isspace():continue
            line+=char;used+=amount
        lines.append(line.rstrip())
    return [u'\n'.join(lines[i:i+rows]) for i in range(0,len(lines),rows)]
