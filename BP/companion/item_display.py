# -*- coding: utf-8 -*-
"""Native equipment for items; a depth-bearing bow layer for authored draw stages."""
import mod.client.extraClientApi as api
from . import config,domain
from .item_poses import shape_for


class ItemDisplay(object):
    def __init__(self,level):
        self.level=level

    def resolve(self,item,bow_stage=-1):
        if domain.empty(item):return (0,0)
        comp=api.GetEngineCompFactory().CreateItem(self.level)
        name=domain.item_name(item)
        info=comp.GetItemBasicInfo(domain.native_value(name),item.get('newAuxValue',0)) or {}
        shape=shape_for(name,info.get('itemType'))
        return (1 if name=='minecraft:bow' else 0,shape)
