# -*- coding: utf-8 -*-
"""A player geometry layer shares the owner's native per-frame transform."""
import mod.client.extraClientApi as api
from .joined_data import LAYERS, CLIPS


def install_player_poses(render):
    # Reapply these after adding companion layers: a player-render rebuild can
    # otherwise leave the earlier arm/socket animations ahead of the new rig.
    results=[]
    for name,animation,condition in (
        ('hug','hug','q.mod.ec_hug>0.001 && q.mod.ec_third>0.5'),
        ('hand','hand','q.mod.ec_hand>0.001 && q.mod.ec_third>0.5'),
        ('steady','held_steady','q.mod.ec_held>.5 && q.mod.ec_third<.5'),
        ('socket','item_socket','q.mod.ec_held>.5 && q.mod.ec_third<.5')):
        key='echo_companion_'+name
        results.append(render.AddPlayerAnimation(key,'animation.echo.player.'+animation))
        results.append(render.AddPlayerScriptAnimate(key,condition,True))
    return results


def install(player, defaults):
    factory=api.GetEngineCompFactory();render=factory.CreateActorRender(player)
    query=factory.CreateQueryVariable(player)
    query.Register('query.mod.ec_join_visible',0.)
    for key,value in defaults.items():query.Register('query.mod.ec_join_'+key,float(value))
    results=[render.AddPlayerRenderMaterial('ec_join','entity_alphatest')]
    for layer in LAYERS:
        key='ec_join_'+layer['key']
        for suffix,geometry in zip(('','_xiuqi'),layer['geometry']):results.append(render.AddPlayerGeometry(key+suffix,geometry))
        for suffix,texture in zip(('','_xiuqi'),layer['texture']):results.append(render.AddPlayerTexture(key+suffix,texture))
        results.append(render.AddPlayerRenderController(layer['controller'],'q.mod.ec_join_visible>.5'))
    for key,condition in CLIPS:
        name='ec_join_'+key
        results.append(render.AddPlayerAnimation(name,'animation.echo.joined.'+key))
        results.append(render.AddPlayerScriptAnimate(name,'q.mod.ec_join_visible>.5 && ('+condition+')',True))
    results.extend(install_player_poses(render))
    results.append(render.RebuildPlayerRender())
    return all(results)
