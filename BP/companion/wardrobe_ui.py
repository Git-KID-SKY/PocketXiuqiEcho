# -*- coding: utf-8 -*-
import mod.client.extraClientApi as api
from . import config
from .accessory_previews import PREVIEW_INDEX


class PreviewTurn(object):
    """Keep the view in Python: RenderEntity recreates the native renderer."""
    def __init__(self,panel):
        # Native paper dolls face the viewer at 180 degrees. Each newly opened
        # panel starts slightly turned toward the viewer; refreshes keep this state.
        self.p=panel;self.angle=160.;self.gesture=None

    def down(self,args):
        point=(args.get('TouchPosX',0),args.get('TouchPosY',0))
        factory=api.GetEngineCompFactory();raw=factory.CreateActorMotion(self.p.system.player).GetMousePosition()
        factor=(1.,1.)
        if raw:
            pixels=factory.CreateGame(api.GetLevelId()).GetScreenSize()
            factors=[factor,(self.p.ui_size[0]/float(pixels[0]),self.p.ui_size[1]/float(pixels[1]))]
            factor=min(factors,key=lambda v:sum((raw[i]*v[i]-point[i])**2 for i in (0,1)))
        self.gesture={'start':point,'angle':self.angle,'factor':factor,'touch':False}

    def point(self,point):
        if not self.gesture:return
        self.angle=(self.gesture['angle']+(point[0]-self.gesture['start'][0])*1.5/max(.01,self.p.ui_scale))%360
        self.p.render_preview(self.p.system.data['record'])

    def move(self,args):
        if not self.gesture:return
        self.gesture['touch']=True
        self.point((args.get('TouchPosX',self.gesture['start'][0]),args.get('TouchPosY',self.gesture['start'][1])))

    def up(self,args):
        if args.get('TouchEvent')!=3:self.move(args)
        self.gesture=None

    def cancel(self,args):self.gesture=None

    def tick(self):
        if self.gesture and not self.gesture['touch']:
            raw=api.GetEngineCompFactory().CreateActorMotion(self.p.system.player).GetMousePosition()
            if raw:self.point(tuple(raw[i]*self.gesture['factor'][i] for i in (0,1)))


