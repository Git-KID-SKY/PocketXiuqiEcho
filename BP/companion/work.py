# -*- coding: utf-8 -*-
"""Owner-commanded, bounded cooperative jobs. Native world effects never replay.

Mining borrows the companion tool into the owner's selected slot for one
synchronous native PlayerDestroyBlock call. Both swaps use the inventory WAL;
the player's exact item is restored, and native permissions/loot/enchantments run.
"""
from __future__ import division
import math
import random
import traceback
import uuid
import time
import mod.server.extraServerApi as api
from . import config,domain,work_rules as rules,mining_navigation as mining
from .animation_timing import DURATIONS, IMPACTS
from .navigation_rules import PASSABLE, WORK_LEASH, TARGET_RETRY_TICKS

F=api.GetEngineCompFactory()
E=api.GetMinecraftEnum()


def dist(a,b):return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


class TargetUnavailable(domain.Refused):
    """A local target failure; automatic work may continue with another target."""
    pass


class Work(object):
    def __init__(self,system):
        self.s=system;self.capture=None;self.arrows={};self.last_break=None

    def put(self,record,after,operation=None):
        if operation:domain.finish(after,operation)
        self.s.save(after);record.clear();record.update(after)
        self.s.records[record['companion_id']]=record

    def ready(self,record):
        if record.get('tool_loan') or record.get('loot_pending'):
            raise domain.Refused(u'正在核对上一次工具或产物转移，请先重新进入世界。')

    def info(self,item):
        return F.CreateItem(self.s.level).GetItemBasicInfo(domain.native_value(domain.item_name(item)),
            (item or {}).get('newAuxValue',(item or {}).get('auxValue',0))) or {}

    def equip(self,record,slot,operation,hand=None):
        self.ready(record)
        if self.s.rt(record).get('job') or self.s.rt(record)['offering'] is not None:
            raise domain.Refused(u'先停止任务或结束递物，再换装备。')
        if slot is not None and type(slot) is int and 0<=slot<len(record['inventory']):
            from .interaction_rules import slot_for
            expected=slot_for(record['inventory'][slot],self.info(record['inventory'][slot]))
            if expected is None:raise domain.Refused(u'请选择工具、武器、盾牌或盔甲。')
            if hand is not None and hand!=expected:
                raise domain.Refused(u'盾牌放在副手，武器和工具放在主手。')
            hand=expected
        hand=hand or 'main'
        after=rules.equipment_swap(record,slot,hand)
        self.validate_equipment(after)
        if hand=='main':
            after['settings']['active_work']=False
            from .interaction_rules import kind
            sample=after['settings'].get('mine_sample')
            if sample and rules.MINING.get(sample['name'],(None,))[0]!=kind(after['equipment'].get('main'),self.info(after['equipment'].get('main'))):
                after['settings']['mine_sample']=None
        self.put(record,after,operation)
        self.s.interactions.mode(record);self.s.save(record)

    def validate_equipment(self,after):
        from . import interaction_rules
        for hand,item in after['equipment'].items():
            if domain.empty(item):continue
            info=self.info(item);name=domain.item_name(item)
            if hand=='off' and name!='minecraft:shield':raise domain.Refused(u'副手槽用来放盾牌。')
            if interaction_rules.slot_for(item,info)!=hand:raise domain.Refused(u'这个物品不适合该装备位置。')
            if item.get('count')!=1:raise domain.Refused(u'装备槽一次只能放一件。')
            if name not in interaction_rules.TORCHES and int(item.get('durability',info.get('maxDurability',0)))<=0:raise domain.Refused(u'这件工具已经损坏。')
        main=after['equipment'].get('main');off=after['equipment'].get('off')
        # Shield stays strapped to the forearm while other tools are used.

    def allowed(self,player,kind):
        ability=F.CreatePlayer(player).GetPlayerAbilities() or {}
        key='mine' if kind=='mine' else 'attackmobs'
        if not ability.get(key,False):raise domain.Refused(u'当前没有执行这个任务的权限。')
        if F.CreateGame(self.s.level).GetPlayerGameType(player) not in (0,1):
            raise domain.Refused(u'当前游戏模式不能下达采掘或战斗任务。')

    def hostile(self,target):
        return self.attackable(target,'aggressive')

    def attackable(self,target,mode=None):
        if not self.s.live(target) or target in api.GetPlayerList():return False
        name=F.CreateEngineType(target).GetEngineTypeStr()
        allowed=rules.HOSTILE|rules.HUNTABLE if mode in ('hunt','protect') else rules.HOSTILE
        if name not in allowed:return False
        owner=F.CreateActorOwner(target).GetEntityOwner()
        return not owner or owner=='-1'

    def ray(self,dimension,start,end,entities=False):
        length=dist(start,end)
        if length<.01:return []
        direction=tuple((end[i]-start[i])/length for i in range(3))
        return api.getEntitiesOrBlockFromRay(dimension,tuple(start),direction,int(math.ceil(length)),True,
            E.RayFilterType.BothEntitiesAndBlock if entities else E.RayFilterType.OnlyBlocks) or []

    def clear(self,dimension,start,end,block=None):
        length=dist(start,end)
        for hit in self.ray(dimension,start,end):
            if hit.get('identifier') in PASSABLE or hit.get('identifier') in ('minecraft:water','minecraft:flowing_water'):continue
            if block is not None and tuple(hit.get('pos',()))==tuple(block):continue
            if dist(start,hit.get('hitPos',end))<length-.08:return False
        return True

    def aimed(self,player,companion,kind):
        foot=self.s.pos(player);start=(foot[0],foot[1]+1.62,foot[2])
        direction=api.GetDirFromRot(F.CreateRot(player).GetRot())
        hits=api.getEntitiesOrBlockFromRay(self.s.dim(player),start,tuple(direction),12,True,E.RayFilterType.BothEntitiesAndBlock) or []
        for hit in hits:
            if hit.get('entityId') in (player,companion):continue
            if hit.get('identifier') in PASSABLE or hit.get('identifier') in ('minecraft:water','minecraft:flowing_water'):continue
            if hit.get('type')=='Block':
                if kind=='mine':return {'block':list(hit['pos'])}
                break
            if kind!='mine' and self.hostile(hit.get('entityId')):return {'entity':hit['entityId']}
            # A non-hostile entity in front blocks command selection as well.
            break
        raise domain.Refused(u'先瞄准一个可采掘方块。' if kind=='mine' else u'先瞄准一只怪物，目标前面不能有遮挡。')

    def mine_check(self,record,job):
        block=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(job['block']),job['dimension'])
        if not block or block.get('name') not in rules.MINING:raise TargetUnavailable(u'这里只支持天然石材、矿石、木材和土砂；不拆容器与功能方块。')
        if job.get('original') and block!=job['original']:raise TargetUnavailable(u'目标方块已经变化，任务已取消。')
        tool=record['equipment'].get('main');info=self.info(tool)
        kind,tier=rules.MINING[block['name']]
        if job.get('stair') and mining.soil(block):kind,tier='pickaxe',0
        problem=rules.mining_tool_error(info,kind,tier)
        if problem:raise domain.Refused(problem)
        from .interaction_rules import capacity
        if sum(domain.empty(v) for v in record['inventory'][:capacity(record)])<4:raise domain.Refused(u'采掘前请给伙伴背包留出至少 4 个空格。')
        # Never undermine either participant's standing block.
        for actor in list(api.GetPlayerList())+[record.get('entity_id')]:
            if not actor or self.s.dim(actor)!=job['dimension']:continue
            p=self.s.pos(actor)
            if p and (int(math.floor(p[0])),int(math.floor(p[1]-.05)),int(math.floor(p[2])))==tuple(job['block']):
                raise TargetUnavailable(u'先离开目标方块，再让它采掘。')
        if job.get('automatic') or job.get('opening_goal'):
            comp=F.CreateBlockInfo(self.s.level)
            if mining.hazard(lambda p:comp.GetBlockNew(p,job['dimension']),job['block']):
                raise TargetUnavailable(u'目标旁有液体、落砂或容器，先换一个安全位置。')
        return block

    def select_mine(self,player,record):
        target=self.aimed(player,record.get('entity_id'),'mine')
        target['dimension']=self.s.dim(player)
        target['original']=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(target['block']),target['dimension'])
        return target

    def start(self,player,record,kind,operation,automatic_target=None,automatic=None):
        self.ready(record)
        if kind not in ('mine','melee','bow','guard'):raise domain.Refused(u'请选择任务。')
        if record['form']!='deployed':raise domain.Refused(u'先把小修齐放到地上。')
        if self.s.rt(record).get('job'):raise domain.Refused(u'先结束当前任务。')
        self.allowed(player,kind)
        tool=record['equipment'].get('off' if kind=='guard' else 'main');info=self.info(tool)
        if domain.empty(tool):
            raise domain.Refused(u'先在伙伴背包选中盾牌，再点「副手」装备。' if kind=='guard' else u'先在伙伴背包选中工具，再点「主手」装备。')
        from .interaction_rules import kind as item_kind
        if kind=='melee' and item_kind(tool,info) not in ('sword','axe','trident','spear','mace'):raise domain.Refused(u'近战需要武器。')
        if kind=='bow':
            if domain.item_name(tool)!='minecraft:bow':raise domain.Refused(u'射箭需要先装备弓。')
            rules.spend_arrow(record)
        if kind=='guard':
            if domain.item_name(tool)!='minecraft:shield':raise domain.Refused(u'先在背包给它装备盾牌。')
            if time.time()<record.get('guard_next_at',0):raise domain.Refused(u'盾牌防护还在恢复，稍等一会儿。')
        if int(tool.get('durability',info.get('maxDurability',0)))<=0:raise domain.Refused(u'工具已经损坏。')
        if automatic:
            if automatic not in config.WORK_MODES or automatic!=record['settings'].get('work_mode'):
                raise domain.Refused(u'工作模式已经改变。')
            target=domain.clone(automatic_target or {})
            if kind!='mine' and not self.attackable(target.get('entity'),automatic):
                raise TargetUnavailable(u'这个目标不能攻击。')
        elif kind=='mine':
            panel=self.s.panels.get(player,{})
            selected=panel.get('mine_target') if panel.get('id')==record['companion_id'] else None
            if not selected:raise domain.Refused(u'请在设置页的目标方块旁打开背包，选择要采掘的方块样本。')
            if selected['dimension']!=self.s.dim(player):raise domain.Refused(u'已离开目标所在维度，请重新选目标。')
            target=domain.clone(selected);p=self.s.pos(player);b=target['block']
            eye=(p[0],p[1]+1.62,p[2]);point=tuple(v+.5 for v in b)
            if dist(eye,point)>12 or not self.clear(selected['dimension'],eye,point,b):
                raise domain.Refused(u'目标太远或被挡住，请重新选目标。')
        else:target={} if kind=='guard' else self.aimed(player,record['entity_id'],kind)
        job=dict(target,kind=kind,player=player,dimension=self.s.dim(player),started=self.s.ticks,
                 next=self.s.ticks+12,return_state='waiting' if record['state']=='waiting' else 'following')
        if automatic:job['automatic']=automatic
        if kind=='mine':job['original']=self.mine_check(record,job)
        self.s.unhand(record);self.s.rt(record)['offering']=None
        after=domain.clone(record);after['state']={'mine':'working','melee':'fighting','bow':'shooting','guard':'guarding'}[kind]
        if kind=='guard':after['guard_next_at']=time.time()+10
        after['task']={'kind':kind,'target':target,'return_state':job['return_state']}
        self.put(record,after,operation);self.s.rt(record)['job']=job
        self.s.rt(record).pop('path_result',None)
        if not automatic:
            self.s.panels.pop(player,None);self.s.NotifyToClient(player,'Close',{})

    def cancel(self,record,message=None):
        job=self.s.rt(record).pop('job',None)
        task=record.get('task')
        if job or task:
            after=domain.clone(record);after.pop('task',None)
            after['state']=(job or task).get('return_state','following') if after['form']=='deployed' else 'stored'
            self.put(record,after);self.s.stop(record.get('entity_id'));self.s.rt(record)['action_until']=0
            if message and job and not job.get('automatic'):self.s.notify(job['player'],message)

    def turn(self,entity,point):
        pos=self.s.pos(entity);dx,dz=point[0]-pos[0],point[2]-pos[2]
        F.CreateRot(entity).SetRot((0,-math.degrees(math.atan2(dx,dz))))

    def finish_target(self,record,job,message):
        # An escaped target ends this pursuit, not the owner's selected mode.
        self.cancel(record,message)
        if job.get('automatic'):
            rt=self.s.rt(record);rt['mode_status']=message;rt['mode_next']=self.s.ticks+15
            self.s.attention.defer(record,job,TARGET_RETRY_TICKS)

    def tick(self,player,record):
        job=self.s.rt(record).get('job')
        if not job:return False
        try:
            self.allowed(player,job['kind']);self.ready(record)
            entity=record.get('entity_id')
            if not self.s.live(entity) or not self.s.live(player) or self.s.dim(entity)!=job['dimension'] or self.s.dim(player)!=job['dimension']:
                raise domain.Refused(u'任务已结束。')
            independent_mining=job.get('automatic')=='excavate' and job['kind']=='mine'
            if self.s.ticks-job['started']>900 or (not independent_mining and
                    dist(self.s.pos(player),self.s.pos(entity))>WORK_LEASH):
                self.finish_target(record,job,u'目标太远或任务超时，已结束这次追击。');return True
            if domain.empty(record['equipment'].get('off' if job['kind']=='guard' else 'main')):raise domain.Refused(u'工具已用尽，任务停止。')
            if job['kind']=='guard':self.tick_guard(record,job)
            elif job['kind']=='mine':self.tick_mine(record,job)
            else:self.tick_combat(record,job)
        except TargetUnavailable as error:
            self.finish_target(record,job,error.args[0])
        except domain.Refused as error:
            self.cancel(record,error.args[0])
            if job.get('automatic'):
                self.s.modes.failed(record,error.args[0]);self.s.notify(player,error.args[0])
        except Exception:
            traceback.print_exc();self.cancel(record,u'任务已停止，物品记录已保留。')
        return True

    def tick_guard(self,record,job):
        if self.s.ticks-job['started']>=150:self.cancel(record,u'这次举盾结束了。');return
        entity=record['entity_id'];player=job['player'];pos=self.s.pos(player)
        yaw=F.CreateRot(player).GetRot()[1];radians=math.radians(yaw)
        target=(pos[0]-math.sin(radians)*1.1,pos[1],pos[2]+math.cos(radians)*1.1)
        safe=target if self.s.swimming.wet(pos,job['dimension']) else self.s.safe(target,job['dimension'])
        if safe and dist(self.s.pos(entity),safe)>.45:
            self.s.move(record,safe,1.3)
            # Native navigation needs its own facing while approaching. Forcing
            # the player's yaw here can make it walk away from the destination.
            self.s.rt(record)['action_until']=0
        else:
            self.s.hold(record)
            F.CreateRot(entity).SetRot((0,yaw));self.s.action(record,8,.3)

    def protect(self,args):
        player=args.get('entityId');source=args.get('srcId');damage=args.get('damage',0)
        if player not in api.GetPlayerList() or damage<=0 or not self.hostile(source):return
        # Environmental damage, explosions and non-hostile/player attacks do
        # not become an accidental invulnerability effect.
        if args.get('cause') not in (E.ActorDamageCause.EntityAttack,E.ActorDamageCause.Projectile):return
        for record in self.s.owned(player):
            job=self.s.rt(record).get('job');entity=record.get('entity_id')
            if not job or job['kind']!='guard' or self.s.ticks-job['started']>=150 or not self.s.live(entity):continue
            shield=record['equipment'].get('off')
            if domain.item_name(shield)!='minecraft:shield' or self.s.dim(entity)!=self.s.dim(player):continue
            pos=self.s.pos(entity);owner=self.s.pos(player);attack=self.s.pos(source)
            if not attack or dist(pos,owner)>2.5 or not rules.in_front(pos,F.CreateRot(entity).GetRot()[1],attack):continue
            if not self.clear(self.s.dim(entity),(pos[0],pos[1]+.6,pos[2]),(owner[0],owner[1]+1,owner[2])):continue
            worn=shield;maximum=self.info(shield).get('maxDurability',336)
            for unused in range(min(int(math.ceil(damage))+1,int(shield.get('durability',maximum)))):
                if domain.empty(worn):break
                worn=rules.wear(worn,maximum,random.random())
            after=domain.clone(record);after['equipment']['off']=worn
            self.put(record,after)
            args['damage']=damage*.25;args['knock']=False
            if domain.empty(worn):self.cancel(record,u'盾牌已经损坏，防护结束。')
            return

    def mine_stands(self,record,block,dimension,get_block=None,budget=None,tree=False):
        """Only navigate to safe cells from which this block can really be hit."""
        pos=self.s.pos(record['entity_id']);stands=[];comp=F.CreateBlockInfo(self.s.level)
        get=get_block or (lambda p:comp.GetBlockNew(p,dimension))
        headroom=1 if tree else 2
        points=mining.stand_cells(block,pos)
        # Keep an already valid working spot; native navigation need not force
        # the companion to a neighbouring block centre before every swing.
        points.insert(0,tuple(pos));tested=0
        for candidate in points:
            x,y,z=[int(math.floor(v)) for v in candidate]
            if any((get((x,y+dy,z)) or {}).get('name') not in PASSABLE for dy in range(headroom)):continue
            eye=(candidate[0],candidate[1]+.65,candidate[2]);aim=mining.face(eye,block)
            if mining.squared(eye,aim)>mining.REACH**2:continue
            if budget is not None:
                if budget['stands']<=0:break
                budget['stands']-=1
            tested+=1
            point=self.s.safe(candidate,dimension,headroom) if tree else self.s.safe(candidate,dimension)
            if point and self.clear(dimension,eye,aim,block):stands.append(point)
            if tested>=mining.STAND_BUDGET or len(stands)>=8:break
        return sorted(set(stands),key=lambda p:dist(p,pos))

    def tick_mine(self,record,job):
        if job.get('mined'):
            if self.s.ticks>=job['swing_end']:
                self.cancel(record,u'采掘完成，产物已收进伙伴背包。')
                self.s.rt(record)['mode_next']=self.s.ticks
            return
        current=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(job['block']),job['dimension'])
        if job.get('original') and current!=job['original']:
            self.finish_target(record,job,u'目标已经变化，继续寻找其他目标。');return
        block=self.mine_check(record,job);b=job['block'];point=(b[0]+.5,b[1]+.5,b[2]+.5)
        entity=record['entity_id'];pos=self.s.pos(entity);eye=(pos[0],pos[1]+.65,pos[2])
        base=job.get('tree_base');reach=mining.face(eye,base or b)
        reachable=dist(eye,reach)<=mining.REACH and (not base or abs(pos[1]-base[1])<=1.5)
        reachable=reachable and self.clear(job['dimension'],eye,reach,base or b)
        if not reachable:
            job.pop('impact',None)
            anchor=base or b
            candidates=job.get('stands')
            if candidates is None:
                candidates=self.mine_stands(record,anchor,job['dimension'],tree=True) if base else self.mine_stands(record,anchor,job['dimension']);job['stands']=candidates
            if not candidates:
                self.finish_target(record,job,u'方块旁边没有可站立的位置，继续寻找其他目标。');return
            # Native failure or arrival without hit range immediately tries the
            # next valid face; interrupted duplicate move callbacks (3) do not.
            rt=self.s.rt(record);index=job.get('stand_index',0)
            result=rt.pop('path_result',None)
            recent=rt.get('path_result_at',self.s.ticks)>=job.get('route_at',self.s.ticks)
            failed=recent and result in (-3,-2,-1,1,2)
            arrived=index<len(candidates) and dist(pos,candidates[index])<.3
            if job.get('route_at') is not None and (failed or arrived):
                job['stand_index']=index+1;job['approach_progress']=(pos,self.s.ticks)
                job.pop('route_at',None)
            # A moving but ultimately blocked path also has a bounded retry.
            progress=job.get('approach_progress')
            if not progress or dist(pos,progress[0])>.25:job['approach_progress']=(pos,self.s.ticks)
            elif self.s.ticks-progress[1]>=36:
                job['stand_index']=job.get('stand_index',0)+1;job['approach_progress']=(pos,self.s.ticks)
                job.pop('route_at',None)
            index=job.get('stand_index',0)
            if index>=len(candidates):
                self.finish_target(record,job,u'暂时走不到目标旁边，继续寻找其他目标。');return
            if job.get('route_at') is None:job['route_at']=self.s.ticks
            self.s.move(record,candidates[index],1.2);return
        self.s.stop(entity);self.turn(entity,point);self.s.action(record,5,.3)
        if 'impact' not in job:
            tool=record['equipment']['main']
            duration=F.CreateBlockInfo(self.s.level).GetDestroyTotalTime(block['name']+':'+str(block.get('aux',0)),
                domain.native_value(domain.item_name(tool)),{'mining_efficiency':rules.enchant(tool,15)})
            ticks=mining.break_ticks(duration)
            if ticks is None:raise TargetUnavailable(u'这个方块目前无法采掘，继续寻找其他目标。')
            job['impact']=self.s.ticks+ticks
            job['swing_end']=job['impact']+3
        if self.s.ticks<job['impact']:return
        self.mine_native(record,job)
        job['mined']=True
        rt=self.s.rt(record)
        rt['last_mined']={'block':list(b),'dimension':job['dimension'],'at':self.s.ticks}
        scan=rt.get('mining_scan')
        if scan and scan['dimension']==job['dimension']:
            scan['blocks'][tuple(b)]={'name':'minecraft:air','aux':0}
        if job.get('opening_goal'):
            rt['mining_goal']=domain.clone(job['opening_goal'])
            rt['mining_goal']['remaining']-=1

    def restore_loan(self,player,record,reloading=False):
        loan=record.get('tool_loan')
        if not loan:return
        from .server import InventoryAdapter
        adapter=InventoryAdapter(self.s,player);current=adapter.inventory()[loan['slot']]
        if not domain.empty(current) and not rules.same_tool(current,loan['tool']):
            raise domain.Refused(u'工具转移需要核对，已保留记录，不会重复发放。')
        if reloading and domain.empty(current) and int(loan['tool'].get('durability',2))>1:
            raise domain.Refused(u'工具所在格已改变，已保留待核对记录。')
        after=domain.clone(record);after['equipment']['main']=domain.clone(current);after.pop('tool_loan',None)
        domain.transaction(adapter,record,after,[{'slot':loan['slot'],'before':current,'after':loan['owner_item']}],
            'return-tool:'+uuid.uuid4().hex)

    def mine_native(self,record,job):
        from .server import InventoryAdapter
        player=job['player'];adapter=InventoryAdapter(self.s,player)
        slot=F.CreateItem(player).GetSelectSlotId()
        if not 0<=slot<9:raise domain.Refused(u'快捷栏还没准备好。')
        owner_item=adapter.inventory()[slot];tool=domain.clone(record['equipment']['main'])
        after=domain.clone(record);after['equipment']['main']=None
        after['tool_loan']={'slot':slot,'owner_item':owner_item,'tool':tool,'block':job['block']}
        domain.transaction(adapter,record,after,[{'slot':slot,'before':owner_item,'after':tool}], 'borrow-tool:'+uuid.uuid4().hex)
        p=job['block'];lower=tuple(v-2 for v in p);upper=tuple(v+3 for v in p)
        game=F.CreateGame(self.s.level)
        previous=set(game.GetEntitiesInSquareArea(None,lower,upper,job['dimension']) or [])
        captures=[];self.capture=(job,captures);self.last_break=None
        success=False
        try:
            success=F.CreateBlockInfo(player).PlayerDestroyBlock(tuple(job['block']),1,True)
            now=F.CreateBlockInfo(self.s.level).GetBlockNew(tuple(job['block']),job['dimension'])
            success=bool(success and now and now.get('name')=='minecraft:air')
            if success and F.CreateGame(self.s.level).GetPlayerGameType(player)==1:
                # Creative has no native tool wear; cooperative equipment still wears.
                worn=rules.wear(tool,self.info(tool).get('maxDurability',1),random.random())
                adapter.set_slot(slot,worn)
                if not captures and (self.last_break or {}).get('spawnResources',True):
                    block=job['original'];comp=F.CreateBlockInfo(self.s.level)
                    if rules.enchant(tool,16):comp.SpawnResourcesSilkTouched(domain.native_value(block['name']),tuple(job['block']),block.get('aux',0),job['dimension'])
                    else:comp.SpawnResources(domain.native_value(block['name']),tuple(job['block']),block.get('aux',0),1.0,rules.enchant(tool,18),job['dimension'],True,True)
        finally:
            self.capture=None
            self.restore_loan(player,record)
        if not success:raise TargetUnavailable(u'方块未被破坏，可能受区域保护；工具已归还。')
        captures.extend(set(game.GetEntitiesInSquareArea(None,lower,upper,job['dimension']) or [])-previous)
        for drop in set(captures):
            if F.CreateItem(self.s.level).GetDroppedItem(drop,True):self.collect(record,drop)

    def added(self,args):
        if self.capture and args.get('engineTypeStr')=='minecraft:item':
            job,ids=self.capture
            p=(args.get('posX',0),args.get('posY',0),args.get('posZ',0))
            center=tuple(v+.5 for v in job['block'])
            if args.get('dimensionId')==job['dimension'] and dist(p,center)<2:ids.append(args['id'])

    def before_break(self,args):
        if self.capture and args.get('playerId')==self.capture[0]['player']:self.last_break=args

    def collect(self,record,drop):
        item=F.CreateItem(self.s.level).GetDroppedItem(drop,True)
        if domain.empty(item):return
        after=domain.clone(record)
        after['inventory']=rules.insert_bag(record,item,max(1,self.info(item).get('maxStackSize',64)))
        staged=domain.clone(record);staged['loot_pending']={'id':drop,'item':item,'inventory':after['inventory']}
        self.put(record,staged)
        if not self.s.DestroyEntity(drop):
            staged=domain.clone(record);staged.pop('loot_pending',None);self.put(record,staged)
            raise domain.Refused(u'产物仍留在原地，可自行拾取。')
        # Missing entity after a crash is ambiguous; never reissue this journal.
        after.pop('loot_pending',None);self.put(record,after)

    def tick_combat(self,record,job):
        # A hit/release is resolved once at the source animation's contact frame.
        # Let its recovery frames finish even if that hit killed the target.
        if job.get('cycle_started') is not None:
            if self.s.ticks>=job['cycle_end']:
                job.pop('cycle_started',None);job.pop('impact_done',None)
            elif job.get('impact_done'):
                self.s.hold(record);return
        target=job.get('entity')
        if not self.attackable(target,job.get('automatic')):
            self.cancel(record,u'目标已消失或不能攻击，继续寻找目标。')
            self.s.rt(record)['mode_next']=self.s.ticks+3
            return
        entity=record['entity_id'];pos=self.s.pos(entity);point=self.s.pos(target)
        if not point or self.s.dim(target)!=job['dimension'] or dist(point,self.s.pos(job['player']))>WORK_LEASH:
            self.finish_target(record,job,u'目标离开范围，已结束这次追击。');return
        bounds=F.CreateCollisionBox(target).GetSize() or (.6,1.8)
        height=max(.12,min(1.1,bounds[1]*.5))
        eye=(pos[0],pos[1]+.65,pos[2]);aim=(point[0],point[1]+height,point[2]);gap=dist(eye,aim)
        # Measure melee reach to the target's body surface, not its centre.
        # Large actors otherwise stop native navigation outside our hit radius.
        width=max(.1,min(2.0,bounds[0]))
        limit=1.6+width*.5 if job['kind']=='melee' else 10
        motion=F.CreateActorMotion(entity).GetMotion() or (0,0,0)
        wet=self.s.swimming.wet(pos,job['dimension'])
        # Do not zero horizontal motion in the middle of climbing a ledge.
        # Finish the rise before the first swing; a smaller approach radius
        # also leaves room for a moving target during the wind-up.
        climbing=not wet and (motion[1]>.1 or not self.s.swimming.grounded(pos,job['dimension']))
        reach=limit-.2 if job['kind']=='melee' and job.get('cycle_started') is None else limit
        if climbing or gap>reach or not self.clear(job['dimension'],eye,aim):
            if job.pop('cycle_started',None) is not None:
                job.pop('impact_done',None);self.s.rt(record)['action_until']=0;job['next']=self.s.ticks+6
            self.s.move(record,point,1.2);return
        self.s.hold(record);self.turn(entity,point)
        if job.get('cycle_started') is None:
            if self.s.ticks<job['next']:return
            animation='attack' if job['kind']=='melee' else 'archer_attack'
            job['cycle_started']=self.s.ticks
            job['cycle_end']=self.s.ticks+int(math.ceil(DURATIONS[animation]*30))
            job['impact_at']=self.s.ticks+int(math.ceil(IMPACTS[animation]*30))
            job['next']=job['cycle_end']+6
            self.s.action(record,6 if job['kind']=='melee' else 7,DURATIONS[animation],True)
            self.s.set_visual(entity,self.s.visual(record));return
        if self.s.ticks<job['impact_at']:return
        job['impact_done']=True
        tool=record['equipment']['main'];info=self.info(tool)
        if job['kind']=='melee':
            after=domain.clone(record);after['equipment']['main']=rules.wear(tool,info.get('maxDurability',1),random.random())
            # Persist wear before world damage, so a restart cannot replay a hit for free.
            self.put(record,after)
            damage=max(1,info.get('weaponDamage',1))+1.25*rules.enchant(tool,9)
            F.CreateHurt(target).Hurt(damage,E.ActorDamageCause.EntityAttack,entity,None,True)
        else:
            after,arrow=rules.spend_arrow(record)
            after['equipment']['main']=rules.wear(tool,info.get('maxDurability',384),random.random())
            self.put(record,after)
            direction=[aim[i]-eye[i] for i in range(3)]
            direction[1]+=.5*.05*(gap/1.6)**2
            length=math.sqrt(sum(v*v for v in direction));direction=tuple(v/length for v in direction)
            start=tuple(eye[i]+direction[i]*.42 for i in range(3))
            projectile=F.CreateProjectile(self.s.level).CreateProjectileEntity(entity,'minecraft:arrow',{
                'position':start,'direction':direction,'power':1.6,'gravity':.05,
                'damage':3+rules.enchant(tool,19),'auxValue':arrow.get('newAuxValue',arrow.get('auxValue',0)),
                'isDamageOwner':False})
            if not projectile or projectile=='-1':
                # Known synchronous failure: refund exactly the pre-shot record.
                refund=domain.clone(record);refund['equipment']['main']=tool
                refund['inventory']=rules.insert(refund['inventory'],arrow,64) if not (rules.enchant(tool,22) and arrow.get('newAuxValue',0)==0) else refund['inventory']
                self.put(record,refund);raise domain.Refused(u'箭矢没有发射成功，已退回箭和耐久。')
            # Vanilla non-player arrows use uncertainty_base=16. Set the launch
            # velocity once so that a deliberate aimed command is accurate;
            # gravity, collisions and every subsequent flight step remain native.
            F.CreateActorMotion(projectile).SetMotion(tuple(v*1.6 for v in direction))
            context={'owner':job['player'],'companion':entity,'expires':self.s.ticks+300,'work_mode':job.get('automatic')}
            self.arrows[projectile]=context
            F.CreateExtraData(projectile).SetExtraData('echo_companion_arrow',domain.native_value(context))

    def projectile(self,args):
        identity=args.get('id');context=self.arrows.get(identity)
        if not context and identity:
            context=F.CreateExtraData(identity).GetExtraData('echo_companion_arrow')
        if not context:return
        if args.get('hitTargetType')=='ENTITY' and not self.attackable(args.get('targetId'),context.get('work_mode')):
            args['cancel']=True;self.s.DestroyEntity(identity);self.arrows.pop(identity,None)

    def damage(self,args):
        self.s.modes.on_damage(args)
        source=args.get('srcId');arrow=args.get('projectileId')
        record=self.s.record_for_entity(source);context=self.arrows.get(arrow)
        if not context and arrow and arrow!='-1':context=F.CreateExtraData(arrow).GetExtraData('echo_companion_arrow')
        ours=record is not None or bool(context)
        mode=(context or {}).get('work_mode') if context else (self.s.rt(record).get('job') or {}).get('automatic') if record else None
        if ours and not self.attackable(args.get('entityId'),mode):
            args['damage']=0;args['knock']=False;args['ignite']=False
        else:self.protect(args)

    def cleanup(self):
        for identity,context in list(self.arrows.items()):
            if not self.s.live(identity):self.arrows.pop(identity,None)
            elif self.s.ticks>context['expires']:
                if self.s.DestroyEntity(identity):self.arrows.pop(identity,None)

    def recover(self,player,record):
        if record.get('pending'):return
        self.restore_loan(player,record,True)
        self.cancel(record)
        journal=record.get('loot_pending')
        if journal:
            item=F.CreateItem(self.s.level).GetDroppedItem(journal['id'],True)
            if item and domain.same(item,journal['item']):
                after=domain.clone(record);after.pop('loot_pending',None);self.put(record,after)
            else:raise domain.Refused(u'上次采掘产物正在等待核对，未重复发放。')

    def destroy(self):
        for record in self.s.records.values():self.cancel(record)
        for identity in list(self.arrows):
            if self.s.live(identity):self.s.DestroyEntity(identity)
        self.arrows.clear()
