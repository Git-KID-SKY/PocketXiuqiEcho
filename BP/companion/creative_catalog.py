# -*- coding: utf-8 -*-
"""Decorate our native creative tab; retain vanilla inventory interactions.

Uses the scoped ScreenProxy/recipe_book inheritance approach from the user's
337dd081456b4134bd258d1119234d9a reference project. No grant-item messages.
"""
from __future__ import division
import re
import mod.client.extraClientApi as api

TITLES=(u'itemCategory.name.echo_companion',u'随行伙伴',u'Companion')
ITEMS={
    'echo:companion_doll':(u'修齐公仔',u'放出伙伴'),
    'echo:companion_guide':(u'伙伴手册',u'翻阅教程'),
    'echo:companion_wardrobe':(u'伙伴衣柜',u'更换装扮')}
SCROLLS=('/scroll_mouse/scroll_view/stack_panel/background_and_viewport/scrolling_view_port/scrolling_content',
         '/scroll_touch/scroll_view/panel/background_and_viewport/scrolling_view_port/scrolling_content')
REGISTERED=set()
CATALOGS=[]

def plain(value):
    if isinstance(value,bytes) and not isinstance(value,type(u'')):value=value.decode('utf8','replace')
    return re.sub(u'§.','',value or '').strip()

class Catalog(object):
    def __init__(self,node):
        self.node=node;self.panes=[];self.hidden={};self.sizes={};self.layout_nodes={};self.tick=0;self.failed=False;self.active=[]

    def ctrl(self,path):
        try:return self.node.GetBaseUIControl(path)
        except Exception:return None

    def create(self):
        paths=[]
        for root in ('','/','/inventory_screen','/inventory_screen_pocket','/variables_button_mappings_and_controls',
                     '/inventory_screen/variables_button_mappings_and_controls','/inventory_screen_pocket/variables_button_mappings_and_controls'):
            try:found=self.node.GetAllChildrenPath(root) or []
            except Exception:continue
            if found:
                prefix=root.rstrip('/');paths=[p if p.startswith(prefix+'/') else prefix+p for p in found];break
        for path in paths:
            if not path.endswith('/scroll_pane') or 'tab_content' not in path:continue
            prefix=path.rsplit('/',1)[0]+'/'
            labels=[p for p in paths if p.startswith(prefix) and p.endswith('/creative_label')]
            if not labels:continue
            pair=(path,labels[0])
            fresh=pair not in self.panes
            if fresh:self.panes.append(pair)
            for definition,name in (('creative_mode_probe','ec_catalog_mode'),('embedded','ec_catalog')):
                # Native screens may cache children across close/reopen. Begin
                # each proxy from authored dimensions rather than rescale a copy.
                old=self.ctrl(path+'/'+name)
                if fresh and old:self.node.RemoveChildControl(old)
                if not self.ctrl(path+'/'+name):self.node.CreateChildControl('echo_catalog.'+definition,name,self.ctrl(path),True)

    def grid(self,pane):
        for suffix in SCROLLS:
            path=pane+suffix+'/grid'
            if self.ctrl(path):return path

    def collection(self,grid):
        result={}
        for name in self.node.GetChildrenName(grid) or []:
            match=re.search(r'(\d+)$',name)
            if not match:continue
            index=int(match.group(1))-1
            if not 0<=index<len(ITEMS):continue
            for suffix in ('/item_cell/item/common.item_renderer','/item_cell/item/item_renderer'):
                control=self.ctrl(grid+'/'+name+suffix)
                if control:
                    data=control.asItemRenderer().GetUiItem() or {}
                    result[index]=data.get('itemName',data.get('newItemName'));break
        return [result.get(i) for i in range(len(ITEMS))]

    def restore(self,grid):
        if grid in self.hidden:
            control=self.ctrl(grid)
            if control:control.SetVisible(self.hidden[grid])
            self.hidden.pop(grid,None)

    def layout(self,pane,panel):
        width,height=panel.GetSize();scale=min(width/192.,height/100.,1.65)
        if scale<=0 or self.sizes.get(pane)==(width,height):return
        root=pane+'/ec_catalog/body';body=self.ctrl(root)
        if pane not in self.layout_nodes:
            nodes=[]
            def walk(path):
                for name in self.node.GetChildrenName(path) or []:
                    child=path+'/'+name;control=self.ctrl(child)
                    if control:
                        nodes.append((child,control.GetPosition(),control.GetSize()));walk(child)
            walk(root);self.layout_nodes[pane]=nodes
        body.SetSize((192*scale,100*scale))
        body.SetPosition(((width-192*scale)/2,(height-100*scale)/2))
        # Native fixed-pixel descendants do not follow SetSize(..., True).
        # Scale their original coordinates once, including inherited slot hitboxes.
        for path,position,size in self.layout_nodes[pane]:
            control=self.ctrl(path)
            if control:
                control.SetSize(tuple(v*scale for v in size))
                control.SetPosition(tuple(v*scale for v in position))
        self.sizes[pane]=(width,height)

    def update(self):
        if self.failed:return
        self.tick+=1
        try:
            if not self.panes:
                if self.tick%6==0 and self.tick<=90:self.create()
                return
            self.active=[]
            for pane,label in self.panes:
                panel=self.ctrl(pane+'/ec_catalog');mode=self.ctrl(pane+'/ec_catalog_mode')
                if not panel or not mode:
                    if self.tick%6==0:self.create()
                    continue
                parent=self.ctrl(pane);lab=self.ctrl(label);grid=self.grid(pane)
                active=bool(grid and lab and parent and parent.GetVisible() and mode.GetVisible() and plain(lab.asLabel().GetText()) in TITLES)
                items=self.collection(grid) if active else []
                active=active and items==sorted(ITEMS)
                if active:
                    self.layout(pane,panel)
                    if grid not in self.hidden:self.hidden[grid]=self.ctrl(grid).GetVisible();self.ctrl(grid).SetVisible(False)
                    self.active.append(pane)
                elif grid:self.restore(grid)
                panel.SetVisible(bool(active))
        except Exception as exc:
            self.failed=True;self.destroy();print('[Companion creative] '+str(exc))

    def destroy(self):
        for grid in list(self.hidden):self.restore(grid)
        for pane,label in self.panes:
            panel=self.ctrl(pane+'/ec_catalog')
            if panel:panel.SetVisible(False)
        self.active=[]

