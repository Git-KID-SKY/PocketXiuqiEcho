# -*- coding: utf-8 -*-
"""Hand sockets and item categories; positions use Bedrock model units."""
from . import domain
MAIN_GRIP = (-3.7, 6.0, -0.05)
OFF_GRIP = (3.7, 6.0, -0.05)
# Order is the render-controller geometry array, not Minecraft item IDs.
SHAPES = (
    {'name':'small','size':3.5,'pixel':(8.0,8.0),'rotation':(12.0,0.0,0.0)},
    {'name':'bow','size':7.0,'pixel':(5.5,6.5),'rotation':(0.0,90.0,0.0)},
    {'name':'sword','size':6.2,'pixel':(3.5,12.5),'rotation':(55.0,0.0,0.0)},
    {'name':'pickaxe','size':6.0,'pixel':(4.5,11.5),'rotation':(50.0,0.0,0.0)},
    {'name':'axe','size':5.7,'pixel':(4.5,11.5),'rotation':(50.0,0.0,0.0)},
    {'name':'shovel','size':6.2,'pixel':(4.5,11.5),'rotation':(55.0,0.0,0.0)},
    {'name':'torch','size':5.0,'pixel':(8.0,11.0),'rotation':(0.0,0.0,0.0)},
)


def shape_for(name,item_type):
    if name=='minecraft:bow':return 1
    if name in ('minecraft:torch','minecraft:soul_torch','minecraft:redstone_torch'):return 6
    return {'sword':2,'pickaxe':3,'axe':4,'shovel':5}.get(item_type,0)


def native_display_item(item):
    """Only a visual mirror; the draw-stage bow is rendered by its own layer."""
    if domain.empty(item) or domain.item_name(item)=='minecraft:bow':return None
    value=domain.clone(item);value['count']=1
    return value
