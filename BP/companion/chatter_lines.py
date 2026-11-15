# -*- coding: utf-8 -*-
"""Speech categories describe the real situation, not just the selected mode."""
HURT_ECHO_CHANCE = .02
HURT_ECHO_LINES = (u'关注修齐Echo喵', u'关注修齐Echo谢谢喵')

LINES={
    'owner':(u'达咩～',u'轻一点嘛！',u'呜哇，别戳我啦～',u'小修齐要揉揉！'),
    'danger':(u'我快撑不住啦，先退到你身边！',u'有点顶不住了，帮我挡一下呀！'),
    'battle':(u'哼哼，看我的！',u'小修齐认真起来啦！',u'我会小心的，嘿呀！'),
    'protect':(u'我来挡住它，你小心！',u'有我在，快站到安全的地方！'),
    'work':(u'挖东西时被偷袭啦，小心后面！',u'有家伙来捣乱，帮我看一下呀！'),
    'ambush':(u'有家伙打我，帮帮我呀！',u'呜哇，我被偷袭啦，小心！'),
    'environment':(u'呜，疼疼～这里有危险！',u'这里会受伤，绕开一点呀～')
}


def hurt_echo_trigger(source,entity,roll):
    """A rare extra line for an incoming actor hit, never self/environment damage."""
    return source not in (None,'','-1',-1,entity) and 0<=roll<HURT_ECHO_CHANCE


def hurt_topic(source,player,remaining,job,mode):
    if remaining<=0:return None
    if source==player:return 'owner'
    if remaining<=6:return 'danger'
    if source in (None,'','-1',-1):return 'environment'
    if (job or {}).get('kind')=='guard' or mode=='protect':return 'protect'
    if (job or {}).get('kind') in ('melee','bow'):return 'battle'
    if (job or {}).get('kind')=='mine':return 'work'
    return 'ambush'
