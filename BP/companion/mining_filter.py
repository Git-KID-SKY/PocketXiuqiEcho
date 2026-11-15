# -*- coding: utf-8 -*-
"""A non-consuming block sample, validated from an authoritative inventory slot."""
from . import domain, work_rules as rules


def identity(name,aux=0):
    logs=('oak','spruce','birch','jungle','acacia','dark_oak')
    for index,kind in enumerate(logs):
        if name=='minecraft:'+kind+'_log':name='minecraft:log' if index<4 else 'minecraft:log2';aux=index%4;break
    variants={'minecraft:granite':1,'minecraft:polished_granite':2,'minecraft:diorite':3,
              'minecraft:polished_diorite':4,'minecraft:andesite':5,'minecraft:polished_andesite':6}
    if name in variants:aux=variants[name];name='minecraft:stone'
    name={'minecraft:lit_redstone_ore':'minecraft:redstone_ore',
          'minecraft:lit_deepslate_redstone_ore':'minecraft:deepslate_redstone_ore',
          'minecraft:grass_block':'minecraft:grass'}.get(name,name)
    # Logs carry their axis in the upper metadata bits; match the tree species.
    if name in ('minecraft:log','minecraft:log2'):aux=int(aux)&3
    elif name not in ('minecraft:stone','minecraft:dirt','minecraft:sand','minecraft:planks','minecraft:wood','minecraft:sandstone','minecraft:red_sandstone'):aux=0
    return name,int(aux)


def sample(item):
    if domain.empty(item) or domain.item_name(item) not in rules.MINING:
        raise domain.Refused(u'请放入石材、矿石、原木或土砂方块；物品和容器不能作为采掘目标。')
    name,aux=identity(domain.item_name(item),item.get('newAuxValue',item.get('auxValue',0)))
    return {'name':name,'aux':aux}


def matches(selected,block):
    if selected and block and selected.get('family'):
        ore=selected['family']+'_ore'
        return block.get('name') in ('minecraft:'+ore,'minecraft:deepslate_'+ore)
    return bool(selected and block and identity(selected['name'],selected.get('aux',0))==identity(block.get('name'),block.get('aux',0)))


def label(selected):
    name=selected['name'].replace('minecraft:','');aux=selected.get('aux',0)
    ores={'iron':u'铁矿','gold':u'金矿','copper':u'铜矿','diamond':u'钻石矿',
        'coal':u'煤矿','emerald':u'绿宝石矿','redstone':u'红石矿','lapis':u'青金石矿'}
    key=selected.get('family') or name.replace('deepslate_','').replace('_ore','')
    if name.endswith('_ore') and key in ores:return ores[key]
    if name=='log':return (u'橡木',u'云杉木',u'白桦木',u'丛林木')[int(aux)&3]
    if name=='log2':return (u'金合欢木',u'深色橡木',u'原木',u'原木')[int(aux)&3]
    return { 'oak_log':u'橡木','spruce_log':u'云杉木','birch_log':u'白桦木',
        'jungle_log':u'丛林木','acacia_log':u'金合欢木','dark_oak_log':u'深色橡木',
        'stone':u'石材','dirt':u'泥土','sand':u'沙子','gravel':u'砂砾'}.get(name,u'指定的方块')


def item(selected):
    return {'newItemName':selected['name'],'newAuxValue':selected.get('aux',0),'count':1} if selected else None
