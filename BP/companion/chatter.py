# -*- coding: utf-8 -*-
"""Short contextual lines for a deployed companion, with per-topic cooldowns."""
import math
import random
import mod.server.extraServerApi as api
from . import work_rules, chatter_lines

F=api.GetEngineCompFactory()


class Chatter(object):
    def __init__(self,system):self.s=system

    def say(self,player,record,key,text,interval=900,urgent=False):
        rt=self.s.rt(record);now=self.s.ticks;cooldowns=rt.setdefault('speech_cooldowns',{})
        if now<cooldowns.get(key,0) or (not urgent and now<rt.get('speech_next',0)):return False
        self.s.supply.say(player,record,text)
        cooldowns[key]=now+interval;rt['speech_next']=now+180
        return True

    def damage(self,args):
        if args.get('damage',0)<=0:return
        record=self.s.record_for_entity(args.get('entityId'))
        if not record or record.get('fallen') or record['form']!='deployed':return
        player=next((p for p in api.GetPlayerList() if self.s.owners.get(p)==record['owner_id']),None)
        if not player:return
        rt=self.s.rt(record);health=F.CreateAttr(record['entity_id']).GetAttrValue(api.GetMinecraftEnum().AttrType.HEALTH)
        topic=chatter_lines.hurt_topic(args.get('srcId'),player,health-args['damage'],rt.get('job'),record['settings'].get('work_mode'))
        if topic is None:return
        choices=[line for line in chatter_lines.LINES[topic] if line!=rt.get('last_hurt_line')]
        reaction=random.choice(choices);text=reaction
        if chatter_lines.hurt_echo_trigger(args.get('srcId'),record['entity_id'],random.random()):
            # Keep the normal reaction in the same bubble. Reuse the existing
            # hurt/global cooldown rather than dispatching a second Speech event.
            text+=u'\n'+random.choice(chatter_lines.HURT_ECHO_LINES)
        if self.say(player,record,'hurt_danger' if topic=='danger' else 'hurt',text,240,urgent=topic=='danger'):
            rt['last_hurt_line']=reaction

    def nearby_lava(self,record,position,dimension):
        rt=self.s.rt(record)
        if self.s.ticks<rt.get('lava_check_at',0):return rt.get('near_lava',False)
        rt['lava_check_at']=self.s.ticks+90;rt['near_lava']=False
        block=F.CreateBlockInfo(self.s.level)
        base=tuple(int(math.floor(v)) for v in position)
        eye=(position[0],position[1]+1.45,position[2])
        for dx in range(-3,4):
            for dz in range(-3,4):
                if abs(dx)+abs(dz)>3:continue
                for dy in (-1,0,1):
                    point=(base[0]+dx,base[1]+dy,base[2]+dz)
                    if (block.GetBlockNew(point,dimension) or {}).get('name') not in ('minecraft:lava','minecraft:flowing_lava'):continue
                    if self.s.work.clear(dimension,eye,tuple(v+.5 for v in point),point):
                        rt['near_lava']=True;return True
        return False

    def transition(self,player,record,key,active,text,interval):
        rt=self.s.rt(record);flag='speech_announced_'+key
        if not active:rt[flag]=False;return False
        if rt.get(flag):return False
        if self.say(player,record,key,text,interval):rt[flag]=True;return True
        return False

    def tick(self,player,record):
        if self.s.ticks%30 or record['form']!='deployed' or record.get('fallen'):return
        if player in self.s.panels or self.s.rt(record).get('offering') is not None:return
        p=self.s.pos(player);e=self.s.pos(record['entity_id'])
        if not p or not e or sum((p[i]-e[i])**2 for i in range(3))>8**2:return
        block=F.CreateBlockInfo(self.s.level);dim=self.s.dim(player)
        def water(height):
            point=(int(math.floor(p[0])),int(math.floor(p[1]+height)),int(math.floor(p[2])))
            return (block.GetBlockNew(point,dim) or {}).get('name') in ('minecraft:water','minecraft:flowing_water')
        wet=water(.2);under=water(1.5);rt=self.s.rt(record)
        rt.update({'speech_wet':wet,'speech_under':under})
        breath=F.CreateBreath(player)
        if under and breath.IsConsumingAirSupply() and breath.GetCurrentAirSupply()<=breath.GetMaxAirSupply()*.25:
            self.say(player,record,'air',u'快上去换气啦，咕噜咕噜！',300,urgent=True);return
        if self.nearby_lava(record,p,dim):
            if self.say(player,record,'lava',u'前面有岩浆，烫烫！绕开一点呀～',1350,urgent=True):return
        health=F.CreateAttr(player).GetAttrValue(api.GetMinecraftEnum().AttrType.HEALTH)
        if 0<health<=6:
            if self.say(player,record,'health',u'只剩一点血啦，先躲安全的地方休息吧！',1800,urgent=True):return
        if (rt.get('job') or {}).get('kind') in ('melee','bow','guard') or rt.get('danger_until',0)>self.s.ticks:return
        if self.transition(player,record,'underwater',under,u'潜到水下啦，记得上去换气哦～',600):return
        if self.transition(player,record,'water',wet and not under,u'下水啦，慢慢游，我陪着你～',600):return
        if self.s.ticks%90==0:
            nearby=F.CreateGame(self.s.level).GetEntitiesAroundByType(player,5,api.GetMinecraftEnum().EntityType.Mob) or []
            for actor in nearby:
                if F.CreateEngineType(actor).GetEngineTypeStr() in work_rules.HOSTILE:
                    if self.say(player,record,'monster',u'附近有怪物，小心一点呀！',1350):return
        # Weather and day/night only describe the overworld. An entry reminder
        # waits through the shared speech cooldown instead of being lost.
        rain=dim==0 and F.CreateWeather(self.s.level).IsRaining()
        if self.transition(player,record,'rain',rain,u'外面下雨啦，找个地方躲躲雨吧～',9000):return
        night=dim==0 and 13000<=F.CreateTime(self.s.level).GetTime()%24000<23000
        self.transition(player,record,'night',night,u'天黑啦，带好火把，小修齐陪你走～',9000)
