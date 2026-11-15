# -*- coding: utf-8 -*-
"""One truthful work announcement shared by gestures and the original panel."""
from . import domain, interaction_rules as rules, mining_filter


def signature(record, info=None):
    settings=record['settings'];sample=settings.get('mine_sample') or {}
    return (rules.kind(record['equipment'].get('main'),info),
        settings.get('work_mode','follow'),bool(settings.get('active_work')),
        settings.get('movement','follow'),sample.get('name'),sample.get('aux',0),sample.get('family'))


def line(record, info=None):
    settings=record['settings'];tool=rules.kind(record['equipment'].get('main'),info)
    movement=settings.get('movement','follow');mode=settings.get('work_mode','follow')
    if movement=='wait':return u'我在这里等你，工作先停一下～'
    if movement=='roam' and mode in ('follow','protect','stroll'):return u'我在附近逛逛，不会跑远哦～'
    if tool=='torch':return u'照明交给我，陪你一起走～'
    if mode=='excavate':
        sample=settings.get('mine_sample')
        if sample:return u'收到！我去采集'+mining_filter.label(sample)+u'～'
        return {'axe':u'我去砍树啦，有树苗就帮你补种～',
            'pickaxe':u'我去找露出的矿石啦～','shovel':u'我去采集附近的土砂～'}.get(tool,u'我去采集指定的方块～')
    if mode=='hoe':return u'我去耕地种菜，种子放我背包里哦～'
    if mode=='shears':return u'我去帮小羊剪毛啦～'
    if mode=='hunt':return u'我去狩猎啦，驯养的小动物不碰～'
    if mode=='aggressive':return u'我去清理附近的怪物，保护你～'
    if mode=='protect':return u'武器准备好啦，我来守护你～'
    if mode=='stroll':return u'我在附近逛逛，不会跑远哦～'
    if tool in ('pickaxe','axe','shovel','hoe','shears'):
        title={'pickaxe':u'挖矿','axe':u'砍树','shovel':u'挖土','hoe':u'种植','shears':u'剪羊毛'}[tool]
        return title+u'工具收到！潜行空手点我就开工～'
    return u'先停下工作，继续陪着你～'


class WorkFeedback(object):
    def __init__(self,system):self.s=system

    def owner(self,record):
        return next((p for p,owner in self.s.owners.items() if owner==record['owner_id']),None)

    def changed(self,record,force=False):
        info=self.s.work.info(record['equipment'].get('main'));key=signature(record,info);rt=self.s.rt(record)
        if not force and key==rt.get('work_bubble_signature'):return
        rt['work_bubble_signature']=key
        if record['form']!='deployed' or record.get('fallen'):return
        rt['work_bubble_pending']=line(record,info)
        self.flush(record)

    def flush(self,record):
        rt=self.s.rt(record);message=rt.get('work_bubble_pending');player=self.owner(record)
        if not player or player in self.s.panels:return
        if record['form']!='deployed' or not self.s.live(record.get('entity_id')):
            rt.pop('work_bubble_pending',None);return
        if record.get('fallen') or rt.get('offering') is not None:return
        if message:
            rt.pop('work_bubble_pending',None);rt.pop('work_problem_pending',None)
            self.s.chatter.say(player,record,'work_change',message,0,urgent=True)
            rt['work_bubble_until']=self.s.ticks+90
        elif self.s.ticks>=rt.get('work_bubble_until',0) and rt.get('work_problem_pending'):
            message=rt.pop('work_problem_pending')
            self.s.chatter.say(player,record,'work_problem:'+message,message,600,urgent=True)

    def problem(self,record,message):
        player=self.owner(record)
        if player and record['form']=='deployed' and self.s.live(record.get('entity_id')):
            rt=self.s.rt(record)
            if self.s.ticks<rt.setdefault('speech_cooldowns',{}).get('work_problem:'+message,0):return
            rt['work_problem_pending']=message;self.flush(record)
