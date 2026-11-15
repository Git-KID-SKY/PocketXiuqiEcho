# -*- coding: utf-8 -*-
import random,uuid
import mod.server.extraServerApi as api
from . import config,domain
F=api.GetEngineCompFactory();E=api.GetMinecraftEnum()
class Carry(object):
    def __init__(self,system):self.s=system;self.selections={}
    def worn(self,player,bind=False):
        item=F.CreateItem(player).GetPlayerItem(E.ItemPosType.ARMOR,1,True)
        if domain.item_name(item) not in (config.ITEM,config.WEARABLE):return None
        parts=domain.token_parts(item)
        if parts:
            record=self.s.records.get(parts[0])
            if record and record['owner_id']==self.s.owner(player) and record['token']==parts[1] and record['form']=='stored':return record
        elif bind:
            from .server import InventoryAdapter
            record=domain.new_record(self.s.owner(player));self.s.interactions.apply_preferences(player,record)
            self.s.save(record);after=domain.clone(record)
            domain.transaction(InventoryAdapter(self.s,player,True),record,after,[{'slot':37,'before':item,'after':domain.doll(record,True)}],'wear_bind:'+uuid.uuid4().hex)
            return record
        return None
    def set_worn(self,player,record,enabled,operation):
        from .server import InventoryAdapter
        if record['form']!='stored':raise domain.Refused(u'先潜行用木棍收回伙伴，再背到身后。')
        adapter=InventoryAdapter(self.s,player,True);items=adapter.inventory();after=domain.clone(record)
        identity=(record['companion_id'],record['token'])
        if enabled:
            if not domain.empty(items[37]):raise domain.Refused(u'先空出胸甲格，再把修齐背到身后。')
            slot=next((i for i,v in enumerate(items[:36]) if domain.token_parts(v)==identity),None)
            if slot is None:raise domain.Refused(u'公仔不在背包中，请重新拿起。')
            patches=[{'slot':slot,'before':items[slot],'after':None},{'slot':37,'before':items[37],'after':domain.doll(after,True)}]
            if len(after['inventory'])<54:after['inventory'].extend([None]*(54-len(after['inventory'])))
        else:
            if domain.token_parts(items[37])!=identity:raise domain.Refused(u'这只伙伴没有背在身后。')
            selected=F.CreateItem(player).GetSelectSlotId()
            slot=selected if 0<=selected<36 and domain.empty(items[selected]) else domain.first_empty(items[:36])
            patches=[{'slot':37,'before':items[37],'after':None},{'slot':slot,'before':items[slot],'after':domain.doll(after)}]
        after['worn']=enabled
        domain.transaction(adapter,record,after,patches,operation)
        if not enabled and slot<9:F.CreatePlayer(player).ChangeSelectSlot(slot)
        self.selections[player]=(F.CreateItem(player).GetSelectSlotId(),record['companion_id'] if not enabled else None)
    def normalize_tokens(self,player,worn):
        # Armor items are rendered as flat inventory icons when held in this
        # NetEase engine. Convert representations without changing identity.
        from .server import InventoryAdapter
        adapter=InventoryAdapter(self.s,player,True);items=adapter.inventory()
        changes=[]
        if worn and domain.item_name(items[37])==config.ITEM:changes.append((37,worn,config.WEARABLE))
        for slot,item in enumerate(items[:36]):
            if domain.item_name(item)!=config.WEARABLE:continue
            parts=domain.token_parts(item);record=self.s.records.get(parts[0]) if parts else None
            if record and record['token']==parts[1] and record['form']=='stored' and record['owner_id']==self.s.owner(player):changes.append((slot,record,config.ITEM))
        for slot,record,name in changes:
            if record.get('pending'):continue
            value=domain.normalized(items[slot]);value['newItemName']=name;after=domain.clone(record)
            if slot<36:after['worn']=False
            domain.transaction(adapter,record,after,[{'slot':slot,'before':items[slot],'after':value}],'carry_kind:'+uuid.uuid4().hex)
    def tick(self,player):
        worn=self.worn(player,True)
        self.normalize_tokens(player,worn)
        for record in self.s.owned(player):
            enabled=record is worn
            if bool(record.get('worn'))!=enabled:
                record['worn']=enabled
                if enabled and len(record['inventory'])<54:record['inventory'].extend([None]*(54-len(record['inventory'])))
                self.s.save(record)
        slot=F.CreateItem(player).GetSelectSlotId();record=self.s.selected(player,True)
        key=(slot,record['companion_id'] if record else None)
        if self.selections.get(player)==key:return
        self.selections[player]=key
        if record and record['settings'].get('random_carry',True):
            mode=random.choice(('hold','hug'))
            record['settings']['mode']=mode;record['settings']['last_held']=mode
            self.s.save(record)
