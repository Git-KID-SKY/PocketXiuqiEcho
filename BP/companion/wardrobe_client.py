# -*- coding: utf-8 -*-
"""Animate only nearby real wardrobe block entities; no extra world entities."""
import mod.client.extraClientApi as api
F=api.GetEngineCompFactory()


class WardrobeView(object):
    def __init__(self,system):self.s=system;self.entries={}

    def sync(self,args):
        incoming={}
        for row in args.get('entries',[]):
            pos=tuple(row['pos']);old=self.entries.get(pos,{})
            value=dict(row);value['amount']=old.get('amount',0.);incoming[pos]=value
        self.entries=incoming

    def tick(self):
        if not self.entries:return
        comp=F.CreateBlockInfo(self.s.level)
        for pos,value in self.entries.items():
            target=1. if value.get('open') else 0.;amount=value['amount']
            if amount!=target:value['amount']=max(target,amount-.13) if target<amount else min(target,amount+.13)
            if amount==target and self.s.ticks%30:continue
            block=comp.GetBlock(pos)
            if not block or block[0]!='echo:companion_wardrobe':continue
            comp.SetEnableBlockEntityAnimations(pos,True)
            comp.SetBlockEntityMolangValue(pos,'variable.wardrobe_yaw',value.get('yaw',0.))
            comp.SetBlockEntityMolangValue(pos,'variable.wardrobe_open',value['amount'])
