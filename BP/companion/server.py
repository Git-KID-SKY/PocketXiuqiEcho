# -*- coding: utf-8 -*-
from __future__ import division
import math
import json
import traceback
import uuid
import mod.server.extraServerApi as api
from . import config, domain
from .work import Work
from .work_modes import WorkModes
from .navigation_rules import independent
from .supply import Supply
from .attention import Attention
from .animation_timing import DURATIONS
from .navigation_rules import PASSABLE

Factory = api.GetEngineCompFactory()
Enum = api.GetMinecraftEnum()
Base = api.GetServerSystemCls()


def distance(a, b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


class InventoryAdapter(object):
    def __init__(self, system, player, armor=False):
        self.system, self.player = system, player
        self.armor=armor
        self.comp = Factory.CreateItem(player)

    def inventory(self):
        values = self.comp.GetPlayerAllItems(Enum.ItemPosType.INVENTORY, True)
        if not values or len(values) < 36:
            raise domain.Refused(u'背包还没准备好，请稍后再试。')
        return values[:36]+([self.comp.GetPlayerItem(Enum.ItemPosType.ARMOR,i,True) for i in range(4)] if self.armor else [])

    def set_slot(self, slot, value):
        if domain.same(self.inventory()[slot],value):return
        if self.armor and slot>=36:
            if not self.comp.SetEntityItem(Enum.ItemPosType.ARMOR,domain.native_item(value) if value else None,slot-36):raise domain.Refused(u'胸甲格暂时无法更新。')
            return
        if domain.empty(value):
            if not self.comp.SetInvItemNum(slot, 0):
                raise domain.Refused(u'物品格暂时无法更新。')
        else:
            result = self.comp.SetPlayerAllItems({(Enum.ItemPosType.INVENTORY, slot): domain.native_item(value)})
            if not result or not result.get((Enum.ItemPosType.INVENTORY, slot)):
                raise domain.Refused(u'物品格暂时无法更新。')

    def save(self, record):
        self.system.save(record)


class CompanionServer(Base):
    def __init__(self, namespace, name):
        Base.__init__(self, namespace, name)
        self.level = api.GetLevelId()
        self.world = Factory.CreateExtraData(self.level)
        self.records, self.owners, self.sessions = {}, {}, {}
        self.runtime, self.panels, self.cleanup = {}, {}, set()
        self.bindings={}
        self.block_properties={}
        self.ticks, self.outbound = 0, {}
        self.index = self.world.GetExtraData('echo_companion_index') or []
        for cid in self.index:
            value = self.world.GetExtraData(domain.native_value('echo_companion_' + cid))
            if value:
                if isinstance(value,domain.string_types):value=json.loads(value)
                if value.get('state') in ('hand_in_hand','offering','deploying'):
                    value['state']='following' if value['form']=='deployed' else 'stored'
                self.records[cid] = domain.migrate(value)
        self.work=Work(self)
        self.attention=Attention(self)
        self.modes=WorkModes(self)
        self.supply=Supply(self)
        from .interactions import Interactions
        self.interactions=Interactions(self)
        from .utility_work import UtilityWork
        self.utility=UtilityWork(self)
        from .carry import Carry
        self.carry=Carry(self)
        from .wardrobe import Wardrobe
        self.wardrobe=Wardrobe(self)
        from .chatter import Chatter
        self.chatter=Chatter(self)
        from .work_feedback import WorkFeedback
        self.feedback=WorkFeedback(self)
        from .swimming import Swimming
        self.swimming=Swimming(self)
        from .starter import StarterGift
        self.starter=StarterGift(self)
        self.events = []
        for event, handler in [('OnScriptTickServer', self.tick),
            ('ServerItemUseOnEvent', self.use_on), ('PlayerDoInteractServerEvent', self.interact),
            ('PlayerInteractServerEvent', self.can_interact), ('AddEntityServerEvent', self.entity_added),
            ('DelServerPlayerEvent', self.leave), ('PlayerDieEvent', self.died), ('MobDieEvent',self.mob_died),
            ('PlayerRespawnFinishServerEvent',self.respawned),
            ('DimensionChangeServerEvent', self.dimension_change),
            ('PlayerAttackEntityEvent', self.break_hand), ('StartDestroyBlockServerEvent', self.break_hand),
            ('ItemUseAfterServerEvent', self.break_hand),
            ('ServerPlayerTryDestroyBlockEvent',self.before_break),
            ('ProjectileDoHitEffectEvent',self.projectile),('DamageEvent',self.damage),
            ('ItemDurabilityChangedServerEvent',self.durability)]:
            self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(), event, self, handler)
            self.events.append((api.GetEngineNamespace(), api.GetEngineSystemName(), event, handler))
        for event,handler in [('EntityPlaceBlockAfterServerEvent',self.placed),('InventoryItemChangedServerEvent',self.inventory_changed),
            ('ServerEntityTryPlaceBlockEvent',self.before_place),
            ('ServerBlockUseEvent',self.use),('BlockRemoveServerEvent',self.removed),('ServerBlockEntityTickEvent',self.block_tick)]:
            self.ListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),event,self,handler)
            self.events.append((api.GetEngineNamespace(),api.GetEngineSystemName(),event,handler))
        for event, handler in [('Hello', self.hello), ('Request', self.request)]:
            self.ListenForEvent(config.NAMESPACE, config.CLIENT, event, self, handler)
            self.events.append((config.NAMESPACE, config.CLIENT, event, handler))

    # The native dispatcher resolves callback names on the listener instance.
    def placed(self,args):self.supply.placed(args);self.wardrobe.placed(args)
    def inventory_changed(self,args):self.supply.inventory_changed(args)
    def before_place(self,args):self.wardrobe.before_place(args)
    def use(self,args):self.wardrobe.use(args)
    def removed(self,args):self.wardrobe.removed(args)
    def block_tick(self,args):self.utility.block_tick(args);self.wardrobe.block_tick(args)

    def save(self, record):
        cid = record['companion_id']
        # Engine ExtraData rejects nested Python 2 unicode; ASCII JSON preserves
        # Chinese names, arbitrary item metadata and the complete write journal.
        if not self.world.SetExtraData(domain.native_value('echo_companion_' + cid), json.dumps(record,ensure_ascii=True)):
            raise domain.Refused(u'伙伴数据暂时无法保存，操作已停止。')
        if cid not in self.index:
            updated = self.index + [cid]
            if not self.world.SetExtraData('echo_companion_index', domain.native_value(updated)):
                raise domain.Refused(u'伙伴数据暂时无法保存。')
            self.index = updated
        self.records[cid] = record

    def owner(self, player):
        if player not in self.owners:
            comp = Factory.CreateExtraData(player)
            token = comp.GetExtraData('echo_companion_owner')
            if not token:
                token = uuid.uuid4().hex
                if not comp.SetExtraData('echo_companion_owner', token):
                    raise domain.Refused(u'正在准备伙伴资料。')
            self.owners[player] = token
        return self.owners[player]

    def owned(self, player):
        owner = self.owner(player)
        return [r for r in self.records.values() if r['owner_id'] == owner]

    def live(self, entity):
        return bool(entity and Factory.CreateGame(self.level).IsEntityAlive(entity))

    def pos(self, entity):
        return Factory.CreatePos(entity).GetFootPos()

    def dim(self, entity):
        return Factory.CreateDimension(entity).GetEntityDimensionId()

    def notify(self, player, text):
        self.NotifyToClient(player, 'Notice', {'message': text})

    def rt(self, record):
        return self.runtime.setdefault(record['companion_id'], {'offering': None, 'cooldown': 0,
            'action': 0, 'action_until': 0, 'busy_until': 0, 'last_path': -100,
            'far_since': None, 'hand_target': False, 'approach_until': 0})

    def hello(self, args):
        player = args.get('playerId')
        if player not in api.GetPlayerList():
            return
        session = self.sessions.setdefault(player, {'token': uuid.uuid4().hex, 'last': -100, 'hello': -100})
        if self.ticks-session['hello'] < 30:
            return
        session['hello'] = self.ticks
        self.wardrobe.sent.pop(player,None)
        self.NotifyToClient(player, 'Welcome', {'token': session['token'],
            'entities':[r['entity_id'] for r in self.records.values() if r.get('entity_id')]})
        self.NotifyToClient(player,'Preferences',self.interactions.settings(player))
        try:
            for record in self.owned(player):
                if record.get('pending'):
                    domain.recover(InventoryAdapter(self, player,any(p['slot']>=36 for p in record['pending']['patches'])), record)
                self.work.recover(player,record)
                if record.get('owner_respawn_pending') and Factory.CreateAttr(player).GetAttrValue(Enum.AttrType.HEALTH)>0:
                    self.rt(record)['respawn_ready']=self.ticks+15
                self.save(record)
                if record['state'] == 'hand_in_hand':
                    record['state'] = 'following'
                    self.save(record)
            self.starter.give(player,InventoryAdapter(self,player))
            self.publish_all()
        except domain.Refused:
            # Inventory/player initialization can finish after the UI handshake.
            # The server tick retries the persistent starter entitlement.
            pass
        except Exception:
            traceback.print_exc()

    def selected(self, player, bind=False):
        comp = Factory.CreateItem(player)
        slot = comp.GetSelectSlotId()
        if slot < 0:
            return None
        item = comp.GetPlayerItem(Enum.ItemPosType.INVENTORY, slot, True)
        if domain.item_name(item) != config.ITEM:
            return None
        parts = domain.token_parts(item)
        if not parts and bind:
            key=(player,slot)
            record=self.bindings.get(key)
            if record is None:
                record = domain.new_record(self.owner(player))
                self.interactions.apply_preferences(player,record)
                self.save(record);self.bindings[key]=record
            domain.require_owner(record,self.owner(player))
            after = domain.clone(record)
            domain.transaction(InventoryAdapter(self, player), record, after,
                [{'slot':slot,'before':item,'after':domain.doll(record)}], 'bind:'+uuid.uuid4().hex)
            self.bindings.pop(key,None)
            return record
        if not parts:
            return None
        record = self.records.get(parts[0])
        if not record or record['token'] != parts[1] or record['form'] != 'stored':
            if bind:
                raise domain.Refused(u'这个公仔凭证已失效，请使用当前的小修齐。')
            return None
        if record['owner_id'] != self.owner(player):
            if bind:
                raise domain.Refused(u'这是别人的小修齐。')
            return None
        return record

    def accessible(self, player, record):
        domain.require_owner(record, self.owner(player))
        if record.get('fallen'):
            if self.ticks<self.rt(record).get('death_until',0):raise domain.Refused(u'正在播放倒下动作，请稍等。')
            return
        if record['form'] == 'stored':
            available=[r['companion_id'] for r in (self.selected(player),self.carry.worn(player)) if r]
            if record['companion_id'] not in available:
                raise domain.Refused(u'先把这只公仔拿在手里。')
        elif record['form'] == 'deployed':
            entity = record.get('entity_id')
            if not self.live(entity) or self.dim(player) != self.dim(entity):
                raise domain.Refused(u'小修齐正在赶来，请稍等。')
            if distance(self.pos(player), self.pos(entity)) > config.MAX_DISTANCE:
                raise domain.Refused(u'靠近小修齐，再打开面板吧。')

    def safe(self, position, dim, headroom=2):
        """Conservative full-block standing test; no air/water/lava/unloaded cells."""
        block = Factory.CreateBlockInfo(self.level)
        x, y, z = position
        base_y = int(math.floor(y-.04))
        # Feet are required to be close to the surface, never teleported into slabs.
        floor_y = base_y+1
        if abs(y-floor_y) > .35:
            return None
        for dx,dz in [(-.23,-.23),(-.23,.23),(.23,-.23),(.23,.23)]:
            bx,bz=int(math.floor(x+dx)),int(math.floor(z+dz))
            below=block.GetBlockNew((bx,base_y,bz),dim)
            if not below:
                return None
            name=below.get('name','')
            if name not in self.block_properties:self.block_properties[name]=block.GetBlockBasicInfo(name) or {}
            if self.block_properties[name].get('solid') is not True:return None
            if name in ('minecraft:air','minecraft:water','minecraft:flowing_water','minecraft:lava','minecraft:flowing_lava'):
                return None
            if any(word in name for word in ('cactus','magma','fire','campfire','fence','wall','slab','stairs','leaves','glass_pane','door','trapdoor','berry','powder_snow')):
                return None
            for by in range(floor_y,floor_y+headroom):
                above=block.GetBlockNew((bx,by,bz),dim)
                if not above or above.get('name') not in PASSABLE:
                    return None
        return (x,float(floor_y),z)

    def near_spot(self, player, hand=False):
        p=self.pos(player);yaw=math.radians(Factory.CreateRot(player).GetRot()[1])
        forward=(-math.sin(yaw),math.cos(yaw));right=(-math.cos(yaw),-math.sin(yaw))
        offsets=[(config.HAND_SIDE,0)] if hand else [(1,-1.6),(-1,-1.6),(1.4,0),(-1.4,0),(0,-2)]
        for side,back in offsets:
            point=(p[0]+right[0]*side+forward[0]*back,p[1],p[2]+right[1]*side+forward[1]*back)
            result=self.safe(point,self.dim(player))
            if result:return result
        return None

    def can_hand(self, player, allow_doll=False, maintaining=False):
        if Factory.CreatePlayer(player).isSneaking():
            raise domain.Refused(u'蹲下会松手，站起来再牵手吧。')
        motion=Factory.CreateActorMotion(player).GetMotion() or (0,0,0)
        if not maintaining and (abs(motion[1]) > .12 or math.hypot(motion[0],motion[2]) > .25):
            raise domain.Refused(u'先站稳，再牵手。')
        if Factory.CreateFly(player).IsPlayerFlying() or Factory.CreateRide(player).IsEntityRiding() or Factory.CreatePlayer(player).isSwimming() or self.swimming.wet(self.pos(player),self.dim(player)):
            raise domain.Refused(u'先站稳，再牵手。')
        if not maintaining and not self.safe(self.pos(player),self.dim(player)):
            raise domain.Refused(u'先站稳，再牵手。')
        hand=Factory.CreateItem(player).GetPlayerItem(Enum.ItemPosType.CARRIED,0,True)
        if not domain.empty(hand) and not (allow_doll and domain.item_name(hand)==config.ITEM):
            raise domain.Refused(u'把主手空出来，再牵手吧。')
        if maintaining:
            p=self.pos(player);yaw=math.radians(Factory.CreateRot(player).GetRot()[1])
            return (p[0]-config.HAND_SIDE*math.cos(yaw),p[1],p[2]-config.HAND_SIDE*math.sin(yaw))
        return self.near_spot(player,True)

    def spawn(self, player, record, position):
        owner_pos=self.pos(player)
        yaw=Factory.CreateRot(player).GetRot()[1]
        if owner_pos and math.hypot(owner_pos[0]-position[0],owner_pos[2]-position[2])>.05:
            yaw=math.degrees(math.atan2(-(owner_pos[0]-position[0]),owner_pos[2]-position[2]))
        entity=self.CreateEngineEntityByTypeStr(config.ENTITY,tuple(position),(0,yaw),self.dim(player))
        if not entity:
            record['state']='suspended';self.save(record)
            raise domain.Refused(u'这里暂时不能站立，伙伴已保存，换个位置再试。')
        token={'id':record['companion_id'],'token':record['token']}
        if not Factory.CreateExtraData(entity).SetExtraData('echo_companion_identity',domain.native_value(token)):
            self.DestroyEntity(entity)
            raise domain.Refused(u'伙伴暂时无法保存，稍后会重新到你身边。')
        record['entity_id']=entity
        record['last_position']={'pos':list(position),'dimension':self.dim(player)}
        record['state']='following'
        self.save(record)
        Factory.CreateName(entity).SetName(domain.native_value(record.get('name',u'')))
        Factory.CreateAttr(entity).SetAttrValue(Enum.AttrType.HEALTH,record.get('health',20))
        self.action(record,1,.65)
        self.effect(record,'deploy')

    def deploy(self, player, record, position=None, hand=False, operation=None):
        if record['form']!='stored':raise domain.Refused(u'它已经在你身边啦。')
        if any(r['form']=='deployed' for r in self.owned(player)):
            raise domain.Refused(u'先收回身边的小修齐，再放出这一只。')
        if hand:position=self.can_hand(player,True)
        position=position or self.near_spot(player)
        if not position:raise domain.Refused(u'找一块平坦安全的地面，再放出来吧。')
        comp=Factory.CreateItem(player);slot=comp.GetSelectSlotId()
        item=comp.GetPlayerItem(Enum.ItemPosType.INVENTORY,slot,True)
        if domain.token_parts(item)!=(record['companion_id'],record['token']):raise domain.Refused(u'先拿好这只公仔。')
        after=domain.clone(record);after.update({'form':'deployed','state':'deploying','entity_id':None,'token':uuid.uuid4().hex})
        after['last_position']={'pos':list(position),'dimension':self.dim(player)}
        if hand:after['settings']['mode']='hand'
        domain.transaction(InventoryAdapter(self,player),record,after,[{'slot':slot,'before':item,'after':None}],operation or 'deploy:'+uuid.uuid4().hex)
        self.spawn(player,record,position)
        self.placement_sound(record,position)
        if hand:
            record['state']='hand_in_hand';self.save(record)

    def recall(self, player, record, mode, operation):
        if mode not in ('hug','hold','hand'):raise domain.Refused(u'请选择一种手持方式。')
        items=InventoryAdapter(self,player).inventory();slot=domain.first_empty(items);patches=[]
        selected=Factory.CreateItem(player).GetSelectSlotId()
        if slot>=9 and 0<=selected<9:
            patches.append({'slot':slot,'before':items[slot],'after':items[selected]});slot=selected
        entity=record.get('entity_id');position=self.pos(entity) if self.live(entity) else None
        retiring=self.visual(record)
        after=domain.clone(record);after.update({'form':'stored','state':'stored','entity_id':None,'token':uuid.uuid4().hex})
        if self.live(entity):
            attr=Factory.CreateAttr(entity)
            after['health']=attr.GetAttrValue(Enum.AttrType.HEALTH)
            after['health_max']=attr.GetAttrMaxValue(Enum.AttrType.HEALTH)
        after.pop('fallen',None)
        mode='hug' if mode=='hug' else 'hold'
        after['settings']['mode']=mode;after['settings']['last_held']=mode
        self.unhand(record)
        patches.append({'slot':slot,'before':items[slot],'after':domain.doll(after)})
        domain.transaction(InventoryAdapter(self,player),record,after,patches,operation)
        if self.live(entity):
            # Commit inventory first. The old actor is a short visual tail;
            # its stale identity cannot open a panel or transfer items.
            self.stop(entity)
            retiring.update({'active':True,'action':4,'offering':0,'state':'recalling','hand':False,'hand_owner':None})
            Factory.CreateModAttr(entity).SetAttr('echo_companion_visual',domain.native_value(retiring))
            self.cleanup.add(('retire',entity,self.ticks+15))
        if slot<9:Factory.CreatePlayer(player).ChangeSelectSlot(slot)
        else:self.notify(player,u'公仔已收好，放进快捷栏就能抱着它。')
        self.supply.finish(record)
        self.carry.selections[player]=(slot,record['companion_id'])
        if position:self.effect(record,'recall',position)

    def stop(self, entity):
        if self.live(entity):
            pos=self.pos(entity)
            if pos is None:return
            record=self.record_for_entity(entity)
            if record:
                rt=self.rt(record);rt['last_path']=-100;rt['swim_direct']=False
                rt.pop('move_progress',None)
                rt.pop('swim_goal',None)
            # A normal-speed path to the current point can keep native swim
            # steering alive and fight scripted depth/pursuit motion.
            Factory.CreateMoveTo(entity).SetMoveSetting(tuple(pos),.01,16,self.path_done)
            motion=Factory.CreateActorMotion(entity).GetMotion() or (0,0,0)
            Factory.CreateActorMotion(entity).SetMotion((0,motion[1],0))

    def hold(self, record):
        if not self.swimming.hold(record):self.stop(record['entity_id'])

    def unhand(self, record):
        rt=self.rt(record);rt['hand_target']=False
        rt.pop('approach_steer',None)
        rt.pop('hand_anchor_yaw',None)
        yaw=rt.pop('hand_release_yaw',None)
        if yaw is not None and self.live(record.get('entity_id')):
            Factory.CreateRot(record['entity_id']).SetRot((0,yaw))
        if record['state']=='hand_in_hand':record['state']='following'

    def lock_hand(self, player, record, target=None):
        # A joined hand is a relative-position constraint, not a path to chase.
        # Run every script tick, including while jumping and turning.
        entity=record.get('entity_id')
        if not self.live(entity) or not self.live(player) or self.dim(entity)!=self.dim(player):return
        if target is None:target=self.can_hand(player,maintaining=True)
        Factory.CreatePos(entity).SetFootPos(tuple(target))
        # Position follows the owner once. Extra velocity and native body turns
        # otherwise compete with the render constraint and shake the whole rig.
        Factory.CreateActorMotion(entity).SetMotion((0,0,0))
        rt=self.rt(record);yaw=Factory.CreateRot(player).GetRot()[1]
        if 'hand_anchor_yaw' not in rt:rt['hand_anchor_yaw']=yaw
        rt['hand_release_yaw']=yaw
        Factory.CreateRot(entity).SetRot((0,rt['hand_anchor_yaw']))

    def action(self, record, code, seconds, restart=False):
        rt=self.rt(record)
        if restart or rt['action']!=code or self.ticks>=rt['action_until']:
            rt['action_started']=self.ticks;rt['action_stamp']=rt.get('action_stamp',0)+1
        rt['action']=code;rt['action_until']=self.ticks+int(math.ceil(seconds*30))

    def motion_role(self,record):
        if domain.item_name(record.get('equipment',{}).get('main'))=='minecraft:bow':return 1
        return 2 if record['settings'].get('style')=='wizard' else 0

    def greet(self,record):
        if record.get('fallen') or self.rt(record).get('job'):return
        self.action(record,3,DURATIONS['wizard_attack' if self.motion_role(record)==2 else 'interact'],True)

    def effect(self, record, kind, position=None):
        if not record['settings']['particles']:return
        position=position or (self.pos(record['entity_id']) if self.live(record.get('entity_id')) else None)
        if not position:return
        data={'kind':kind,'position':list(position),'owner':record.get('entity_id'),'id':record['companion_id']}
        dimension=record.get('last_position',{}).get('dimension',0)
        for player in api.GetPlayerList():
            if self.dim(player)==dimension and distance(self.pos(player),position)<40:self.NotifyToClient(player,'Effect',data)

    def placement_sound(self,record,position):
        data={'name':'echo.companion.deploy','position':list(position)}
        dimension=record['last_position']['dimension']
        for player in api.GetPlayerList():
            if self.dim(player)==dimension and distance(self.pos(player),position)<16:self.NotifyToClient(player,'Sound',data)

    def recall_worker(self,player):
        record=next((r for r in self.owned(player) if r['form']=='deployed'),None)
        if not record:
            raise domain.Refused(u'没有放出的小跟班。')
        if (record.get('pending') or record.get('fallen') or record.get('owner_respawn_pending')
                or not self.live(player) or self.pos(player) is None):
            raise domain.Refused(u'小跟班暂时不能召回，请稍后再试。')
        self.work.ready(record)
        spot=self.near_spot(player)
        if spot is None:
            raise domain.Refused(u'你身边没有安全落点，站到平坦地面再召回。')
        self.work.cancel(record)
        self.unhand(record)
        self.supply.finish(record)
        entity=record.get('entity_id')
        if self.live(entity) and self.pos(entity) is not None and self.dim(entity)==self.dim(player):
            self.stop(entity)
            if not Factory.CreatePos(entity).SetFootPos(spot):
                raise domain.Refused(u'暂时无法到达这个位置，换个落点再试。')
        else:
            # Retire the previous generation even when its chunk is unloaded.
            self.suspend(record)
            self.spawn(player,record,spot)
        record['state']='following'
        record['settings'].update(work_mode='follow',movement='follow',active_work=False)
        rt=self.rt(record)
        for key in ('tree','mining_goal','mining_scan','stair_plan','stair_origin','catching_up','far_since'):
            rt.pop(key,None)
        rt['far_since']=None
        self.commit(record,'recall-worker:'+uuid.uuid4().hex)
        self.publish_all()
        self.notify(player,u'小跟班已停止工作，回到你身边。')

    def request(self, args):
        player=args.get('playerId');session=self.sessions.get(player)
        if not session or args.get('token')!=session['token'] or player not in api.GetPlayerList():return
        action=args.get('action')
        if action=='heartbeat':
            if player in self.panels:self.panels[player]['time']=self.ticks
            return
        if action=='close':
            self.panels.pop(player,None);return
        if action=='recall_worker':
            if self.ticks-session.get('recall_at',-30)<15:
                self.notify(player,u'刚刚召回过，请稍候。');return
            session['recall_at']=self.ticks
        elif self.ticks-session['last']<3:return
        session['last']=self.ticks
        record=None
        try:
            if action=='recall_worker':
                self.recall_worker(player);return
            if action=='mod_option':
                self.interactions.option(player,args.get('key'),args.get('value'));return
            if action=='interact':
                record=self.record_for_entity(args.get('entity'))
                if not record:raise domain.Refused(u'伙伴暂时不在这里。')
                self.interactions.use(player,record);self.publish_all();self.snapshot(player,record);return
            if action=='close':
                self.panels.pop(player,None);return
            if action=='open':
                record=self.record_for_entity(args.get('entity')) if args.get('entity') else self.selected(player,True) or self.carry.worn(player,True)
                if args.get('entity') and not record:raise domain.Refused(u'没有找到这只小修齐。')
                if not record:
                    candidates=[r for r in self.owned(player) if r['form']=='deployed']
                    if not candidates:raise domain.Refused(u'先拿起公仔，或对身边的小修齐交互。')
                    record=candidates[0]
                self.open_panel(player,record);return
            if action=='place':
                # Ground clicks also work before the panel has ever opened.
                # Resolve the currently held token on the server, never a stale UI id.
                record=self.selected(player,True)
                if not record:raise domain.Refused(u'先拿好公仔，再点击地面。')
                operation=args.get('op')
                if not domain.check_request(record,self.owner(player),record['revision'],operation):return
                position=self.ground_spot(player,args.get('target'))
                self.deploy(player,record,position,operation=operation)
                self.publish_all();self.snapshot(player,record);return
            record=self.records.get(args.get('id'))
            self.accessible(player,record)
            operation=args.get('op');revision=args.get('revision')
            if not domain.check_request(record,self.owner(player),revision,operation):
                self.snapshot(player,record);return
            rt=self.rt(record)
            self.work.ready(record)
            if action in ('outfit','outfit_all') or (action=='option' and args.get('key')=='appearance'):
                panel=self.panels.get(player,{})
                if panel.get('context')!='wardrobe' or panel.get('id')!=record['companion_id']:
                    raise domain.Refused(u'请在衣柜中更换外观和饰品。')
                self.wardrobe.check(player,panel)
            if record.get('fallen') and action not in ('recall','transfer','sort','move_item'):
                raise domain.Refused(u'伙伴已倒下，先留出一格背包收回公仔。')
            if rt.get('job') and action in ('transfer','offer','accept','equip','unequip','sort','reserve','move_item'):
                raise domain.Refused(u'先停止当前任务，再存取、递物或换装备。')
            if action in ('mode','follow','wait','release','recall','reset','cancel_task','wear','active_work'):
                self.work.cancel(record)
                record['settings']['work_mode']='follow'
                if action!='active_work':record['settings']['active_work']=False
            if action=='transfer':
                if rt['offering'] is not None:raise domain.Refused(u'先领取或取消正在递出的物品。')
                direction=args.get('direction')
                if direction not in ('deposit','withdraw'):raise domain.Refused(u'请选择存入或取出。')
                if direction=='deposit':
                    panel=self.panels.get(player,{})
                    view=next((v for v in panel.get('inventory_views',[]) if v['id']==args.get('inventory_view')),None)
                    slot=args.get('slot')
                    if view and (type(slot) is not int or not 0<=slot<36 or not domain.same(InventoryAdapter(self,player).inventory()[slot],view['items'][slot])):
                        raise domain.Refused(u'这一格已变化，请重新点击。')
                domain.transfer(InventoryAdapter(self,player),record,direction,args.get('slot'),operation)
            elif action=='move_item':
                if rt['offering'] is not None:raise domain.Refused(u'先领取或取消正在递出的物品。')
                from . import inventory_moves
                source=inventory_moves.address(args.get('source'));destination=inventory_moves.address(args.get('destination'))
                panel=self.panels.get(player,{})
                view=next((v for v in panel.get('inventory_views',[]) if v['id']==args.get('inventory_view')),None)
                if not view or panel.get('id')!=record['companion_id']:raise domain.Refused(u'背包页面已更新，请重新拖动。')
                adapter=InventoryAdapter(self,player);items=adapter.inventory()
                for area,slot in (source,destination):
                    if area=='player' and not domain.same(items[slot],view['items'][slot]):
                        raise domain.Refused(u'该格物品已经变化，请重新拖动。')
                after,patches=inventory_moves.plan(record,items,args['source'],args['destination'],
                    lambda item:self.work.info(item).get('maxStackSize',64),self.work.validate_equipment)
                equipment_changed=not domain.same(record['equipment'],after['equipment'])
                if not domain.same(record['equipment'].get('main'),after['equipment'].get('main')):
                    after['settings']['active_work']=False;after['settings']['mine_sample']=None
                domain.transaction(adapter,record,after,patches,operation)
                if equipment_changed:self.interactions.mode(record);self.save(record)
            elif action=='set_mine_sample':
                from . import inventory_moves,mining_filter
                source=args.get('source')
                if source is None:selected=None
                else:
                    area,slot=inventory_moves.address(source)
                    if area not in ('player','bag'):raise domain.Refused(u'从背包选择一个目标方块。')
                    panel=self.panels.get(player,{})
                    view=next((v for v in panel.get('inventory_views',[]) if v['id']==args.get('inventory_view')),None)
                    if not view or panel.get('id')!=record['companion_id']:raise domain.Refused(u'背包页面已更新，请重新选择方块。')
                    items=InventoryAdapter(self,player).inventory()
                    if area=='player' and not domain.same(items[slot],view['items'][slot]):raise domain.Refused(u'该格物品已变化，请重新选择。')
                    selected=mining_filter.sample(items[slot] if area=='player' else record['inventory'][slot])
                self.work.cancel(record)
                record['settings']['mine_sample']=selected
                record['settings']['work_mode']='follow';record['settings']['active_work']=False;rt.pop('tree',None)
                self.commit(record,operation)
                if selected:self.NotifyToClient(player,'SampleSelected',{})
                if selected and record['form']=='deployed':
                    try:
                        self.modes.check(record,'excavate')
                        self.unhand(record);record['settings']['work_mode']='excavate';record['settings']['active_work']=True
                        record['settings']['movement']='follow';record['state']='following'
                        rt['mode_next']=0;rt['mode_status']=u'目标已设好，关面板后开始采掘';self.save(record)
                        self.notify(player,u'已记住目标方块，不消耗样本。关面板后开始寻找。')
                    except domain.Refused as error:self.notify(player,u'目标已保存。'+error.args[0])
                else:self.notify(player,u'目标已保存，放到地上并选择「开凿」即可。' if selected else u'已清除目标，停止自动采掘。')
            elif action=='equip':self.work.equip(record,args.get('slot'),operation,args.get('hand'))
            elif action=='unequip':self.work.equip(record,None,operation,args.get('hand','main'))
            elif action=='sort':
                if rt['offering'] is not None:raise domain.Refused(u'先领取或取消递物，再整理。')
                from .work_rules import sort_bag
                self.work.put(record,sort_bag(record,lambda item:self.work.info(item).get('maxStackSize',64)),operation)
            elif action=='reserve':
                if rt['offering'] is not None:raise domain.Refused(u'先结束递物，再修改备用格。')
                self.supply.reserve(record,args.get('slot'),operation)
            elif action=='work_mode':self.modes.choose(player,record,args.get('value'),operation)
            elif action=='task':
                self.work.cancel(record);record['settings']['work_mode']='follow'
                record['settings']['movement']='follow';record['settings']['active_work']=False
                self.work.start(player,record,args.get('kind'),operation)
            elif action=='cancel_task':self.commit(record,operation)
            elif action=='wear':
                if type(args.get('value')) is not bool:raise domain.Refused(u'请选择背负或取下。')
                self.carry.set_worn(player,record,args['value'],operation)
            elif action=='active_work':
                if type(args.get('value')) is not bool:raise domain.Refused(u'请选择开启或停止。')
                if record['form']!='deployed':raise domain.Refused(u'先点右下角「放到身边」，再开始协助。')
                if args['value']:
                    from .interaction_rules import work_mode
                    candidate=domain.clone(record);candidate['settings']['active_work']=True
                    active_mode=work_mode(candidate,self.work.info(candidate['equipment'].get('main')))
                    if active_mode=='follow':raise domain.Refused(u'先把工具或武器交给我，再叫我开工吧～')
                    self.modes.check(candidate,active_mode)
                self.unhand(record);record['settings']['active_work']=args['value']
                if args['value']:record['settings']['movement']='follow'
                self.interactions.mode(record);self.commit(record,operation)
            elif action=='mode':
                mode=args.get('value')
                if mode not in ('hug','hold','hand'):raise domain.Refused(u'请选择陪伴方式。')
                if record.get('worn'):self.carry.set_worn(player,record,False,'unwear-mode:'+uuid.uuid4().hex)
                if mode=='hand':
                    position=self.can_hand(player,record['form']=='stored')
                    if not position:raise domain.Refused(u'身边没有安全落点，换个位置再牵手。')
                    if record['form']=='stored':self.deploy(player,record,position,True,operation)
                    else:
                        record['settings']['mode']='hand';record['state']='following';rt['hand_target']=True;rt['approach_until']=self.ticks+150
                        self.panels.pop(player,None)
                        self.commit(record,operation)
                elif record['form']=='deployed':self.recall(player,record,mode,operation)
                else:
                    record['settings']['mode']=mode;record['settings']['last_held']=mode;self.commit(record,operation)
            elif action in ('follow','wait','release'):
                if record['form']!='deployed':raise domain.Refused(u'先把它放到地上吧。')
                self.unhand(record);self.supply.finish(record)
                record['state']='waiting' if action=='wait' else 'following'
                record['settings']['movement']='wait' if action=='wait' else 'follow'
                self.stop(record['entity_id']);self.commit(record,operation)
            elif action=='recall':
                if record['form']!='deployed':raise domain.Refused(u'它已经收好啦。')
                self.recall(player,record,record['settings']['last_held'],operation)
            elif action=='deploy':self.deploy(player,record,operation=operation)
            elif action=='option':
                key,value=args.get('key'),args.get('value')
                from .interaction_rules import DEFAULTS
                if key in DEFAULTS:self.interactions.option(player,key,value)
                elif key=='style' and (rt['action_until']>self.ticks or rt['offering'] is not None):
                    if value not in ('default','wizard','q'):raise domain.Refused(u'请选择动画风格。')
                    rt['pending_style']=value;self.notify(player,u'当前动作结束后切换。')
                else:
                    domain.set_option(record,key,value)
                    if key=='supply_mode':
                        import json
                        prefs=self.interactions.settings(player);prefs['food_prompt']=value!='off'
                        if not self.world.SetExtraData('ec_preferences_'+self.owner(player),json.dumps(prefs,ensure_ascii=True)):
                            raise domain.Refused(u'设置暂时无法保存。')
                        self.NotifyToClient(player,'Preferences',prefs)
                self.supply.changed(record)
                self.commit(record,operation)
            elif action=='reset':
                if record['form']=='deployed':self.recall(player,record,'hold',operation)
                else:
                    record['settings']['mode']='hold';record['settings']['last_held']='hold';self.commit(record,operation)
                record['settings']['style']='default';record['settings']['fall_reaction']=True
                record['settings']['food_prompt']=True;record['settings']['particles']=True
                record['settings'].update(domain.clone(config.SUPPLY_DEFAULTS))
                rt.pop('pending_style',None);self.save(record)
            elif action=='outfit':
                domain.set_outfit(record,args.get('key'),args.get('value'));self.greet(record);self.commit(record,operation)
            elif action=='outfit_all':
                outfit=args.get('value')
                if not isinstance(outfit,dict) or set(outfit)!=set(config.ACCESSORIES):
                    raise domain.Refused(u'请选择完整的装扮。')
                checked=domain.clone(record)
                for category,value in outfit.items():domain.set_outfit(checked,category,value)
                record['outfit']=checked['outfit'];self.greet(record);self.commit(record,operation)
            elif action=='offer':
                if record['form']!='deployed':raise domain.Refused(u'先把它放到地上，再让它递给你。')
                slot=args.get('slot')
                if type(slot) is not int or not 0<=slot<len(record['inventory']) or domain.empty(record['inventory'][slot]):raise domain.Refused(u'先选一个伙伴背包里的物品。')
                self.supply.offer(record,slot,'manual');self.commit(record,operation)
            elif action=='accept':
                slot=rt['offering']
                if slot is None:raise domain.Refused(u'还没有要领取的物品。')
                self.supply.deliver(player,record,slot,operation,rt.get('offer_kind')=='food')
                self.supply.finish(record);self.save(record)
            elif action=='cancel_offer':
                self.supply.finish(record);self.commit(record,operation)
            else:raise domain.Refused(u'这个操作暂时不可用。')
            if action in ('work_mode','active_work','set_mine_sample','follow','wait','release','cancel_task','equip','unequip','move_item'):
                self.feedback.changed(record)
            self.publish_all();self.snapshot(player,record)
            if action=='mode' and args.get('value')=='hand':
                self.panels.pop(player,None);self.NotifyToClient(player,'Close',{})
        except domain.Refused as error:
            self.notify(player,error.args[0])
            if record and record.get('owner_id')==self.owners.get(player) and action in ('interact','work_mode','active_work','set_mine_sample'):
                self.feedback.problem(record,error.args[0])
            if record and record.get('owner_id')==self.owners.get(player):self.snapshot(player,record)
        except Exception:
            traceback.print_exc();self.notify(player,u'操作未完成，伙伴资料已保留，请重新打开面板。')
            if record and record.get('owner_id')==self.owners.get(player):self.snapshot(player,record)

    def commit(self, record, operation):
        domain.finish(record,operation);self.save(record)

    def snapshot(self, player, record, opening=False):
        rt=self.rt(record)
        data={'record':domain.clone(record),'player_items':InventoryAdapter(self,player).inventory(),
              'offering':rt['offering'],'pending_style':rt.get('pending_style'),'opening':opening,
              'work_status':rt.get('mode_status',u''),'work_reasons':self.modes.reasons(record),
              'supply_status':self.supply.status(player,record)}
        # Live values belong to the snapshot, not to a persisted preview copy.
        health=record.get('health',20);maximum=record.get('health_max',20)
        if record['form']=='deployed' and self.live(record.get('entity_id')):
            attr=Factory.CreateAttr(record['entity_id'])
            health=attr.GetAttrValue(Enum.AttrType.HEALTH)
            maximum=attr.GetAttrMaxValue(Enum.AttrType.HEALTH)
        def finite(value):
            return isinstance(value,(int,long,float)) and value==value and abs(value)<float('inf')
        data['health']={'current':max(0,health) if finite(health) else None,
                        'maximum':maximum if finite(maximum) and maximum>0 else None}
        panel=self.panels.get(player,{})
        data['context']=panel.get('context','bag')
        if panel.get('id')==record['companion_id']:
            view={'id':uuid.uuid4().hex,'items':domain.clone(data['player_items'])}
            panel['inventory_views']=(panel.get('inventory_views',[])+[view])[-8:]
            data['inventory_view']=view['id']
        data['mine_target']=panel.get('mine_target') if panel.get('id')==record['companion_id'] else None
        data['record'].pop('pending',None);data['record'].pop('recent_ops',None);data['record'].pop('token',None)
        self.NotifyToClient(player,'Snapshot',data)

    def open_panel(self, player, record, context='bag', wardrobe=None):
        self.accessible(player,record)
        if (self.rt(record).get('job') or {}).get('automatic'):self.work.cancel(record)
        self.panels[player]={'id':record['companion_id'],'time':self.ticks,'context':context,'wardrobe':wardrobe}
        self.stop(record.get('entity_id'))
        self.snapshot(player,record,True)

    def ground_spot(self,player,target):
        if not isinstance(target,dict) or target.get('face')!=1:
            raise domain.Refused(u'对着平坦地面的上表面使用公仔。')
        if any(type(target.get(k)) not in (int,long) for k in ('x','y','z')):
            raise domain.Refused(u'没有找到落点，请重新点击地面。')
        block=(target['x'],target['y'],target['z'])
        point=(block[0]+.5,block[1]+1.0,block[2]+.5)
        foot=self.pos(player)
        if distance(foot,point)>5:raise domain.Refused(u'站近一点，再把它放出来。')
        dimension=self.dim(player);position=self.safe(point,dimension)
        if not position:raise domain.Refused(u'这里站不稳，换一块安全地面吧。')
        eye=(foot[0],foot[1]+1.62,foot[2])
        if not self.work.clear(dimension,eye,(point[0],point[1]+.03,point[2])):
            raise domain.Refused(u'落点被挡住了，换一块看得见的地面吧。')
        return position

    def use_on(self, args):
        if domain.item_name(args.get('itemDict'))!=config.ITEM:return
        args['ret']=True;player=args['entityId']
        try:
            position=self.ground_spot(player,args)
            record=self.selected(player,True);domain.require_owner(record,self.owner(player))
            self.deploy(player,record,position);self.publish_all()
        except domain.Refused as error:self.notify(player,error.args[0])
        except Exception:traceback.print_exc()

    def record_for_entity(self, entity):
        return next((r for r in self.records.values() if r.get('entity_id')==entity and r['form']=='deployed'),None)

    def interact(self, args):
        record=self.record_for_entity(args.get('interactEntityId'))
        if not record:return
        try:
            self.interactions.use(args['playerId'],record);self.publish_all()
        except domain.Refused as error:
            self.notify(args['playerId'],error.args[0])
            if record.get('owner_id')==self.owners.get(args['playerId']):self.feedback.problem(record,error.args[0])

    def can_interact(self, args):
        record=self.record_for_entity(args.get('victimId'))
        if record and record['owner_id']!=self.owner(args['playerId']):args['cancel']=True

    def entity_added(self, args):
        self.work.added(args)
        if args.get('engineTypeStr')==config.ENTITY:
            # ExtraData may not exist until the next engine tick.
            self.cleanup.add(('check',args['id'],self.ticks+2))

    def reconcile_entities(self, players):
        # Saved actors can load before event registration, and their runtime ID
        # can change across sessions. Reconcile identity tokens near players.
        game=Factory.CreateGame(self.level)
        for player in players:
            position=self.pos(player)
            if not position:continue
            lower=tuple(int(math.floor(v))-32 for v in position)
            upper=tuple(int(math.ceil(v))+32 for v in position)
            for entity in game.GetEntitiesInSquareArea(None,lower,upper,self.dim(player)) or []:
                if Factory.CreateEngineType(entity).GetEngineTypeStr()==config.ENTITY:
                    self.cleanup.add(('check',entity,self.ticks))

    def before_break(self,args):self.work.before_break(args)
    def projectile(self,args):self.work.projectile(args)
    def damage(self,args):
        self.work.damage(args);self.interactions.damage(args);self.attention.damage(args);self.chatter.damage(args)
    def durability(self,args):
        if domain.item_name(args.get('itemDict')) in (config.ITEM,config.WEARABLE) and args.get('canChange'):
            args['durability']=args.get('durabilityBefore',77);return
        self.supply.durability(args)

    def break_hand(self, args):
        player=args.get('playerId',args.get('entityId'))
        if not player or player not in api.GetPlayerList():return
        # A brief empty-hand use/attack only releases the pose, not the mode.
        self.outbound.pop(player,None)
        Factory.CreateModAttr(player).SetAttr('echo_companion_busy',self.ticks+18)

    def leave(self, args):
        player=args.get('id',args.get('playerId'))
        if player in self.owners:
            for record in self.owned(player):
                if record['form']=='deployed':self.suspend(record)
        self.panels.pop(player,None);self.sessions.pop(player,None);self.outbound.pop(player,None)
        self.supply.needs.pop(player,None)
        self.wardrobe.sent.pop(player,None);self.wardrobe.last.pop(player,None)

    def died(self,args):
        player=args.get('id',args.get('playerId'))
        for record in self.owned(player):
            if record['form']=='deployed':
                self.suspend(record)
                record['owner_respawn_pending']=True;record['settings']['work_mode']='follow'
                self.rt(record).pop('respawn_ready',None);self.save(record)
        self.panels.pop(player,None);self.outbound.pop(player,None)
        self.NotifyToClient(player,'Close',{})

    def respawned(self,args):
        player=args.get('playerId')
        for record in self.owned(player):
            if record.get('owner_respawn_pending'):
                self.rt(record)['respawn_ready']=self.ticks+3

    def reunite(self,player,record):
        rt=self.rt(record)
        if not self.live(player) or self.ticks<rt.get('respawn_ready',float('inf')):return
        if record.get('fallen'):
            record.pop('owner_respawn_pending',None);self.save(record);return
        target=self.near_spot(player)
        if not target:return
        entity=record.get('entity_id')
        if self.live(entity) and self.dim(entity)==self.dim(player):
            self.stop(entity);Factory.CreatePos(entity).SetFootPos(target);record['state']='following'
        else:self.spawn(player,record,target)
        record.pop('owner_respawn_pending',None);rt.pop('respawn_ready',None)
        record['settings']['work_mode']='follow';self.save(record)
        self.publish_all()

    def mob_died(self,args):
        record=self.record_for_entity(args.get('id'))
        if not record or record.get('fallen'):return
        Factory.CreateItem(record['entity_id']).SetEntityItem(Enum.ItemPosType.CARRIED,None,0)
        # The native death remains real. Its corpse has time to play the full
        # authored 0.5-second clip before the inventory WAL returns the doll.
        # Never modify the killer's inventory from inside MobDieEvent.
        self.work.cancel(record);self.unhand(record)
        self.supply.finish(record)
        rt=self.rt(record);rt['action_until']=0;rt['death_until']=self.ticks+33
        record['fallen']=True;record['state']='fallen';self.save(record)
        self.set_visual(record['entity_id'],self.visual(record))

    def recover_fallen(self,player,record):
        if self.live(record.get('entity_id')):
            self.interactions.tick(player,record);return
        rt=self.rt(record)
        if self.ticks<rt.get('death_until',0) or self.ticks%15 or not self.live(player):return
        try:
            self.work.ready(record)
            spot=self.near_spot(player)
            if not spot:return
            old=record.get('entity_id')
            if old:self.cleanup.add(old)
            record['token']=uuid.uuid4().hex;record['entity_id']=None;record['health']=1;self.save(record)
            self.spawn(player,record,spot);self.interactions.down(record)
            self.notify(player,u'伙伴倒下了，空手靠近交互救治。')
        except domain.Refused:
            if not rt.get('death_notice'):
                self.notify(player,u'伙伴已倒下，正在寻找安全落点，物品已保存。');rt['death_notice']=True

    def dimension_change(self, args):
        player=args['playerId']
        for record in self.owned(player):
            if record['form']=='deployed':self.suspend(record)
        self.panels.pop(player,None)
        self.NotifyToClient(player,'Close',{})

    def suspend(self, record):
        self.work.cancel(record)
        entity=record.get('entity_id')
        self.unhand(record);self.supply.finish(record)
        record['entity_id']=None;record['state']='fallen' if record.get('fallen') else 'suspended';record['token']=uuid.uuid4().hex
        self.save(record)
        if entity:
            self.cleanup.add(entity)
            if self.DestroyEntity(entity):self.cleanup.discard(entity)

    def path_done(self, entity, result):
        record=self.record_for_entity(entity)
        if record:
            rt=self.rt(record);rt['path_result']=result;rt['path_result_at']=self.ticks

    def move(self, record, target, speed=1):
        rt=self.rt(record)
        if not target:return
        if self.swimming.move(record,target,speed):return
        if self.ticks-rt['last_path']<18:return
        rt['last_path']=self.ticks
        # Mining searches twelve blocks away and may need to route around a
        # wall. The old 200-iteration budget barely covered a straight route.
        iterations=500 if (rt.get('job') or {}).get('kind')=='mine' else 200
        Factory.CreateMoveTo(record['entity_id']).SetMoveSetting(tuple(target),speed,iterations,self.path_done)

    def update_partner(self, player, record):
        rt=self.rt(record)
        if record.get('pending'):return
        if record.get('owner_respawn_pending'):
            self.reunite(player,record);return
        if record.get('fallen'):
            self.recover_fallen(player,record);return
        if rt.get('pending_style') and rt['offering'] is None and rt['action_until']<=self.ticks:
            record['settings']['style']=rt.pop('pending_style');record['revision']+=1;self.save(record)
            if player in self.panels:self.snapshot(player,record)
        if record['form']!='deployed':return
        if self.pos(player) is None:return
        entity=record.get('entity_id')
        # IsEntityAlive may stay true for a saved actor whose transform is not
        # available yet. Apply the same grace/recovery as an unloaded actor.
        if not self.live(entity) or self.pos(entity) is None:
            if not self.live(player) or independent(record):return
            # Give saved actors time to load and be adopted before issuing a
            # new generation. A delayed old generation is removed by the scan.
            if entity:
                if rt.get('missing_since') is None:rt['missing_since']=self.ticks
                if self.ticks-rt['missing_since']<180:return
            if self.ticks%60:return
            # New generation invalidates any unloaded old entity before replacing it.
            spot=self.near_spot(player)
            if spot:
                old=record.get('entity_id')
                waiting=record['state']=='waiting'
                if old:self.cleanup.add(old)
                record['token']=uuid.uuid4().hex;record['entity_id']=None;self.save(record)
                self.spawn(player,record,spot)
                if waiting:
                    record['state']='waiting';self.stop(record['entity_id']);self.save(record)
            return
        rt.pop('missing_since',None)
        if self.dim(entity)!=self.dim(player):self.suspend(record);return
        if rt.get('name_applied')!=(entity,record.get('name',u'')):
            if Factory.CreateName(entity).SetName(domain.native_value(record.get('name',u''))):rt['name_applied']=(entity,record.get('name',u''))
        if self.interactions.tick(player,record):return
        self.chatter.tick(player,record)
        if self.attention.tick(player,record):return
        if self.work.tick(player,record):return
        if not independent(record):self.supply.tick(player,record)
        p,e=self.pos(player),self.pos(entity)
        gap=distance(p,e)
        if record['state']=='hand_in_hand' or rt['hand_target']:
            try:target=self.can_hand(player,maintaining=record['state']=='hand_in_hand')
            except domain.Refused:target=None
            maximum_gap=12
            if not target or gap>maximum_gap:
                self.unhand(record);self.save(record);return
            if rt['hand_target']:
                if distance(e,target)<.2:
                    rt['hand_target']=False;record['state']='hand_in_hand';self.stop(entity);self.save(record)
                elif self.ticks>rt['approach_until']:
                    self.unhand(record);self.save(record);self.notify(player,u'这里牵不到手，换个平坦位置吧。')
                elif distance(e,target)<2:
                    # Native pathfinding stops short of the precise hand socket.
                    # Finish the last safe steps with real ground motion.
                    midpoint=((target[0]+e[0])/2,e[1],(target[2]+e[2])/2)
                    if not self.safe(midpoint,self.dim(entity)):
                        self.unhand(record);self.save(record);return
                    if not rt.get('approach_steer'):
                        self.stop(entity);rt['approach_steer']=True
                    current=Factory.CreateActorMotion(entity).GetMotion() or (0,0,0)
                    vx=max(-.1,min(.1,(target[0]-e[0])*.28))
                    vz=max(-.1,min(.1,(target[2]-e[2])*.28))
                    Factory.CreateActorMotion(entity).SetMotion((vx,current[1],vz))
                else:self.move(record,target,1.1)
                return
            self.lock_hand(player,record,target)
            return
        if rt['offering'] is not None:
            if gap>6 or self.ticks>rt['offer_until']:
                self.supply.finish(record);self.save(record)
            self.hold(record)
            return
        panel=self.panels.get(player)
        if panel and panel['id']==record['companion_id']:self.hold(record);return
        if record['state']=='waiting':self.hold(record);return
        if self.utility.tick(player,record):return
        if record['settings'].get('work_mode') not in ('hoe','shears') and self.modes.tick(player,record):return
        if independent(record):return
        if self.swimming.tick(player,record):return
        if gap>12:
            if rt['far_since'] is None:rt['far_since']=self.ticks
            elif self.ticks-rt['far_since']>=90:
                target=self.near_spot(player)
                if target:
                    Factory.CreatePos(entity).SetFootPos(target);rt['far_since']=None
        else:rt['far_since']=None
        # Retain a nearby resting spot while the player only turns their head.
        # A moving player starts another approach only after leaving the radius.
        chasing=rt.get('follow_chasing',False)
        if abs(p[1]-e[1])<.6 and (gap<=1.8 or (not chasing and gap<=2.8)) and self.swimming.grounded(e,self.dim(entity)):
            if chasing or not rt.get('follow_resting'):self.stop(entity)
            rt['follow_chasing']=False;rt['follow_resting']=True
            return
        rt['follow_chasing']=True;rt['follow_resting']=False
        # Approach a point along the current owner-to-companion line, independent
        # of camera yaw. This cannot chase a point that circles behind the player.
        flat=max(.01,math.hypot(e[0]-p[0],e[2]-p[2]))
        point=(p[0]+(e[0]-p[0])*1.5/flat,p[1],p[2]+(e[2]-p[2])*1.5/flat)
        target=self.safe(point,self.dim(player)) or self.near_spot(player) or p
        if target:self.move(record,target,1.6 if gap>5 else 1)

    def visual(self, record):
        rt=self.rt(record)
        offered=record['inventory'][rt['offering']] if rt['offering'] is not None else None
        display=offered or record.get('equipment',{}).get('main')
        if record['state']=='hand_in_hand':display=None
        armor={}
        for slot in ('head','chest','legs','feet'):
            item=record['equipment'].get(slot);name=domain.item_name(item).split(':')[-1]
            material=name.split('_')[0]
            armor[slot]=0 if domain.empty(item) else {'chainmail':2,'golden':3,'diamond':4,'netherite':5,'leather':6,'turtle':7}.get(material,1)
        return {'active':True,'id':record['companion_id'],'settings':record['settings'],'outfit':record['outfit'],'armor':armor,
                'state':record['state'],'action':rt['action'] if self.ticks<rt['action_until'] else 0,
                'action_stamp':rt.get('action_stamp',0),'action_elapsed':(self.ticks-rt.get('action_started',self.ticks))/30.0 if self.ticks<rt['action_until'] else 0,
                'role':self.motion_role(record),'dead':bool(record.get('fallen')),
                'offering':1 if offered else 0,'display_item':domain.clone(display),
                'hand':record['state']=='hand_in_hand',
                'hand_owner':next((p for p,owner in self.owners.items() if owner==record['owner_id']),None),
                'shield':record['state']!='hand_in_hand' and domain.item_name(record.get('equipment',{}).get('off'))=='minecraft:shield'}

    def set_visual(self, entity, value):
        if self.outbound.get(entity)!=value:
            Factory.CreateModAttr(entity).SetAttr('echo_companion_visual',domain.native_value(value))
            self.outbound[entity]=domain.clone(value)

    def sync_equipment_display(self,record,value):
        # The record remains authoritative. Native equipment is a non-dropping
        # visual mirror, never a second source for inventory recovery.
        entity=record['entity_id'];rt=self.rt(record)
        from .item_poses import native_display_item
        display=None if record.get('fallen') else native_display_item(value.get('display_item'))
        key=(entity,display)
        if rt.get('native_equipment')==key:return
        if Factory.CreateItem(entity).SetEntityItem(Enum.ItemPosType.CARRIED,domain.native_item(display) if display else None,0):
            rt['native_equipment']=domain.clone(key)

    def publish_all(self):
        for player in api.GetPlayerList():
            held=self.selected(player)
            worn=self.carry.worn(player)
            active=next((r for r in self.owned(player) if r['state']=='hand_in_hand'),None)
            value=self.visual(held or active or worn) if held or active or worn else {'active':False}
            value['held']=bool(held);value['worn']=bool(worn and not held)
            value['carry_slot']=Factory.CreateItem(player).GetSelectSlotId()
            value['hand']=bool(active) or bool(held and held['settings'].get('last_held')=='hand')
            value['busy']=(Factory.CreateModAttr(player).GetAttr('echo_companion_busy',0) or 0)>self.ticks
            value['fall_blocked']=bool(Factory.CreateFly(player).IsPlayerFlying() or Factory.CreateRide(player).IsEntityRiding() or Factory.CreatePlayer(player).isSwimming())
            self.set_visual(player,value)
        for record in self.records.values():
            if record['form']=='deployed' and self.live(record.get('entity_id')):
                value=self.visual(record)
                self.sync_equipment_display(record,value)
                self.set_visual(record['entity_id'],value)

    def tick(self):
        self.ticks+=1
        if self.ticks%3:
            for player in api.GetPlayerList():
                for record in self.owned(player):
                    if record['state']=='hand_in_hand' and record['form']=='deployed' and not record.get('fallen'):
                        try:self.lock_hand(player,record)
                        except domain.Refused:
                            self.unhand(record);self.save(record)
                        except Exception:traceback.print_exc()
            return
        players=api.GetPlayerList()
        self.wardrobe.tick()
        self.work.cleanup()
        if self.ticks%60==0:
            try:self.reconcile_entities(players)
            except Exception:traceback.print_exc()
        for task in list(self.cleanup):
            try:
                if isinstance(task,tuple):
                    kind,entity,due=task
                    if self.ticks<due:continue
                    self.cleanup.discard(task)
                    if not self.live(entity):continue
                    if kind=='retire':
                        if not self.DestroyEntity(entity):self.cleanup.add(entity)
                        continue
                    token=Factory.CreateExtraData(entity).GetExtraData('echo_companion_identity')
                    record=self.records.get((token or {}).get('id'))
                    if not record or record['form']!='deployed' or token.get('token')!=record['token']:
                        self.cleanup.add(entity)
                    elif not self.live(record.get('entity_id')):
                        record['entity_id']=entity
                        self.rt(record).pop('missing_since',None)
                        if record['state']=='hand_in_hand':record['state']='following'
                        self.save(record)
                    elif record.get('entity_id')!=entity:self.cleanup.add(entity)
                elif not self.live(task):self.cleanup.discard(task)
                elif self.DestroyEntity(task):self.cleanup.discard(task)
            except Exception:traceback.print_exc()
        for player in players:
            try:
                self.owner(player)
                if self.ticks%60==0 and player in self.sessions and self.live(player):
                    self.starter.give(player,InventoryAdapter(self,player))
                self.carry.tick(player)
                if self.ticks%15==0:self.selected(player,True)
                for record in self.owned(player):
                    self.utility.light(record)
                    self.update_partner(player,record)
                    self.feedback.flush(record)
                panel=self.panels.get(player)
                if panel:
                    record=self.records.get(panel['id'])
                    try:
                        self.accessible(player,record)
                        if panel.get('context')=='wardrobe':self.wardrobe.check(player,panel)
                        if self.ticks-panel['time']>180:raise domain.Refused(u'面板已关闭。')
                    except domain.Refused:
                        self.panels.pop(player,None);self.NotifyToClient(player,'Close',{})
                    else:
                        if self.ticks%60==0:self.snapshot(player,record)
            except domain.Refused:pass
            except Exception:traceback.print_exc()
        if self.ticks%6==0:
            try:self.publish_all()
            except Exception:traceback.print_exc()
        if self.ticks%300==0:
            for record in self.records.values():
                if record['form']=='deployed' and self.live(record.get('entity_id')):
                    record['last_position']={'pos':list(self.pos(record['entity_id'])),'dimension':self.dim(record['entity_id'])}
                    self.save(record)

    def Destroy(self):
        self.utility.cleanup()
        self.work.destroy()
        for record in self.records.values():
            if record['state']=='hand_in_hand':record['state']='following'
            self.save(record)
        for namespace,system,event,handler in self.events:self.UnListenForEvent(namespace,system,event,self,handler)
