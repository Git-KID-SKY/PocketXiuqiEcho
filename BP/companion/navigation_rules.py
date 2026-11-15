# -*- coding: utf-8 -*-
"""Shared work bounds and harmless plants, independent of engine imports."""
SEARCH_RADIUS = 12
WORK_LEASH = 18
RETURN_RADIUS = 6

def independent(record):
    return record["settings"].get("work_mode") in ("excavate", "hoe", "shears")

TARGET_RETRY_TICKS = 300
PASSABLE = frozenset('minecraft:'+name for name in (
    'air','cave_air','snow_layer','short_grass','tallgrass','tall_grass','fern','large_fern',
    'yellow_flower','red_flower','dandelion','poppy','oxeye_daisy','azure_bluet',
    'cornflower','allium','blue_orchid','lily_of_the_valley','orange_tulip',
    'pink_tulip','red_tulip','white_tulip','double_plant','sunflower','lilac',
    'rose_bush','peony','deadbush','dead_bush','pink_petals','torchflower'))


def palette_position(index, volume, start):
    """Native palette volume is Z,X,Y; flat index is y*X*Z+x*Z+z."""
    depth,width,height=volume
    return (start[0]+(index%(width*depth))//depth,
            start[1]+index//(width*depth),start[2]+index%depth)
