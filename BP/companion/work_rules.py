# -*- coding: utf-8 -*-
"""Pure item rules shared by cooperative tasks and regression checks."""
from . import domain


def enchant(item, identity):
    return max([int(v[1]) for v in (item or {}).get('enchantData',[]) if int(v[0])==identity] or [0])


def equipment_swap(record, slot=None, hand='main'):
    if hand not in ('main','off','head','chest','legs','feet'):raise domain.Refused(u'请选择装备位置。')
    after=domain.clone(record)
    current=after['equipment'].get(hand)
    if slot is None:
        if domain.empty(current):raise domain.Refused(u'它还没有装备工具。')
        from .interaction_rules import capacity
        slot=domain.first_empty(after['inventory'][:capacity(after)])
        after['inventory'][slot]=current;after['equipment'][hand]=None
    else:
        if type(slot) is not int or not 0<=slot<len(after['inventory']):raise domain.Refused(u'先选择伙伴背包里的工具。')
        item=after['inventory'][slot]
        if domain.empty(item):raise domain.Refused(u'请选择一件工具或武器。')
        take=domain.clone(item);take['count']=1
        if item['count']==1:after['inventory'][slot]=current
        else:
            item['count']-=1
            if not domain.empty(current):
                from .interaction_rules import capacity
                after['inventory'][domain.first_empty(after['inventory'][:capacity(after)])]=current
        after['equipment'][hand]=take
    return after


def give_one(record,slot,player_items,max_stack):
    """One exact-slot transfer; prefer a matching partial stack, preserve NBT."""
    if type(slot) is not int or not 0<=slot<len(record['inventory']):raise domain.Refused(u'请选择伙伴物品。')
    source=record['inventory'][slot]
    if domain.empty(source):raise domain.Refused(u'物品已不在这个格子。')
    take=domain.clone(source);take['count']=1
    destination=None
    for i,value in enumerate(player_items):
        if domain.empty(value) or value['count']>=max_stack:continue
        one=domain.clone(value);one['count']=1
        if domain.same(one,take):destination=i;break
    if destination is None:destination=domain.first_empty(player_items)
    target=domain.clone(player_items[destination])
    if domain.empty(target):target=take
    else:target['count']+=1
    after=domain.clone(record);after['inventory'][slot]['count']-=1
    if after['inventory'][slot]['count']==0:after['inventory'][slot]=None
    return after,[{'slot':destination,'before':player_items[destination],'after':target}]


def sort_bag(record,maximum):
    import json
    after=domain.clone(record);backup=record['settings'].get('backup_slot')
    reserved=record['inventory'][backup] if type(backup) is int and 0<=backup<len(record['inventory']) else None
    values=[domain.clone(v) for v in record['inventory'] if not domain.empty(v)]
    def key(value):
        one=domain.normalized(value);one['count']=1
        return (domain.item_name(value),value.get('newAuxValue',0),json.dumps(one,sort_keys=True,ensure_ascii=True))
    ordered=[None]*len(record['inventory'])
    for value in sorted(values,key=key):ordered=insert(ordered,value,max(1,maximum(value)))
    after['inventory']=ordered
    after['settings']['backup_slot']=next((i for i,v in enumerate(ordered) if not domain.empty(reserved) and domain.same(v,reserved)),None)
    return after


def in_front(origin,yaw,source):
    import math
    dx,dz=source[0]-origin[0],source[2]-origin[2];length=math.hypot(dx,dz)
    if length<.01:return False
    radians=math.radians(yaw)
    return (-math.sin(radians)*dx+math.cos(radians)*dz)/length>=.5


def wear(item, maximum, random_value=0.0):
    """Durability is remaining uses; preserve all unrelated native metadata."""
    if domain.empty(item):raise domain.Refused(u'先给它装备工具。')
    result=domain.clone(item)
    remaining=int(result.get('durability',maximum))
    if remaining<=0:raise domain.Refused(u'工具已经损坏。')
    if random_value<1.0/(enchant(item,17)+1):remaining-=1
    if remaining<=0:return None
    result['durability']=remaining
    # Native userData can mirror remaining durability as Damage (used amount).
    tag=(result.get('userData') or {}).get('Damage')
    if isinstance(tag,dict) and '__value__' in tag:tag['__value__']=max(0,maximum-remaining)
    return result


def spend_arrow(record):
    after=domain.clone(record)
    slot=next((i for i,v in enumerate(after['inventory']) if not domain.empty(v) and domain.item_name(v)=='minecraft:arrow'),None)
    if slot is None:raise domain.Refused(u'伙伴背包里没有箭。')
    arrow=domain.clone(after['inventory'][slot]);arrow['count']=1
    # Infinity requires at least one ordinary arrow, matching the native rule.
    infinite=enchant(after['equipment'].get('main'),22)>0 and arrow.get('newAuxValue',arrow.get('auxValue',0))==0
    if not infinite:
        after['inventory'][slot]['count']-=1
        if after['inventory'][slot]['count']<=0:after['inventory'][slot]=None
    return after,arrow


