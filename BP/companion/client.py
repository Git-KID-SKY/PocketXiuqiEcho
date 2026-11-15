# -*- coding: utf-8 -*-
from __future__ import division
import math
import random
import traceback
import uuid
import mod.client.extraClientApi as api
from . import config, domain, accessories, joined_hand
from .effects import VisualEffects
from .held_position import FIRST_PERSON, THIRD_PERSON, FIRST_PERSON_BOUNCE
from .item_display import ItemDisplay
from .animation_timing import DURATIONS
from .locomotion import Gait, is_teleport, continuous_angle
from .footsteps import Footsteps
from .gaze import Gaze
from . import guide_pose
from .carry_render import render_scale as carry_render_scale

Factory = api.GetEngineCompFactory()
Base = api.GetClientSystemCls()
QUERIES = {'active':1,'style':0,'phase':0,'speed':0,'walk':0,'run':0,'air':0,'vy':0,'land':0,
    'fall':0,'blink':0,'blink_time':0,'hug':0,'hand':0,'action':0,'action_time':0,'role':0,'dead':0,
    'fidget':0,'fidget_time':0,'offer':0,'hat':0,'glasses':0,'backpack':1,'waist':0,'charm':0,
    'third':1,'held':0,'slim':0,'item':0,'item_shape':0,'bow_stage':0,'shield':0,'hand_reach':-135,'hand_lean':0,'hand_arm':13,
    'hand_x':0,'hand_y':0,'hand_z':0,'hand_yaw':0,'held_phase':0,'held_motion':0,'tp_scale':.5,
    'join_hidden':0,'worn':0,'carry_scale':1.,'inspect':0,'inspect_time':0,'armor_head':0,'armor_chest':0,'armor_legs':0,'armor_feet':0,
    'tp_x':0,'tp_y':12,'tp_z':0,'tp_rx':0,'tp_ry':0,'tp_rz':0,'look_pitch':0,'look_yaw':0,'appearance':0,'swim':0}
for _axis,_value in zip('xyz',FIRST_PERSON['position']):QUERIES['fp_'+_axis]=_value
for _prefix,_pose in (('guide_fp_',guide_pose.FIRST),('guide_tp_',guide_pose.THIRD)):
    for _axis,_value in zip('xyz',_pose['position']):QUERIES[_prefix+_axis]=_value
    for _axis,_value in zip('xyz',_pose['rotation']):QUERIES[_prefix+'r'+_axis]=_value
    QUERIES[_prefix+'scale']=_pose['scale']
for _axis,_value in zip('xyz',FIRST_PERSON['rotation']):QUERIES['fp_r'+_axis]=_value
QUERIES['fp_scale']=FIRST_PERSON['scale']
for _axis,_value in zip('xyz',FIRST_PERSON.get('body_position',(0,0,0))):QUERIES['fp_body_'+_axis]=_value
for _axis,_value in zip('xyz',FIRST_PERSON.get('body_rotation',(0,180,0))):QUERIES['fp_body_r'+_axis]=_value
for _mode,_prefix in (('hold','tp_'),('hug','hug_')):
    for _axis,_value in zip('xyz',THIRD_PERSON[_mode]['position']):QUERIES[_prefix+_axis]=_value
    for _axis,_value in zip('xyz',THIRD_PERSON[_mode]['rotation']):QUERIES[_prefix+'r'+_axis]=_value
    QUERIES[_prefix+'scale']=THIRD_PERSON[_mode]['scale']
    for _axis,_value in zip('xyz',THIRD_PERSON[_mode].get('body_position',(0,0,0))):QUERIES[_prefix+'body_'+_axis]=_value
    for _axis,_value in zip('xyz',THIRD_PERSON[_mode].get('body_rotation',(0,0,0))):QUERIES[_prefix+'body_r'+_axis]=_value


def outfit_queries(outfit):
    return {key:int(value[1:]) if value!='none' else 0 for key,value in outfit.items()}


