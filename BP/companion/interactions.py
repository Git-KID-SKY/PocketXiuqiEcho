# -*- coding: utf-8 -*-
from __future__ import division
import math,random,time,uuid
import mod.server.extraServerApi as api
from . import config,domain,interaction_rules as rules
F=api.GetEngineCompFactory();E=api.GetMinecraftEnum()
def gap(a,b):return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))

class Interactions(object):
    def __init__(self,system):self.s=system;self.selected_slots={}
    def adapter(self,player):
        from .server import InventoryAdapter
        return InventoryAdapter(self.s,player)
    def settings(self,player):
        data=self.s.world.GetExtraData('ec_preferences_'+self.s.owner(player))
        if isinstance(data,domain.string_types):
            import json
            data=json.loads(data)
        result=dict(rules.DEFAULTS);result.update(data or {});return result
    def option(self,player,key,value):
        import json
        value=rules.clean_preference(key,value)
        prefs=self.settings(player);prefs[key]=value
        if not self.s.world.SetExtraData('ec_preferences_'+self.s.owner(player),json.dumps(prefs,ensure_ascii=True)):
            raise domain.Refused(u'设置暂时无法保存。')
        records=self.s.owned(player)
        # Naming applies to the held/nearest companion. Preferences apply to all.
        chosen=self.s.selected(player) or self.s.carry.worn(player) or next((r for r in records if r['form']=='deployed'),None) or (records[0] if records else None)
        for record in records:
            if key=='name':
                if record is not chosen:continue
                record['name']=value;self.s.rt(record).pop('name_applied',None)
            else:
                record['settings'][key]=value
                if key=='food_prompt':record['settings']['supply_mode']='prompt' if value else 'off'
                if key=='hunt_animals' and record['settings'].get('active_work'):self.mode(record)
            self.s.save(record)
        self.s.NotifyToClient(player,'Preferences',prefs)
        self.s.notify(player,u'已保存。');self.s.publish_all()
    def apply_preferences(self,player,record):
        prefs=self.settings(player)
        for k in rules.DEFAULTS:record['settings'][k]=prefs[k]
        record['name']=prefs.get('name',config.DEFAULT_NAME)
        record['settings']['supply_mode']='prompt' if prefs['food_prompt'] else 'off'
    def mode(self,record):
        mode=rules.work_mode(record,self.s.work.info(record['equipment'].get('main')))
        record['settings']['work_mode']=mode
        rt=self.s.rt(record);rt['mode_next']=0;rt.pop('wander_target',None)
        record['state']='waiting' if record['settings']['movement']=='wait' else 'following'
        rt.pop('stair_plan',None);rt.pop('stair_origin',None)
        rt.pop('utility_target',None);rt.pop('tree',None)
        self.s.feedback.changed(record)
    def use(self,player,record):
        self.s.accessible(player,record)
        entity=record.get('entity_id')
        if not self.s.live(entity) or gap(self.s.pos(player),self.s.pos(entity))>4.5:raise domain.Refused(u'靠近伙伴再交互。')
        rt=self.s.rt(record)
        if self.s.ticks-rt.get('last_interaction',-100)<8:return
        rt['last_interaction']=self.s.ticks
        adapter=self.adapter(player);items=adapter.inventory();slot=F.CreateItem(player).GetSelectSlotId();held=items[slot]
        name=domain.item_name(held);sneak=bool(F.CreatePlayer(player).isSneaking());operation='interact:'+uuid.uuid4().hex
        if name=='minecraft:stick' and sneak:
            self.s.work.cancel(record);self.s.unhand(record);self.s.supply.finish(record)
            self.s.recall(player,record,'hold',operation);self.s.notify(player,u'已收回。');return
        if record.get('fallen'):
            if not domain.empty(held):raise domain.Refused(u'空出手，靠近交互救治。')
            if not rt.get('revive'):
                rt['revive']={'player':player,'until':self.s.ticks+90,'origin':self.s.pos(player),'pulse_at':self.s.ticks+20}
                self.s.effect(record,'revive')
                self.s.notify(player,u'正在救治，留在身边 3 秒。')
            return
        self.s.work.ready(record)
        if name=='minecraft:stick':
            self.s.work.cancel(record);self.s.unhand(record);self.s.supply.finish(record)
            choices=('follow','roam','wait');current=record['settings'].get('movement','follow')
            movement=choices[(choices.index(current)+1)%3];record['settings']['movement']=movement
            tool=record['equipment'].get('main')
            if rules.kind(tool,self.s.work.info(tool)) in ('pickaxe','axe','shovel','hoe','shears'):
                record['settings']['active_work']=movement=='roam'
            self.mode(record);self.s.stop(entity);self.s.commit(record,operation)
            self.s.notify(player,{'follow':u'跟随你','roam':u'在附近自由活动','wait':u'留在这里等你'}[movement]);return
        if domain.empty(held):
            if rt['offering'] is not None:
                self.s.supply.deliver(player,record,rt['offering'],operation,rt.get('offer_kind')=='food')
                self.s.supply.finish(record);self.s.save(record);self.s.notify(player,u'接到了。');return
            self.s.work.cancel(record)
            if sneak:
                enabled=not record['settings'].get('active_work',False)
                if enabled:
                    planned=domain.clone(record);planned['settings']['active_work']=True
                    work=rules.work_mode(planned,self.s.work.info(planned['equipment'].get('main')))
                    if work=='follow':raise domain.Refused(u'先递给我工具，再潜行空手点我开工～')
                    self.s.modes.check(planned,work)
                    if work in ('excavate','hoe','shears') and record['settings']['movement']=='wait':
                        record['settings']['movement']='roam'
                record['settings']['active_work']=enabled
                self.mode(record);self.s.commit(record,operation)
                self.s.notify(player,u'主动协助已开启。' if record['settings']['active_work'] else u'主动协助已关闭，继续陪着你。');return
            equipment=next((k for k in ('main','off') if not domain.empty(record['equipment'].get(k))),None)
            if equipment:
                after,patches=rules.swap(record,items,slot,equipment)
                if equipment=='main':after['settings']['active_work']=False
                domain.transaction(adapter,record,after,patches,operation);self.mode(record);self.s.save(record)
                self.s.notify(player,u'装备还给你了。');return
            self.s.open_panel(player,record);return
        if sneak:
            sample=rules.sample(held)
            if sample:
                from .work_rules import MINING,mining_tool_error
                problem=mining_tool_error(self.s.work.info(record['equipment'].get('main')),*MINING[sample['name']])
                if problem:raise domain.Refused(problem)
                self.s.work.cancel(record)
                if sample==record['settings'].get('mine_sample'):
                    record['settings']['mine_sample']=None;self.mode(record);self.s.commit(record,operation)
                    self.s.notify(player,u'已取消采集目标限制，样本仍留在你手中。');return
                record['settings']['mine_sample']=sample
                record['settings']['active_work']=True;self.mode(record);self.s.commit(record,operation)
                self.s.notify(player,u'记住这种采集目标了，样本仍留在你手中。');return
        info=self.s.work.info(held);equipment=rules.slot_for(held,info)
        if equipment:
            self.s.work.cancel(record);self.s.supply.finish(record);self.s.unhand(record)
            after,patches=rules.swap(record,items,slot,equipment)
            self.s.work.validate_equipment(after)
            # A changed tool starts in its passive mode. Deliberate crouch toggles autonomy.
            if equipment=='main':after['settings']['active_work']=False
            if equipment=='main':
                from .work_rules import MINING
                selected=after['settings'].get('mine_sample')
                if selected and MINING.get(selected['name'],(None,))[0]!=rules.kind(held,info):after['settings']['mine_sample']=None
            domain.transaction(adapter,record,after,patches,operation);self.mode(record);self.s.save(record)
            self.s.notify(player,u'装备好了。潜行空手交互可开启主动协助。');return
        if info.get('foodNutrition',0)>0:
            self.feed(player,record,items,slot,operation);return
        if name=='minecraft:name_tag':
            label=held.get('customName') or ((held.get('userData') or {}).get('display') or {}).get('Name')
            if isinstance(label,dict):label=label.get('__value__')
            if label:self.option(player,'name',label);return
        # Ordinary held items open only storage; no mode-selection panel.
        self.s.open_panel(player,record)
    def feed(self,player,record,items,slot,operation):
        entity=record['entity_id'];attr=F.CreateAttr(entity);health=attr.GetAttrValue(E.AttrType.HEALTH)
        if health>=20:raise domain.Refused(u'现在很健康，不用喂食。')
        food=items[slot];value=domain.clone(food);value['count']-=1
        after=domain.clone(record);nutrition=self.s.work.info(food).get('foodNutrition',2)
        after['health']=min(20,health+max(1,nutrition));after['heal_pending']=after['health']
        domain.transaction(self.adapter(player),record,after,[{'slot':slot,'before':food,'after':value if value['count'] else None}],operation)
        self.apply_heal(record);self.s.action(record,2,.9)
    def apply_heal(self,record):
        if 'heal_pending' not in record:return
        if F.CreateAttr(record['entity_id']).SetAttrValue(E.AttrType.HEALTH,record['heal_pending']):
            record.pop('heal_pending',None);self.s.save(record)
            if self.s.rt(record).pop('revive_complete',False):self.s.effect(record,'revived')
    def down(self,record):
        self.s.work.cancel(record);self.s.unhand(record);self.s.supply.finish(record)
        record['fallen']=True;record['state']='fallen';record['health']=1
        self.s.rt(record)['action_until']=0
        F.CreateAttr(record['entity_id']).SetAttrValue(E.AttrType.HEALTH,1)
        self.s.stop(record['entity_id']);self.s.save(record)
        self.s.set_visual(record['entity_id'],self.s.visual(record))
    def damage(self,args):
        record=self.s.record_for_entity(args.get('entityId'))
        if not record:return
        rt=self.s.rt(record)
        if record.get('fallen') or self.s.ticks<rt.get('revive_grace',0):
            args['damage']=0;args['knock']=False;args['ignite']=False;return
        amount=max(0,args.get('damage',0))
        shield=record['equipment'].get('off');attacker=args.get('srcId')
        if amount>0 and domain.item_name(shield)=='minecraft:shield' and self.s.live(attacker) and args.get('cause') in (E.ActorDamageCause.EntityAttack,E.ActorDamageCause.Projectile):
            from . import work_rules
            if work_rules.in_front(self.s.pos(record['entity_id']),F.CreateRot(record['entity_id']).GetRot()[1],self.s.pos(attacker)):
                maximum=self.s.work.info(shield).get('maxDurability',336);worn=shield
                for unused in range(min(int(math.ceil(amount))+1,int(shield.get('durability',maximum)))):
                    if domain.empty(worn):break
                    worn=work_rules.wear(worn,maximum,random.random())
                record['equipment']['off']=worn;amount*=.25;args['knock']=False;self.s.action(record,8,.6)
        defense=sum(max(0,self.s.work.info(record['equipment'].get(k)).get('armorDefense',0)) for k in rules.ARMOR)
        if args.get('cause') not in ('void','starve','drowning','suffocation','magic','wither'):
            amount*=1-min(20,defense)*.04
        args['damage']=amount
        health=F.CreateAttr(record['entity_id']).GetAttrValue(E.AttrType.HEALTH)
        if amount>=health and amount>0:
            args['damage']=0;args['knock']=False;self.down(record)
        elif amount>0:
            record['health']=max(1,health-amount)
            from . import work_rules
            for k in rules.ARMOR:
                item=record['equipment'].get(k)
                if not domain.empty(item):record['equipment'][k]=work_rules.wear(item,self.s.work.info(item).get('maxDurability',1),random.random())
            self.s.save(record)
    def tick(self,player,record):
        rt=self.s.rt(record);entity=record.get('entity_id')
        if not self.s.live(entity):return False
        if record.get('fallen'):
            self.s.hold(record);revive=rt.get('revive')
            if revive:
                items=self.adapter(player).inventory();selected=F.CreateItem(player).GetSelectSlotId()
                if revive['player']!=player or gap(self.s.pos(player),self.s.pos(entity))>2.5 or gap(self.s.pos(player),revive['origin'])>.65 or not domain.empty(items[selected]):
                    rt.pop('revive',None);self.s.effect(record,'revive_cancel');self.s.notify(player,u'救治中断，空手靠近后可重试。')
                elif self.s.ticks>=revive['until']:
                    record['fallen']=False;record['health']=4;record['heal_pending']=4
                    rt.pop('revive',None);rt['revive_grace']=self.s.ticks+60;rt['resting_hurt']=False
                    self.s.effect(record,'revive_cancel');rt['revive_complete']=True
                    self.mode(record);self.apply_heal(record);self.s.save(record);self.s.notify(player,u'救起来了，先喂点食物恢复。')
                elif self.s.ticks>=revive.get('pulse_at',0):
                    self.s.effect(record,'revive');revive['pulse_at']=self.s.ticks+20
            return True
        self.apply_heal(record)
        if self.s.ticks%30==0 and record['settings'].get('auto_eat') and not rt.get('job'):
            attr=F.CreateAttr(entity);health=attr.GetAttrValue(E.AttrType.HEALTH)
            if health<20 and self.s.ticks>=rt.get('eat_next',0):
                from .supply import food_slot
                slot=food_slot(record)
                if slot is not None:
                    item=record['inventory'][slot];nutrition=self.s.work.info(item).get('foodNutrition',2)
                    after=domain.clone(record);after['inventory'][slot]['count']-=1
                    if after['inventory'][slot]['count']<=0:after['inventory'][slot]=None
                    after['health']=min(20,health+max(1,nutrition));after['heal_pending']=after['health']
                    self.s.work.put(record,after);self.apply_heal(record);rt['eat_next']=self.s.ticks+90
        return False
