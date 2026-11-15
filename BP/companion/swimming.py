# -*- coding: utf-8 -*-
"""Collision-aware water motion shared by following, pursuit and resting."""
from __future__ import division
import math
import mod.server.extraServerApi as api

F=api.GetEngineCompFactory()
WATER=('minecraft:water','minecraft:flowing_water')
CLEAR=WATER+('minecraft:air','minecraft:cave_air')
DANGEROUS=('minecraft:lava','minecraft:flowing_lava','minecraft:fire','minecraft:soul_fire',
           'minecraft:magma','minecraft:cactus','minecraft:campfire','minecraft:soul_campfire')
RADIUS=.21
HEIGHT=.86


class Swimming(object):
    def __init__(self,system):self.s=system

    def block(self,point,dim):
        p=tuple(int(math.floor(v)) for v in point)
        return (F.CreateBlockInfo(self.s.level).GetBlockNew(p,dim) or {}).get('name')

    def wet(self,point,dim,height=.2):
        return bool(point and self.block((point[0],point[1]+height,point[2]),dim) in WATER)

    def grounded(self,point,dim):
        block=F.CreateBlockInfo(self.s.level)
        for dx,dz in ((0,0),(-.19,-.19),(-.19,.19),(.19,-.19),(.19,.19)):
            x,z=point[0]+dx,point[2]+dz
            cell=(int(math.floor(x)),int(math.floor(point[1]-.04)),int(math.floor(z)))
            box=block.GetBlockCollision(cell,dim) or {};low,high=box.get('min'),box.get('max')
            if low and high and high[1]>low[1] and abs(high[1]-point[1])<.08 and low[0]<=x<=high[0] and low[2]<=z<=high[2]:return True
        return False

    def space(self,point,dim,cache=None):
        # Test the whole body, including its head and both sides. Centre rays
        # miss corners, low ceilings and partially closed passages.
        cache={} if cache is None else cache
        low=(point[0]-RADIUS+.005,point[1]+.015,point[2]-RADIUS+.005)
        high=(point[0]+RADIUS-.005,point[1]+HEIGHT-.015,point[2]+RADIUS-.005)
        block=F.CreateBlockInfo(self.s.level)
        for x in range(int(math.floor(low[0])),int(math.floor(high[0]))+1):
            for y in range(int(math.floor(low[1])),int(math.floor(high[1]))+1):
                for z in range(int(math.floor(low[2])),int(math.floor(high[2]))+1):
                    cell=(x,y,z)
                    if cell not in cache:
                        name=(block.GetBlockNew(cell,dim) or {}).get('name')
                        cache[cell]=(name,None if name in CLEAR else block.GetBlockCollision(cell,dim))
                    name,box=cache[cell]
                    if not name or name in DANGEROUS:return False
                    if name in CLEAR:continue
                    if not box:return False
                    a,b=box.get('min'),box.get('max')
                    if not a or not b:return False
                    if all(b[i]>a[i] and high[i]>a[i]+.001 and low[i]<b[i]-.001 for i in range(3)):return False
        return True

    def clear(self,start,end,dim):
        length=math.sqrt(sum((end[i]-start[i])**2 for i in range(3)))
        if length>24:return False
        count=max(1,int(math.ceil(length/.3)));cache={}
        for i in range(count+1):
            p=tuple(start[a]+(end[a]-start[a])*i/count for a in range(3))
            if not self.space(p,dim,cache):return False
        return True

    def drive(self,record,target,speed=1,turn=True):
        entity=record['entity_id'];rt=self.s.rt(record);pos=self.s.pos(entity)
        if not rt.get('swim_direct'):
            self.s.stop(entity);rt['swim_direct']=True
        if turn:
            goal=rt.get('swim_goal')
            if goal is None or (self.s.ticks-rt['last_path']>=18 and sum((target[i]-goal[i])**2 for i in range(3))>.4**2):
                # Keep native steering aimed at the same destination. A path
                # to our old position otherwise fights every swim impulse.
                F.CreateMoveTo(entity).SetMoveSetting(tuple(target),speed,200,self.s.path_done)
                rt['swim_goal']=tuple(target);rt['last_path']=self.s.ticks
        delta=[target[i]-pos[i] for i in range(3)];flat=math.hypot(delta[0],delta[2])
        velocity=min(.18,max(.05,.13*speed),flat*.16)
        desired=(delta[0]/max(.01,flat)*velocity,max(-.16,min(.18,delta[1]*.22))+.025,
                 delta[2]/max(.01,flat)*velocity)
        current=F.CreateActorMotion(entity).GetMotion() or (0,0,0)
        F.CreateActorMotion(entity).SetMotion(tuple(current[i]*.25+desired[i]*.75 for i in range(3)))
        if turn and flat>.2:
            rotation=F.CreateRot(entity);old=rotation.GetRot()[1]
            yaw=math.degrees(math.atan2(-delta[0],delta[2]));change=(yaw-old+180)%360-180
            rotation.SetRot((0,old+max(-12,min(12,change))))

    def hold(self,record):
        entity=record['entity_id'];rt=self.s.rt(record);pos=self.s.pos(entity)
        if not self.wet(pos,self.s.dim(entity)):
            rt.pop('swim_hold',None);return False
        # Keep depth during a swing, a panel or waiting instead of sinking
        # throughout the animation and then cancelling an out-of-range hit.
        if 'swim_hold' not in rt:self.s.stop(entity)
        depth=rt.setdefault('swim_hold',pos[1])
        self.drive(record,(pos[0],depth,pos[2]),turn=False)
        return True

    def step(self,record,target):
        """A bounded physical jump only after native movement stalls at a step."""
        entity=record['entity_id'];rt=self.s.rt(record);pos=self.s.pos(entity);dim=self.s.dim(entity)
        if self.s.ticks<rt.get('step_next',0):return
        progress=rt.get('move_progress')
        if not progress or sum((pos[i]-progress[0][i])**2 for i in range(3))>.12**2:
            rt['move_progress']=(pos,self.s.ticks);return
        if self.s.ticks-progress[1]<12:return
        current=F.CreateActorMotion(entity).GetMotion() or (0,0,0)
        wet=self.wet(pos,dim)
        if not wet and abs(current[1])>.12:return
        flat=math.hypot(target[0]-pos[0],target[2]-pos[2])
        if flat<.1:return
        dx,dz=(target[0]-pos[0])/flat,(target[2]-pos[2])/flat
        block=F.CreateBlockInfo(self.s.level)
        if not wet and not self.grounded(pos,dim):return
        for reach in (.55,.85):
            x,z=pos[0]+dx*reach,pos[2]+dz*reach
            cell=(int(math.floor(x)),int(math.floor(pos[1]+.1)),int(math.floor(z)))
            name=self.block(cell,dim)
            if not name or name in CLEAR or name in DANGEROUS:continue
            box=block.GetBlockCollision(cell,dim) or {};top=(box.get('max') or (0,0,0))[1]
            rise=top-pos[1]
            if not .1<rise<=1.05:continue
            landing=(x,top,z);apex=(pos[0],top+.15,pos[2])
            if not self.clear(pos,apex,dim) or not self.clear(apex,(x,top+.15,z),dim) or not self.space(landing,dim):continue
            # Native gravity and collision complete the jump; never SetFootPos.
            F.CreateActorMotion(entity).SetMotion((dx*.13,.42,dz*.13))
            rt['step_next']=self.s.ticks+24;rt.pop('move_progress',None);return True

    def move(self,record,target,speed):
        entity=record['entity_id'];rt=self.s.rt(record);pos=self.s.pos(entity);dim=self.s.dim(entity)
        if rt.pop('swim_hold',None) is not None:rt['swim_direct']=False
        if not self.wet(pos,dim):
            if rt.pop('swim_direct',False):rt['last_path']=-100
            # NetEase rejects a new ground path while airborne (-3). Reissuing
            # it during a jump can replace the route that was climbing the step.
            if not self.grounded(pos,dim):return True
            return bool(self.step(record,target))
        if self.clear(pos,target,dim):
            self.drive(record,target,speed);return True
        if rt.pop('swim_direct',False):rt['last_path']=-100
        # Let amphibious navigation route around obstructions. Only assist the
        # rise while submerged, or a verified one-block shore jump.
        if target[1]>pos[1]+.3 and self.wet(pos,dim,.8) and self.clear(pos,(pos[0],pos[1]+.35,pos[2]),dim):
            motion=F.CreateActorMotion(entity).GetMotion() or (0,0,0)
            F.CreateActorMotion(entity).SetMotion((motion[0],.18,motion[2]))
        elif self.step(record,target):return True
        return False

    def tick(self,player,record):
        entity=record['entity_id'];rt=self.s.rt(record)
        p=self.s.pos(player);pos=self.s.pos(entity);dim=self.s.dim(entity)
        owner_wet=self.wet(p,dim);wet=self.wet(pos,dim)
        if not owner_wet and not wet:
            rt['swim_follow']=False;rt['swim_direct']=False;rt.pop('swim_hold',None);return False
        rt['swim_follow']=True
        if not owner_wet:
            target=self.s.safe(p,dim) or self.s.near_spot(player) or p
        else:
            flat=math.hypot(pos[0]-p[0],pos[2]-p[2]);spacing=min(1.15,flat) if wet else 0
            target=(p[0]+(pos[0]-p[0])*spacing/max(.01,flat),
                    p[1]+(.25 if self.wet(p,dim,1.4) else .75),
                    p[2]+(pos[2]-p[2])*spacing/max(.01,flat))
            # The offset may fall inside a wall; the owner's column can still
            # provide a valid water destination for native navigation.
            if not self.space(target,dim):target=(p[0],p[1]+.25,p[2])
        self.s.move(record,target,1.3)
        rt['follow_chasing']=False;rt['follow_resting']=False
        return True
