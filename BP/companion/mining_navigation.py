# -*- coding: utf-8 -*-
"""Bounded mining geometry and timing. No world effects or engine imports."""
from __future__ import division
import math
from .navigation_rules import PASSABLE

REACH = 2.1
SEARCH_BUDGET = 24
STAND_BUDGET = 32
SCAN_TICKS = 90
OPENING_LIMIT = 2
OPENING_BREAK_LIMIT = 4
STAIR_DEPTH = 8
CARDINAL = ((1,0),(-1,0),(0,1),(0,-1))
SIDES = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
NATURAL_STONE = frozenset('minecraft:'+name for name in (
    'stone','granite','diorite','andesite','deepslate','tuff','calcite',
    'netherrack','end_stone','basalt','smooth_basalt','blackstone','dripstone_block'))
FLUIDS = frozenset('minecraft:'+name for name in (
    'water','flowing_water','lava','flowing_lava','bubble_column','powder_snow'))
FALLING = frozenset(('minecraft:sand','minecraft:gravel','minecraft:concrete_powder'))
PROTECTED_WORDS = ('chest','barrel','furnace','hopper','dispenser','dropper','shulker',
    'spawner','command_block','portal','structure_block','jigsaw')


def squared(a,b):return sum((a[i]-b[i])**2 for i in range(3))


def natural(block):
    name=(block or {}).get('name')
    return name in NATURAL_STONE and (name!='minecraft:stone' or block.get('aux',0) in (0,1,3,5))


def ore(block):
    name=(block or {}).get('name','')
    return name.endswith('_ore') or name=='minecraft:ancient_debris'

def soil(block):
    return (block or {}).get('name') in ('minecraft:dirt','minecraft:grass','minecraft:grass_block')


def stair_step(get, origin, direction):
    """A one-block drop with two clear cells and a solid, retained landing."""
    x,y,z=origin
    dx,dz=direction
    landing=(x+dx,y-1,z+dz)
    support=get((landing[0],landing[1]-1,landing[2]))
    if not (natural(support) or soil(support) or ore(support)):
        return None
    blocks=[]
    for height in (1,0):
        cell=(landing[0],landing[1]+height,landing[2])
        block=get(cell)
        if (block or {}).get('name') in PASSABLE:
            continue
        if not (natural(block) or soil(block) or ore(block)) or hazard(get,cell):
            return None
        blocks.append(cell)
    return landing,blocks


def face(eye,block):
    """Aim just inside the nearest block face, not through half a block to its centre."""
    return tuple(max(block[i]+.03,min(block[i]+.97,eye[i])) for i in range(3))


def neighbours(block):
    return [tuple(block[i]+delta[i] for i in range(3)) for delta in SIDES]


def exposed(get,block):
    return any((get(p) or {}).get('name') in PASSABLE for p in neighbours(block))


def hazard(get,block):
    """Do not release liquids/falling material or cut next to functional storage."""
    for p in neighbours(block):
        value=get(p)
        if not value:return True
        name=value.get('name','')
        if name in FLUIDS or any(word in name for word in PROTECTED_WORDS):return True
        if p[1]>block[1] and name in FALLING:return True
    return False


def stand_cells(block,position):
    # Radius two allows a valid working face across a narrow gap. Every cell
    # still needs native safe-ground and line-of-sight checks before navigation.
    points=[]
    for dx in range(-2,3):
        for dz in range(-2,3):
            if dx==0 and dz==0:continue
            for dy in (-1,0,1):
                p=(block[0]+.5+dx,float(block[1]+dy),block[2]+.5+dz)
                eye=(p[0],p[1]+.65,p[2])
                if abs(p[1]-position[1])<=4 and squared(eye,face(eye,block))<=REACH**2:
                    points.append(p)
    return sorted(points,key=lambda p:(squared(p,position),abs(p[1]-position[1])))


def shallow_routes(get,goal,maximum=OPENING_LIMIT):
    """Only paths through up to two natural blocks touching an ore/sample goal.

    Return outermost-first routes; callers must prove the outer block has a
    real working stand and validate every break again through native APIs.
    """
    queue=[(tuple(goal),[])];seen=set([tuple(goal)]);routes=[]
    while queue:
        point,path=queue.pop(0)
        if len(path)>=maximum:continue
        for candidate in neighbours(point):
            if candidate in seen:continue
            seen.add(candidate)
            if not natural(get(candidate)) or hazard(get,candidate):continue
            branch=[candidate]+path
            if exposed(get,candidate):routes.append(branch)
            queue.append((candidate,branch))
    # A two-high passage may need its upper half removed after its lower
    # block. Only clear above an already open cell in the same two layers;
    # never use this clearance rule to extend a tunnel farther from the goal.
    for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
        for depth in range(1,maximum+1):
            lower=(goal[0]+dx*depth,goal[1],goal[2]+dz*depth)
            upper=(lower[0],lower[1]+1,lower[2])
            if ((get(lower) or {}).get('name') in PASSABLE and natural(get(upper)) and
                    not hazard(get,upper) and exposed(get,upper)):
                routes.append([upper])
    return routes


def break_ticks(seconds):
    """Keep native hardness/tool/efficiency time, without one-second rounding."""
    if not isinstance(seconds,(int,float)) or math.isnan(seconds) or math.isinf(seconds):return None
    if seconds<0 or seconds>25:return None
    return max(6,int(math.ceil(seconds*30)))
