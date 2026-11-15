# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.server.extraServerApi as serverApi
import mod.client.extraClientApi as clientApi
from . import config


@Mod.Binding(name=config.NAMESPACE, version=config.VERSION)
class CompanionMod(object):
    @Mod.InitServer()
    def init_server(self):
        serverApi.RegisterSystem(config.NAMESPACE, config.SERVER, 'companion.server.CompanionServer')

    @Mod.InitClient()
    def init_client(self):
        clientApi.RegisterSystem(config.NAMESPACE, config.CLIENT, 'companion.client.CompanionClient')

    @Mod.DestroyServer()
    def destroy_server(self):
        pass

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
