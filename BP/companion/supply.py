# -*- coding: utf-8 -*-
"""Five-second, empty-hand collection of real food and replacement items."""
import time,uuid,math
import mod.server.extraServerApi as api
from . import config,domain,work_rules as rules,interaction_rules
F=api.GetEngineCompFactory()

def food_slot(record,preference=None):
    names=config.FOOD_GROUPS[preference] if preference in config.FOOD_GROUPS else sum((config.FOOD_GROUPS[k] for k in ('bread','cooked','fruit')),())
    allowed=set('minecraft:'+name for name in names)
    return next((i for i,v in enumerate(record['inventory']) if not domain.empty(v) and domain.item_name(v) in allowed),None)

class Supply(object):
    def __init__(self,system):self.s=system;self.needs={};self.placements={};self.empty_blocks={}
    def say(self,player,record,message):
        self.s.NotifyToClient(player,'Speech',{'entity':record.get('entity_id'),'message':message})
    def status(self,player,record):
        mode=record['settings'].get('supply_mode','prompt')
        if mode=='off':return u'食物补给已关闭；装备和方块补给独立设置。'
        if self.player_has_food(player):return u'你背包里还有食物，暂时不用补给。'
        if food_slot(record,record['settings'].get('food_choice')) is None:return u'伙伴背包中没有符合偏好的食物。'
        return { 'prompt':u'递到面前后空手领取；5 秒未领取会收回。','auto':u'缺食物且饥饿时，直接送入背包。','drop':u'缺食物且饥饿时，放到你面前拾取。'}[mode]
    def tool_kind(self,item):return interaction_rules.kind(item,self.s.work.info(item))
    def durability(self,args):
        player=args.get('entityId')
        if player not in api.GetPlayerList() or not args.get('canChange',False):return
        if self.s.work.capture or any(r.get('tool_loan') for r in self.s.owned(player)):return
        if args.get('durabilityBefore',0)>0 and args.get('durability',1)<=0:
            kind=self.tool_kind(args.get('itemDict'))
            if kind:self.needs[player]={'kind':kind,'until':self.s.ticks+900}
    def placed(self,args):
        player=args.get('entityId',args.get('playerId'))
        if player in api.GetPlayerList():self.placements[player]=(self.s.ticks,args.get('fullName'))
    def inventory_changed(self,args):
        player=args.get('playerId');old=args.get('oldItemDict');new=args.get('newItemDict')
        if player not in api.GetPlayerList() or not domain.empty(new) or domain.empty(old):return
        if args.get('slot')!=F.CreateItem(player).GetSelectSlotId():return
        if self.s.work.info(old).get('itemType')=='block':self.empty_blocks[player]=(self.s.ticks,domain.clone(old))
    def reserve(self,record,slot,operation):
        if slot is not None:
            if type(slot) is not int or not 0<=slot<len(record['inventory']):raise domain.Refused(u'先在伙伴背包选一件备用装备。')
            if not self.tool_kind(record['inventory'][slot]):raise domain.Refused(u'这一格不是工具、武器或盔甲。')
        after=domain.clone(record);after['settings']['backup_slot']=slot;self.s.work.put(record,after,operation)
    def offer(self,record,slot,kind):
        rt=self.s.rt(record);rt['offer_return']='waiting' if record['state']=='waiting' else 'following'
        self.s.unhand(record);self.s.stop(record['entity_id'])
        rt['offering']=slot;rt['offer_kind']=kind;rt['offer_until']=self.s.ticks+150
        rt['offer_item']=domain.clone(record['inventory'][slot])
        record['state']='offering';self.s.action(record,2,.9);self.s.effect(record,'offer');self.s.save(record)
    def finish(self,record):
        rt=self.s.rt(record);rt['offering']=None
        for key in ('offer_kind','offer_item','auto_food'):rt.pop(key,None)
        record['state']=rt.pop('offer_return','following') if record['form']=='deployed' else 'stored'
    def deliver(self,player,record,slot,operation,food=False):
        from .server import InventoryAdapter
        adapter=InventoryAdapter(self.s,player);items=adapter.inventory();rt=self.s.rt(record)
        if self.s.ticks>rt.get('offer_until',0):raise domain.Refused(u'它已经把东西收回去了。')
        source=record['inventory'][slot]
        if not domain.same(source,rt.get('offer_item')):raise domain.Refused(u'这份物品已变化，请稍后再取。')
        amount=min(source['count'],64) if rt.get('offer_kind')=='block' else 1
        take=domain.clone(source);take['count']=amount
        updated=rules.insert(items,take,self.s.work.info(source).get('maxStackSize',64))
        after=domain.clone(record);after['inventory'][slot]['count']-=amount
        if after['inventory'][slot]['count']<=0:after['inventory'][slot]=None
        after['supply_next_at']=time.time()+record['settings'].get('supply_interval',30)
        patches=[{'slot':i,'before':items[i],'after':updated[i]} for i in range(36) if not domain.same(items[i],updated[i])]
        domain.transaction(adapter,record,after,patches,operation)
    def drop_food(self,player,record,slot):
        before=domain.clone(record);item=domain.clone(record['inventory'][slot]);item['count']=1
        p=self.s.pos(player);angle=math.radians(F.CreateRot(player).GetRot()[1])
        point=(p[0]-math.sin(angle)*1.5,p[1]+.6,p[2]+math.cos(angle)*1.5)
        block=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(int(math.floor(v)) for v in point),self.s.dim(player))
        if not block or block.get('name') not in ('minecraft:air','minecraft:water','minecraft:flowing_water'):point=(p[0],p[1]+.65,p[2])
        after=domain.clone(record);after['inventory'][slot]['count']-=1
        if after['inventory'][slot]['count']==0:after['inventory'][slot]=None
        after['supply_next_at']=time.time()+record['settings'].get('supply_interval',30)
        # Reserve before emitting a world item; never replay an emitted drop.
        self.s.work.put(record,after,'food-drop:'+uuid.uuid4().hex)
        drop=self.s.CreateEngineItemEntity(domain.native_item(item),self.s.dim(player),point)
        if not drop:
            self.s.work.put(record,before);raise domain.Refused(u'暂时不能丢出食物，食物仍在伙伴背包。')
        F.CreateActorMotion(drop).SetMotion((0,.07,0));return drop
    def changed(self,record):
        rt=self.s.rt(record)
        if rt.get('offer_kind')=='food' and not record['settings'].get('food_prompt',True):self.finish(record);self.s.save(record)
    def player_has_food(self,player):
        from .server import InventoryAdapter
        return any(not domain.empty(v) and self.s.work.info(v).get('foodNutrition',0)>0 for v in InventoryAdapter(self.s,player).inventory())
    def tick(self,player,record):
        rt=self.s.rt(record);settings=record['settings']
        emptied=self.empty_blocks.get(player)
        if emptied:
            placed=self.placements.get(player,(-100,None));old=emptied[1]
            if abs(placed[0]-emptied[0])<=3 and placed[1]==domain.item_name(old):
                self.needs[player]={'kind':'block','name':domain.item_name(old),'aux':old.get('newAuxValue',old.get('auxValue',0)),'until':self.s.ticks+900}
                self.empty_blocks.pop(player,None)
            elif self.s.ticks-emptied[0]>3:self.empty_blocks.pop(player,None)
        if rt.get('danger_until',0)>self.s.ticks:
            if rt['offering'] is not None:self.finish(record);self.s.save(record)
            return
        if self.s.ticks%30 or rt.get('job') or rt['offering'] is not None or player in self.s.panels:return
        if record.get('pending') or record.get('tool_loan') or record.get('loot_pending'):return
        if time.time()<record.get('supply_next_at',0):return
        p,e=self.s.pos(player),self.s.pos(record['entity_id'])
        if not p or not e or sum((p[i]-e[i])**2 for i in range(3))>2.3**2:return
        need=self.needs.get(player)
        if need and need['until']<self.s.ticks:self.needs.pop(player,None);need=None
        slot=None;kind=None
        if need and settings.get('block_supply' if need['kind']=='block' else 'tool_prompt',True):
            indices=list(range(len(record['inventory'])));backup=settings.get('backup_slot')
            if backup in indices:indices.remove(backup);indices.insert(0,backup)
            for i in indices:
                item=record['inventory'][i]
                if domain.empty(item):continue
                match=(domain.item_name(item)==need['name'] and item.get('newAuxValue',item.get('auxValue',0))==need['aux']) if need['kind']=='block' else self.tool_kind(item)==need['kind']
                if match and item.get('durability',1)>0:slot=i;kind='block' if need['kind']=='block' else 'tool';break
        if slot is None and settings.get('food_prompt',True) and settings.get('supply_mode')!='off':
            hunger=F.CreatePlayer(player).GetPlayerHunger()
            if hunger is not None and hunger<settings.get('hunger_threshold',20) and not self.player_has_food(player):slot=food_slot(record,settings.get('food_choice'));kind='food'
        if slot is None:return
        if need and kind!='food':self.needs.pop(player,None)
        record['supply_next_at']=time.time()+settings.get('supply_interval',30)
        if kind=='food' and settings.get('supply_mode')=='drop':
            self.drop_food(player,record,slot);self.say(player,record,u'食物放在你面前了～');return
        self.offer(record,slot,kind)
        if kind=='food' and settings.get('supply_mode')=='auto':
            try:self.deliver(player,record,slot,'auto-food:'+uuid.uuid4().hex,True)
            except domain.Refused:
                self.finish(record);self.s.save(record);return
            self.finish(record);self.s.save(record);self.say(player,record,u'食物放进你的背包了～');return
        self.say(player,record,{'food':u'给你留了吃的，空手接一下～','tool':u'备用装备给你，空手接一下！','block':u'还有方块，空手接一下！'}[kind])
