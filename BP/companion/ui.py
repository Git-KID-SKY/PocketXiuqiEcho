# -*- coding: utf-8 -*-
import math
import mod.client.extraClientApi as api
from . import config, domain, mining_filter
from .client import outfit_queries
from .ui_layout import LAYOUT, CANVAS, PAGE_LAYOUTS, BAG_SCROLL_PATH, BAG_SCROLL_LAYOUT
from .wardrobe_ui import WardrobeCarousel, PreviewTurn
from .accessory_previews import WORN_LIMITS, BALLOON_PREVIEW_BOUNDS, BODY_PREVIEW_BOUNDS

Screen = api.GetScreenNodeCls()


class CompanionPanel(Screen):
    CATEGORIES=('hat','glasses','backpack','waist','charm')
    BALLOON_MODEL_TO_UI=2.5
    BALLOON_SIDE_MARGIN=3.
    BALLOON_PROJECTION_Z=1.
    def Create(self):
        self.ready=False
        self.system=api.GetSystem(config.NAMESPACE,config.CLIENT)
        self.system.panel=self
        self.page='outfit' if (self.system.data or {}).get('context')=='wardrobe' else 'bag'
        self.selected=None;self.preview_outfit=None;self.callbacks=[];self.preview_key=None
        self.outfit_category='hat';self.outfit_page=0
        self.bag_content_path=None;self.bag_scroll_state=None;self.bag_scroll_offset=0.
        self.drag=None;self.slot_addresses={};self.mouse_scale=(1,1);self.item_cache={}
        self.reserve_picker=False;self.work_choice=None;self.transition=None
        self.ui_scale=1.;self.ui_size=None;self.ui_layout_page=None
        self.wardrobe=WardrobeCarousel(self)
        self.preview_turn=PreviewTurn(self)
        self.resize_layout()
        actions={'close':self.close,'guide':self.system.open_guide,'tab_bag':self.show_bag,'tab_outfit':self.show_outfit,'tab_settings':self.show_settings,
                 'follow':self.follow,'wait':self.wait,'release':self.release,
                 'bag/take':self.take,'bag/offer':self.offer,'bag/accept':self.accept,'bag/cancel':self.cancel,
                 'bag/equip':self.equip,'bag/sort':self.sort_bag,'tab_tasks':self.show_tasks,'tab_work':self.show_work,'tasks/unequip':self.unequip,
                 'tasks/unequip_off':self.unequip_off,'tasks/guard':self.guard,
                 'tab_supply':self.show_supply,'supply/mode':self.supply_mode,'supply/food':self.food_choice,
                 'supply/threshold':self.threshold,'supply/interval':self.interval,'supply/tool':self.tool_prompt,
                 'supply/reserve':self.reserve,'supply/clear':self.clear_reserve,
                 'tasks/mine':self.mine,'tasks/melee':self.melee,'tasks/bow':self.bow,'tasks/cancel':self.cancel_task,
                 'tasks/reselect':self.reselect_mine,
                 'outfit/apply':self.apply_outfit,'outfit/reset':self.reset_outfit,'preview/appearance':self.appearance,'outfit/rotate':self.rotate_outfit,
                 'outfit/previous':self.outfit_previous,'outfit/next':self.outfit_next,
                 'settings/wear':self.wear,'settings/random':self.random_carry,'tasks/active':self.active_work,
                 'settings/hug':self.hug,'settings/hold':self.hold,'settings/hand':self.hand,
                 'settings/default':self.default_style,'settings/q':self.q_style,
                 'settings/fall':self.toggle_fall,'settings/food':self.toggle_food,
                 'settings/particles':self.toggle_particles,'settings/reset':self.reset_settings,'deploy':self.deploy,
                 'settings/choose_block':self.open_block_picker,'settings/sample':self.open_block_picker,
                 'settings/clear_sample':self.clear_sample,'block_picker/back':self.show_settings,
                 'home/active':self.active_work,'home/food':self.toggle_food,'home/tool':self.tool_prompt,
                 'home/particles':self.toggle_particles,'home/random':self.random_carry,
                 'home/actions':self.show_settings,'home/wardrobe':self.show_outfit,'home/more':self.show_work}
        for path,handler in actions.items():self.button('/window/'+path,handler)
        self.bind_drag('/window/preview/equip_main',{'area':'equipment','slot':'main'})
        self.bind_drag('/window/preview/equip_off',{'area':'equipment','slot':'off'})
        self.sync_bag_scroll()
        for i in range(36):self.bind_slot('/window/bag/player_'+str(i),i,True)
        for i in range(36):self.bind_slot('/window/block_picker/player_'+str(i),i,True)
        for mode in config.WORK_MODES:
            handler=self.work_handler(mode);self.callbacks.append(handler)
            self.button('/window/work/'+mode,handler);self.button('/window/home/mode_'+mode,handler)
        self.GetBaseUIControl('/drag').SetTouchEnable(False)
        for category in self.CATEGORIES:
            handler=self.category_handler(category);self.callbacks.append(handler);self.button('/window/outfit/'+category,handler)
        swipe=self.GetBaseUIControl('/window/outfit/stage/swipe').asButton()
        swipe.AddTouchEventParams({'isSwallow':True})
        swipe.SetButtonTouchDownCallback(self.outfit_down);swipe.SetButtonTouchMoveCallback(self.outfit_move)
        swipe.SetButtonTouchUpCallback(self.outfit_up);swipe.SetButtonTouchCancelCallback(self.outfit_cancel)
        turn=self.GetBaseUIControl('/window/preview/turn').asButton()
        turn.AddTouchEventParams({'isSwallow':True})
        turn.SetButtonTouchDownCallback(self.preview_turn.down);turn.SetButtonTouchMoveCallback(self.preview_turn.move)
        turn.SetButtonTouchUpCallback(self.preview_turn.up);turn.SetButtonTouchCancelCallback(self.preview_turn.cancel)
        self.GetBaseUIControl('/window/preview/model').SetTouchEnable(False)
        for path in ('wardrobe_notice/model','stage/cards/left','stage/cards/center','stage/cards/right'):
            self.GetBaseUIControl('/window/outfit/'+path).SetTouchEnable(False)
        self.ready=True
        if self.system.data:self.refresh(self.system.data)

    def layout_page(self):
        return self.page if self.page in ('bag','outfit') else 'other'

    def authored_layout(self):
        if not getattr(self,'_authored_layouts',None):
            self._authored_layouts={}
            for page,overrides in PAGE_LAYOUTS.items():
                layout={path:(size,offset,font) for path,size,offset,font in LAYOUT}
                layout.update({path:(size,offset,font) for path,size,offset,font in overrides})
                self._authored_layouts[page]=layout
        return self._authored_layouts[self.layout_page()]

    def authored_control(self,path):
        return self.authored_layout()[path]

    def resize_layout(self):
        bounds=self.GetBaseUIControl('/bounds')
        if bounds is None:
            if getattr(self,'ready',False):self.retire_panel()
            return
        width,height=bounds.GetSize()
        page=self.layout_page()
        if width<=0 or height<=0:return
        if self.ui_size==(width,height) and getattr(self,'ui_layout_page',None)==page:return
        had_drag=self.drag is not None
        if had_drag:self.cancel_drag()
        self.transition=None;self.mouse_scale=(1,1)
        self.wardrobe.swipe=None;self.wardrobe.slide=None
        self.preview_turn.gesture=None
        # Fixed screen proportions also compensate for Minecraft's GUI scale.
        scale=min(width*.94/CANVAS[0],height*.92/CANVAS[1])
        if getattr(self,'bag_scroll_state',None):
            scroll=self.GetBaseUIControl(BAG_SCROLL_PATH).asScrollView()
            self.bag_scroll_offset=scroll.GetScrollViewPos()/max(.01,self.ui_scale)
        self.ui_scale=scale;self.ui_size=(width,height);self.ui_layout_page=page
        # Always start from the authored layout, never rescale current children.
        self.apply_layout(self.authored_layout())
        self.sync_bag_scroll()
        self.GetBaseUIControl('/window').SetPosition(((width-CANVAS[0]*scale)/2,(height-CANVAS[1]*scale)/2))
        self.UpdateScreen()
        if self.ready and self.system.data:
            self.wardrobe.refresh(self.system.data)
            self.render_preview(self.system.data['record'])
            self.refresh_home(self.system.data)
        if had_drag and self.ready and self.system.data:self.refresh(self.system.data)

    def apply_layout(self,layout):
        scale=self.ui_scale
        for path,(size,offset,font) in layout.items():
            control=self.GetBaseUIControl(path)
            actual_size=[v*scale for v in size];position=[v*scale for v in offset]
            if font is not None:
                # Native CJK glyphs lose strokes below their original pixel size.
                # Keep a complete line box when GUI scale shrinks the canvas.
                hint=path in ('/window/message','/window/preview/hint')
                line_height=5. if path.endswith('/count') else 7. if hint else 10.
                actual_size[1]=max(line_height,actual_size[1])
                if path.endswith('/text'):
                    parent=layout[path.rsplit('/',1)[0]][0]
                    position[1]=(parent[1]*scale-actual_size[1])/2.
            # The native scrolling template owns internal viewport/rail children
            # outside LAYOUT; resize them too, then author its content separately.
            control.SetSize(tuple(actual_size),path==BAG_SCROLL_PATH)
            # Native scrolling owns the content root's translation. A runtime
            # SetPosition override pins the contents while its scrollbar moves.
            if path!=getattr(self,'bag_content_path',None):control.SetPosition(tuple(position))
            if font is not None:
                minimum=.5 if path.endswith('/count') else 1.
                # These two secondary hints use a stable smaller pixel size;
                # multiplying by GUI scale again would make CJK unreadable.
                text_scale=.7 if hint else max(minimum,font*scale)
                control.asLabel().SetTextFontSize(text_scale)
                if hint:control.SetAlpha(.5)

    def sync_bag_scroll(self):
        scroll=self.GetBaseUIControl(BAG_SCROLL_PATH).asScrollView()
        content=scroll.GetScrollViewContentPath()
        if not content:return False
        content=content.rstrip('/')
        old=getattr(self,'bag_scroll_state',None)
        old_content,old_scale,unused_rows=old or (None,0.,0)
        changed=content!=getattr(self,'bag_content_path',None)
        count=len((self.system.data or {}).get('record',{}).get('inventory',[]))
        rows=max(3,(count+8)//9)
        state=(content,self.ui_scale,rows)
        if old_content==content and old_scale==self.ui_scale:
            self.bag_scroll_offset=scroll.GetScrollViewPos()/max(.01,old_scale)
        if changed:
            self.cancel_drag()
            for path,address in list(self.slot_addresses.items()):
                if address['area']=='bag':self.slot_addresses.pop(path,None)
            self.bag_content_path=content
            for i in range(54):self.bind_slot(content+'/comp_'+str(i),i,False)
        if state!=old:
            layout={content+path:(size,offset,font) for path,size,offset,font in BAG_SCROLL_LAYOUT}
            size,offset,font=layout[content]
            height=rows*20-2
            layout[content]=((size[0],height),offset,font)
            self.apply_layout(layout)
            self.bag_scroll_state=state
            viewport=self.GetBaseUIControl(self.bag_viewport_path())
            maximum=max(0.,height*self.ui_scale-viewport.GetSize()[1])
            scroll.SetScrollViewPos(min(maximum,max(0.,self.bag_scroll_offset*self.ui_scale)))
        return changed

    def bag_viewport_path(self):
        return self.bag_content_path.rsplit('/scrolling_content',1)[0]

    def bag_slot_path(self,index):
        return self.bag_content_path+'/comp_'+str(index)

    def button(self,path,handler):
        control=self.GetBaseUIControl(path).asButton()
        control.AddTouchEventParams({'isSwallow':True})
        control.SetButtonTouchUpCallback(handler)

    def bind_slot(self,path,index,player):
        self.bind_drag(path,{'area':'player' if player else 'bag','slot':index})

    def bind_drag(self,path,address):
        self.slot_addresses[path]=address
        control=self.GetBaseUIControl(path).asButton()
        control.AddTouchEventParams({'isSwallow':True,'slot_path':path})
        control.SetButtonTouchDownCallback(self.drag_down)
        control.SetButtonTouchMoveCallback(self.drag_move)
        control.SetButtonTouchUpCallback(self.drag_up)
        control.SetButtonTouchCancelCallback(self.drag_up)

    def slot_path(self,args):
        path=args.get('AddTouchEventParams',{}).get('slot_path',args.get('ButtonPath',''))
        return next((p for p in self.slot_addresses if path.endswith(p)),None)

    def slot_item(self,address):
        data=self.system.data;area=address['area'];slot=address['slot']
        values=data.get('player_items',[]) if area=='player' else data['record']['inventory'] if area=='bag' else data['record']['equipment']
        if area!='equipment' and not 0<=slot<len(values):return None
        return values[slot]

    def drag_down(self,args):
        if self.system.pending or not self.system.data:return
        self.sync_bag_scroll()
        path=self.slot_path(args)
        if path is None:return
        address=self.slot_addresses[path]
        if address['area']=='bag':
            point=(args.get('TouchPosX',0),args.get('TouchPosY',0))
            if not self.bag_point_visible(point) or address['slot']>=len(self.system.data['record']['inventory']):return
        self.cancel_drag()
        point=(args.get('TouchPosX',0),args.get('TouchPosY',0))
        factory=api.GetEngineCompFactory();raw=factory.CreateActorMotion(self.system.player).GetMousePosition()
        if raw:
            pixels=factory.CreateGame(api.GetLevelId()).GetScreenSize()
            factors=[(1,1),(self.ui_size[0]/float(pixels[0]),self.ui_size[1]/float(pixels[1]))]
            self.mouse_scale=min(factors,key=lambda f:sum((raw[i]*f[i]-point[i])**2 for i in (0,1)))
        self.drag={'path':path,'source':dict(self.slot_addresses[path]),'item':domain.clone(self.slot_item(self.slot_addresses[path])),
            'start':point,'point':point,'active':False,'view':self.system.data.get('inventory_view'),
            'revision':self.system.data['record']['revision']}

    def drag_move(self,args):
        if not self.drag:return
        point=(args.get('TouchPosX',self.drag['point'][0]),args.get('TouchPosY',self.drag['point'][1]))
        self.move_cursor(point)

    def move_cursor(self,point):
        drag=self.drag
        if not drag or self.page not in ('bag','settings') or domain.empty(drag['item']):return
        drag['point']=point
        if not drag['active'] and sum((point[i]-drag['start'][i])**2 for i in (0,1))<(4*self.ui_scale)**2:return
        starting=not drag['active'];drag['active']=True
        item=drag['item'];ghost=self.GetBaseUIControl('/drag')
        ghost.SetPosition((point[0]+4*self.ui_scale,point[1]+4*self.ui_scale));ghost.SetVisible(True)
        if starting:
            self.GetBaseUIControl('/drag/item').asItemRenderer().SetUiItem(domain.native_value(domain.item_name(item)),
                item.get('newAuxValue',0),bool(item.get('enchantData')),domain.native_value(item.get('userData') or {}))
        self.GetBaseUIControl('/drag/count').asLabel().SetText(str(item['count']))
        self.GetBaseUIControl(drag['path']+'/item').SetVisible(False)

    def update_drag(self):
        if not getattr(self,'ready',False):return
        self.resize_layout()
        if not self.ready:return
        if self.sync_bag_scroll() and self.ready and self.system.data:self.refresh(self.system.data)
        self.wardrobe.tick()
        self.preview_turn.tick()
        if self.transition:
            path,start=self.transition;t=min(1,(self.system.ticks-start)/8.0)
            unused,offset,unused_font=self.authored_control(path)
            self.GetBaseUIControl(path).SetPosition((offset[0]*self.ui_scale,(offset[1]+18*(1-t)**3)*self.ui_scale))
            if t>=1:self.transition=None
        if not self.drag:return
        raw=api.GetEngineCompFactory().CreateActorMotion(self.system.player).GetMousePosition()
        if raw:self.move_cursor(tuple(raw[i]*self.mouse_scale[i] for i in (0,1)))

    def drop_path(self,point):
        if self.page!='bag':return None
        self.sync_bag_scroll()
        for path,address in self.slot_addresses.items():
            if '/block_picker/' in path:continue
            if address['area']=='bag':
                if address['slot']>=len(self.system.data['record']['inventory']) or not self.bag_point_visible(point):continue
            control=self.GetBaseUIControl(path);x,y=control.GetGlobalPosition();w,h=control.GetSize()
            if x<=point[0]<x+w and y<=point[1]<y+h:return path
        return None

    def bag_point_visible(self,point):
        if not self.bag_content_path:return False
        control=self.GetBaseUIControl(self.bag_viewport_path())
        x,y=control.GetGlobalPosition();w,h=control.GetSize()
        return x<=point[0]<x+w and y<=point[1]<y+h

    def drag_up(self,args):
        self.sync_bag_scroll()
        if not self.drag:return
        self.drag_move(args);drag=self.drag;self.drag=None
        self.GetBaseUIControl('/drag').SetVisible(False)
        destination=self.drop_path(drag['point'])
        if drag['active']:
            if destination and destination!=drag['path']:
                self.selected=None
                address=self.slot_addresses[destination]
                if address['area']=='sample':
                    self.system.send('set_mine_sample',source=drag['source'],inventory_view=drag['view'],revision=drag['revision'])
                else:self.system.send('move_item',source=drag['source'],destination=address,
                    inventory_view=drag['view'],revision=drag['revision'])
        elif self.slot_path(args)==drag['path'] and args.get('TouchEvent')!=3:
            area=drag['source']['area'];slot=drag['source']['slot']
            if area=='equipment':self.equip_slot(slot)
            elif area=='player':
                if not domain.empty(drag['item']):
                    if self.page=='block_picker':self.system.send('set_mine_sample',source=drag['source'],inventory_view=drag['view'],revision=drag['revision'])
                    else:self.system.send('transfer',direction='deposit',slot=slot,inventory_view=drag['view'],revision=drag['revision'])
            else:
                self.selected=slot
                if self.reserve_picker:
                    self.reserve_picker=False;self.system.send('reserve',slot=slot);self.page='supply'
        self.refresh(self.system.data)

    def cancel_drag(self):
        self.drag=None
        ghost=self.GetBaseUIControl('/drag')
        if ghost:ghost.SetVisible(False)

    def label(self,path,text):
        path=path if path.startswith('/') else '/window/'+path
        control=self.GetBaseUIControl(path)
        if control is not None:control.asLabel().SetText(text)

    def set_visible(self,path,value):
        self.GetBaseUIControl('/window/'+path).SetVisible(value)

    def set_message(self,text):
        self.label('message',text)

    def selected_button(self,path,selected):
        path=path if path.startswith('/') else '/window/'+path
        slot=any(part in path for part in ('/comp_','/player_','/equip_main','/equip_off')) or path.endswith('/settings/sample')
        base='item_slot' if slot else ('primary' if selected else 'neutral')
        for state in ('default','hover','pressed','locked'):
            texture_state='hover' if slot and selected and state=='default' else state
            self.GetBaseUIControl(path+'/'+state).asImage().SetSprite(
                'textures/ui/companion/ore/'+base+'_'+texture_state)

    def draw_item(self,path,item):
        path=path if '/' in path else 'bag/'+path
        path=path if path.startswith('/') else '/window/'+path
        base=self.GetBaseUIControl(path+'/item')
        occupied=not domain.empty(item)
        # SetUiItem('minecraft:air') returns False and leaves the previous mesh.
        # Explicit visibility prevents stale icons after an item is moved away.
        base.SetVisible(occupied)
        if not occupied:
            self.label(path+'/count','');return
        control=base.asItemRenderer()
        name=domain.item_name(item)
        key=(name,item.get('newAuxValue',item.get('auxValue',0)),bool(item.get('enchantData')),item.get('userData') or {})
        if self.item_cache.get(path)!=key:
            control.SetUiItem(domain.native_value(key[0]),key[1],key[2],domain.native_value(key[3]))
            self.item_cache[path]=domain.clone(key)
        self.label(path+'/count',str(item['count']))

    def preview_fit(self,outfit,appearance,base_scale):
        bounds=[WORN_LIMITS.get(value,{}).get(appearance,(20.3,12.)) for value in outfit.values()]
        scale=base_scale*min(1.,24./max(v[0] for v in bounds),16./max(v[1] for v in bounds))
        balloon=outfit.get('backpack')
        if balloon not in BALLOON_PREVIEW_BOUNDS:return scale,0.
        theta=math.radians(self.preview_turn.angle-180.)
        cosine=math.cos(theta);sine=math.sin(theta)*self.BALLOON_PROJECTION_Z
        projected=[]
        for lower,upper in (BODY_PREVIEW_BOUNDS[appearance],BALLOON_PREVIEW_BOUNDS[balloon][appearance]):
            for x in (lower[0],upper[0]):
                for z in (lower[2],upper[2]):projected.append(x*cosine+z*sine)
        # Preserve room for hats and every other worn accessory as well. Their
        # existing width metadata describes a centered silhouette, not a side arm.
        other_width=max(WORN_LIMITS.get(value,{}).get(appearance,(20.3,12.))[1]
                        for value in outfit.values() if value!=balloon)
        left=min(min(projected),-other_width/2.);right=max(max(projected),other_width/2.)
        size,unused,unused_font=self.authored_control('/window/preview/model')
        available=max(1.,size[0]-2*self.BALLOON_SIDE_MARGIN)
        scale=min(scale,available/(max(1.,right-left)*self.BALLOON_MODEL_TO_UI))
        center=(left+right)/2.
        return scale,-center*scale*self.BALLOON_MODEL_TO_UI

    def render_preview(self,record):
        outfit=self.preview_outfit if self.preview_outfit is not None else record['outfit']
        appearance=record['settings'].get('appearance','original')
        base_scale=2.2 if self.page=='outfit' else 1.55
        scale,shift=self.preview_fit(outfit,appearance,base_scale)
        unused,offset,unused_font=self.authored_control('/window/preview/model')
        self.GetBaseUIControl('/window/preview/model').SetPosition(
            ((offset[0]+shift)*self.ui_scale,(offset[1]+(base_scale-scale)*50)*self.ui_scale))
        key=(tuple(sorted(outfit.items())),appearance,self.preview_turn.angle,base_scale,self.ui_scale,scale)
        if key==self.preview_key:return
        self.preview_key=key
        molang={'variable.ec_preview_'+key:float(value) for key,value in outfit_queries(outfit).items()}
        molang['variable.ec_preview_appearance']=1.0 if appearance=='xiuqi' else 0.0
        molang['variable.ec_preview_shield']=0.;molang['variable.ec_preview_offer']=0.
        # Identifier rendering is a UI-only preview, not a spawned world entity.
        preview=self.GetBaseUIControl('/window/preview/model').asNeteasePaperDoll()
        preview.RenderEntity({'entity_identifier':'echo:companion_preview','scale':scale,'render_depth':-40,
                              'init_rot_y':self.preview_turn.angle,'init_rot_x':0,'molang_dict':molang})

    def refresh_home(self,data):
        record=data['record'];settings=record['settings']
        mode=settings.get('work_mode','follow')
        for key in config.WORK_MODES:self.selected_button('home/mode_'+key,key==mode)
        for path,key,default in (
                ('active','active_work',False),('food','food_prompt',True),
                ('tool','tool_prompt',True),('particles','particles',True),
                ('random','random_carry',True)):
            enabled=settings.get(key,default)
            self.selected_button('home/'+path,enabled)
            self.label('home/'+path+'/text',u'开' if enabled else u'关')
        self.label('home/name_hint',u'')
        self.set_visible('home/name_hint',False)
        health=data.get('health') or {}
        current=health.get('current',record.get('health'))
        maximum=health.get('maximum',record.get('health_max'))
        try:current=float(current)
        except (TypeError,ValueError):current=None
        try:maximum=float(maximum)
        except (TypeError,ValueError):maximum=None
        if current is not None and not 0<=current<float('inf'):current=None
        if maximum is not None and not 0<maximum<float('inf'):maximum=None
        self.label('home/health_text',u'%s / %s'%(
            u'%g'%current if current is not None else u'--',u'%g'%maximum if maximum is not None else u'--'))
        ratio=min(1.,current/maximum) if current is not None and maximum is not None else 0.
        size,unused,unused_font=self.authored_control('/window/home/health_fill')
        fill=self.GetBaseUIControl('/window/home/health_fill')
        fill.SetSize((size[0]*ratio*self.ui_scale,size[1]*self.ui_scale),False)
        fill.SetVisible(ratio>0)

    def selected_item_caption(self,title,count):
        size,unused,font=self.authored_control('/window/bag/selected')
        # This narrow column is two short lines, not a full-width inventory tip.
        # Nine UI units conservatively fit one CJK glyph at the native pixel size.
        limit=max(1,int(size[0]*self.ui_scale/(9*max(1.,font*self.ui_scale))))
        if not isinstance(title,domain.text_type):title=title.decode('utf-8','replace')
        if len(title)>limit:title=title[:max(0,limit-1)]+u'…'
        return title+u'\n× '+str(count)

    def refresh(self,data):
        # Snapshots can arrive while PushScreen is creating or removing controls.
        # Create() redraws the latest stored snapshot once the panel is ready.
        if not data or not getattr(self,'ready',False):return
        if self.GetBaseUIControl('/window/state') is None:self.retire_panel();return
        self.resize_layout()
        if not self.ready:return
        record=data['record'];settings=record['settings'];state=record['state']
        self.label('title',u'小跟班')
        if self.drag and record['revision']!=self.drag['revision']:self.cancel_drag()
        self.label('state',config.STATE_NAMES.get(state,u'陪着你'))
        if settings['mode']=='hand' and state=='following':self.label('state',u'已松手，跟随中')
        used=sum(not domain.empty(v) for v in record['inventory'])
        from .interaction_rules import capacity
        self.label('bag/title',u'随行背包  %d / %d'%(used,capacity(record)))
        self.sync_bag_scroll()
        if self.bag_content_path:
            for index in range(54):
                path=self.bag_slot_path(index);available=index<len(record['inventory'])
                item=record['inventory'][index] if available else None
                control=self.GetBaseUIControl(path)
                control.SetVisible(available)
                # Empty cells allow the native scroll gesture to reach the viewport.
                # Filled cells keep the existing direct item drag interaction.
                control.SetTouchEnable(available and not domain.empty(item))
                self.draw_item(path,item)
                self.selected_button(path,self.selected==index)
        for i,item in enumerate(data.get('player_items',[])[:36]):self.draw_item('player_'+str(i),item)
        for i,item in enumerate(data.get('player_items',[])[:36]):self.draw_item('block_picker/player_'+str(i),item)
        sample=mining_filter.item(settings.get('mine_sample'))
        self.draw_item('settings/sample',sample)
        self.label('settings/sample_name',self.item_title(sample) if sample else u'未设置采掘目标')
        for hand in ('main','off'):
            item=record.get('equipment',{}).get(hand);path='preview/equip_'+hand
            self.draw_item(path,item)
            self.label(path+'/count','')
        self.set_visible('bag/empty',used==0)
        if self.selected is not None and self.selected>=len(record['inventory']):self.selected=None
        selected=record['inventory'][self.selected] if self.selected is not None else None
        text=u'拖动换位\n放入装备'
        if self.selected is not None and self.selected>=27 and not record.get('worn'):text=u'扩展背包\n仅可取出'
        if not domain.empty(selected):
            info=api.GetEngineCompFactory().CreateItem(api.GetLevelId()).GetItemBasicInfo(domain.native_value(domain.item_name(selected)),selected.get('newAuxValue',selected.get('auxValue',0)))
            text=self.selected_item_caption((info or {}).get('itemName',u'已选中物品'),selected['count'])
        self.label('bag/selected',text)
        if self.reserve_picker:self.label('bag/selected',u'选择备用\n点击物品')
        offering=data.get('offering') is not None
        self.set_visible('bag/accept',offering);self.set_visible('bag/cancel',offering)
        self.set_visible('bag/offer',not offering);self.set_visible('bag/take',not offering)
        self.set_visible('release',state=='hand_in_hand');self.set_visible('follow',state!='hand_in_hand')
        deployed=record['form']=='deployed'
        self.set_visible('recall_hint',deployed);self.set_visible('deploy',not deployed)
        for path,value in [('hug','hug'),('hold','hold'),('hand','hand')]:
            title=config.MODE_NAMES[value]
            self.selected_button('settings/'+path,settings['mode']==value)
            self.label('settings/'+path+'/text',(u'✓ ' if settings['mode']==value else '')+title)
        self.label('settings/wear/text',u'取下背包' if record.get('worn') else u'背在身后')
        self.label('settings/random/text',u'随机携带：'+(u'开' if settings.get('random_carry',True) else u'关'))
        self.selected_button('settings/random',settings.get('random_carry',True))
        self.label('tasks/active/text',u'停止主动协助' if settings.get('active_work') else u'开启主动协助（按工具工作）')
        for path,title in [('default',u'原作动画'),('q',u'Q版动画')]:
            self.selected_button('settings/'+path,settings['style']==path)
            self.label('settings/'+path+'/text',(u'✓ ' if settings['style']==path else '')+title)
        for path,key,title in [('fall','fall_reaction',u'下落反应'),('food','food_prompt',u'食物补给'),('particles','particles',u'轻量特效')]:
            self.selected_button('settings/'+path,settings[key])
            self.label('settings/'+path+'/text',title+u'：'+(u'开' if settings[key] else u'关'))
        if self.system.ticks<self.system.message_until:self.set_message(self.system.last_message)
        elif data.get('pending_style'):self.set_message(u'当前动作结束后切换。')
        elif not self.system.pending:self.set_message(u'拖动交换或叠加；移出格子取消。' if self.page=='bag' else u'')
        self.wardrobe.refresh(data)
        self.refresh_home(data)
        self.set_visible('home',self.page=='bag')
        self.set_visible('bag',self.page=='bag');self.set_visible('outfit',self.page=='outfit');self.set_visible('settings',self.page=='settings')
        self.set_visible('tasks',self.page=='tasks')
        self.set_visible('work',self.page=='work')
        self.set_visible('supply',self.page=='supply')
        self.set_visible('block_picker',self.page=='block_picker');self.set_visible('preview',self.page!='block_picker')
        for page in ('bag','outfit','settings','tasks','supply','work'):
            self.selected_button('tab_'+page,self.page==page)
            self.set_visible('tab_'+page,self.page!='bag')
        mode=settings.get('work_mode','follow')
        self.label('work/current',u'当前：'+config.WORK_MODES.get(mode,u'跟随陪伴'))
        self.label('work/hint',u'关面板后工作；条件不足时点击查看原因。')
        reasons=data.get('work_reasons',{})
        problem=reasons.get(self.work_choice,u'') if self.work_choice else u''
        self.label('work/status',problem or (self.system.last_message if self.system.ticks<self.system.message_until else data.get('work_status',u'')) or config.WORK_HINTS.get(mode,u''))
        for key in config.WORK_MODES:
            self.selected_button('work/'+key,key==mode)
            reason=reasons.get(key,u'')
            if not reason:short=u'可使用'
            elif u'放到' in reason:short=u'先放到身边'
            elif u'样本' in reason:short=u'需设置目标方块'
            elif u'空格' in reason:short=u'需留 4 个空格'
            elif u'没有箭' in reason:short=u'背包中需要箭'
            elif key in ('aggressive','protect','hunt'):short=u'需装备武器或盾' if key=='protect' else u'需装备剑、斧或弓'
            else:short=u'工具不符，点查看'
            self.label('work/'+key+'_reason',short)
        rows=[]
        for key,title in [('main',u'主手'),('off',u'副手')]:
            equipped=record.get('equipment',{}).get(key)
            text=title+u'：'+self.item_title(equipped)
            if not domain.empty(equipped) and equipped.get('durability',0)>0:text+=u' · 耐久 '+str(equipped['durability'])
            rows.append(text)
        self.label('tasks/equipment',u'\n'.join(rows))
        text=u'目标：'+self.item_title(sample)+u'\n自动寻找附近可到达的同类方块' if sample else u'自动选择工具可采资源\n样本可选：只采指定方块'
        self.label('tasks/target',text)
        self.label('supply/mode/text',u'食物：'+config.SUPPLY_MODES[settings['supply_mode']])
        self.label('supply/food/text',u'偏好：'+config.FOOD_CHOICES[settings['food_choice']])
        self.label('supply/threshold/text',u'饱食度低于 '+str(settings['hunger_threshold']))
        self.label('supply/status',data.get('supply_status',u''))
        self.label('supply/interval/text',u'间隔：%d 秒'%settings['supply_interval'])
        self.label('supply/tool/text',u'工具提醒：'+(u'开' if settings['tool_prompt'] else u'关'))
        self.selected_button('supply/mode',settings['supply_mode']!='off')
        self.selected_button('supply/tool',settings['tool_prompt'])
        backup=settings.get('backup_slot')
        reserved=record['inventory'][backup] if type(backup) is int and 0<=backup<len(record['inventory']) else None
        self.label('supply/reserved',u'备用工具：未指定' if backup is None else u'备用格 %d：%s'%(backup+1,self.item_title(reserved)))
        self.render_preview(record)
        if self.drag and self.drag['active']:self.move_cursor(self.drag['point'])

    def item_title(self,item):
        if domain.empty(item):return u'未装备 / 空格'
        info=api.GetEngineCompFactory().CreateItem(api.GetLevelId()).GetItemBasicInfo(domain.native_value(domain.item_name(item))) or {}
        return info.get('itemName',domain.item_name(item))

    def page_to(self,page):
        self.cancel_drag()
        self.preview_turn.gesture=None
        if page!='bag':self.reserve_picker=False
        if self.transition:
            path,start=self.transition
            unused,offset,unused_font=self.authored_control(path)
            self.GetBaseUIControl(path).SetPosition(tuple(v*self.ui_scale for v in offset));self.transition=None
        if self.page=='outfit' and page!='outfit':self.wardrobe.reset()
        self.page=page;self.refresh(self.system.data)
        if page in ('bag','block_picker'):
            self.transition=('/window/'+page,self.system.ticks)
            self.update_drag()

    def cycle_handler(self,category):
        def callback(args):
            if not self.outfit_editable():return
            if self.preview_outfit is None:self.preview_outfit=dict(self.system.data['record']['outfit'])
            items=config.ACCESSORIES[category]
            self.preview_outfit[category]=items[(items.index(self.preview_outfit[category])+1)%len(items)]
            self.refresh(self.system.data)
        return callback

    def category_handler(self,category):
        def choose(args):
            self.wardrobe.category(category)
        return choose

    def choose_handler(self,index):
        def choose(args):
            self.wardrobe.choose(index)
        return choose

    def outfit_previous(self,args):self.wardrobe.choose(self.wardrobe.index-1,-1)
    def outfit_next(self,args):self.wardrobe.choose(self.wardrobe.index+1,1)
    def rotate_outfit(self,args):self.wardrobe.turn(args)
    def outfit_down(self,args):self.wardrobe.down(args)
    def outfit_move(self,args):self.wardrobe.move(args)
    def outfit_up(self,args):self.wardrobe.up(args)
    def outfit_cancel(self,args):self.wardrobe.cancel(args)
    def wear(self,args):self.system.send('wear',value=not self.system.data['record'].get('worn',False))
    def random_carry(self,args):self.system.send('option',key='random_carry',value=not self.system.data['record']['settings'].get('random_carry',True))
    def active_work(self,args):self.system.send('active_work',value=not self.system.data['record']['settings'].get('active_work',False))

    def apply_outfit(self,args):
        if not self.outfit_editable():return
        if self.preview_outfit is None:return
        # Submit the whole outfit as one revision-checked action.
        self.system.send('outfit_all',value=dict(self.preview_outfit))

    def appearance(self,args):
        if not self.outfit_editable():return
        current=self.system.data['record']['settings'].get('appearance','original')
        self.system.send('option',key='appearance',value='xiuqi' if current=='original' else 'original')

    def reset_outfit(self,args):
        self.wardrobe.defaults()

    def outfit_editable(self):
        if (self.system.data or {}).get('context')=='wardrobe':return True
        self.set_message(u'请在衣柜中更换外观和饰品。');return False

    def take(self,args):
        if self.selected is not None:self.system.send('transfer',direction='withdraw',slot=self.selected)
        else:self.set_message(u'先点上方伙伴背包的一格，再点「取出」。')

    def offer(self,args):
        if self.selected is not None:self.system.send('offer',slot=self.selected)

    def accept(self,args):self.system.send('accept')
    def cancel(self,args):self.system.send('cancel_offer')
    def equip(self,args):
        if self.selected is not None:self.system.send('equip',slot=self.selected)
        else:self.set_message(u'先选中伙伴背包里的工具、武器、盾牌或盔甲。')
    def equip_slot(self,hand):
        selected=self.system.data['record']['inventory'][self.selected] if self.selected is not None else None
        if not domain.empty(selected):self.system.send('equip',slot=self.selected,hand=hand)
        else:self.system.send('unequip',hand=hand)
        self.selected=None
    def equip_main(self,args):self.equip_slot('main')
    def equip_off(self,args):self.equip_slot('off')
    def unequip(self,args):self.system.send('unequip')
    def unequip_off(self,args):self.system.send('unequip',hand='off')
    def guard(self,args):self.system.send('task',kind='guard')
    def sort_bag(self,args):self.selected=None;self.system.send('sort')
    def cycle_option(self,key,values):
        current=self.system.data['record']['settings'][key]
        self.system.send('option',key=key,value=values[(values.index(current)+1)%len(values)])
    def supply_mode(self,args):self.cycle_option('supply_mode',('off','prompt','auto','drop'))
    def food_choice(self,args):self.cycle_option('food_choice',('bread','cooked','fruit','any'))
    def threshold(self,args):self.cycle_option('hunger_threshold',(8,12,16,20))
    def interval(self,args):self.cycle_option('supply_interval',(15,30,60))
    def tool_prompt(self,args):self.system.send('option',key='tool_prompt',value=not self.system.data['record']['settings']['tool_prompt'])
    def reserve(self,args):
        self.reserve_picker=True;self.selected=None;self.page_to('bag')
    def clear_reserve(self,args):self.system.send('reserve',slot=None)
    def mine(self,args):self.system.send('work_mode',value='excavate')
    def reselect_mine(self,args):
        self.page_to('settings')
    def clear_sample(self,args):self.system.send('set_mine_sample',source=None)
    def open_block_picker(self,args):self.page_to('block_picker')
    def melee(self,args):self.system.send('task',kind='melee')
    def bow(self,args):self.system.send('task',kind='bow')
    def cancel_task(self,args):self.system.send('cancel_task')
    def follow(self,args):self.system.send('follow')
    def wait(self,args):self.system.send('wait')
    def release(self,args):self.system.send('release')
    def deploy(self,args):self.system.send('deploy')
    def hug(self,args):self.system.send('mode',value='hug')
    def hold(self,args):self.system.send('mode',value='hold')
    def hand(self,args):self.system.send('mode',value='hand')
    def default_style(self,args):self.system.send('option',key='style',value='default')
    def q_style(self,args):self.system.send('option',key='style',value='q')
    def toggle_fall(self,args):self.system.send('option',key='fall_reaction',value=not self.system.data['record']['settings']['fall_reaction'])
    def toggle_food(self,args):self.system.send('option',key='food_prompt',value=not self.system.data['record']['settings']['food_prompt'])
    def toggle_particles(self,args):self.system.send('option',key='particles',value=not self.system.data['record']['settings']['particles'])
    def reset_settings(self,args):self.system.send('reset')
    def show_bag(self,args):self.page_to('bag')
    def show_outfit(self,args):self.page_to('outfit')
    def show_settings(self,args):self.page_to('settings')
    def show_tasks(self,args):self.page_to('tasks')
    def show_work(self,args):self.page_to('work')
    def work_handler(self,mode):
        def choose(args):
            self.work_choice=mode
            reason=self.system.data.get('work_reasons',{}).get(mode)
            if reason:self.system.notice({'message':reason});self.refresh(self.system.data);return
            self.system.send('work_mode',value=mode)
        return choose
    def show_supply(self,args):self.page_to('supply')
    def close(self,args):self.system.close()

    def retire_panel(self):
        self.drag=None
        self.ready=False
        self.transition=None
        if getattr(self,'wardrobe',None):self.wardrobe.swipe=None;self.wardrobe.slide=None
        if getattr(self,'preview_turn',None):self.preview_turn.gesture=None
        system=getattr(self,'system',None)
        if system and getattr(system,'panel',None) is self:
            system.panel=None;system.close_requested=False;system.pending=False

    def Destroy(self):
        system=getattr(self,'system',None)
        owned=system and getattr(system,'panel',None) is self
        self.retire_panel()
        if owned:system.send('close')
