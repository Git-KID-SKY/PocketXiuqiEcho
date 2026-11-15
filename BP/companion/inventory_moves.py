# -*- coding: utf-8 -*-
"""Exact-slot drag plans. Item dictionaries only come from authoritative stores."""
from . import domain, config


def address(value):
    if not isinstance(value,dict) or set(value)!=set(('area','slot')):
        raise domain.Refused(u'请选择有效的物品格。')
    area,slot=value['area'],value['slot']
    if area=='equipment' and slot in ('main','off'):return area,slot
    maximum={'bag':54,'player':36}.get(area)
    if maximum and type(slot) is int and 0<=slot<maximum:return area,slot
    raise domain.Refused(u'这个位置不能放物品。')


def get(record,player_items,where):
    area,slot=where
    return (player_items if area=='player' else record['inventory'] if area=='bag' else record['equipment'])[slot]


def set_item(record,player_items,where,item):
    area,slot=where
    (player_items if area=='player' else record['inventory'] if area=='bag' else record['equipment'])[slot]=item


def same_stack(a,b):
    if domain.empty(a) or domain.empty(b):return False
    a=domain.clone(a);b=domain.clone(b);a['count']=b['count']=1
    return domain.same(a,b)


def plan(record,player_items,source,destination,maximum,validate_equipment):
    source=address(source);destination=address(destination)
    from .interaction_rules import capacity
    for where in (source,destination):
        if where[0]=='bag' and where[1]>=len(record['inventory']):raise domain.Refused(u'这个背包格尚未解锁。')
    if destination[0]=='bag' and destination[1]>=capacity(record):raise domain.Refused(u'穿在胸甲栏时才能向扩展格放入物品。')
    if source==destination:raise domain.Refused(u'物品还在原来的格子里。')
    before=domain.clone(player_items);players=domain.clone(player_items);after=domain.clone(record)
    first=get(after,players,source);second=get(after,players,destination)
    if domain.empty(first):raise domain.Refused(u'物品已经移动，请重新拖动。')
    if destination[0]!='player' and domain.item_name(first) in (config.ITEM,config.WEARABLE):
        raise domain.Refused(u'小修齐不能放进伙伴背包。')
    slot_capacity=1 if destination[0]=='equipment' else max(1,int(maximum(first)))
    if domain.empty(second) or same_stack(first,second):
        available=slot_capacity-(0 if domain.empty(second) else second['count'])
        amount=min(first['count'],available)
        if amount<=0:raise domain.Refused(u'这个格子已经放满了。')
        target=domain.clone(first if domain.empty(second) else second)
        target['count']=amount+(0 if domain.empty(second) else second['count'])
        remaining=domain.clone(first);remaining['count']-=amount
        set_item(after,players,source,None if domain.empty(remaining) else remaining)
        set_item(after,players,destination,target)
    else:
        if source[0]=='bag' and source[1]>=capacity(record):raise domain.Refused(u'扩展格暂时只可取出，不能交换放入。')
        if source[0]!='player' and domain.item_name(second) in (config.ITEM,config.WEARABLE):
            raise domain.Refused(u'小修齐不能放进伙伴背包。')
        source_capacity=1 if source[0]=='equipment' else max(1,int(maximum(second)))
        if first['count']>slot_capacity or second['count']>source_capacity:
            raise domain.Refused(u'这一组放不进装备槽，先卸下原装备再拖入。')
        set_item(after,players,source,domain.clone(second))
        set_item(after,players,destination,domain.clone(first))
    if 'equipment' in (source[0],destination[0]):validate_equipment(after)
    reserved=record['settings'].get('backup_slot')
    if type(reserved) is int and 0<=reserved<len(record['inventory']):
        item=record['inventory'][reserved]
        after['settings']['backup_slot']=next((i for i,v in enumerate(after['inventory'])
            if not domain.empty(item) and domain.same(item,v)),None)
    patches=[{'slot':i,'before':before[i],'after':players[i]} for i in range(36) if not domain.same(before[i],players[i])]
    return after,patches