class WardrobeCarousel(object):
    def __init__(self,panel):
        self.p=panel;self.index=0;self.cache={};self.renders={}
        self.swipe=None;self.slide=None;self.angle=-25;self.initialized=False

    def control(self,name):return self.p.GetBaseUIControl('/window/outfit/'+name)

    def position_cards(self,offset=0):
        unused,position,unused_font=self.p.authored_control('/window/outfit/stage/cards')
        self.control('stage/cards').SetPosition(
            (position[0]*self.p.ui_scale+offset,position[1]*self.p.ui_scale))

    def reset(self):
        self.swipe=None;self.slide=None;self.initialized=False;self.index=0
        self.p.preview_outfit=None
        self.position_cards()

    def values(self):return config.ACCESSORIES[self.p.outfit_category]

    def refresh(self,data):
        p=self.p;editing=data.get('context')=='wardrobe';record=data['record']
        if not editing:p.preview_outfit=None;self.initialized=False
        p.set_visible('outfit/wardrobe_notice',not editing)
        for name in ('title','category_title','divider','page','stage','previous','next','name','rotate','preview_status','apply','reset')+p.CATEGORIES:
            p.set_visible('outfit/'+name,editing)
        p.set_visible('preview/appearance',editing and p.page=='outfit')
        for name in ('main_label','off_label','equip_main','equip_off'):
            p.set_visible('preview/'+name,not (editing and p.page=='outfit'))
        if not editing:
            if p.page=='outfit' and self.cache.get('cabinet')!=p.ui_scale:
                ok=self.control('wardrobe_notice/model').asNeteasePaperDoll().RenderEntity({
                    'entity_identifier':'echo:wardrobe_display','scale':.9,'render_depth':-40,
                    'init_rot_y':155,'init_rot_x':0,'molang_dict':{'variable.wardrobe_open':0.,'variable.wardrobe_yaw':0.}})
                self.renders['cabinet']=ok
                if ok is not False:self.cache['cabinet']=p.ui_scale
            return
        if p.page!='outfit':return
        if not self.initialized:
            p.preview_outfit=dict(record['outfit']);self.index=0
            p.preview_outfit[p.outfit_category]=self.values()[self.index];self.initialized=True
        values=self.values();self.index=min(self.index,len(values)-1);key=values[self.index]
        p.label('outfit/name',config.ACCESSORY_NAMES[key])
        p.label('outfit/page',u'%d / %d'%(self.index+1,len(values)))
        changed=p.preview_outfit!=record['outfit']
        p.label('outfit/preview_status',u'左右滑动选饰品 · 点穿上保存' if changed else u'当前已穿戴 · 左右滑动选饰品')
        p.label('outfit/apply/text',u'穿上' if changed else u'已穿戴')
        p.label('preview/appearance/text',u'切换外观')
        for category in p.CATEGORIES:p.selected_button('outfit/'+category,category==p.outfit_category)
        if p.page!='outfit':return
        self.control('stage/none').SetVisible(key=='none')
        for name,delta,scale in (('left',-1,.95),('center',0,1.9),('right',1,.95)):
            selected=values[(self.index+delta)%len(values)]
            self.render(name,selected,scale)

    def render(self,name,key,scale):
        control=self.control('stage/cards/'+name);control.SetVisible(key!='none')
        if key=='none':return
        signature=(key,self.angle if name=='center' else -25,scale,self.p.ui_scale)
        if self.cache.get(name)==signature:return
        ok=control.asNeteasePaperDoll().RenderEntity({'entity_identifier':'echo:accessory_preview',
            'scale':scale,'render_depth':-40,'init_rot_y':signature[1],'init_rot_x':-8,
            'molang_dict':{'variable.ec_accessory_index':float(PREVIEW_INDEX[key])}})
        self.renders[name]=ok
        if ok is not False:self.cache[name]=signature

    def choose(self,index,animate=0):
        p=self.p
        if not p.outfit_editable():return
        self.index=index%len(self.values())
        if p.preview_outfit is None:p.preview_outfit=dict(p.system.data['record']['outfit'])
        p.preview_outfit[p.outfit_category]=self.values()[self.index]
        self.initialized=True
        if animate:self.slide=(p.system.ticks,animate*18.)
        p.refresh(p.system.data)

    def category(self,category):
        if not self.p.outfit_editable():return
        self.swipe=None;self.slide=None;self.position_cards();self.p.outfit_category=category
        outfit=self.p.preview_outfit or self.p.system.data['record']['outfit']
        self.choose(self.values().index(outfit[category]))

    def turn(self,args):
        if not self.p.outfit_editable():return
        self.angle=(self.angle+90)%360;self.p.refresh(self.p.system.data)

    def defaults(self):
        if not self.p.outfit_editable():return
        self.p.preview_outfit={key:'none' for key in config.ACCESSORIES};self.p.preview_outfit['backpack']='b01'
        self.choose(self.values().index(self.p.preview_outfit[self.p.outfit_category]))

    def down(self,args):
        if not self.p.outfit_editable():return
        point=(args.get('TouchPosX',0),args.get('TouchPosY',0));f=api.GetEngineCompFactory()
        raw=f.CreateActorMotion(self.p.system.player).GetMousePosition();factor=(1.,1.)
        if raw:
            pixels=f.CreateGame(api.GetLevelId()).GetScreenSize()
            factors=[(1.,1.),(self.p.ui_size[0]/float(pixels[0]),self.p.ui_size[1]/float(pixels[1]))]
            factor=min(factors,key=lambda v:sum((raw[i]*v[i]-point[i])**2 for i in (0,1)))
        self.swipe={'start':point,'point':point,'factor':factor,'touch':False};self.slide=None

    def move(self,args):
        if not self.swipe:return
        self.swipe['touch']=True
        self.update_point((args.get('TouchPosX',self.swipe['point'][0]),args.get('TouchPosY',self.swipe['point'][1])))

    def update_point(self,point):
        if not self.swipe:return
        self.swipe['point']=point;dx=point[0]-self.swipe['start'][0];dy=point[1]-self.swipe['start'][1]
        offset=max(-28*self.p.ui_scale,min(28*self.p.ui_scale,dx*.35)) if abs(dx)>abs(dy) else 0
        self.position_cards(offset)

    def up(self,args):
        if not self.swipe:return
        self.move(args);swipe=self.swipe;self.swipe=None
        self.position_cards()
        dx=swipe['point'][0]-swipe['start'][0];dy=swipe['point'][1]-swipe['start'][1]
        if args.get('TouchEvent')!=3 and abs(dx)>=24*self.p.ui_scale and abs(dx)>abs(dy)*1.25:
            step=1 if dx<0 else -1;self.choose(self.index+step,step)

    def cancel(self,args):
        self.swipe=None;self.position_cards()

    def tick(self):
        if self.swipe and not self.swipe['touch']:
            raw=api.GetEngineCompFactory().CreateActorMotion(self.p.system.player).GetMousePosition()
            if raw:self.update_point(tuple(raw[i]*self.swipe['factor'][i] for i in (0,1)))
        if self.slide:
            start,distance=self.slide;t=min(1.,(self.p.system.ticks-start)/6.)
            self.position_cards(distance*(1-t)**3*self.p.ui_scale)
            if t>=1:self.slide=None