Proxy=api.GetUIScreenProxyCls()

class InventoryProxy(Proxy):
    def __init__(self,screenName,screenNode):
        Proxy.__init__(self,screenName,screenNode);self.catalog=Catalog(screenNode);CATALOGS.append(self.catalog)
    def OnCreate(self):
        try:self.catalog.create()
        except Exception as exc:self.catalog.failed=True;self.catalog.destroy();print('[Companion creative] '+str(exc))
    def OnTick(self):self.catalog.update()
    def OnDestroy(self):
        self.catalog.destroy()
        for pane,label in self.catalog.panes:
            for name in ('ec_catalog','ec_catalog_mode'):
                control=self.catalog.ctrl(pane+'/'+name)
                if control:self.catalog.node.RemoveChildControl(control)
        if self.catalog in CATALOGS:CATALOGS.remove(self.catalog)

class PocketInventoryProxy(InventoryProxy):pass

def register():
    manager=api.GetNativeScreenManagerCls().instance()
    for screen,cls in (('crafting.inventory_screen','InventoryProxy'),('crafting_pocket.inventory_screen_pocket','PocketInventoryProxy')):
        if screen not in REGISTERED:
            if manager.RegisterScreenProxy(screen,__name__+'.'+cls) is False:raise ValueError('Creative proxy registration failed: '+screen)
            REGISTERED.add(screen)
