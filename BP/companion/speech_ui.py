# -*- coding: utf-8 -*-
import mod.client.extraClientApi as api
from .speech_layout import pages, HEAD_OFFSET, bubble_scale, bubble_position, speech_preferences

Screen=api.GetScreenNodeCls()
Factory=api.GetEngineCompFactory()


class SpeechBubble(Screen):
    def __init__(self,namespace,name,params):
        Screen.__init__(self,namespace,name,params)
        self.ready=False;self.message=params.get('speech',u'')
        self.pages=[self.message];self.age=0;self.page=-1
        self.entity=params.get('bindEntityId');self.layout=None;self.visible=None
        self.preferences=speech_preferences(params.get('speech_preferences'))
        self.active=False

    def Create(self):
        self.ready=True
        for path in ('/bubble','/bubble/background','/bubble/words'):
            self.GetBaseUIControl(path).SetTouchEnable(False)
        # Native binding projects the entity's world anchor every frame. Only
        # the panel's bottom tip is attached there; its body grows upward.
        panel=self.GetBaseUIControl('/bubble')
        panel.SetAnchorFrom('center');panel.SetAnchorTo('bottom_middle')
        panel.SetPosition((0,-41))
        self.ChangeBindOffset(HEAD_OFFSET);self.ChangeBindAutoScale(0)
        self.show_message(self.message)

    def bind_speech_actor(self,entity):
        self.entity=entity;self.layout=None;self.visible=None
        self.ChangeBindEntityId(entity);self.ChangeBindOffset(HEAD_OFFSET)

    def clear_message(self):
        self.active=False;self.message=u'';self.pages=[u''];self.page=-1;self.layout=None
        if self.ready:self.SetScreenVisible(False)
        self.visible=False

    def apply_preferences(self,values):
        preferences=speech_preferences(values)
        if preferences==self.preferences:return
        self.preferences=preferences;self.layout=None
        if not preferences['speech_enabled']:
            self.clear_message()
        elif self.active and self.ready:
            # Reposition immediately without restarting the current message/page.
            self.update_message(False)

    def show_message(self,message):
        if not self.preferences['speech_enabled']:
            self.clear_message();return False
        self.message=message
        self.pages=pages(message);self.age=0;self.page=-1;self.layout=None;self.visible=None
        self.active=True
        if not self.ready:return
        self.update_message()

    def update_message(self,advance=True):
        if not self.ready or not self.active or not self.preferences['speech_enabled']:return
        page=min(len(self.pages)-1,self.age//105)
        if advance:self.age+=1
        camera=Factory.CreateCamera(api.GetLevelId())
        foot=Factory.CreatePos(self.entity).GetFootPos() if self.entity else None
        scale=bubble_scale(foot,camera.GetPosition(),camera.GetForward())
        visible=scale is not None
        if visible!=self.visible:self.SetScreenVisible(visible);self.visible=visible
        if not visible:return
        offset_x=self.preferences['speech_offset_x'];offset_y=self.preferences['speech_offset_y']
        layout=(page,scale,offset_x,offset_y)
        if layout==self.layout:return
        self.layout=layout;self.page=page
        width,height=156*scale,78*scale
        panel=self.GetBaseUIControl('/bubble')
        panel.SetSize((width,height),True)
        # SetPosition is the resolved top-left in the fixed 156x78 bound root.
        # Native entity binding anchors the ROOT CENTRE (78,39). Keep the tip
        # two units above that point, at (78,37), including
        # when native anchor properties have already been resolved.
        panel.SetPosition(bubble_position(scale,offset_x,offset_y))
        self.GetBaseUIControl('/bubble/background').SetSize((width,height))
        label=self.GetBaseUIControl('/bubble/words').asLabel()
        rows=len(self.pages[page].split(u'\n'));height=rows*12*scale
        label.SetAnchorFrom('top_left');label.SetAnchorTo('top_left')
        label.SetSize((132*scale,height));label.SetPosition((12*scale,33*scale-height/2.))
        label.SetTextAlignment('center');label.SetTextFontSize(.4*scale)
        label.SetText(self.pages[page]);self.UpdateScreen()
