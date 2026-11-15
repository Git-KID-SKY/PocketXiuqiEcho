# -*- coding: utf-8 -*-
from __future__ import division
import copy
import mod.client.extraClientApi as api
from .vfx_engine import Engine
from .vfx_data import EFFECTS
from .rescue_vfx_data import RESCUE_EFFECTS


class ParticleAdapter(object):
    """Small particle-only adapter; the scheduler is the validated Workbench engine."""
    def __init__(self):
        self.comp=api.GetEngineCompFactory().CreateParticleSystem(None)
        self.failed=[]

    def origin(self,binding,context):
        return (tuple(context['position']),context.get('yaw',0))

    def create(self,layer,state):
        handle=self.comp.Create(layer['asset'],state['pos'],(0,0,0))
        return handle or None

    def update(self,handle,state,dt):
        if not self.comp.Exist(handle):raise ValueError('companion particle disappeared')
        self.comp.SetPos(handle,state['pos'])
        for key,value in [('size',state['scale']),('alpha',state['alpha']),('rate',state['rate'])]+list(zip(('r','g','b'),state['color'])):
            self.comp.SetVariable(handle,'variable.vfx_'+key,float(value))

    def remove(self,handle):
        if self.comp.Remove(handle) is False:self.failed.append((handle,0))

    def tick(self,dt):
        pending,self.failed=self.failed,[]
        for handle,tries in pending:
            if self.comp.Exist(handle) and self.comp.Remove(handle) is False and tries<3:self.failed.append((handle,tries+1))

    def cancel(self,token):
        pass

    def sound(self,cue,pos,token):
        pass

    def camera(self,*args):
        pass

    def shutdown(self):
        for handle,_ in self.failed:self.comp.Remove(handle)
        self.failed=[]

    def error(self,message):
        print('[Companion particles] '+str(message))


class VisualEffects(object):
    def __init__(self,system):
        self.engine=Engine(ParticleAdapter())

    def play(self,args):
        kind=args['kind'];token=args['id']
        if kind.startswith('revive'):
            # Dedicated key: rescue cancellation never removes an unrelated gift.
            token='revive:'+token
            self.engine.cancel(token)
            if kind=='revive_cancel':return
            effect=RESCUE_EFFECTS[kind]
        else:effect=EFFECTS['gift' if kind=='offer' else 'stardust']
        if kind=='recall':
            effect=copy.deepcopy(effect)
            for profile in effect['profiles'].values():
                for layer in profile['layers']:
                    for path in layer.get('tracks',[]):path.reverse()
        self.engine.play(effect,{'position':args['position'],'owner':args.get('owner')},'high',token)

    def tick(self,dt):
        self.engine.tick(dt)

    def clear(self):
        self.engine.clear()

    def cancel_owner(self,owner):
        self.engine.cancel_owner(owner)

    def destroy(self):
        self.engine.destroy()
