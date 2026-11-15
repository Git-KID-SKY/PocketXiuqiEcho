# -*- coding: utf-8 -*-
"""Client-only speech presentation; disabled bubbles never accumulate work."""
import mod.client.extraClientApi as api
from . import config
from .speech_layout import HEAD_OFFSET, speech_preferences


def preferences(system):
    current=getattr(system,'speech_preferences',None)
    if current is None:
        settings=getattr(system,'mod_settings',None)
        current=speech_preferences(getattr(settings,'values',{}))
        system.speech_preferences=current
    return current


def clear(system,entity):
    old=system.bubbles.pop(entity,None)
    if old and system.bubble_ui and not system.bubbles:
        system.bubble_ui.clear_message()


def clear_all(system):
    system.bubbles.clear()
    if system.bubble_ui:system.bubble_ui.clear_message()


def apply_preferences(system,values):
    """Accept a complete preference snapshot, including unsaved local preview."""
    current=speech_preferences(values)
    system.speech_preferences=current
    if system.bubble_ui:system.bubble_ui.apply_preferences(current)
    if not current['speech_enabled']:clear_all(system)


def receive(system,args):
    current=preferences(system)
    if not current['speech_enabled']:
        clear_all(system);return False
    entity=args.get('entity')
    if not entity:return False
    clear_all(system)
    message=args.get('message',u'')
    if system.bubble_ui is None:
        system.bubble_ui=api.CreateUI(config.NAMESPACE,'speech',{
            'isHud':1,'bindEntityId':entity,'bindOffset':HEAD_OFFSET,'autoScale':0,
            'speech':message,'speech_preferences':current})
    else:
        system.bubble_ui.apply_preferences(current)
        system.bubble_ui.bind_speech_actor(entity)
    if not system.bubble_ui:return False
    system.bubble_ui.show_message(message)
    system.bubbles[entity]=(entity,system.ticks+max(135,len(system.bubble_ui.pages)*105))
    return True


def tick(system):
    if not preferences(system)['speech_enabled']:
        if system.bubbles:clear_all(system)
        return
    for entity,(unused,until) in list(system.bubbles.items()):
        if system.ticks>=until:clear(system,entity)
    if system.bubbles and system.bubble_ui:system.bubble_ui.update_message()
