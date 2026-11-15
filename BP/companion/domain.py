# -*- coding: utf-8 -*-
"""Authoritative records and recoverable inventory transactions, Python 2.7 compatible.

The adapter writes exact slots, verifies the readback and persists the journal
before touching the player inventory. No item data is accepted from the client.
"""
from __future__ import division
import copy
import uuid
from . import config

try:
    string_types = (basestring,)
    text_type = unicode
except NameError:
    string_types = (str,)
    text_type = str


def native_value(value):
    """Python 2 ModAPI's native dictionary bridge expects UTF-8 byte strings."""
    if text_type is not str and isinstance(value,text_type):return value.encode('utf-8')
    if isinstance(value,dict):return {native_value(k):native_value(v) for k,v in value.items()}
    if isinstance(value,list):return [native_value(v) for v in value]
    if isinstance(value,tuple):return tuple(native_value(v) for v in value)
    return value


def native_item(item):
    """Restore native enchantment tuples after a JSON save/load round trip."""
    result=native_value(item)
    for key in ('enchantData','modEnchantData'):
        if result.get(key):result[key]=[tuple(entry) for entry in result[key]]
    return result


class Refused(Exception):
    pass


def clone(value):
    return copy.deepcopy(value)


def item_name(item):
    return (item or {}).get('newItemName', (item or {}).get('itemName', 'minecraft:air'))


def empty(item):
    return not item or item.get('count', 0) <= 0 or item_name(item) in ('', 'minecraft:air')


