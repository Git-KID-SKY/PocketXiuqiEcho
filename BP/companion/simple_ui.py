# -*- coding: utf-8 -*-
import mod.client.extraClientApi as api
from . import config,domain,interaction_rules
from .ui import CompanionPanel

class SimplePanel(CompanionPanel):
    CATEGORIES=('hat','glasses','backpack','waist','charm')
    TITLES={ 'hat':u'头饰','glasses':u'面饰 / 眼镜','backpack':u'背饰 / 背包','waist':u'颈饰 / 腰饰','charm':u'手饰'}
    def Create(self):
        self.ready=False;self.system=api.GetSystem(config.NAMESPACE,config.CLIENT);self.system.panel=self
        self.page='outfit' if (self.system.data or {}).get('context')=='wardrobe' else 'bag'
        self.selected=None;self.preview_outfit=None;self.callbacks=[];self.preview_key=None
        self.drag=None;self.slot_addresses={};self.mouse_scale=(1,1);self.item_cache={}
        self.reserve_picker=False;self.transition=None;self.ui_scale=1.;self.ui_size=None;self.bag_page=0;self.outfit_category=0;self.outfit_page=0
        self.resize_layout()
        actions={'close':self.close,'bag/sort':self.sort_bag,'bag/page':self.next_page,
                 'outfit/apply':self.apply_outfit,'outfit/reset':self.reset_outfit,'outfit/appearance':self.appearance,
                 'outfit/category':self.category_next,'outfit/previous':self.outfit_previous,'outfit/next':self.outfit_next}
        for path,handler in actions.items():self.button('/window/'+path,handler)
        for i in range(27):self.bind_slot('/window/bag/comp_'+str(i),i,False)
        for i in range(36):self.bind_slot('/window/bag/player_'+str(i),i,True)
        for i in range(6):
            handler=self.choose_handler(i);self.callbacks.append(handler);self.button('/window/outfit/choice_'+str(i),handler)
        self.GetBaseUIControl('/drag').SetTouchEnable(False)
        self.ready=True;self.refresh(self.system.data)

    def category_next(self,args):
        self.outfit_category=(self.outfit_category+1)%len(self.CATEGORIES);self.outfit_page=0;self.refresh(self.system.data)
    def outfit_previous(self,args):
        self.outfit_page=max(0,self.outfit_page-1);self.refresh(self.system.data)
    def outfit_next(self,args):
        values=config.ACCESSORIES[self.CATEGORIES[self.outfit_category]]
        self.outfit_page=min((len(values)-1)//6,self.outfit_page+1);self.refresh(self.system.data)
    def choose_handler(self,index):
        def choose(args):
            category=self.CATEGORIES[self.outfit_category];values=config.ACCESSORIES[category];slot=self.outfit_page*6+index
            if slot>=len(values):return
            if self.preview_outfit is None:self.preview_outfit=dict(self.system.data['record']['outfit'])
            self.preview_outfit[category]=values[slot];self.refresh(self.system.data)
        return choose

    def next_page(self,args):
        self.cancel_drag();self.bag_page=1-self.bag_page;self.refresh(self.system.data)

    def slot_item(self,address):
        items=self.system.data.get('player_items',[]) if address['area']=='player' else self.system.data['record']['inventory']
        return items[address['slot']] if address['slot']<len(items) else None

    def drag_up(self,args):
        if not self.drag:return
        self.drag_move(args);drag=self.drag;self.drag=None;self.GetBaseUIControl('/drag').SetVisible(False)
        destination=self.drop_path(drag['point'])
        if drag['active']:
            if destination and destination!=drag['path']:
                self.system.send('move_item',source=drag['source'],destination=self.slot_addresses[destination],
                                 inventory_view=drag['view'],revision=drag['revision'])
        elif self.slot_path(args)==drag['path'] and args.get('TouchEvent')!=3 and not domain.empty(drag['item']):
            self.system.send('transfer',direction='deposit' if drag['source']['area']=='player' else 'withdraw',
                             slot=drag['source']['slot'],inventory_view=drag['view'],revision=drag['revision'])
        self.refresh(self.system.data)

    def refresh(self,data):
        if not data or not self.ready:return
        record=data['record'];wardrobe=data.get('context')=='wardrobe';self.page='outfit' if wardrobe else 'bag'
        if self.drag and record['revision']!=self.drag['revision']:self.cancel_drag()
        self.set_visible('bag',not wardrobe);self.set_visible('preview',wardrobe);self.set_visible('outfit',wardrobe)
        self.label('title',u'衣柜' if wardrobe else (record.get('name') or u'伙伴')+u'的背包')
        self.label('state',config.STATE_NAMES.get(record['state'],u''))
        if wardrobe:
            category=self.CATEGORIES[self.outfit_category];values=config.ACCESSORIES[category]
            selected=(self.preview_outfit or record['outfit'])[category]
            self.label('outfit/category/text',self.TITLES[category]+u' · 点击切换分类')
            self.label('outfit/page',u'%d / %d'%(self.outfit_page+1,(len(values)+5)//6))
            for i in range(6):
                slot=self.outfit_page*6+i;path='outfit/choice_'+str(i);self.set_visible(path,slot<len(values))
                if slot<len(values):self.label(path+'/text',config.ACCESSORY_NAMES[values[slot]]);self.selected_button(path,values[slot]==selected)
            self.label('outfit/appearance/text',u'外观：'+(u'小修齐' if record['settings'].get('appearance')=='xiuqi' else u'原版'))
            self.render_preview(record)
        else:
            items=record['inventory'];capacity=interaction_rules.capacity(record)
            if len(items)<=27:self.bag_page=0
            self.label('bag/title',u'随行背包  %d / %d'%(sum(not domain.empty(i) for i in items),capacity))
            self.set_visible('bag/page',len(items)>27);self.label('bag/page/text',u'第 %d 页'%(self.bag_page+1))
            for i in range(27):
                index=i+self.bag_page*27;self.slot_addresses['/window/bag/comp_'+str(i)]['slot']=index
                self.draw_item('comp_'+str(i),items[index] if index<len(items) else None)
            for i in range(36):self.draw_item('player_'+str(i),data['player_items'][i])
            self.label('bag/hint',u'扩展格暂时只可取出；穿在胸甲栏可继续使用' if capacity==27 and self.bag_page else u'点击整组存取 · 拖动调整位置')
        self.set_message(self.system.last_message if self.system.ticks<self.system.message_until else u'')
