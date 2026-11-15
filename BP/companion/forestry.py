# -*- coding: utf-8 -*-
"""Small, rooted living trees; bounded connected logs and optional replanting."""
from . import domain

SPECIES=('oak','spruce','birch','jungle','acacia','dark_oak','mangrove','cherry')
SOIL=('minecraft:dirt','minecraft:grass','minecraft:grass_block','minecraft:podzol',
      'minecraft:mycelium','minecraft:rooted_dirt','minecraft:mud')


def species(block,leaf=False):
    name=(block or {}).get('name','').replace('minecraft:','');aux=int((block or {}).get('aux',0))
    if leaf and aux&4:return None  # Persistent, player-placed leaves are not a living canopy.
    if name==('leaves' if leaf else 'log'):return SPECIES[aux&3]
    if name==('leaves2' if leaf else 'log2'):return SPECIES[4+(aux&1)]
    suffix='_leaves' if leaf else '_log'
    if name.endswith(suffix) and name[:-len(suffix)] in SPECIES:return name[:-len(suffix)]
    return None


def discover(get_block,point):
    """No world effects. Reject overlarge/connected groves before cutting anything."""
    point=tuple(point);kind=species(get_block(point))
    if not kind:return None
    root=point
    for unused in range(25):
        below=(root[0],root[1]-1,root[2])
        if species(get_block(below))!=kind:break
        root=below
    if (get_block((root[0],root[1]-1,root[2])) or {}).get('name') not in SOIL:return None
    queue=[root];seen=set();logs=[]
    while queue:
        p=queue.pop()
        if p in seen:continue
        seen.add(p);b=get_block(p)
        if species(b)!=kind:continue
        if abs(p[0]-root[0])>4 or abs(p[2]-root[2])>4 or not 0<=p[1]-root[1]<=24:return None
        logs.append(p)
        if len(logs)>96:return None
        for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            queue.append((p[0]+dx,p[1]+dy,p[2]+dz))
    if len(logs)<3 or max(p[1] for p in logs)-root[1]<2:return None
    canopy=set()
    for p in logs:
        if p[1]<root[1]+2:continue
        for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,0,1),(0,0,-1),(2,0,0),(-2,0,0),(0,0,2),(0,0,-2)):
            q=(p[0]+dx,p[1]+dy,p[2]+dz)
            if species(get_block(q),True)==kind:canopy.add(q)
    if len(canopy)<4:return None
    return {'base':list(root),'species':kind,'logs':[list(p) for p in sorted(logs,key=lambda p:(p[1],abs(p[0]-root[0])+abs(p[2]-root[2])))]}


def sapling(item,kind):
    name=domain.item_name(item);aux=int((item or {}).get('newAuxValue',(item or {}).get('auxValue',0)))
    return not domain.empty(item) and (name=='minecraft:'+kind+'_sapling' or
        name=='minecraft:sapling' and kind in SPECIES[:6] and (aux&7)==SPECIES.index(kind) or
        kind=='mangrove' and name=='minecraft:mangrove_propagule')


def replant(system,record,tree,dimension):
    import mod.server.extraServerApi as api
    block=api.GetEngineCompFactory().CreateBlockInfo(system.level);pos=tuple(tree['base']);kind=tree['species']
    if (block.GetBlockNew(pos,dimension) or {}).get('name')!='minecraft:air':return
    if (block.GetBlockNew((pos[0],pos[1]-1,pos[2]),dimension) or {}).get('name') not in SOIL:return
    # Two-by-two species need a deliberate group planting; do not consume one
    # sapling into a location where it cannot grow.
    if kind=='dark_oak':return
    slot=next((i for i,v in enumerate(record['inventory']) if sapling(v,kind)),None)
    if slot is None:
        system.feedback.problem(record,u'树砍好啦；背包放些对应树苗，我下次会补种～');return
    before=domain.clone(record);after=domain.clone(record);seed=after['inventory'][slot]
    name=domain.item_name(seed);aux=int(seed.get('newAuxValue',seed.get('auxValue',0)))
    seed['count']-=1
    if not seed['count']:after['inventory'][slot]=None
    system.work.put(record,after)
    if not block.SetBlockNew(pos,{'name':domain.native_value(name),'aux':aux},0,dimension):
        system.work.put(record,before);system.feedback.problem(record,u'树苗在这里种不下，已经放回背包啦～')