def normalized(item):
    if empty(item):
        return None
    value = clone(item)
    value['newItemName'] = item_name(value)
    value['newAuxValue'] = value.get('newAuxValue', value.get('auxValue', 0))
    value.pop('itemName', None)
    value.pop('auxValue', None)
    # The wearable token has no gameplay durability. Older engine builds add
    # a default armor durability even when max_damage is zero.
    if item_name(value) in (config.ITEM,config.WEARABLE):
        value.pop('durability',None)
        if isinstance(value.get('userData'),dict):value['userData'].pop('Damage',None)
    # The item bridge mirrors these top-level properties into NBT on writes.
    # Ignore only matching mirrors, never independent user metadata.
    data=value.get('userData')
    if isinstance(data,dict):
        # ModAPI exposes remaining durability at top level and synthesizes its
        # reserved NBT Damage mirror on a native inventory write. Compare the
        # authoritative remaining value; retain all unrelated custom NBT.
        damage=data.get('Damage')
        if 'durability' in value and isinstance(damage,dict) and damage.get('__type__')==3 and isinstance(damage.get('__value__'),int):data.pop('Damage',None)
        for nbt,key in [('ItemExtraID','extraId'),('ItemCustomTips','customTips')]:
            tag=data.get(nbt)
            if isinstance(tag,dict) and native_value(tag.get('__value__'))==native_value(value.get(key)):
                data.pop(nbt,None)
    # The engine adds empty optional fields when reading a newly created item.
    # Only discard empty defaults; all meaningful metadata stays in comparisons.
    for key in ('userData', 'enchantData', 'modEnchantData', 'customTips', 'extraId', 'canPlaceOn', 'canDestroy', 'modId', 'modItemId', 'durability'):
        if key in value and not value[key]:
            value.pop(key)
    for key in ('itemId','isDiggerItem','showInHand'):
        value.pop(key,None)
    def canonical(data):
        if isinstance(data,bytes):
            try:return data.decode('utf-8')
            except UnicodeDecodeError:return data
        if isinstance(data, dict):
            return {k: canonical(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [canonical(v) for v in data]
        return data
    return canonical(value)


def same(a, b):
    return normalized(a) == normalized(b)


def token_parts(item):
    if item_name(item) not in (config.ITEM,config.WEARABLE):
        return None
    parts = (item.get('extraId') or '').split(':')
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == 'ec1' else None


def doll(record,wearable=False):
    return {'newItemName': config.WEARABLE if wearable else config.ITEM, 'newAuxValue': 0, 'count': 1,
            'extraId': 'ec1:' + record['companion_id'] + ':' + record['token'],
            'customTips': (record.get('name') or u'随行伙伴')+u'\n空手交互取回装备；木棍切换跟随状态'}


def new_record(owner):
    record = {'schema_version': 3, 'companion_id': uuid.uuid4().hex, 'owner_id': owner,
            'revision': 0, 'token': uuid.uuid4().hex, 'form': 'stored',
            'state': 'stored', 'inventory': [None] * config.CAPACITY,
            'equipment': {'main': None,'off':None}, 'outfit': {'hat': 'none', 'glasses': 'none',
            'backpack': 'b01', 'waist': 'none'}, 'settings': {'mode': 'hold',
            'last_held': 'hold', 'style': 'default', 'motion_revision': 2, 'fall_reaction': True,
            'food_prompt': True, 'particles': True, 'work_mode': 'follow', 'mine_sample': None, 'appearance':'original'}, 'last_position': None,
            'entity_id': None, 'name': config.DEFAULT_NAME, 'recent_ops': [], 'pending': None}
    record['settings'].update(clone(config.SUPPLY_DEFAULTS))
    return migrate(record)


def migrate(record):
    """Grow old bags and pending journal snapshots without dropping any item."""
    values=record.setdefault('inventory',[])
    if len(values)<config.CAPACITY:values.extend([None]*(config.CAPACITY-len(values)))
    record.setdefault('equipment',{'main':None})
    record['equipment'].setdefault('off',None)
    from .interaction_rules import DEFAULTS,ARMOR
    for slot in ARMOR:record['equipment'].setdefault(slot,None)
    record.setdefault('name',u'')
    for category in config.ACCESSORIES:record.setdefault('outfit',{}).setdefault(category,'none')
    settings=record.setdefault('settings',{})
    settings.setdefault('work_mode','follow')
    settings.setdefault('mine_sample',None)
    if settings.get('appearance') not in config.APPEARANCES:settings['appearance']='original'
    if settings.get('motion_revision',0)<2:
        settings['style']='default';settings['motion_revision']=2
    if settings.get('supply_revision',0)<4:
        if settings.get('supply_mode','prompt')!='off':
            settings.update({'supply_mode':'prompt','hunger_threshold':20})
            if settings.get('food_choice','bread')=='bread':settings['food_choice']='any'
            record['supply_next_at']=0
        settings['supply_revision']=4
    for key,value in config.SUPPLY_DEFAULTS.items():settings.setdefault(key,value)
    for key,value in DEFAULTS.items():settings.setdefault(key,value)
    settings.setdefault('active_work',False)
    settings.setdefault('movement','follow')
    settings.setdefault('interaction_revision',1)
    if not settings.get('food_prompt',True):settings['supply_mode']='off'
    record['schema_version']=3
    if record.get('pending') and record['pending'].get('after'):
        migrate(record['pending']['after'])
    return record


def require_owner(record, owner):
    if not record or record.get('owner_id') != owner:
        raise Refused(u'这是别人的小修齐，只能看看它。')
    if record.get('pending'):
        raise Refused(u'正在核对上一次存取，请稍后再试。')


def check_request(record, owner, revision, operation):
    require_owner(record, owner)
    if not isinstance(operation, string_types) or not 1 <= len(operation) <= 96:
        raise Refused(u'这次操作没有完成，请重新打开面板。')
    if operation in record['recent_ops']:
        return False
    if revision != record['revision']:
        raise Refused(u'物品已经更新，请再点一次。')
    return True


def finish(record, operation):
    record['revision'] += 1
    record['recent_ops'] = (record['recent_ops'] + [operation])[-32:]


def first_empty(items):
    for index, item in enumerate(items):
        if empty(item):
            return index
    raise Refused(u'腾一个物品格，再继续吧。')


def transaction(adapter, record, after_record, patches, operation):
    """Commit checked exact-slot changes. Journal recovery never guesses unknown slots."""
    if record.get('pending'):
        raise Refused(u'上一次存取还在核对中。')
    current = adapter.inventory()
    for patch in patches:
        if not same(current[patch['slot']], patch['before']):
            raise Refused(u'背包物品变了，请再试一次。')
    after = clone(after_record)
    after['pending'] = None
    finish(after, operation)
    journal = {'operation': operation, 'patches': clone(patches), 'after': after}
    staged = clone(record)
    staged['pending'] = journal
    adapter.save(staged)
    record.clear()
    record.update(staged)
    try:
        for patch in patches:
            adapter.set_slot(patch['slot'], clone(patch['after']))
            if not same(adapter.inventory()[patch['slot']], patch['after']):
                raise Refused(u'物品没有成功移动，已保留存取记录。')
        adapter.save(after)
        record.clear()
        record.update(after)
    except Exception:
        # Keep the journal, including original item dictionaries, for recovery.
        raise


def recover(adapter, record):
    journal = record.get('pending')
    if not journal:
        return True
    current = adapter.inventory()
    for patch in journal['patches']:
        value = current[patch['slot']]
        # Never reissue an item after a restart. An empty target could mean it
        # was already granted and then moved before the final save failed.
        # Ambiguous writes remain in escrow instead of guessing or duplicating.
        if not same(value, patch['after']):
            return False
    after = clone(journal['after'])
    adapter.save(after)
    record.clear()
    record.update(after)
    return True


def transfer(adapter, record, direction, slot, operation, count=None):
    items = adapter.inventory()
    after = clone(record)
    if direction == 'deposit':
        if not isinstance(slot, int) or not 0 <= slot < len(items):
            raise Refused(u'请选择一个物品格。')
        source = items[slot]
        if empty(source):
            raise Refused(u'这个格子是空的。')
        if item_name(source) in (config.ITEM,config.WEARABLE):
            raise Refused(u'小修齐不能放进自己的背包。')
        from .interaction_rules import capacity
        destination = first_empty(after['inventory'][:capacity(record)])
        after['inventory'][destination] = clone(source)
        patch = {'slot': slot, 'before': source, 'after': None}
    else:
        if not isinstance(slot, int) or not 0 <= slot < len(after['inventory']):
            raise Refused(u'请选择一个伙伴物品格。')
        source = after['inventory'][slot]
        if empty(source):
            raise Refused(u'这个格子是空的。')
        destination = first_empty(items)
        amount = source['count'] if count is None else min(source['count'], count)
        if amount < 1:
            raise Refused(u'物品数量不正确。')
        take = clone(source)
        take['count'] = amount
        left = clone(source)
        left['count'] -= amount
        after['inventory'][slot] = None if empty(left) else left
        patch = {'slot': destination, 'before': items[destination], 'after': take}
    transaction(adapter, record, after, [patch], operation)


def set_option(record, category, value):
    if category=='appearance' and value in config.APPEARANCES:record['settings'][category]=value
    elif category == 'style' and value in ('default', 'q', 'wizard'):
        record['settings'][category] = value
    elif category in ('fall_reaction', 'food_prompt', 'particles') and isinstance(value, bool):
        record['settings'][category] = value
        if category=='food_prompt':record['settings']['supply_mode']='prompt' if value else 'off'
    elif category=='supply_mode' and value in config.SUPPLY_MODES:
        record['settings'][category]=value;record['settings']['food_prompt']=value!='off'
    elif category=='food_choice' and value in config.FOOD_CHOICES:record['settings'][category]=value
    elif category=='hunger_threshold' and type(value) is int and value in (8,12,16,20):record['settings'][category]=value
    elif category=='supply_interval' and type(value) is int and value in (15,30,60):record['settings'][category]=value
    elif category=='tool_prompt' and type(value) is bool:record['settings'][category]=value
    else:
        raise Refused(u'这个设置无法保存。')


def set_outfit(record, category, value):
    if category not in config.ACCESSORIES or value not in config.ACCESSORIES[category]:
        raise Refused(u'这件装扮暂时不能穿。')
    record['outfit'][category] = value


class FallReaction(object):
    """Transient state only; at most one landing pulse for each fall."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.down = 0.0
        self.distance = 0.0
        self.intensity = 0.0
        self.landing = 0.0
        self.was_air = False

    def step(self, dt, vertical_speed, grounded, eligible=True):
        if not eligible:
            self.reset()
            return (0.0, 0.0)
        self.landing = max(0.0, self.landing - dt / .35)
        if grounded:
            if self.was_air and self.down >= .25:
                self.landing = 1.0
            self.down = 0.0
            self.distance = 0.0
            self.intensity = 0.0
        elif vertical_speed < -.04:
            self.down += dt
            self.distance += -vertical_speed * dt
            self.intensity = min(1.0, .35 + self.distance / 4) if self.down >= .25 else .08
        elif vertical_speed <= .04 and self.down >= .25:
            # Network/physics samples may report a zero velocity while airborne.
            # Keep the falling pose until landing or an actual upward movement.
            pass
        else:
            self.down = 0.0
            self.distance = 0.0
            self.intensity = 0.0
        self.was_air = not grounded
        return self.intensity, self.landing
