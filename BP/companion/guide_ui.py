# -*- coding: utf-8 -*-
"""A real book silhouette, cover, facing pages, chapter ribbons and page turns."""
import time,math
import mod.client.extraClientApi as api
from . import config,guide_content,guide_layout
Screen=api.GetScreenNodeCls()


class CompanionGuide(Screen):
    def __init__(self,namespace,name,params):
        Screen.__init__(self,namespace,name,params)
        self.system=api.GetSystem(config.NAMESPACE,config.CLIENT)
        self.ready=False;self.cover=True;self.page=max(0,min(len(guide_content.SPREADS)-1,getattr(self.system,'guide_page',0)))
        self.flip=None;self.scale=1.;self.screen_size=None;self.callbacks=[]

    def Create(self):
        self.system.guide=self
        for name,handler in [('open',self.open_book),('close',self.close),('shut',self.shut),('previous',self.previous),('next',self.next)]:
            self.bind(name,handler)
        for i in range(len(guide_content.CHAPTERS)):
            handler=self.chapter_handler(i);self.callbacks.append(handler);self.bind('tab_'+str(i),handler)
        self.leaf_controls=[self.GetBaseUIControl('/book/turn/strip_'+str(i)).asImage() for i in range(12)]
        self.leaf_sprite=None
        self.ready=True;self.resize();self.show()

    def bind(self,name,handler):
        control=self.GetBaseUIControl('/book/'+name).asButton()
        control.AddTouchEventParams({'isSwallow':True});control.SetButtonTouchUpCallback(handler)

    def chapter_handler(self,index):
        def handler(args):
            if self.flip:return
            if self.cover:self.page=index;self.open_book()
            else:self.turn_to(index)
        return handler

    def show_control(self,name,value):self.GetBaseUIControl('/book/'+name).SetVisible(bool(value))
    def set_words(self,name,value):self.GetBaseUIControl('/book/'+name).asLabel().SetText(value)

    def resize(self):
        size=tuple(self.GetBaseUIControl('/bounds').GetSize())
        if size==self.screen_size:return
        self.screen_size=size;w,h=guide_layout.CANVAS;self.scale=min(1.5,(size[0]-12.)/w,(size[1]-12.)/h)
        for path,dimensions,position,font in guide_layout.LAYOUT:
            control=self.GetBaseUIControl(path);control.SetSize(tuple(v*self.scale for v in dimensions))
            control.SetPosition(((size[0]-w*self.scale)/2,(size[1]-h*self.scale)/2) if path=='/book' else tuple(v*self.scale for v in position))
            if font is not None:control.asLabel().SetTextFontSize(font*self.scale)
        self.UpdateScreen()

    def page_sprite(self,side,index):
        self.GetBaseUIControl('/book/'+side+'_page').asImage().SetSprite(
            'textures/ui/companion/guide/page_%02d'%index)

    def show(self):
        if not self.ready:return
        cover=self.GetBaseUIControl('/book/cover')
        cover.asImage().SetSprite('textures/ui/companion/guide/cover')
        cover.SetPosition((116*self.scale,8*self.scale));cover.SetSize((224*self.scale,272*self.scale))
        for name in ('cover','open'):self.show_control(name,self.cover)
        for name in ('paper','shut','left_page','right_page'):
            self.show_control(name,not self.cover)
        for i in range(len(guide_content.CHAPTERS)):
            self.show_control('tab_'+str(i),not self.cover)
        self.show_control('turn',False)
        self.page_sprite('left',self.page*2)
        self.page_sprite('right',self.page*2+1)
        self.show_control('previous',not self.cover and self.page>0)
        self.show_control('next',not self.cover and self.page<len(guide_content.SPREADS)-1)
        self.system.guide_page=self.page;self.UpdateScreen()

    def open_book(self,args=None):
        if self.flip:return
        self.cover=False
        # Keep the two-page spread hidden until the cover has landed. The
        # closed-cover control temporarily holds the exposed right-hand page.
        for name in ('open','paper','shut','left_page','right_page','previous','next'):
            self.show_control(name,False)
        for i in range(len(guide_content.CHAPTERS)):self.show_control('tab_'+str(i),False)
        self.GetBaseUIControl('/book/cover').asImage().SetSprite(
            'textures/ui/companion/guide/open_right_%02d'%self.page)
        self.leaf_sprite=None
        self.flip={'kind':'open','start':time.time(),'duration':.72,'frame':None}
        self.tick()

    def shut(self,args=None):
        self.flip=None;self.cover=True;self.show()

    def previous(self,args=None):self.turn_to(self.page-1)
    def next(self,args=None):self.turn_to(self.page+1)

    def turn_to(self,index):
        if self.cover or self.flip or index==self.page or not 0<=index<len(guide_content.SPREADS):return
        self.leaf_sprite=None
        forward=index>self.page
        self.flip={'kind':'page','target':index,'source':self.page,'forward':forward,
                   'start':time.time(),'duration':.72,'frame':None,'midpoint':False}
        # The exposed paper is already the destination. Only the turning leaf
        # carries the outgoing illustration, so text never pops over a blank card.
        self.page_sprite('right' if forward else 'left',index*2+(1 if forward else 0))
        self.tick()

    def tick(self):
        if not self.ready:return
        self.resize()
        if not self.flip:return
        flip=self.flip
        progress=max(0.,(time.time()-flip['start'])/flip['duration'])
        if progress>=1.:
            if flip['kind']=='page':self.page=flip['target']
            self.flip=None;self.show();return
        if flip['kind']=='open':
            # A full 180-degree opening. Both faces and the exposed page share
            # one moving hinge; the final hinge matches the open book's spine.
            eased=progress*progress*(3.-2.*progress)
            hinge=116.+114.*eased
            base=self.GetBaseUIControl('/book/cover')
            base.SetPosition((hinge*self.scale,8*self.scale))
            base.SetSize((224*self.scale,272*self.scale))
            if progress<.5:sprite='cover';side='r';phase=progress*2.
            else:sprite='open_left_%02d'%self.page;side='l';phase=(1.-progress)*2.
            flip['frame']=sprite
            self.draw_leaf(sprite,side,phase,True,hinge)
            return
        else:
            forward=flip['forward']
            if progress>=.5 and not flip['midpoint']:
                flip['midpoint']=True;self.page=flip['target']
                # Keep the old stationary page underneath until the leaf lands.
                # Replacing it here would reveal a duplicate destination page.
            if progress<.5:
                number=flip['source']*2+(1 if forward else 0)
                side='r' if forward else 'l';phase=progress*2
            else:
                number=flip['target']*2+(0 if forward else 1)
                side='l' if forward else 'r';phase=(1-progress)*2
            sprite='page_%02d'%number
        flip['frame']=sprite
        self.draw_leaf(sprite,side,phase)

    def draw_leaf(self,sprite,side,phase,opening=False,hinge=None):
        w,h=(224.,272.) if opening else (204.,246.)
        if hinge is None:hinge=230.
        y=8. if opening else 20.
        theta=phase*math.pi*.5
        width=max(1.,w*math.cos(theta));bend=math.sin(theta)
        # Both faces rotate about the same spine; the inner paper margin also
        # projects horizontally, so it closes at the edge-on midpoint.
        inner=0. if opening else 6.*math.cos(theta)
        x=hinge+inner if side=='r' else hinge-inner-width
        changed=self.leaf_sprite!=sprite
        self.leaf_sprite=sprite
        for i,control in enumerate(self.leaf_controls):
            if changed:
                control.SetSprite('textures/ui/companion/guide/'+sprite)
                control.SetSpriteUV((w*2*i/12.,0.))
                control.SetSpriteUVSize((w*2/12.,h*2))
            q=(i+.5)/12.;q=q if side=='r' else 1-q
            lift=0. if opening else bend*9*q*q
            control.SetPosition(((x+width*i/12.)*self.scale,(y+lift)*self.scale))
            control.SetSize(((width/12.+.45)*self.scale,(h-lift*1.4)*self.scale))
            shade=1.-.20*bend*q
            control.SetSpriteColor((shade,shade,shade))
        shadow=self.GetBaseUIControl('/book/turn/shadow')
        shadow.SetPosition(((x+4*bend)*self.scale,(y+4*bend)*self.scale))
        shadow.SetSize(((width+3*bend)*self.scale,h*self.scale))
        shadow.SetAlpha(.25+.5*bend)
        self.show_control('turn',True);self.UpdateScreen()

    def close(self,args=None):
        self.flip=None
        if api.GetTopUINode() is self:api.PopScreen()

    def Destroy(self):
        self.ready=False;self.flip=None
        self.system.guide_page=self.page
        if self.system.guide is self:self.system.guide=None
