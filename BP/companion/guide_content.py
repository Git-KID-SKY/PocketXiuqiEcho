# -*- coding: utf-8 -*-
"""Shared handbook identifiers and chapter ordering."""
from .guide_pages import PAGES
ITEM='echo:companion_guide'
CHAPTERS=(u'出发',u'携带',u'协助',u'采集',u'陪伴',u'战斗',u'换装',u'设置')
SPREADS=tuple(PAGES[i:i+2] for i in range(0,len(PAGES),2))
