# -*- coding: utf-8 -*-
"""Continuous owner-selected work, sharing the existing native task machinery."""
from __future__ import division
import math
import random
import uuid
import mod.server.extraServerApi as api
from . import config, domain, work_rules as rules, mining_filter, forestry, mining_navigation as mining
from .navigation_rules import SEARCH_RADIUS, WORK_LEASH, TARGET_RETRY_TICKS, independent, palette_position
from .work import TargetUnavailable

F=api.GetEngineCompFactory()


def distance(a,b):return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


class WorkModes(object):
    def __init__(self,system):self.s=system

    def weapon(self,record):
        item=record['equipment'].get('main');info=self.s.work.info(item)
        from .interaction_rules import kind
        if kind(item,info) in ('sword','axe','trident','spear','mace'):return 'melee'
        if domain.item_name(item)=='minecraft:bow':return 'bow'
        return None

    def check(self,record,mode):
        if mode in ('aggressive','protect','hunt'):
            kind=self.weapon(record)
            if not kind and not (mode=='protect' and domain.item_name(record['equipment'].get('off'))=='minecraft:shield'):
                raise domain.Refused(u'手持武器与伙伴交互装备；盾牌会装备到副手。')
            if kind=='bow':rules.spend_arrow(record)
        elif mode=='excavate':
            selected=record['settings'].get('mine_sample')
            info=self.s.work.info(record['equipment'].get('main'))
            kind,tier=rules.MINING[selected['name']] if selected else (info.get('itemType'),0)
            if kind not in ('pickaxe','axe','shovel'):raise domain.Refused(u'先手持工具交给伙伴。')
            problem=rules.mining_tool_error(self.s.work.info(record['equipment'].get('main')),kind,tier)
            if problem:raise domain.Refused(problem)
            from .interaction_rules import capacity
            if sum(domain.empty(v) for v in record['inventory'][:capacity(record)])<4:
                raise domain.Refused(u'开凿前请给伙伴背包留出至少 4 个空格。')

    def reasons(self,record):
        result={}
        for mode in config.WORK_MODES:
            try:
                if record['form']!='deployed':raise domain.Refused(u'先点右下角「放到身边」。')
                if record.get('fallen'):raise domain.Refused(u'伙伴已倒下，空手靠近交互救治。')
                self.check(record,mode)
                result[mode]=u''
            except domain.Refused as error:result[mode]=error.args[0]
        return result

    def choose(self,player,record,mode,operation):
        if mode not in config.WORK_MODES:raise domain.Refused(u'请选择工作模式。')
        if record['form']!='deployed':raise domain.Refused(u'先把小修齐放到地上，再开始工作。')
        self.check(record,mode)
        self.s.work.cancel(record);self.s.unhand(record)
        rt=self.s.rt(record);rt['offering']=None;rt['mode_next']=0;rt['mode_status']=u'准备中'
        rt.pop('wander_target',None);rt.pop('threats',None)
        for key in ('stair_plan','stair_origin','mining_goal','tree','mining_scan','blocked_targets'):
            rt.pop(key,None)
        record['settings']['work_mode']=mode;record['state']='following'
        record['settings']['movement']='roam' if mode=='stroll' else 'follow'
        record['settings']['active_work']=mode in ('aggressive','hunt','excavate')
        self.s.stop(record['entity_id']);self.s.commit(record,operation)

    def failed(self,record,message):
        settings=record['settings']
        if independent(record):
            record['state']='waiting'
            settings['movement']='wait'
            self.s.hold(record)
        else:
            settings['work_mode']='follow'
        settings['active_work']=False
        self.s.save(record)
        rt=self.s.rt(record);rt['mode_status']=message
        for key in ('utility_target','tree','work_bubble_pending','stair_plan'):
            rt.pop(key,None)
        self.s.feedback.problem(record,message)

    def on_damage(self,args):
        if args.get('damage',0)<=0:return
        victim=args.get('entityId');source=args.get('srcId')
        if not self.s.work.attackable(source,'protect'):return
        for player in api.GetPlayerList():
            for record in self.s.owned(player):
                if victim not in (player,record.get('entity_id')) or record['settings'].get('work_mode')!='protect':continue
                self.s.rt(record).setdefault('threats',{})[source]=self.s.ticks+360
                self.s.rt(record)['mode_next']=0

    def nearby(self,player,record,mode):
        pos=self.s.pos(record['entity_id']);owner=self.s.pos(player)
        if not pos or not owner:return None
        radius=SEARCH_RADIUS
        low=(pos[0]-radius,pos[1]-6,pos[2]-radius);high=(pos[0]+radius,pos[1]+6,pos[2]+radius)
        entities=F.CreateGame(self.s.level).GetEntitiesInSquareArea(None,low,high,self.s.dim(player)) or []
        threats=self.s.rt(record).setdefault('threats',{})
        candidates=[]
        for entity in entities:
            if self.s.attention.blocked(record,{'entity':entity}):continue
            if not self.s.work.attackable(entity,mode):continue
            point=self.s.pos(entity)
            if not point or distance(point,owner)>WORK_LEASH-2 or distance(point,pos)>SEARCH_RADIUS:continue
            if mode=='protect' and threats.get(entity,0)<self.s.ticks:
                if F.CreateAction(entity).GetAttackTarget() not in (player,record['entity_id']) and (F.CreateEngineType(entity).GetEngineTypeStr() not in rules.HOSTILE or distance(point,owner)>4):continue
            candidates.append((distance(point,owner) if mode=='protect' else distance(point,pos),entity))
        return min(candidates)[1] if candidates else None

    def remember_trees(self,rt,trees):
        # Keep partially cut trees until their blocked logs can be retried. The
        # existing tree key is also cleared by equipment/mode changes.
        rt.pop('tree',None)
        if trees:
            for tree in trees:tree.pop('pending',None)
            rt['tree']=trees[0]
            rt['tree']['pending']=trees[1:]

    def tree_target(self,player,record,tree,comp):
        remaining=False
        for b in tree['logs']:
            if forestry.species(comp.GetBlockNew(tuple(b),tree['dimension']))!=tree['species']:continue
            remaining=True
            job={'block':list(b),'dimension':tree['dimension'],'player':player,'tree_base':tree['base']}
            if self.s.attention.blocked(record,job):continue
            try:job['original']=self.s.work.mine_check(record,job)
            except TargetUnavailable:
                self.s.attention.defer(record,job,TARGET_RETRY_TICKS);continue
            return job,True
        return None,remaining

    def mine_signature(self,record):
        selected=record['settings'].get('mine_sample') or {}
        return (domain.item_name(record['equipment'].get('main')),
                tuple(sorted(selected.items())))

    def mine_matches(self,record,block,info):
        rule=rules.MINING.get((block or {}).get('name'))
        if not rule or rules.mining_tool_error(info,*rule):return False
        selected=record['settings'].get('mine_sample')
        if selected:return mining_filter.matches(selected,block)
        if rule[0]=='pickaxe':return mining.ore(block) or mining.natural(block)
        return block['name'] not in ('minecraft:planks','minecraft:wood')

    def mine_scan(self,record,pos,dimension,info):
        rt=self.s.rt(record);signature=self.mine_signature(record);scan=rt.get('mining_scan')
        if (scan and scan['dimension']==dimension and scan['signature']==signature and
                self.s.ticks-scan['at']<mining.SCAN_TICKS and mining.squared(scan['origin'],pos)<9):return scan
        x,y,z=[int(math.floor(v)) for v in pos]
        tool=info.get('itemType')
        down=12 if tool=='pickaxe' else 4
        up=8 if tool=='axe' else 4
        start=(x-SEARCH_RADIUS,y-down,z-SEARCH_RADIUS);end=(x+SEARCH_RADIUS,y+up,z+SEARCH_RADIUS)
        palette=F.CreateBlock(record['entity_id']).GetBlockPaletteBetweenPos(dimension,start,end,False)
        if not palette:return None
        data=palette.SerializeBlockPalette();blocks={};candidates=[]
        for key,indexes in data['common'].items():
            block={'name':key[0],'aux':key[1]};wanted=self.mine_matches(record,block,info)
            for index in indexes:
                position=palette_position(index,data['volume'],start)
                blocks[position]=block
                if wanted:candidates.append(position)
        scan={'dimension':dimension,'signature':signature,'at':self.s.ticks,'origin':tuple(pos),
              'blocks':blocks,'candidates':candidates,'cursor':0}
        rt['mining_scan']=scan;return scan

    def mine_candidate(self,player,record,block,dimension,get,budget,opening=None):
        if not mining.exposed(get,block):return None
        job={'block':list(block),'dimension':dimension,'player':player,'automatic':'excavate'}
        try:job['original']=self.s.work.mine_check(record,job)
        except TargetUnavailable:return None
        stands=self.s.work.mine_stands(record,block,dimension,get,budget)
        if not stands:return None
        job['stands']=stands
        if opening:job['opening_goal']=opening
        return job

    def open_mine_goal(self,player,record,goal,get,budget,try_direct=True):
        if goal['dimension']!=self.s.dim(record['entity_id']) or goal['signature']!=self.mine_signature(record):return None
        point=tuple(goal['block']);dimension=goal['dimension']
        current=F.CreateBlockInfo(self.s.level).GetBlockNew(point,dimension)
        if current!=goal['original']:return None
        if try_direct:
            direct=self.mine_candidate(player,record,point,dimension,get,budget)
            if direct:return direct
        # At most two layers/four necessary natural blocks per goal. No deep tunnelling,
        # manufactured blocks, fluid release, or deleting the destination remotely.
        if goal['remaining']<=0:return None
        routes=mining.shallow_routes(get,point,mining.OPENING_LIMIT)
        pos=self.s.pos(record['entity_id'])
        routes.sort(key=lambda route:(len(route),mining.squared(route[0],pos)))
        for route in routes[:6]:
            outer=route[0]
            if self.s.attention.blocked(record,{'block':outer,'dimension':dimension}):continue
            actual=F.CreateBlockInfo(self.s.level).GetBlockNew(outer,dimension)
            if not mining.natural(actual):continue
            job=self.mine_candidate(player,record,outer,dimension,get,budget,domain.clone(goal))
            if job:return job
            if budget['stands']<=0:break
        return None

    def stone(self,player,record):
        entity=record['entity_id'];pos=self.s.pos(entity);dimension=self.s.dim(entity)
        rt=self.s.rt(record);comp=F.CreateBlockInfo(self.s.level)
        first=rt.pop('tree',None);trees=([first]+first.pop('pending',[])) if first else []
        pending=[]
        for index,tree in enumerate(trees):
            if tree['dimension']!=dimension or distance(tree['base'],pos)>SEARCH_RADIUS+4:continue
            job,remaining=self.tree_target(player,record,tree,comp)
            if job:
                self.remember_trees(rt,[tree]+pending+trees[index+1:]);return job
            if remaining:pending.append(tree)
            else:forestry.replant(self.s,record,tree,dimension)
        self.remember_trees(rt,pending)
        info=self.s.work.info(record['equipment'].get('main'))
        scan=self.mine_scan(record,pos,dimension,info)
        if not scan:return None
        cached=dict(scan['blocks']);budget={'stands':48}
        def get(p):
            p=tuple(p)
            if p not in cached:cached[p]=comp.GetBlockNew(p,dimension)
            return cached[p]
        goal=rt.pop('mining_goal',None)
        if goal:
            target=self.open_mine_goal(player,record,goal,get,budget)
            if target:return target
            # Do not silently reset an exhausted opening plan in this scan.
            self.s.attention.defer(record,goal,TARGET_RETRY_TICKS)
        last=rt.get('last_mined')
        def priority(p):
            block=get(p);near=bool(last and last['dimension']==dimension and
                self.s.ticks-last['at']<300 and mining.squared(p,last['block'])<=9)
            return (0 if mining.ore(block) else 1,0 if near else 1,mining.squared(p,pos),p)
        candidates=sorted(scan['candidates'],key=priority)
        offset=scan['cursor'];ordered=candidates[offset:]+candidates[:offset]
        examined=0;opened=0
        for index,block in enumerate(ordered):
            if examined>=mining.SEARCH_BUDGET or budget['stands']<=0:
                scan['cursor']=(offset+index)%max(1,len(candidates))
                rt['mode_next']=self.s.ticks+9
                rt['mining_search_status']=u'正在换另一侧工作面，继续检查可达位置'
                return None
            if self.s.attention.blocked(record,{'block':block,'dimension':dimension}):continue
            # Fully buried bulk stone cannot be a working face. Palette reads
            # make this filter cheap even on a solid cliff with thousands of cells.
            expected=get(block)
            if not self.mine_matches(record,expected,info):continue
            if not (mining.ore(expected) or forestry.species(expected)) and not mining.exposed(get,block):continue
            examined+=1
            current=comp.GetBlockNew(block,dimension)
            if not self.mine_matches(record,current,info):continue
            cached[block]=current
            job=None
            if rules.MINING[current['name']][0]=='axe' and forestry.species(current):
                tree=forestry.discover(get,block)
                if tree and not any(tree['base']==old['base'] for old in pending) and len(pending)<8:
                    tree['dimension']=dimension
                    job,remaining=self.tree_target(player,record,tree,comp)
                    self.remember_trees(rt,[tree]+pending)
                    if not job:pending.append(tree)
            else:
                job=self.mine_candidate(player,record,block,dimension,get,budget)
                if not job and mining.ore(current) and opened<2:
                    opened+=1
                    goal={'block':list(block),'dimension':dimension,'original':current,
                          'signature':self.mine_signature(record),'remaining':mining.OPENING_BREAK_LIMIT}
                    job=self.open_mine_goal(player,record,goal,get,budget,False)
            if job:
                scan['cursor']=0;return job
        scan['cursor']=0
        rt['mining_search_status']=u'附近没有可安全到达的目标；靠近矿壁或换个站位'
        return None

    def descend(self,player,record,plan_new):
        """Clear one step, walk down it, then let the local scan choose again."""
        rt=self.s.rt(record)
        entity=record['entity_id']
        pos=self.s.pos(entity)
        dimension=self.s.dim(entity)
        comp=F.CreateBlockInfo(self.s.level)
        def get(point):
            return comp.GetBlockNew(point,dimension)
        plan=rt.get('stair_plan')
        if plan is None:
            if not plan_new:return None
            origin=tuple(int(math.floor(v)) for v in pos)
            start=rt.setdefault('stair_origin',origin[1])
            if origin[1]<=start-mining.STAIR_DEPTH:return None
            if not self.s.safe((origin[0]+.5,float(origin[1]),origin[2]+.5),dimension):return None
            scan=rt.get('mining_scan') or {}
            below=[p for p in scan.get('candidates',()) if p[1]<origin[1]-1 and
                   abs(p[0]-origin[0])+abs(p[2]-origin[2])<=8 and mining.ore(scan['blocks'].get(p))]
            sample=record['settings'].get('mine_sample')
            if sample and not below:return None
            ore_goal=min(below,key=lambda p:mining.squared(p,origin)) if below else None
            directions=list(mining.CARDINAL)
            if ore_goal:
                directions.sort(key=lambda d:mining.squared(
                    (origin[0]+d[0],origin[1]-1,origin[2]+d[1]),ore_goal))
            for direction in directions:
                step=mining.stair_step(get,origin,direction)
                if not step or (not step[1] and not ore_goal):continue
                landing,blocks=step
                if self.s.attention.blocked(record,{'block':landing,'dimension':dimension}):continue
                plan={'origin':origin,'direction':direction,'landing':landing,'dimension':dimension,
                      'started':self.s.ticks}
                rt['stair_plan']=plan
                break
        if not plan:return None
        landing=plan['landing']
        step=mining.stair_step(get,plan['origin'],plan['direction'])
        if plan['dimension']==dimension and step and self.s.ticks-plan['started']<300:
            for block in step[1]:
                if self.s.attention.blocked(record,{'block':block,'dimension':dimension}):break
                job={'block':list(block),'dimension':dimension,'player':player,
                     'automatic':'excavate','stair':True}
                try:job['original']=self.s.work.mine_check(record,job)
                except TargetUnavailable:break
                stands=self.s.work.mine_stands(record,block,dimension,get,{'stands':16})
                if not stands:break
                job['stands']=stands
                return job
            else:
                target=(landing[0]+.5,float(landing[1]),landing[2]+.5)
                if distance(pos,target)<.45:
                    rt.pop('stair_plan',None)
                    rt.pop('mining_scan',None)
                    return None
                if self.s.safe(target,dimension):
                    self.s.move(record,target,1.)
                    rt['mode_next']=self.s.ticks+3
                    rt['mode_status']=u'正在沿台阶下矿'
                    return None
        rt.pop('stair_plan',None)
        self.s.attention.defer(record,{'block':landing,'dimension':dimension},TARGET_RETRY_TICKS)
        return None

    def tick(self,player,record):
        mode=record['settings'].get('work_mode','follow');rt=self.s.rt(record)
        if record['settings'].get('movement')=='roam' and mode in ('follow','protect'):mode='stroll'
        if rt.get('pause_work'):return False
        if mode=='follow':return False
        if record['state'] in ('hand_in_hand','waiting') or rt['hand_target'] or rt['offering'] is not None:return False
        panel=self.s.panels.get(player)
        if panel and panel['id']==record['companion_id']:
            rt['mode_status']=u'查看背包中，关面板后继续';return True
        pos=self.s.pos(record['entity_id']);owner=self.s.pos(player)
        if mode!='excavate' and distance(pos,owner)>WORK_LEASH-2:
            rt['mode_status']=u'正在跟上主人';return False
        if mode=='stroll':
            target=rt.get('wander_target')
            if target and distance(pos,target)>.5:
                if self.s.ticks<rt.get('wander_until',0):self.s.move(record,target,.7);return True
            self.s.stop(record['entity_id'])
            if self.s.ticks>=rt.get('mode_next',0):
                rt['mode_next']=self.s.ticks+random.randint(90,150);rt['wander_until']=self.s.ticks+120
                angle=random.uniform(0,math.pi*2);radius=random.uniform(2,4)
                rt['wander_target']=self.s.safe((owner[0]+math.cos(angle)*radius,owner[1],owner[2]+math.sin(angle)*radius),self.s.dim(player))
            rt['mode_status']=u'在主人身边散步';return True
        if self.s.ticks<rt.get('mode_next',0):return mode=='excavate'
        rt['mode_next']=self.s.ticks+30
        try:
            self.check(record,mode)
            if mode=='excavate':
                tool=self.s.work.info(record['equipment'].get('main'))
                target=None
                if rt.get('stair_plan'):
                    target=self.descend(player,record,False)
                    if target is None and rt.get('stair_plan'):return True
                if target is None:
                    target=self.stone(player,record)
                    if tool.get('itemType')=='pickaxe' and (not target or (
                            not target.get('opening_goal') and not mining.ore(target['original']))):
                        step_target=self.descend(player,record,True)
                        if step_target is not None:target=step_target
                        elif rt.get('stair_plan'):return True
                if not target:
                    if not rt.get('stair_plan'):
                        rt['mode_status']=u'正在本地寻找可采目标，可在模组设置召回'
                    return True
                kind='mine'
            else:
                target_id=self.nearby(player,record,mode)
                if not target_id:
                    rt['mode_status']=u'守在主人身边' if mode=='protect' else u'正在寻找目标';return False
                target={'entity':target_id}
                kind=self.weapon(record) or 'guard'
                if kind=='guard':
                    import time
                    if time.time()<record.get('guard_next_at',0):return False
            self.s.work.start(player,record,kind,'auto:'+uuid.uuid4().hex,target,mode)
            rt['mode_status']=(u'正在挖台阶下矿' if target.get('stair') else u'先清理目标前的天然石材，再继续采矿' if target.get('opening_goal') else u'正在采集指定样本' if record['settings'].get('mine_sample') else u'正在采集附近矿物和天然资源') if kind=='mine' else u'正在保护主人' if mode=='protect' else u'正在追踪目标'
            return True
        except TargetUnavailable as error:
            rt['mode_status']=error.args[0];rt['mode_next']=self.s.ticks+3
            return mode=='excavate'
        except domain.Refused as error:
            self.failed(record,error.args[0]);self.s.notify(player,error.args[0]);return False
