# -*- coding: utf-8 -*-
"""Context shared by following, jobs, delivery and speech. No inventory writes."""
import math
import time
import mod.server.extraServerApi as api
from .supply import food_slot
from .navigation_rules import WORK_LEASH, RETURN_RADIUS, independent

F=api.GetEngineCompFactory()
E=api.GetMinecraftEnum()


def target_key(job):
    if job.get('block') is not None:return ('block',job.get('dimension',0))+tuple(job['block'])
    return ('entity',job.get('entity'))


class Attention(object):
    def __init__(self,system):self.s=system

    def damage(self,args):
        if args.get('damage',0)<=0:return
        source=args.get('srcId');victim=args.get('entityId')
        for player in api.GetPlayerList():
            for record in self.s.owned(player):
                if victim in (player,record.get('entity_id')) and source!=player:
                    rt=self.s.rt(record);rt['danger_until']=self.s.ticks+150;rt['danger_source']=source

    def blocked(self,record,target):
        return self.s.rt(record).get('blocked_targets',{}).get(target_key(target),0)>self.s.ticks

    def defer(self,record,target,duration):
        rt=self.s.rt(record)
        blocked={k:v for k,v in rt.get('blocked_targets',{}).items() if v>self.s.ticks}
        key=target_key(target)
        if key not in blocked and len(blocked)>=32:blocked.pop(min(blocked,key=blocked.get))
        blocked[key]=self.s.ticks+duration;rt['blocked_targets']=blocked

    def stalled(self,player,record,job,position):
        rt=self.s.rt(record)
        if not job or not job.get('automatic') or job['kind']=='guard' or rt['action_until']>self.s.ticks:
            rt.pop('progress',None);return
        key=target_key(job);progress=rt.get('progress')
        if not progress or progress['key']!=key or sum((position[i]-progress['pos'][i])**2 for i in range(3))>.35**2:
            rt['progress']={'key':key,'pos':position,'at':self.s.ticks};return
        if self.s.ticks-progress['at']<150:return
        self.defer(record,job,600);rt.pop('progress',None)
        self.s.work.cancel(record);rt['mode_status']=u'这个目标暂时到不了，先换一个；20 秒后再检查'
        self.s.chatter.say(player,record,'stalled',u'这边过不去，我先换个目标，陪着你走～',1350)

    def tick(self,player,record):
        rt=self.s.rt(record);rt['pause_work']=None
        if record['state'] in ('waiting','hand_in_hand') or rt['hand_target'] or player in self.s.panels:return False
        entity=record['entity_id'];p=self.s.pos(player);v=self.s.pos(entity)
        gap=math.sqrt(sum((p[i]-v[i])**2 for i in range(3)))
        job=rt.get('job');mode=record['settings'].get('work_mode','follow')
        health=F.CreateAttr(entity).GetAttrValue(E.AttrType.HEALTH)
        battle=bool(job and job.get('kind') in ('melee','bow','guard'))
        if health>=12:rt['resting_hurt']=False
        elif health<=6 and (battle or rt.get('danger_until',0)>self.s.ticks):rt['resting_hurt']=True
        if independent(record):
            rt['catching_up']=False
            if rt.get('resting_hurt'):
                if job:self.s.work.cancel(record)
                rt['mode_status']=u'受伤停工，可在模组设置召回'
                self.s.hold(record)
                return True
            self.stalled(player,record,job,v)
            return False
        if job and job.get('automatic') and gap>WORK_LEASH:rt['catching_up']=True
        if gap<RETURN_RADIUS:rt['catching_up']=False
        # Severe hunger may interrupt automatic mining or strolling, never combat.
        hungry=False
        if not battle and (not job or job.get('automatic')) and mode in ('excavate','stroll','follow') and record['settings']['supply_mode']!='off' and time.time()>=record.get('supply_next_at',0) and self.s.ticks>=rt.get('supply_retry',0):
            hunger=F.CreatePlayer(player).GetPlayerHunger()
            if self.s.ticks>=rt.get('food_scan_at',0):
                rt['food_scan_at']=self.s.ticks+30;rt['player_has_food']=self.s.supply.player_has_food(player)
            hungry=hunger is not None and hunger<20 and food_slot(record) is not None and not rt.get('player_has_food',True)
        if rt.get('resting_hurt'):
            rt['pause_work']=u'血量低，暂停工作并靠近你；收回休整后继续'
        elif rt.get('catching_up'):
            rt['pause_work']=u'先跟上你，靠近后继续原来的工作'
        elif hungry and rt.get('danger_until',0)<=self.s.ticks:
            rt['pause_work']=u'先靠近你递食物，补给后继续原来的工作'
        if rt['pause_work']:
            if job:self.s.work.cancel(record)
            rt['mode_status']=rt['pause_work']
            if hungry and not rt.get('resting_hurt') and gap>2 and gap<8:
                target=self.s.safe(p,self.s.dim(player))
                if target:self.s.move(record,target,1.15);return True
            return False
        self.stalled(player,record,job,v)
        if rt.get('job') or rt['offering'] is not None:return False
        if self.s.swimming.wet(p,self.s.dim(player)) or self.s.swimming.wet(v,self.s.dim(entity)):return False
        # Step aside only for a moving player, never for camera rotation alone.
        until=rt.get('yield_until',0)
        if until>self.s.ticks:
            target=rt.get('yield_target')
            if target and math.hypot(target[0]-v[0],target[2]-v[2])>.3:self.s.move(record,target,.9);return True
            rt['yield_until']=0;self.s.stop(entity)
        if gap<1.3 and self.s.ticks>=rt.get('yield_next',0):
            motion=F.CreateActorMotion(player).GetMotion() or (0,0,0);speed=math.hypot(motion[0],motion[2])
            if speed>.04 and abs(motion[1])<.12:
                dx,dz=v[0]-p[0],v[2]-p[2];ahead=(dx*motion[0]+dz*motion[2])/speed
                if 0<ahead<1.3 and abs(dx*motion[2]-dz*motion[0])/speed<.6:
                    side=1 if dx*motion[2]-dz*motion[0]>=0 else -1
                    target=self.s.safe((v[0]+side*motion[2]/speed,v[1],v[2]-side*motion[0]/speed),self.s.dim(player))
                    if target:
                        rt.update(yield_target=target,yield_until=self.s.ticks+30,yield_next=self.s.ticks+90)
                        self.s.move(record,target,.9);return True
        return False
