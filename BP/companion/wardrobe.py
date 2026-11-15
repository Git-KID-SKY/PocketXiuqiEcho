# -*- coding: utf-8 -*-
import json
import mod.server.extraServerApi as api
from . import domain
F=api.GetEngineCompFactory()
LOW='echo:companion_wardrobe';TOP='echo:companion_wardrobe_top'

class Wardrobe(object):
    def __init__(self,system):
        self.s=system;self.last={};self.sent={}
        value=self.s.world.GetExtraData('ec_wardrobes_v15') or '{}'
        self.entries=json.loads(value) if isinstance(value,domain.string_types) else value

    def track(self,pos,dimension,yaw=None):
        key=','.join(str(v) for v in (dimension,)+tuple(pos))
        if key in self.entries and yaw is None:return
        if yaw is None:
            block=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(pos),dimension) or {}
            yaw=(int(block.get('aux',0))%4)*90
        self.entries[key]={'pos':list(pos),'dimension':dimension,'yaw':float(yaw)}
        self.s.world.SetExtraData('ec_wardrobes_v15',json.dumps(self.entries,ensure_ascii=True))

    def block_tick(self,args):
        if args.get('blockName')==LOW:self.track((args['posX'],args['posY'],args['posZ']),args['dimension'])

    def tick(self,force=False):
        if not force and self.s.ticks%15:return
        opened=set()
        for panel in self.s.panels.values():
            location=panel.get('wardrobe')
            if panel.get('context')=='wardrobe' and location:
                opened.add((location['dimension'],)+tuple(location['pos']))
        for player in api.GetPlayerList():
            point=self.s.pos(player)
            if not point:continue
            dim=self.s.dim(player);rows=[]
            for value in self.entries.values():
                if value['dimension']!=dim or sum((value['pos'][i]+.5-point[i])**2 for i in range(3))>48**2:continue
                row=dict(value);row['open']=(dim,)+tuple(value['pos']) in opened;rows.append(row)
            rows.sort(key=lambda row:tuple(row['pos']))
            signature=json.dumps(rows,sort_keys=True)
            if force or self.sent.get(player)!=signature:
                self.sent[player]=signature;self.s.NotifyToClient(player,'Wardrobes',{'entries':rows})
    def before_place(self,args):
        if args.get('fullName')!=LOW:return
        pos=(args['x'],args['y']+1,args['z'])
        above=F.CreateBlockInfo(self.s.level).GetBlockNew(pos,args['dimensionId'])
        if not above or above['name']!='minecraft:air':
            args['cancel']=True;self.s.notify(args['entityId'],u'衣柜需要上方空出一格。')
    def placed(self,args):
        if args.get('fullName')!=LOW:return
        pos=(args['x'],args['y']+1,args['z']);block=F.CreateBlockInfo(self.s.level);dim=args['dimensionId']
        above=block.GetBlockNew(pos,dim)
        if above and above['name']=='minecraft:air':block.SetBlockNew(pos,{'name':TOP,'aux':args.get('auxData',0)},0,dim)
        rotation=F.CreateRot(args['entityId']).GetRot()
        self.track((args['x'],args['y'],args['z']),dim,round(rotation[1]/90.)*90)
        self.tick(True)
    def removed(self,args):
        name=args.get('fullName')
        if name not in (LOW,TOP):return
        block=F.CreateBlockInfo(self.s.level);pos=(args['x'],args['y']+(1 if name==LOW else -1),args['z']);dim=args['dimension']
        other=block.GetBlockNew(pos,dim)
        if other and other['name']==(TOP if name==LOW else LOW):block.SetBlockNew(pos,{'name':'minecraft:air','aux':0},0,dim)
        lower=(args['x'],args['y']-(1 if name==TOP else 0),args['z'])
        self.entries.pop(','.join(str(v) for v in (dim,)+lower),None)
        self.s.world.SetExtraData('ec_wardrobes_v15',json.dumps(self.entries,ensure_ascii=True));self.tick(True)
    def use(self,args):
        if args.get('blockName') not in (LOW,TOP):return
        args['cancel']=True;player=args['playerId']
        if self.s.ticks-self.last.get(player,-100)<15:return
        self.last[player]=self.s.ticks
        try:
            record=self.s.selected(player,True) or self.s.carry.worn(player,True)
            if not record:
                candidates=[r for r in self.s.owned(player) if r['form']=='deployed' and self.s.live(r.get('entity_id')) and self.s.dim(r['entity_id'])==self.s.dim(player)]
                candidates.sort(key=lambda r:sum((self.s.pos(r['entity_id'])[i]-self.s.pos(player)[i])**2 for i in range(3)))
                record=candidates[0] if candidates else None
            if not record:raise domain.Refused(u'把伙伴带到衣柜旁，或拿在手里。')
            pos=[args['x'],args['y']-(1 if args['blockName']==TOP else 0),args['z']]
            self.track(pos,args['dimensionId'])
            self.s.open_panel(player,record,'wardrobe',{'pos':pos,'dimension':args['dimensionId']})
            self.tick(True)
        except domain.Refused as error:self.s.notify(player,error.args[0])
    def check(self,player,panel):
        location=panel.get('wardrobe');p=self.s.pos(player)
        if not location or location['dimension']!=self.s.dim(player) or sum((p[i]-location['pos'][i]-.5)**2 for i in range(3))>36:
            raise domain.Refused(u'靠近衣柜再换装。')
        block=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(location['pos']),location['dimension'])
        if not block or block['name'] not in (LOW,TOP):raise domain.Refused(u'衣柜已经移走了。')
