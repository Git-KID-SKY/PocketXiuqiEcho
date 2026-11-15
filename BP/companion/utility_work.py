# -*- coding: utf-8 -*-
"""Bounded shearing/farming and tracked, removable companion light blocks."""
import math,random
import mod.server.extraServerApi as api
from . import domain,work_rules,interaction_rules
from .navigation_rules import palette_position, TARGET_RETRY_TICKS
F=api.GetEngineCompFactory();E=api.GetMinecraftEnum()
SEEDS={'minecraft:wheat_seeds':'minecraft:wheat','minecraft:beetroot_seeds':'minecraft:beetroot',
       'minecraft:carrot':'minecraft:carrots','minecraft:potato':'minecraft:potatoes'}
CROPS=frozenset(SEEDS.values())
LIGHT='echo:companion_light'
def distance(a,b):return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))

class UtilityWork(object):
    def __init__(self,system):self.s=system
    def block_tick(self,args):
        if args.get('blockName')!=LIGHT:return
        pos=(args['posX'],args['posY'],args['posZ']);dim=args['dimension']
        players=set(api.GetPlayerList())
        for record in self.s.records.values():
            last=record.get('light_position')
            if not last or last['dimension']!=dim or tuple(last['pos'])!=pos:continue
            owner=next((p for p in players if self.s.owners.get(p)==record['owner_id']),None)
            if owner and record['form']=='deployed' and self.s.live(record.get('entity_id')) and not record.get('fallen') and domain.item_name(record['equipment'].get('main')) in interaction_rules.TORCHES:return
        F.CreateBlockInfo(self.s.level).SetBlockNew(pos,{'name':'minecraft:air','aux':0},0,dim,False)
    def clear_light(self,record):
        last=record.get('light_position')
        if not last:return
        block=F.CreateBlockInfo(self.s.level);p=tuple(last['pos']);dim=last['dimension']
        current=block.GetBlockNew(p,dim)
        if not current:return
        if current['name']==LIGHT and not block.SetBlockNew(p,{'name':'minecraft:air','aux':0},0,dim,False):return
        record.pop('light_position',None);self.s.save(record)
    def light(self,record):
        enabled=record['form']=='deployed' and not record.get('fallen') and self.s.live(record.get('entity_id')) and domain.item_name(record['equipment'].get('main')) in interaction_rules.TORCHES
        if not enabled:self.clear_light(record);return
        entity=record['entity_id'];point=self.s.pos(entity)
        if not point:return
        pos=tuple(int(math.floor(v)) for v in (point[0],point[1]+.5,point[2]));dim=self.s.dim(entity)
        target={'pos':list(pos),'dimension':dim}
        if record.get('light_position')==target:return
        self.clear_light(record)
        if record.get('light_position'):return
        block=F.CreateBlockInfo(self.s.level);current=block.GetBlockNew(pos,dim)
        if current and current['name']=='minecraft:air':
            # Journal before placement; cleanup only removes our dedicated type.
            record['light_position']=target;self.s.save(record)
            if not block.SetBlockNew(pos,{'name':LIGHT,'aux':0},0,dim,False):
                record.pop('light_position',None);self.s.save(record)
    def tick(self,player,record):
        rt=self.s.rt(record);mode=record['settings'].get('work_mode')
        if mode not in ('hoe','shears') or record['state'] in ('waiting','hand_in_hand') or rt['offering'] is not None:return False
        if player in self.s.panels or rt.get('pause_work'):return False
        tool=record['equipment'].get('main')
        if interaction_rules.kind(tool,self.s.work.info(tool))!=mode or (tool or {}).get('durability',1)<=0:
            self.s.modes.failed(record,u'工具用坏啦，换一把再开工吧～');return False
        entity=record['entity_id'];pos=self.s.pos(entity)
        target=rt.get('utility_target')
        if target:
            if mode=='shears':
                if not self.s.live(target.get('entity')):rt.pop('utility_target',None);return False
                target['point']=self.s.pos(target['entity'])
            point=target['point']
            if self.s.ticks>target['until']:
                self.s.attention.defer(record,target,TARGET_RETRY_TICKS)
                rt.pop('utility_target',None)
                return True
            if distance(pos,point)>1.8:
                self.s.move(record,point,1.2)
                return True
            dimension=self.s.dim(entity)
            eye=(pos[0],pos[1]+.65,pos[2])
            if target.get('harvest'):
                x,y,z=target['block']
                aim=(x+.5,y+.4,z+.5)
            else:
                aim=(point[0],point[1]+.5,point[2])
            if not self.s.work.clear(dimension,eye,aim,target.get('block')):
                self.s.attention.defer(record,target,TARGET_RETRY_TICKS)
                rt.pop('utility_target',None)
                return True
            self.s.stop(entity)
            try:
                self.s.work.allowed(player,'mine')
                if mode=='shears':self.shear(record,target['entity'])
                elif target.get('harvest'):self.harvest(player,record,target)
                else:self.farm(record,target['block'],target['dimension'])
            except domain.Refused as error:
                self.s.modes.failed(record,error.args[0]);return False
            rt.pop('utility_target',None);rt['utility_next']=self.s.ticks+45;return True
        if self.s.ticks<rt.get('utility_next',0):return True
        rt['utility_next']=self.s.ticks+30
        dimension=self.s.dim(entity)
        if mode=='shears':
            x,y,z=pos
            entities=F.CreateGame(self.s.level).GetEntitiesInSquareArea(
                None,(x-18,y-4,z-18),(x+18,y+4,z+18),dimension) or []
            sheep=[]
            for other in entities:
                if F.CreateEngineType(other).GetEngineTypeStr()!='minecraft:sheep':continue
                if self.s.attention.blocked(record,{'entity':other}):continue
                if F.CreateActorOwner(other).GetEntityOwner() not in (None,'-1',player):continue
                if F.CreateEntityDefinitions(other).IsSheared() or F.CreateEntityDefinitions(other).IsBaby():continue
                point=self.s.pos(other)
                if point and distance(pos,point)<=18:
                    sheep.append((distance(pos,point),other,point))
            if sheep:
                unused,other,point=min(sheep)
                rt['utility_target']={'entity':other,'point':point,'until':self.s.ticks+240}
        else:
            target=self.find_crop(record,pos,dimension)
            if target:
                rt['utility_target']=target
                return True
            if not any(not domain.empty(v) and domain.item_name(v) in SEEDS for v in record['inventory']):
                return True
            block=F.CreateBlockInfo(self.s.level)
            x,z=int(math.floor(pos[0])),int(math.floor(pos[2]))
            # Hydrated farmland puts the actor 1/16 below the normal foot plane.
            y=int(math.floor(pos[1]+.1))
            for dx,dz in sorted(((a,b) for a in range(-4,5) for b in range(-4,5)),key=lambda q:q[0]**2+q[1]**2):
                ground=(x+dx,y-1,z+dz);soil=block.GetBlockNew(ground,dimension);above=block.GetBlockNew((ground[0],y,ground[2]),dimension)
                if self.s.attention.blocked(record,{'block':ground,'dimension':dimension}):continue
                if not soil or soil['name'] not in ('minecraft:dirt','minecraft:grass','minecraft:grass_block','minecraft:farmland') or not above or above['name']!='minecraft:air':continue
                water=any((block.GetBlockNew((ground[0]+a,ground[1],ground[2]+b),dimension) or {}).get('name') in ('minecraft:water','minecraft:flowing_water') for a,b in ((1,0),(-1,0),(0,1),(0,-1),(2,0),(-2,0),(0,2),(0,-2),(3,0),(-3,0),(0,3),(0,-3),(4,0),(-4,0),(0,4),(0,-4)))
                if not water:continue
                rt['utility_target']={'block':ground,'dimension':dimension,'point':(ground[0]+.5,y,ground[2]+.5),'until':self.s.ticks+180};break
        if not rt.get('utility_target'):
            self.s.feedback.problem(record,u'附近没有长好毛的小羊，带我找找吧～' if mode=='shears' else u'带我去水边的空地，我再开始种植～')
        return True

    def find_crop(self,record,pos,dimension):
        x,y,z=[int(math.floor(v)) for v in pos]
        start=(x-10,y-2,z-10);end=(x+10,y+2,z+10)
        palette=F.CreateBlock(record['entity_id']).GetBlockPaletteBetweenPos(dimension,start,end,False)
        if not palette:return None
        data=palette.SerializeBlockPalette()
        cells=[]
        for (name,aux),indexes in data['common'].items():
            if name in CROPS:
                cells.extend(palette_position(i,data['volume'],start) for i in indexes)
        states=F.CreateBlockState(self.s.level)
        for cell in sorted(cells,key=lambda p:distance(pos,p)):
            target={'block':cell,'dimension':dimension}
            if self.s.attention.blocked(record,target):continue
            if (states.GetBlockStates(cell,dimension) or {}).get('growth')!=7:continue
            stand=self.s.safe((cell[0]+.5,cell[1],cell[2]+.5),dimension)
            if not stand:
                for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                    stand=self.s.safe((cell[0]+dx+.5,cell[1],cell[2]+dz+.5),dimension)
                    if stand:break
            if stand:
                target.update(point=stand,until=self.s.ticks+240,harvest=True)
                return target
        return None

    def harvest(self,player,record,target):
        cell=tuple(target['block']);dimension=target['dimension']
        block=F.CreateBlockInfo(self.s.level)
        crop=block.GetBlockNew(cell,dimension) or {}
        states=F.CreateBlockState(self.s.level)
        if crop.get('name') not in CROPS or (states.GetBlockStates(cell,dimension) or {}).get('growth')!=7:
            return
        self.s.work.mine_native(record,dict(target,player=player,original=crop))
        soil=(cell[0],cell[1]-1,cell[2])
        if ((block.GetBlockNew(cell,dimension) or {}).get('name')=='minecraft:air' and
                (block.GetBlockNew(soil,dimension) or {}).get('name')=='minecraft:farmland'):
            block.SetBlockNew(cell,{'name':crop['name'],'aux':0},0,dimension)
        self.s.action(record,5,.8)
    def shear(self,record,entity):
        if not self.s.live(entity):return
        definition=F.CreateEntityDefinitions(entity)
        if definition.IsSheared():return
        item=record['equipment'].get('main')
        if interaction_rules.kind(item,self.s.work.info(item))!='shears':return
        # Variant is the native sheep wool colour, retained in the resulting item.
        variant=definition.GetMobColor() or 0
        wool={'newItemName':'minecraft:wool','newAuxValue':int(variant)&15,'count':random.randint(1,3)}
        after=domain.clone(record);after['inventory']=work_rules.insert_bag(after,wool,64)
        after['equipment']['main']=work_rules.wear(item,self.s.work.info(item).get('maxDurability',238),random.random())
        if not F.CreateEntityEvent(entity).TriggerCustomEvent(entity,'minecraft:on_sheared'):return
        definition.SetSheared(True)
        self.s.work.put(record,after);self.s.action(record,5,.8)
    def farm(self,record,pos,dimension):
        block=F.CreateBlockInfo(self.s.level);above=(pos[0],pos[1]+1,pos[2]);soil=block.GetBlockNew(pos,dimension)
        if not soil or soil['name'] not in ('minecraft:dirt','minecraft:grass','minecraft:grass_block','minecraft:farmland') or (block.GetBlockNew(above,dimension) or {}).get('name')!='minecraft:air':return
        slot=next((i for i,v in enumerate(record['inventory']) if not domain.empty(v) and domain.item_name(v) in SEEDS),None)
        if slot is None:return
        tool=record['equipment'].get('main')
        if interaction_rules.kind(tool,self.s.work.info(tool))!='hoe':return
        crop=SEEDS[domain.item_name(record['inventory'][slot])]
        before=domain.clone(record);after=domain.clone(record)
        after['inventory'][slot]['count']-=1
        if after['inventory'][slot]['count']==0:after['inventory'][slot]=None
        after['equipment']['main']=work_rules.wear(tool,self.s.work.info(tool).get('maxDurability',1),random.random())
        self.s.work.put(record,after)
        if soil['name']!='minecraft:farmland' and not block.SetBlockNew(pos,{'name':'minecraft:farmland','aux':7},0,dimension):self.s.work.put(record,before);return
        if not block.SetBlockNew(above,{'name':crop,'aux':0},0,dimension):
            if soil['name']!='minecraft:farmland':block.SetBlockNew(pos,soil,0,dimension)
            self.s.work.put(record,before);return
        self.s.action(record,5,.8)
    def cleanup(self):
        for record in self.s.records.values():self.clear_light(record)