class CompanionClient(Base):
    def __init__(self, namespace, name):
        Base.__init__(self, namespace, name)
        self.level=api.GetLevelId();self.player=api.GetLocalPlayerId()
        self.token=None;self.ticks=0;self.ui_ready=False;self.panel=None;self.close_requested=False;self.use_started=None;self.use_target=None
        self.data=None;self.pending=False;self.pending_tick=0;self.actors={};self.entities=set();self.registered=set();self.skin_ready=set()
        self.last_message=u'';self.message_until=0;self.bubbles={};self.bubble_ui=None
        self.guide=None;self.guide_page=0
        self.visuals=VisualEffects(self)
        self.accessories_ready=False
        self.joined_ready=set()
        self.item_models={}
        self.item_display=ItemDisplay(self.level)
        from .mod_settings import ModSettings
        self.mod_settings=ModSettings(self)
        from .wardrobe_client import WardrobeView
        self.wardrobes=WardrobeView(self)
        self.events=[]
        for event,handler in [('UiInitFinished',self.ui_init),('OnLocalPlayerStopLoading',self.loaded),
            ('PushScreenEvent',self.settings_screen_pushed),
            ('OnScriptTickClient',self.tick),('GameRenderTickEvent',self.render_hands),('OnKeyPressInGame',self.key),
            ('AddEntityClientEvent',self.entity_added),('RemoveEntityClientEvent',self.entity_removed),
            ('AddPlayerCreatedClientEvent',self.player_created),
            ('DimensionChangeClientEvent',self.dimension_change),
            ('HoldBeforeClientEvent',self.long_press),('RightClickBeforeClientEvent',self.use_down),('TapBeforeClientEvent',self.tap_companion),
            ('RightClickReleaseClientEvent',self.use_up),('TapOrHoldReleaseClientEvent',self.use_up)]:
            self.ListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),event,self,handler)
            self.events.append((api.GetEngineNamespace(),api.GetEngineSystemName(),event,handler))
        for event,handler in [('Welcome',self.welcome),('Snapshot',self.snapshot),('Notice',self.notice),
            ('Close',self.close),('Effect',self.effect),('Speech',self.speech),('SampleSelected',self.sample_selected),('Sound',self.sound),('Preferences',self.sync),('Wardrobes',self.wardrobe_sync)]:
            self.ListenForEvent(config.NAMESPACE,config.SERVER,event,self,handler)
            self.events.append((config.NAMESPACE,config.SERVER,event,handler))

    def sync(self,data):self.mod_settings.sync(data);self.pending=False
    def settings_screen_pushed(self,args):self.mod_settings.screen_pushed(args)
    def wardrobe_sync(self,data):self.wardrobes.sync(data)

    def ui_init(self, args=None):
        self.mod_settings.register()
        from .creative_catalog import register
        register()
        if not self.accessories_ready:self.accessories_ready=accessories.install()
        if self.ui_ready:return
        api.RegisterUI(config.NAMESPACE,'panel','companion.ui.CompanionPanel','echo_companion.main')
        api.RegisterUI(config.NAMESPACE,'speech','companion.speech_ui.SpeechBubble','echo_companion.speech')
        api.RegisterUI(config.NAMESPACE,'guide','companion.guide_ui.CompanionGuide','echo_guide.main')
        self.ui_ready=True

    def tap_companion(self,args):
        if self.panel:return
        pick=Factory.CreateCamera(self.level).PickFacing() or {}
        entity=pick.get('entityId')
        if pick.get('type')!='Entity' or entity not in self.entities:return
        value=Factory.CreateModAttr(entity).GetAttr('echo_companion_visual',{}) or {}
        if value.get('hand_owner')!=self.player:return
        args['cancel']=True;self.send('interact',entity=entity)

    def sample_selected(self,args):
        if self.panel and self.panel.page=='block_picker':self.panel.page_to('settings')

    def sound(self,args):
        if args.get('name')!='echo.companion.deploy':return
        Factory.CreateCustomAudio(self.level).PlayCustomMusic(args['name'],tuple(args['position']),1.0,1.0,False,None)

    def speech(self,args):
        from .speech_client import receive
        receive(self,args)

    def clear_bubble(self,entity):
        from .speech_client import clear
        clear(self,entity)

    def holding_doll(self):
        item=Factory.CreateItem(self.player).GetPlayerItem(api.GetMinecraftEnum().ItemPosType.CARRIED,0,False)
        return domain.item_name(item)==config.ITEM

    def holding_guide(self):
        from .guide_content import ITEM
        return domain.item_name(Factory.CreateItem(self.player).GetPlayerItem(api.GetMinecraftEnum().ItemPosType.CARRIED,0,False))==ITEM

    def open_guide(self,args=None):
        if self.ui_ready and self.guide is None:self.guide=api.PushScreen(config.NAMESPACE,'guide',{})

    def long_press(self,args):
        if self.holding_guide():args['cancel']=True;self.open_guide();return
        if self.panel or not (self.holding_doll() or self.open_worn_gesture()):return
        args['cancel']=True;self.use_started=None;self.use_target=None;self.send('open')

    def open_worn_gesture(self):
        comp=Factory.CreateItem(self.player);pos=api.GetMinecraftEnum().ItemPosType
        return (domain.empty(comp.GetPlayerItem(pos.CARRIED,0,False)) and
            domain.item_name(comp.GetPlayerItem(pos.ARMOR,1,False)) in (config.ITEM,config.WEARABLE) and Factory.CreatePlayer(self.player).isSneaking())

    def use_down(self,args):
        if self.guide:return
        if self.holding_guide():args['cancel']=True;self.open_guide();return
        if not self.panel:
            pick=Factory.CreateCamera(self.level).PickFacing() or {}
            if pick.get('type')=='Entity' and pick.get('entityId') in self.entities:
                args['cancel']=True;self.send('interact',entity=pick['entityId']);return
            if self.open_worn_gesture():args['cancel']=True;self.send('open');return
            if pick.get('type') not in ('Block','Entity') and Factory.CreatePlayer(self.player).isSneaking():
                item=Factory.CreateItem(self.player).GetPlayerItem(api.GetMinecraftEnum().ItemPosType.CARRIED,0,False)
                if domain.empty(item) and Factory.CreateNeteaseWindow(self.level).OpenSettingUI():
                    args['cancel']=True
                    return
        if self.panel or not self.holding_doll():return
        args['cancel']=True
        if self.use_started is None:
            self.use_started=self.ticks
            pick=Factory.CreateCamera(self.level).PickFacing() or {}
            self.use_target={key:pick[key] for key in ('x','y','z','face') if key in pick} if pick.get('type')=='Block' else None

    def use_up(self,args):
        started,target=self.use_started,self.use_target
        self.use_started=None;self.use_target=None
        if started is None or self.panel or not self.holding_doll():return
        if self.ticks-started>=14:self.send('open')
        elif target:self.send('place',target=target)

    def loaded(self,args=None):
        self.skin_ready.add(self.player)
        self.NotifyToServer('Hello',{'playerId':self.player})

    def welcome(self,args):
        self.token=args.get('token')
        for entity in args.get('entities',[]):self.entities.add(entity)

    def send(self, action, **values):
        if not self.token:
            self.loaded();return
        if self.pending and action not in ('close','heartbeat'):return
        data={'playerId':self.player,'token':self.token,'action':action}
        if self.data:
            record=self.data['record'];data.update({'id':record['companion_id'],'revision':record['revision']})
        data.update(values)
        if action not in ('open','close','heartbeat'):
            self.last_message=u'';self.message_until=0
            data['op']=uuid.uuid4().hex
            self.pending=True;self.pending_tick=self.ticks
            if self.panel:self.panel.set_message(u'正在保存…')
        self.NotifyToServer('Request',data)

    def snapshot(self,args):
        self.pending=False;self.data=args
        entity=args['record'].get('entity_id')
        if entity:self.entities.add(entity)
        if args.get('opening') and self.ui_ready and self.panel is None:
            # Create() is asynchronous; the ScreenNode takes ownership when ready.
            self.panel=api.PushScreen(config.NAMESPACE,'panel',{})
        elif self.panel:self.panel.refresh(args)

    def notice(self,args):
        self.pending=False
        message=args.get('message',u'')
        self.last_message=message;self.message_until=self.ticks+300
        Factory.CreateGame(self.level).SetTipMessage(domain.native_value(message))
        if self.panel:self.panel.set_message(message)

    def close(self,args=None):
        # PopScreen closes the actual top screen, which may be a native bag or
        # another menu opened over this one. Wait until our panel is on top.
        if self.panel and api.GetTopUINode() is not self.panel:
            self.close_requested=True;self.send('close');return
        self.close_requested=False
        panel=self.panel;self.panel=None
        self.pending=False
        self.send('close')
        if panel:api.PopScreen()

    def key(self,args):
        if args.get('key')=='80' and str(args.get('isDown'))=='1' and not self.panel:
            if args.get('screenName') in ('hud_screen','hud','in_game_play_screen'):self.send('open')

    def entity_added(self,args):
        if args.get('engineTypeStr')==config.ENTITY:self.entities.add(args['id'])

    def player_created(self,args):
        entity=args.get('playerId')
        if entity:
            # Render additions persist across skin-load notifications. Repeating
            # RebuildPlayerRender here can force another unnecessary load.
            self.skin_ready.add(entity)

    def entity_removed(self,args):
        self.clear_bubble(args.get('id'))
        entity=args.get('id');self.clear_item(entity);self.entities.discard(entity);self.actors.pop(entity,None)
        self.registered.discard(entity);self.skin_ready.discard(entity);self.visuals.cancel_owner(entity)
        self.joined_ready.discard(entity)

    def dimension_change(self,args):
        if args.get('playerId')!=self.player:return
        self.wardrobes.entries.clear()
        if self.guide:self.guide.close()
        self.close();self.visuals.clear()
        for entity in list(self.bubbles):self.clear_bubble(entity)
        for entity in list(self.item_models):self.clear_item(entity)
        for entity in list(self.actors):self.clear_pose(entity)
        self.actors.clear();self.entities.clear();self.registered.clear()
        self.loaded()

    def effect(self,args):
        try:self.visuals.play(args)
        except Exception:traceback.print_exc()

    def register(self, entity, player=False):
        query=Factory.CreateQueryVariable(entity)
        for key,value in QUERIES.items():
            name='query.mod.ec_'+key
            query.Register(name,float(value))
            # Register does not replace an existing value after a render reload.
            if key.startswith('fp_') or key in ('hand_arm','hand_reach'):query.Set(name,float(value))
        if player and entity not in self.registered:
            render=Factory.CreateActorRender(entity)
            joined_hand.install_player_poses(render)
            render.RebuildPlayerRender()
            self.registered.add(entity)
        self.actors[entity]={'query':query,'fall':domain.FallReaction(),'gait':Gait(),'footsteps':Footsteps(),'gaze':Gaze(),'look_until':0,'phase':0,'last_pos':None,
            'blink_time':0,'next_blink':self.ticks+random.randint(70,170),'style':0,'hug':0,'hand':0,'land':0,'air':False,
            'next_fidget':self.ticks+random.randint(240,450),'fidget_start':None,'fidget_role':None,
            'action_clock':None,'action_received':self.ticks,'held_phase':0,'held_motion':0}
        return self.actors[entity]

    def clear_pose(self, entity):
        state=self.actors.get(entity)
        if state:
            for key in ('hug','hand','held','worn','inspect','armor_head','armor_chest','armor_legs','armor_feet','fall','land','blink','fidget','dead','hand_x','hand_y','hand_z','hand_yaw','look_pitch','look_yaw','join_hidden','join_visible'):
                state['query'].Set('query.mod.ec_'+key,0)
            state['query'].Set('query.mod.ec_carry_scale',1.)
            if state.pop('shadow_hidden',False):Factory.CreateModel(entity).SetEntityShadowShow(True)

    def clear_item(self,entity):
        self.item_models.pop(entity,None)
        if entity in self.actors:self.actors[entity]['query'].Set('query.mod.ec_item',0)

    def sync_item(self,entity,item,bow_stage=-1):
        old=self.item_models.get(entity)
        display=None
        if not domain.empty(item):
            display={'newItemName':domain.item_name(item),'newAuxValue':item.get('newAuxValue',item.get('auxValue',0)),
                     'isEnchanted':bool(item.get('enchantData') or item.get('modEnchantData')),'userData':{},'bow_stage':bow_stage}
        if old and old['item']==display:return
        if old:self.clear_item(entity)
        if display:
            index,shape=self.item_display.resolve(item,bow_stage)
            self.item_models[entity]={'id':index,'item':display}
            self.actors[entity]['query'].Set('query.mod.ec_item',index)
            self.actors[entity]['query'].Set('query.mod.ec_item_shape',shape)
            self.actors[entity]['query'].Set('query.mod.ec_bow_stage',max(0,min(3,bow_stage+1)))

    def update_actor(self, entity, is_player):
        if is_player and entity not in self.skin_ready:return
        value=Factory.CreateModAttr(entity).GetAttr('echo_companion_visual',{}) or {}
        if not value.get('active') and entity not in self.actors:return
        state=self.actors.get(entity) or self.register(entity,is_player)
        if not is_player:
            elapsed=value.get('action_elapsed',0)
            if (value.get('action_stamp',0),elapsed)==state['action_clock']:
                elapsed+=(self.ticks-state['action_received'])/30.0
            stage=(-1 if value.get('action')!=7 or elapsed<.12 or elapsed>=1.16667 else
                   (0 if elapsed<.5 else 1 if elapsed<.9 else 2))
            self.sync_item(entity,value.get('display_item') if value.get('active') else None,stage)
        query=state['query'];active=value.get('active',False)
        state['hand_owner']=value.get('hand_owner') if not is_player and active and value.get('hand') else None
        settings=value.get('settings',{})
        if not is_player:
            appearance=settings.get('appearance','original')
            if state.get('native_appearance')!=appearance:
                render=Factory.CreateActorRender(self.level)
                geometry='geometry.echo.xiuqi' if appearance=='xiuqi' else 'geometry.echo.companion'
                layers_ready=state.get('native_layers') or accessories.bind_entity(entity,state.setdefault('native_layer_controllers',set()))
                if layers_ready and render.AddGeometryToOneActor(entity,'default',geometry) and Factory.CreateActorRender(entity).RebuildRenderForOneActor():
                    state['native_layers']=True
                    state['native_appearance']=appearance
        pos=Factory.CreatePos(entity).GetFootPos()
        if pos is None:return
        grounded=Factory.CreateAttr(entity).isEntityOnGround()
        previous=state['last_pos'];state['last_pos']=pos
        delta=[pos[i]-previous[i] for i in range(3)] if previous else [0,0,0]
        if state.get('hand_owner'):
            owner_pos=Factory.CreatePos(state['hand_owner']).GetFootPos()
            previous_owner=state.get('hand_last_owner');state['hand_last_owner']=owner_pos
            # Authoritative companion teleports and small turns are not strides.
            delta=[owner_pos[i]-previous_owner[i] for i in range(3)] if owner_pos and previous_owner else [0,0,0]
            grounded=Factory.CreateAttr(state['hand_owner']).isEntityOnGround()
        else:state.pop('hand_last_owner',None)
        moved=math.hypot(delta[0],delta[2])
        # A teleport is not an animation step or a fall.
        motion=Factory.CreateActorMotion(entity).GetMotion()
        teleported=is_teleport(delta,motion)
        if teleported:
            moved=0;delta=[0,0,0];state['fall'].reset()
        gait=state['gait'];gait.step(moved,teleported)
        speed=gait.speed
        # Render-position samples can repeat between physics ticks. Using their
        # zero delta would repeatedly cancel a real fall before its delay ends.
        vertical=(motion[1]*20 if motion is not None else delta[1]*30) if not grounded else 0
        state['phase']=gait.phase
        blocked=value.get('fall_blocked',False) or any(bool(query.GetMolangValue(key)) for key in ('query.is_in_water','query.is_gliding','query.is_climbing','query.is_riding','query.is_flying'))
        swimming=not is_player and bool(query.GetMolangValue('query.is_in_water'))
        state['swim']=state.get('swim',0)+max(-.12,min(.12,(1 if swimming else 0)-state.get('swim',0)))
        carrying=active and value.get('held',False)
        if is_player:
            # Local held check removes an overlay on the very next tick, ahead of network updates.
            current=Factory.CreateItem(entity).GetPlayerItem(api.GetMinecraftEnum().ItemPosType.CARRIED,0,False)
            carrying=carrying and domain.item_name(current)==config.ITEM
            offhand=Factory.CreateItem(entity).GetPlayerItem(api.GetMinecraftEnum().ItemPosType.OFFHAND,0,False)
            occupied=not domain.empty(offhand) or bool(query.GetMolangValue('query.is_using_item')) or (query.GetMolangValue('query.attack_time') or 0)>.01 or value.get('busy',False)
        else:occupied=False
        eligible=carrying and settings.get('fall_reaction',True) and not blocked if is_player else (active and not blocked)
        fall,landing=state['fall'].step(1/30,vertical,grounded,eligible)
        if state['air'] and grounded:state['land']=1
        else:state['land']=max(0,state['land']-1/10.5)
        state['air']=not grounded
        target_style=1 if settings.get('style')=='q' else 0
        state['style']+=max(-1/6,min(1/6,target_style-state['style']))
        target_hug=1 if carrying and settings.get('last_held','hug')=='hug' and not occupied else 0
        held_moving=carrying and gait.moving
        state['held_motion']+=max(-1/12,min(1/12,(1 if held_moving else 0)-state['held_motion']))
        if held_moving:state['held_phase']=(state['held_phase']+FIRST_PERSON_BOUNCE['frequency']/30)%1
        target_hand=1 if active and value.get('hand',value.get('state')=='hand_in_hand') and not occupied else 0
        inspect_ok=is_player and entity==self.player and Factory.CreatePlayerView(entity).GetPerspective()==0 and carrying and settings.get('inspect_animation',True) and grounded and not occupied and not gait.moving and not self.panel and not value.get('dead')
        carry_key=(value.get('id'),value.get('carry_slot'),carrying)
        if state.get('inspect_key')!=carry_key:
            state['inspect_key']=carry_key;state['inspect_next']=self.ticks+42;state['inspect_start']=None
        if not inspect_ok:
            state['inspect_start']=None;state['inspect_next']=max(state.get('inspect_next',0),self.ticks+60)
        elif state.get('inspect_start') is None and self.ticks>=state.get('inspect_next',0):
            state['inspect_choice']=3-state['inspect_choice'] if state.get('inspect_choice') else random.randint(1,2)
            state['inspect_start']=self.ticks
        inspect_time=(self.ticks-state['inspect_start'])/30.0 if state.get('inspect_start') is not None else 0
        if state.get('inspect_start') is not None and inspect_time>=(3.7 if state['inspect_choice']==1 else 2.66667):
            state['inspect_start']=None;state['inspect_next']=self.ticks+random.randint(360,720)
        for key,target in [('hug',target_hug),('hand',target_hand)]:
            state[key]+=max(-1/5,min(1/5,target-state[key]))
        if self.ticks>=state['next_blink']:
            state['blink_time']=9;state['next_blink']=self.ticks+random.randint(85,190)
        blink=0;blink_time=0
        if state['blink_time']>0:
            blink=1;blink_time=(9-state['blink_time'])/30.0
            state['blink_time']-=1
        action=value.get('action',0);role=value.get('role',0);dead=value.get('dead',False)
        audible=active and not is_player and grounded and not dead and not teleported and gait.moving and gait.walk>.5 and not blocked and action not in (1,4)
        for side in state['footsteps'].step(gait.phase,audible,state['style']>.5,gait.run):
            state['last_step_audio']=Factory.CreateCustomAudio(api.GetLevelId()).PlayCustomMusic(
                'echo.companion.step_'+side,tuple(pos),1.0,1.0,False,None)
        clock=(value.get('action_stamp',0),value.get('action_elapsed',0))
        if clock!=state['action_clock']:
            state['action_clock']=clock;state['action_received']=self.ticks
        action_time=clock[1]+(self.ticks-state['action_received'])/30.0 if action else 0
        idle=active and not is_player and not dead and gait.walk<.01 and grounded and not swimming and not action and not value.get('offering') and state['hand']<.01
        if not idle or state['fidget_role']!=role:
            state['fidget_start']=None;state['next_fidget']=self.ticks+random.randint(240,450);state['fidget_role']=role
        if idle and state['fidget_start'] is None and self.ticks>=state['next_fidget']:state['fidget_start']=self.ticks
        fidget_time=(self.ticks-state['fidget_start'])/30.0 if state['fidget_start'] is not None else 0
        duration=DURATIONS[('fidget','archer_fidget','wizard_fidget')[role]]
        if state['fidget_start'] is not None and fidget_time>=duration:
            state['fidget_start']=None;state['next_fidget']=self.ticks+random.randint(240,450)
        # Authored idle/fidget already contain eyelid keyframes. The separate
        # authored blink is used while walking, in Q style, and on held dolls.
        if idle and settings.get('style')!='q' and settings.get('appearance')!='xiuqi':blink=0
        values={'active':1 if active else 0,'style':state['style'],'phase':state['phase'],
            'speed':speed,'walk':gait.walk,'run':gait.run,'air':0 if grounded else 1,'vy':vertical,'land':landing if is_player else state['land'],
            'fall':fall if is_player else 0,'blink':blink,'blink_time':blink_time,'hug':state['hug'],'hand':state['hand'],'swim':state['swim'],
            'held':1 if carrying else 0,'held_phase':state['held_phase'],'held_motion':state['held_motion'],
            'worn':1 if value.get('worn') else 0,'carry_scale':carry_render_scale(settings,value.get('worn',False),is_player),
            'inspect':state.get('inspect_choice',0) if state.get('inspect_start') is not None else 0,'inspect_time':inspect_time,
            'action':action,'action_time':action_time,'role':role,'dead':1 if dead else 0,
            'fidget':1 if state['fidget_start'] is not None else 0,'fidget_time':fidget_time,
            'offer':value.get('offering',0),'shield':1 if value.get('shield') else 0}
        values['third']=0 if is_player and entity==self.player and Factory.CreatePlayerView(entity).GetPerspective()==0 else 1
        if not is_player:
            enabled=active and not dead and not carrying and not value.get('hand') and grounded and not action and state['fidget_start'] is None
            body_yaw=Factory.CreateRot(value.get('hand_owner') if value.get('hand') else entity).GetBodyRot()
            if enabled and self.ticks>=state['look_until']:
                state['look_until']=self.ticks+random.randint(75,150)
                owner=value.get('hand_owner')
                nearby=Factory.CreateGame(self.level).GetEntitiesAroundByType(entity,5,api.GetMinecraftEnum().EntityType.Mob) or []
                nearby=[v for v in nearby if v!=entity and v!=owner]
                state['look_entity']=owner if random.random()<.65 or not nearby else random.choice(nearby)
                if random.random()<.2:state['look_entity']=None
                state['look_angle']=random.uniform(-28,28)
            target=None
            if enabled:
                look=state.get('look_entity')
                p=Factory.CreatePos(look).GetFootPos() if look else None
                if p and sum((p[i]-pos[i])**2 for i in range(3))<36:
                    target=(p[0],p[1]+(1.5 if look in api.GetPlayerList() else .7),p[2])
                else:
                    angle=math.radians(body_yaw+state.get('look_angle',0))
                    target=(pos[0]-math.sin(angle)*3,pos[1]+.85,pos[2]+math.cos(angle)*3)
            pitch,yaw=state['gaze'].step((pos[0],pos[1]+.85,pos[2]),body_yaw,target,enabled,teleported)
            values.update({'look_pitch':pitch,'look_yaw':yaw})
        if is_player:values['slim']=1 if Factory.CreateActorRender(entity).GetModelStyle()=='slim' else 0
        values.update(outfit_queries(value.get('outfit',{})))
        for slot in ('head','chest','legs','feet'):values['armor_'+slot]=value.get('armor',{}).get(slot,0)
        values['appearance']=1 if settings.get('appearance')=='xiuqi' else 0
        for key,item in values.items():query.Set('query.mod.ec_'+key,float(item))
        state['values']=values
        if is_player and not carrying and not value.get('hand'):
            state['fall'].reset()

    def sync_joined_hands(self):
        visible={}
        for entity,state in self.actors.items():
            owner=state.get('hand_owner')
            if owner and state['hand']>.99 and owner in self.skin_ready:
                if owner==self.player and Factory.CreatePlayerView(owner).GetPerspective()==0:continue
                if owner not in self.joined_ready:
                    if joined_hand.install(owner,QUERIES):self.joined_ready.add(owner)
                if owner in self.joined_ready:visible[owner]=(entity,state)
        for owner in self.joined_ready:
            query=Factory.CreateQueryVariable(owner);entry=visible.get(owner)
            if entry:
                for key,value in entry[1].get('values',{}).items():query.Set('query.mod.ec_join_'+key,float(value))
            query.Set('query.mod.ec_join_visible',1. if entry else 0.)
        hidden=set(entry[0] for entry in visible.values())
        for entity,state in self.actors.items():
            active=entity in hidden
            state['query'].Set('query.mod.ec_join_hidden',1. if active else 0.)
            hand=bool(state.get('hand_owner'))
            if hand!=state.get('shadow_hidden',False):
                Factory.CreateModel(entity).SetEntityShadowShow(not hand)
                state['shadow_hidden']=hand

    def render_hands(self,args=None):
        # Local first-person player layers are suppressed by the native renderer.
        # Anchor the world model to the interpolated camera feet in that view;
        # third-person and other players share the owner's native render matrix.
        first=Factory.CreatePlayerView(self.player).GetPerspective()==0
        for entity,state in self.actors.items():
            query=state['query']
            if not first or state.get('hand_owner')!=self.player or state['hand']<.99:
                for key in ('hand_x','hand_y','hand_z','hand_yaw'):query.Set('query.mod.ec_'+key,0)
                continue
            camera=Factory.CreateCamera(self.level)
            own=camera.GetPosition();pos=Factory.CreateModel(entity).GetBonePositionFromMinecraftObject('ec_hand_anchor')
            if own is None or pos is None:continue
            own=(own[0],own[1]-camera.GetFpHeight(),own[2])
            yaw=Factory.CreateRot(entity).GetBodyRot();owner_yaw=Factory.CreateRot(self.player).GetBodyRot()
            angle=math.radians(owner_yaw)
            target=(own[0]-config.HAND_SIDE*math.cos(angle),own[1],own[2]-config.HAND_SIDE*math.sin(angle))
            dx,dy,dz=[target[i]-pos[i] for i in range(3)]
            angle=math.radians(yaw);c,s=math.cos(angle),math.sin(angle)
            values={'hand_x':(dx*c+dz*s)*16/.66949,'hand_y':dy*16/.66949,
                'hand_z':(dx*s-dz*c)*16/.66949,
                'hand_yaw':continuous_angle(query.Get('query.mod.ec_hand_yaw'),owner_yaw-yaw)}
            for key,value in values.items():query.Set('query.mod.ec_'+key,value)

    def tick(self):
        if self.guide:self.guide.tick()
        self.wardrobes.tick()
        self.mod_settings.tick()
        self.ticks+=1
        from .speech_client import tick as tick_speech
        tick_speech(self)
        if self.use_started is not None:
            if self.panel or not self.holding_doll():self.use_started=None;self.use_target=None
            elif self.ticks-self.use_started>=14:
                self.use_started=None;self.use_target=None;self.send('open')
        if not self.accessories_ready and self.ticks%60==0:
            self.accessories_ready=accessories.install()
        if not self.token and self.ticks%60==0:self.loaded()
        if self.close_requested and self.panel and api.GetTopUINode() is self.panel:self.close()
        if self.panel and not self.close_requested and self.ticks%60==0:self.send('heartbeat')
        if self.panel and getattr(self.panel,'ready',False):self.panel.update_drag()
        if self.pending and self.ticks-self.pending_tick>150:
            self.pending=False
            if self.panel:self.panel.set_message(u'连接有些慢，重新打开面板可核对结果。')
        players=set(api.GetPlayerList())
        for entity in players|self.entities:
            try:self.update_actor(entity,entity in players)
            except Exception:
                if self.ticks%90==0:traceback.print_exc()
        try:self.sync_joined_hands()
        except Exception:
            if self.ticks%90==0:traceback.print_exc()
        try:self.visuals.tick(1/30)
        except Exception:traceback.print_exc()

    def Destroy(self):
        for entity in list(self.bubbles):self.clear_bubble(entity)
        if self.bubble_ui:self.bubble_ui.SetRemove();self.bubble_ui=None
        for entity in list(self.item_models):self.clear_item(entity)
        for entity in list(self.actors):self.clear_pose(entity)
        self.visuals.destroy()
        for namespace,system,event,handler in self.events:self.UnListenForEvent(namespace,system,event,self,handler)
