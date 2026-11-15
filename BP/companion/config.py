# -*- coding: utf-8 -*-
NAMESPACE = 'echo_companion'
VERSION = '1.8.0'
DEFAULT_NAME = u'小修齐'
HAND_SIDE = .64
ITEM = 'echo:companion_doll'
WEARABLE = 'echo:companion_backpack'
ENTITY = 'echo:companion'
SERVER = 'CompanionServer'
CLIENT = 'CompanionClient'
CAPACITY = 27
TICK_RATE = 30
MAX_DISTANCE = 7.0
ACCESSORIES = {
    'hat': ['none'] + ['h%02d' % n for n in range(1, 11)],
    'glasses': ['none', 'g01', 'g02', 'g03'],
    'backpack': ['none','b01', 'b02', 'b03', 'b04'],
    'waist': ['none', 'w01', 'w02'],
    'charm': ['none'],
}
ACCESSORY_NAMES = {
    'none': u'不佩戴', 'b01': u'旅伴小方包', 'b02': u'小邮差背包',
    'b03': u'小工匠工具包', 'b04': u'小航海旅行包', 'h01': u'牛仔帽',
    'h02': u'海盗帽', 'h03': u'探险帽', 'h04': u'渔夫帽', 'h05': u'小巫师帽',
    'h06': u'毛线便帽', 'h07': u'水手帽', 'h08': u'厨师帽', 'h09': u'小草帽',
    'h10': u'护耳冬帽', 'g01': u'方框眼镜', 'g02': u'飞行员眼镜',
    'g03': u'游泳护目镜', 'w01': u'奶油橙游泳圈', 'w02': u'小鸭游泳圈',
}
from .accessory_catalog import ENTRIES as IMPORTED_ACCESSORIES
for _accessory in IMPORTED_ACCESSORIES:
    ACCESSORIES[_accessory['category']].append(_accessory['id'])
    ACCESSORY_NAMES[_accessory['id']]=_accessory['name']
if 'h78' in ACCESSORIES['hat']:
    ACCESSORIES['hat'].remove('h78')
    ACCESSORIES['hat'].insert(0,'h78')
MODE_NAMES = {'hug': u'抱着它', 'hold': u'普通手持', 'hand': u'牵手走'}
APPEARANCES = {'original':u'原版小修齐','xiuqi':u'修齐meshy'}
STATE_NAMES = {'stored': u'公仔在背包里', 'following': u'跟随中',
    'waiting': u'原地等候', 'hand_in_hand': u'牵手中', 'offering': u'等你领取',
    'deploying': u'正在放出', 'recalling': u'正在收回', 'suspended': u'等你回来',
    'working': u'正在采掘', 'fighting': u'近战协助', 'shooting': u'弓箭协助', 'guarding': u'举盾保护',
    'fallen': u'已倒下 · 空手交互救治'}
SUPPLY_DEFAULTS = {'supply_mode':'prompt','food_choice':'any','hunger_threshold':20,
    'supply_interval':30,'tool_prompt':True,'backup_slot':None,'supply_revision':4}
SUPPLY_MODES = {'off':u'关闭','prompt':u'提醒领取','auto':u'自动送入背包','drop':u'丢到玩家面前'}
FOOD_CHOICES = {'bread':u'面包','cooked':u'熟食','fruit':u'水果','any':u'允许的食物'}
FOOD_GROUPS = {'bread':('bread',),'cooked':('cooked_beef','cooked_porkchop','cooked_chicken',
    'cooked_mutton','cooked_rabbit','cooked_cod','cooked_salmon','baked_potato'),
    'fruit':('apple','melon_slice','sweet_berries','carrot','golden_carrot')}
WORK_MODES = {'follow':u'跟随陪伴','aggressive':u'主动攻击','protect':u'保护主人',
    'hunt':u'狩猎生物','stroll':u'散步','excavate':u'开凿'}
WORK_HINTS = {
    'follow':u'跟着主人，不主动寻找工作目标。',
    'aggressive':u'主动寻找附近怪物。\n需要剑、斧，或弓和箭。',
    'protect':u'跟随主人，反击正在攻击主人的生物。\n需要武器或盾牌；不攻击玩家和宠物。',
    'hunt':u'自动狩猎野生牛、猪、羊、鸡、兔等。\n需要武器；不攻击玩家和已驯养生物。',
    'stroll':u'在主人附近轻松散步，不主动战斗。\n主人走远后会跟上。',
    'excavate':u'自动寻找设置里的目标方块。\n需要对应工具和至少 4 个背包空格。'}
