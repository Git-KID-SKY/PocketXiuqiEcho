# -*- coding: utf-8 -*-
"""Authoritative, testable rules for direct companion interactions."""
from . import config, domain, work_rules

ARMOR=('head','chest','legs','feet')
ARMOR_SUFFIX={'helmet':'head','chestplate':'chest','leggings':'legs','boots':'feet'}
TOOLS=('pickaxe','axe','shovel','hoe','shears','sword','trident','spear','mace')
TORCHES=('minecraft:torch','minecraft:soul_torch','minecraft:redstone_torch')
DEFAULTS={'auto_eat':False,'food_prompt':True,'tool_prompt':True,'block_supply':True,
          'particles':True,'fall_reaction':True,'inspect_animation':True,'random_carry':True,'hunt_animals':False,
          'carry_scale':1.,'speech_enabled':True,'speech_offset_x':0,'speech_offset_y':0}
NUMERIC_OPTIONS={'carry_scale':(.6,1.5),'speech_offset_x':(-60,60),'speech_offset_y':(-30,100)}
SAMPLES={'minecraft:iron_ingot':('minecraft:iron_ore',0),'minecraft:raw_iron':('minecraft:iron_ore',0),
    'minecraft:gold_ingot':('minecraft:gold_ore',0),'minecraft:raw_gold':('minecraft:gold_ore',0),
    'minecraft:copper_ingot':('minecraft:copper_ore',0),'minecraft:diamond':('minecraft:diamond_ore',0),
    'minecraft:coal':('minecraft:coal_ore',0),'minecraft:emerald':('minecraft:emerald_ore',0)}

def kind(item,info=None):
    name=domain.item_name(item);short=name.split(':')[-1];info=info or {}
    if domain.empty(item):return None
    if name in (config.ITEM,config.WEARABLE):return None
    if name in TORCHES:return 'torch'
    if short=='bow':return 'bow'
    if short=='shield':return 'shield'
    if info.get('itemType')=='armor' and info.get('armorSlot') in (0,1,2,3):return ARMOR[info['armorSlot']]
    for suffix,slot in ARMOR_SUFFIX.items():
        if short.endswith('_'+suffix) or short==suffix:return slot
    if short in ('trident','spear','mace') or short.endswith('_spear'):return 'spear' if short.endswith('_spear') else short
    if info.get('itemType') in TOOLS:return info['itemType']
    for tool in TOOLS:
        if short.endswith('_'+tool):return tool
    return None

def slot_for(item,info=None):
    k=kind(item,info)
    return 'off' if k=='shield' else k if k in ARMOR else 'main' if k else None

def work_mode(record,info=None):
    k=kind(record['equipment'].get('main'),info)
    active=record['settings'].get('active_work',False)
    if k in ('sword','bow','trident','spear','mace'):
        return ('hunt' if record['settings'].get('hunt_animals',False) else 'aggressive') if active else 'protect'
    if k in ('pickaxe','axe','shovel'):return 'excavate' if active else 'follow'
    if k in ('hoe','shears'):return k if active else 'follow'
    return 'protect' if not domain.empty(record['equipment'].get('off')) else 'follow'

def sample(item):
    name=domain.item_name(item)
    family=name in SAMPLES
    if family:name,aux=SAMPLES[name]
    else:aux=int((item or {}).get('newAuxValue',(item or {}).get('auxValue',0)))
    from .mining_filter import identity
    name,aux=identity(name,aux)
    if name not in work_rules.MINING:return None
    result={'name':name,'aux':aux}
    if family:result['family']=name.replace('minecraft:','').replace('_ore','')
    return result

def swap(record,items,selected,slot):
    """One item to equipment, exact old item back; stack leftovers never vanish."""
    after=domain.clone(record);players=domain.clone(items);held=players[selected]
    old=after['equipment'].get(slot)
    if domain.empty(held):
        if domain.empty(old):raise domain.Refused(u'这个位置没有装备。')
        players[selected]=old;after['equipment'][slot]=None
    else:
        take=domain.clone(held);take['count']=1
        held['count']-=1
        if held['count']==0:players[selected]=old
        elif not domain.empty(old):players[domain.first_empty(players[:36])]=old
        after['equipment'][slot]=take
    patches=[{'slot':i,'before':items[i],'after':players[i]} for i in range(36) if not domain.same(items[i],players[i])]
    return after,patches

def clean_name(value):
    if not isinstance(value,domain.string_types):raise domain.Refused(u'请输入名字。')
    if not isinstance(value,domain.text_type):value=value.decode('utf-8','replace')
    value=u''.join(c for c in value.strip() if ord(c)>=32 and c!=u'§')
    if len(value)>20:raise domain.Refused(u'名字最多 20 个字。')
    return value

def clean_preference(key,value):
    if key=='name':return clean_name(value)
    if key in NUMERIC_OPTIONS:
        if type(value) not in (int,float) or value!=value or abs(value)==float('inf'):
            raise domain.Refused(u'请输入有效的设置数值。')
        lower,upper=NUMERIC_OPTIONS[key]
        if not lower<=value<=upper:raise domain.Refused(u'设置数值超出可调范围。')
        return round(float(value),2) if key=='carry_scale' else int(round(value))
    if key not in DEFAULTS or type(value) is not bool:raise domain.Refused(u'这个设置无效。')
    return value

def capacity(record):return 54 if record.get('worn',False) else config.CAPACITY
