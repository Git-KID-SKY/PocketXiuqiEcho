# -*- coding: utf-8 -*-
"""Independent geometry layers, following the supplied kid scabbard binding.

Player reference: AddPlayerGeometry/Texture/RenderController, RebuildPlayerRender.
Companion equivalent: AddActorGeometry/Texture/RenderController, RebuildActorRender.
Each geometry contains empty named body bones and its own accessory cubes only.
The entity's existing animations therefore drive the attachment skeleton as well.
"""
import mod.client.extraClientApi as api
from . import config
from .binding_data import LAYERS


def install():
    render=api.GetEngineCompFactory().CreateActorRender(api.GetLevelId())
    results=[]
    for layer in LAYERS:
        key='acc_'+layer['id']
        results.append(render.AddActorGeometry(config.ENTITY,key,layer['geometry']))
        results.append(render.AddActorGeometry(config.ENTITY,key+'_xiuqi',layer['geometry']+'_xiuqi'))
        results.append(render.AddActorTexture(config.ENTITY,key,layer['texture']))
        results.append(render.AddActorRenderController(config.ENTITY,
            'controller.render.echo.accessory.'+layer['id'],layer['condition']))
    results.append(render.RebuildActorRender(config.ENTITY))
    return all(results)


def bind_entity(entity,registered):
    """Keep accessory layers in the individual actor's appearance override.

    NetEase's per-actor rebuild does not inherit layers registered later on the
    identifier. Bind the same references locally before rebuilding that actor.
    """
    render=api.GetEngineCompFactory().CreateActorRender(api.GetLevelId())
    results=[]
    for layer in LAYERS:
        key='acc_'+layer['id']
        results.append(render.AddGeometryToOneActor(entity,key,layer['geometry']))
        results.append(render.AddGeometryToOneActor(entity,key+'_xiuqi',layer['geometry']+'_xiuqi'))
        results.append(render.AddTextureToOneActor(entity,key,layer['texture']))
        controller='controller.render.echo.accessory.'+layer['id']
        if controller not in registered:
            added=render.AddRenderControllerToOneActor(entity,controller,layer['condition'])
            results.append(added)
            if added:registered.add(controller)
    return all(results)
