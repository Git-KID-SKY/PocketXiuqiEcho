# -*- coding: utf-8 -*-
"""One bound starter companion per persistent player identity and world."""
import json
from . import domain


class StarterGift(object):
    def __init__(self, system):
        self.s = system
        self.finished = set()
        self.full_notice = set()

    def record(self, player, owner):
        # Stable key also recovers a save interrupted between record and index.
        cid = 'starter_' + owner
        record = self.s.records.get(cid)
        if record is None:
            record = self.s.world.GetExtraData(domain.native_value('echo_companion_' + cid))
            if isinstance(record, domain.string_types):
                record = json.loads(record)
            if record:
                record = domain.migrate(record)
            else:
                record = domain.new_record(owner)
                record['companion_id'] = cid
                record['starter_gift'] = 'waiting'
                self.s.interactions.apply_preferences(player, record)
            self.s.save(record)
        # Pending inventory journals are expected here and recovered below.
        if record.get('owner_id') != owner:
            raise domain.Refused(u'开局伙伴身份无法核对，请稍后再试。')
        return record

    def give(self, player, adapter):
        owner = self.s.owner(player)
        if owner in self.finished:
            return 'done'
        record = self.record(player, owner)
        if record.get('starter_gift') == 'granted':
            self.finished.add(owner)
            return 'done'
        items = adapter.inventory()
        expected = (record['companion_id'], record['token'])
        pending = record.get('pending')
        if pending:
            # Readback can find the unique token even if the player moved it
            # between a successful inventory write and a failed final save.
            if not any(domain.token_parts(item) == expected for item in items):
                return 'pending'
            after = domain.clone(pending['after'])
            self.s.save(after)
            record.clear(); record.update(after)
        else:
            slot = next((i for i, item in enumerate(items[:36]) if domain.empty(item)), None)
            if slot is None:
                if owner not in self.full_notice:
                    self.s.notify(player, u'开局小修齐已为你保留，腾出一格背包后会自动领取。')
                    self.full_notice.add(owner)
                return 'full'
            after = domain.clone(record)
            after['starter_gift'] = 'granted'
            patch = {'slot': slot, 'before': items[slot], 'after': domain.doll(record)}
            try:
                domain.transaction(adapter, record, after, [patch], 'starter:' + owner)
            except domain.Refused:
                # Same synchronous call, before gameplay can move the item:
                # a refused no-op write can be safely retried. After a restart
                # an ambiguous pending write stays journaled, never reissued.
                if record.get('pending') and domain.same(adapter.inventory()[slot], patch['before']):
                    retry = domain.clone(record); retry['pending'] = None
                    self.s.save(retry)
                    record.clear(); record.update(retry)
                raise
        self.finished.add(owner)
        self.full_notice.discard(owner)
        self.s.notify(player, u'收到开局小修齐！拿在手中，对地面使用可放出伙伴。')
        return 'granted'
