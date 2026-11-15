# -*- coding: utf-8 -*-
"""Native menu > Mod settings, with server-authoritative saved values."""
import mod.client.extraClientApi as api
from . import config,domain,interaction_rules as rules
LABELS={'auto_eat':u'伙伴自己吃东西回血','food_prompt':u'缺食物时递给我',
    'tool_prompt':u'工具、武器、盔甲损坏时递备用品','block_supply':u'方块用完时递补给',
    'particles':u'轻量粒子效果','fall_reaction':u'手持下落反应',
    'inspect_animation':u'第一人称检视小动作','random_carry':u'切换快捷栏时随机普通手持／抱着',
    'hunt_animals':u'主动战斗时狩猎普通动物（不攻击已驯养生物）',
    'speech_enabled':u'显示小跟班对话气泡'}
SLIDERS=(('carry_scale',u'背负大小',90,40),
         ('speech_offset_x',u'气泡左右位置（左 ← → 右）',120,60),
         ('speech_offset_y',u'气泡上下位置（下 ← → 上）',130,30))
SAVE_RETRY_TICKS=150
SETTING_SCREEN='netease_general_setting.setting_screen'
SETTING_REFRESH_TICKS=12

def slider_value(key,value):
    if key=='carry_scale':return int(round(float(value)*100))-60
    return int(value)+(60 if key=='speech_offset_x' else 30)

def setting_value(key,value):
    if key=='carry_scale':return round((int(value)+60)/100.,2)
    return int(value)-(60 if key=='speech_offset_x' else 30)
class ModSettings(object):
    def __init__(self,system):
        self.s=system;self.instance=None;self.queue={};self.callbacks=[];self.values={}
        self.send_ready_at=0;self.inflight=None;self.refresh_at=None
    def register(self):
        if self.instance:return
        comp=api.GetEngineCompFactory().CreateNeteaseWindow(api.GetLevelId())
        self.instance=comp.RegisterSettingInst(config.NAMESPACE,domain.native_value(u'随行伙伴'),'textures/items/companion_doll')
        if not self.instance:return
        inst=self.instance;inst.Clear()
        inst.AddText('help',domain.native_value(u'工具交互装备；空手取回；潜行空手开工／停止；木棍切换移动，潜行用木棍收回。外观和饰品只能在衣柜更换。教程见伙伴手册。'))
        inst.AddButton('recall_worker',domain.native_value(u'正在外面工作的小跟班'),
                       domain.native_value(u'召回身边'),self.recall_worker)
        inst.AddInput('name',domain.native_value(u'伙伴名字（留空不显示）'),self.changed,default=domain.native_value(config.DEFAULT_NAME))
        inst.AddText('display_help',domain.native_value(u'背负与气泡显示：调节后自动保存。背负默认 100％；气泡位置 0 为头顶，右移和上移为正。'))
        for key,label,maximum,default in SLIDERS:
            inst.AddText(key+'_value',domain.native_value(label))
            inst.AddSlider(key,domain.native_value(label),maximum,self.slider_changed,default=default)
        inst.AddToggle('speech_enabled',domain.native_value(LABELS['speech_enabled']),self.changed,default=True)
        inst.AddButton('reset_display',domain.native_value(u'背负与气泡位置'),domain.native_value(u'恢复默认'),self.reset_display)
        for key in ('auto_eat','food_prompt','tool_prompt','block_supply','hunt_animals','inspect_animation','random_carry','fall_reaction','particles'):
            inst.AddToggle(key,domain.native_value(LABELS[key]),self.changed,default=rules.DEFAULTS[key])
        self.sync(self.values,False)
    def recall_worker(self,key,value):
        self.s.send('recall_worker')

    def changed(self,key,value):
        self.queue[key]=value;self.values[key]=value
        if self.refresh_at is not None:self.refresh_at=self.s.ticks+SETTING_REFRESH_TICKS
        from .speech_client import apply_preferences
        apply_preferences(self.s,self.values)
        self.sync_labels()
    def slider_changed(self,key,value):self.changed(key,setting_value(key,value))
    def reset_display(self,key,value):
        for option in ('carry_scale','speech_offset_x','speech_offset_y'):
            self.changed(option,rules.DEFAULTS[option])
            self.instance.SetSliderValue(option,slider_value(option,rules.DEFAULTS[option]))
    def sync_labels(self):
        if not self.instance:return
        for key,label,unused_max,unused_default in SLIDERS:
            value=self.values.get(key,rules.DEFAULTS[key])
            text=u'%s：%d％'%(label,int(round(value*100))) if key=='carry_scale' else u'%s：%+d'%(label,value)
            self.instance.SetText(key+'_value',domain.native_value(text))
    def screen_pushed(self,args):
        self.refresh_at=self.s.ticks+SETTING_REFRESH_TICKS if args.get('screenDef')==SETTING_SCREEN else None
    def refresh_native(self):
        if self.refresh_at is None or self.s.ticks<self.refresh_at:return
        self.refresh_at=None
        # PC SettingInst caches the value but only notifies Cocos to redraw.
        # Resolve the live screen now; never retain a possibly destroyed node.
        node=api.GetTopUINode()
        if node and node.GetScreenName()==SETTING_SCREEN:node.UpdateScreen(True)
    def tick(self):
        self.refresh_native()
        if self.inflight:
            if self.s.ticks-self.inflight[3]<SAVE_RETRY_TICKS:return
            if self.s.pending:return
            self.inflight=None
        if self.queue and self.s.token and not self.s.pending and self.s.ticks>=self.send_ready_at:
            key=sorted(self.queue)[0];value=self.queue[key]
            try:normalized=rules.clean_preference(key,value)
            except domain.Refused:
                # Let the server report invalid input once; it cannot produce
                # a matching saved preference and must not retry forever.
                self.queue.pop(key)
            else:
                # Keep the last desired value until Preferences confirms it.
                # A throttled request has no reply; a later tick retries it.
                self.inflight=(key,normalized,value,self.s.ticks)
            # Server requests are rate limited to one every three ticks. A
            # fast preference acknowledgement must not drop the next slider.
            self.send_ready_at=self.s.ticks+6
            self.s.send('mod_option',key=key,value=value)
    def sync(self,data,confirmed=True):
        if confirmed and self.inflight:
            key,normalized,sent_value,unused_tick=self.inflight
            if key in data and data[key]==normalized:
                if key in self.queue and self.queue[key]==sent_value:self.queue.pop(key)
                self.inflight=None
        self.values=dict(data);self.values.update(self.queue)
        from .speech_client import apply_preferences
        apply_preferences(self.s,self.values)
        if not self.instance:return
        self.instance.SetInputValue('name',domain.native_value(self.values.get('name',config.DEFAULT_NAME)))
        for key in LABELS:self.instance.SetToggleValue(key,bool(self.values.get(key,rules.DEFAULTS[key])))
        for key,unused_label,unused_max,unused_default in SLIDERS:
            self.instance.SetSliderValue(key,slider_value(key,self.values.get(key,rules.DEFAULTS[key])))
        self.sync_labels()
        if confirmed:
            node=api.GetTopUINode()
            if node and node.GetScreenName()==SETTING_SCREEN:self.refresh_at=self.s.ticks+SETTING_REFRESH_TICKS