def insert(items, item, max_stack):
    result=domain.clone(items);left=domain.clone(item)
    if domain.empty(left):return result
    for value in result:
        if domain.empty(value):continue
        a,b=domain.clone(value),domain.clone(left);a['count']=b['count']=1
        if domain.same(a,b):
            count=min(left['count'],max(0,max_stack-value['count']))
            value['count']+=count;left['count']-=count
            if left['count']==0:return result
    while left['count']>0:
        slot=domain.first_empty(result);value=domain.clone(left)
        value['count']=min(left['count'],max_stack);left['count']-=value['count'];result[slot]=value
    return result


def insert_bag(record,item,max_stack):
    from .interaction_rules import capacity
    limit=capacity(record)
    return insert(record['inventory'][:limit],item,max_stack)+domain.clone(record['inventory'][limit:])


def same_tool(a,b):
    if domain.empty(a) or domain.empty(b):return False
    a,b=domain.clone(a),domain.clone(b)
    for value in (a,b):
        value.pop('durability',None)
        if isinstance(value.get('userData'),dict):value['userData'].pop('Damage',None)
    return domain.same(a,b)


# Explicitly supported natural blocks. Containers and functional blocks are not targets.
TOOL_NAMES={'pickaxe':u'镐','axe':u'斧','shovel':u'铲'}


def mining_tool_error(info,kind,tier):
    """Explain the missing equipment step without changing native tool tiers."""
    if not info:return u'先手持工具与伙伴交互来装备。'
    name=info.get('itemName') or u'当前工具'
    if not isinstance(name,domain.text_type):name=name.decode('utf-8','replace')
    if info.get('itemType')!=kind:
        return u'这个方块需要%s，当前主手是%s；手持合适的工具交互即可替换。'%(TOOL_NAMES[kind],name)
    level=info.get('itemTierLevel')
    if level is None or level<0:
        return u'无法读取%s的采掘等级，请换一把原版%s再试。'%(name,TOOL_NAMES[kind])
    if level<tier:
        required=(u'木',u'石',u'铁',u'钻石')[tier]+TOOL_NAMES[kind]
        return u'这个方块至少需要%s；当前主手是%s，请换装后再下达任务。'%(required,name)
    return None


MINING={}
for _name in ('stone','cobblestone','mossy_cobblestone','deepslate','cobbled_deepslate','netherrack',
              'end_stone','sandstone','red_sandstone','basalt','blackstone','tuff','calcite','coal_ore','nether_quartz_ore','quartz_ore','nether_gold_ore'):
    MINING['minecraft:'+_name]=('pickaxe',0)
for _name in ('iron_ore','copper_ore','lapis_ore'):
    MINING['minecraft:'+_name]=('pickaxe',1)
for _name in ('gold_ore','diamond_ore','emerald_ore','redstone_ore','lit_redstone_ore'):
    MINING['minecraft:'+_name]=('pickaxe',2)
for _name in ('obsidian','crying_obsidian','ancient_debris'):
    MINING['minecraft:'+_name]=('pickaxe',3)
for _key,_rule in list(MINING.items()):
    if _key.endswith('_ore') and 'nether_' not in _key:MINING[_key.replace('minecraft:','minecraft:deepslate_')]=_rule
for _name in ('log','log2','wood','planks','oak_log','spruce_log','birch_log','jungle_log','acacia_log','dark_oak_log','mangrove_log','cherry_log','crimson_stem','warped_stem'):
    MINING['minecraft:'+_name]=('axe',0)
for _name in ('dirt','grass','grass_block','sand','gravel','clay','snow','snow_layer','soul_sand','soul_soil','mud'):
    MINING['minecraft:'+_name]=('shovel',0)

HOSTILE=set('minecraft:'+name for name in (
    'zombie','husk','drowned','skeleton','stray','bogged','wither_skeleton','creeper','spider','cave_spider',
    'slime','magma_cube','witch','pillager','vindicator','evocation_illager','evoker','ravager','vex',
    'blaze','ghast','phantom','silverfish','endermite','guardian','elder_guardian','hoglin','zoglin',
    'piglin_brute','shulker','breeze','wither','ender_dragon','warden'))

HUNTABLE=set('minecraft:'+name for name in ('cow','pig','sheep','chicken','rabbit','mooshroom','goat'))
EXCAVATION=set('minecraft:'+name for name in ('stone','andesite','granite','diorite','deepslate','tuff',
    'basalt','polished_basalt','smooth_basalt','blackstone','dripstone_block','netherrack','calcite'))
for _name in EXCAVATION:MINING.setdefault(_name,('pickaxe',0))
