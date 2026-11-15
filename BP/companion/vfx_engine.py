# -*- coding: utf-8 -*-
"""Pure visual scheduler shared by offline simulation and the game adapter."""
from __future__ import division
import math


def curve(keys, u):
    if u <= keys[0][0]:
        return keys[0][1]
    for j in range(1, len(keys)):
        b, v = keys[j]
        a, w = keys[j - 1]
        if u <= b:
            return w + (v - w) * (u - a) / (b - a)
    return keys[-1][1]


def sample(points, u):
    t = max(0, min(1, u)) * (len(points) - 1)
    a = min(int(t), len(points) - 2)
    f = t - a
    return [points[a][k] * (1-f) + points[a+1][k] * f for k in range(3)]


def transform(local, origin, offset, yaw):
    a = math.radians(yaw)
    p = [local[k] + offset[k] for k in range(3)]
    return (origin[0] + p[0]*math.cos(a) - p[2]*math.sin(a),
            origin[1] + p[1], origin[2] + p[0]*math.sin(a) + p[2]*math.cos(a))


class Engine(object):
    """adapter: origin, create, update, remove, sound, tick, shutdown, error."""
    MAX_HANDLES = 128
    MAX_INSTANCES = 8

    def __init__(self, adapter):
        self.adapter = adapter
        self.instances = {}
        self.serial = 0
        self.handles = 0
        self.closed = False

    def play(self, effect, context=None, profile='medium', key=None):
        if self.closed:
            raise ValueError('visual engine has been destroyed')
        if profile not in effect['profiles']:
            raise ValueError('unknown quality profile: ' + str(profile))
        if key is not None:
            self.cancel(key)
        same = sum(1 for x in self.instances.values() if x['effect']['id'] == effect['id'])
        if same >= effect['budget']['instances'] or len(self.instances) >= self.MAX_INSTANCES:
            raise ValueError('concurrent visual instance budget exceeded')
        reserve = effect['profiles'][profile]['usage']['handles']
        reserved = sum(x['reserve'] for x in self.instances.values())
        if reserved + reserve > self.MAX_HANDLES:
            raise ValueError('global visual handle reservation budget exceeded')
        self.serial += 1
        token = key or ('vfx_%d' % self.serial)
        self.instances[token] = {'effect': effect, 'context': context or {}, 'age': 0,
                                 'profile': profile, 'reserve': reserve, 'starts': {}, 'events': {},
                                 'active': {}, 'last_states': {}, 'cued': set()}
        return token

    def signal(self, token, event):
        item = self.instances.get(token)
        if not item:
            return False
        if event not in item['effect']['events']:
            raise ValueError('undeclared visual event: ' + str(event))
        if event not in item['events']:
            item['events'][event] = item['age']
        return True

    def cancel(self, token):
        item = self.instances.pop(token, None)
        if item:
            for handle in list(item['active'].values()):
                self._remove(handle)
            try:
                self.adapter.cancel(token)
            except Exception as exc:
                self.adapter.error('cancel cleanup: '+str(exc))
            return True
        return False

    def cancel_owner(self, owner):
        for token, item in list(self.instances.items()):
            if item['context'].get('owner') == owner:
                self.cancel(token)

    def clear(self):
        for token in list(self.instances):
            self.cancel(token)

    def destroy(self):
        self.clear()
        self.closed = True
        self.adapter.shutdown()

    def _remove(self, handle):
        try:
            self.adapter.remove(handle)
        except Exception as exc:
            self.adapter.error(str(exc))
        finally:
            self.handles = max(0, self.handles - 1)

    def _start(self, layer, item, by_id):
        lid = layer['id']
        if lid in item['starts']:
            return item['starts'][lid]
        trigger = layer['start']
        if 'at' in trigger:
            value = trigger['at']
        elif 'event' in trigger:
            if trigger['event'] not in item['events']:
                return None
            value = item['events'][trigger['event']] + trigger.get('delay', 0)
        else:
            other = by_id[trigger['after']]
            value = self._start(other, item, by_id)
            if value is None:
                return None
            value += other['duration'] + max(other.get('delays', [0])) + trigger.get('delay', 0)
        item['starts'][lid] = value
        return value

    def tick(self, dt):
        if self.closed:
            return
        if not isinstance(dt, (int, float)) or not (0 < dt <= 1):
            raise ValueError('tick duration must be finite and in (0, 1]')
        try:
            self.adapter.tick(dt)
        except Exception as exc:
            self.clear()
            self.adapter.error('adapter tick failed: '+str(exc))
            return
        for token, item in list(self.instances.items()):
            try:
                self._advance(token, item, dt)
            except Exception as exc:
                self.adapter.error('cancelled %s: %s' % (token, exc))
                self.cancel(token)

    def _advance(self, token, item, dt):
        effect = item['effect']
        if item['age'] >= effect['max_seconds']:
            self.cancel(token)
            return
        anchor = self.adapter.origin(effect['binding'], item['context'])
        if anchor is None:
            self.cancel(token)
            return
        origin, yaw = anchor
        if effect.get('camera') and item['context'].get('allow_camera'):
            self.adapter.camera(token, effect['camera'], item['age'], origin, yaw, item['context'], dt)
        layers = effect['profiles'][item['profile']]['layers']
        by_id = dict((l['id'], l) for l in layers)
        pending = False
        for layer in layers:
            start = self._start(layer, item, by_id)
            if start is None:
                pending = True
                continue
            for index, track in enumerate(layer['tracks']):
                key = (layer['id'], index)
                t = item['age'] - start - layer.get('delays', [0]*len(layer['tracks']))[index]
                if t < 0:
                    pending = True
                    continue
                looping = layer.get('loop', False)
                if not looping and t >= layer['duration']:
                    if layer['kind'] == 'particle' and key in item['active'] and t < layer['duration']+layer['lifetime']:
                        pending = True
                        fading = dict(item['last_states'][key], rate=0)
                        self.adapter.update(item['active'][key], fading, dt)
                        continue
                    if key in item['active']:
                        self._remove(item['active'].pop(key))
                    continue
                pending = True
                u = (t % layer['duration'] if looping else t) / layer['duration']
                point = sample(track, u)
                pos = transform(point, origin, effect['binding']['offset'], yaw)
                state = {'pos': pos, 'scale': curve(layer['size'], u),
                         'alpha': curve(layer['alpha'], u), 'color': layer['color'],
                         'rotation': layer.get('spin', 0) * t + yaw,
                         'rate': layer.get('rate', 0)}
                if key not in item['active']:
                    if self.handles >= self.MAX_HANDLES:
                        raise ValueError('global active handle budget exceeded')
                    handle = self.adapter.create(layer, state)
                    if handle is None:
                        raise ValueError('engine could not create layer ' + layer['id'])
                    item['active'][key] = handle
                    self.handles += 1
                self.adapter.update(item['active'][key], state, dt)
                item['last_states'][key] = state
                if layer['id'] not in item['cued']:
                    item['cued'].add(layer['id'])
                    for cue in effect.get('cues', []):
                        if cue['layer'] == layer['id']:
                            self.adapter.sound(cue, pos, token)
        item['age'] += dt
        if not pending:
            self.cancel(token)
