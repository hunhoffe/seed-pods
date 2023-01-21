from .DomainNameService import DomainNameService, DomainNameServer
from seedemu.core import Node, NodeSoftware, Emulator, Service, Server
from typing import List

class ReverseDomainNameServer(Server):
    """!
    @brief Reverse DNS server.
    """

    def install(self, node: Node):
        pass

    @property
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return []

class ReverseDomainNameService(Service):
    """!
    @brief Reverse DNS. This service hosts the in-addr.arpa. zone and resolve
    IP addresses to nodename-netname.nodetype.asn.net
    """

    __dns: DomainNameService

    def __init__(self):
        """!
        @brief ReverseDomainNameService constructor
        """
        super().__init__()
        self.addDependency('DomainNameService', True, False)
        self.addDependency('Base', False, False)

    def _createServer(self) -> Server:
        return ReverseDomainNameServer()

    def install(self, vnode: str) -> Server:
        assert False, 'ReverseDomainNameService is not a real service and should not be installed this way. Please install a DomainNameService on the node and host the zone "in-addr.arpa." yourself.'

    def configure(self, emulator: Emulator):
        reg = emulator.getRegistry()

        self._log('Creating "in-addr.arpa." zone...')
        self.__dns = reg.get('seedemu', 'layer', 'DomainNameService')
        zone = self.__dns.getZone('in-addr.arpa.')

        self._log('Collecting IP addresses...')
        for ([scope, type, name], obj) in reg.getAll().items():
            if type != 'rnode' and type != 'hnode': continue
            self._log('Collecting {}/{}/{}...'.format(scope, type, name))

            if scope == 'ix':
                scope = name
                name = 'rs'
            else: scope = 'as' + scope

            node: Node = obj
            for iface in node.getInterfaces():
                addr = '.'.join(reversed(str(iface.getAddress()).split('.')))
                netname = iface.getNet().getName()
                record = '{} PTR {}-{}.{}.{}.net.'.format(addr, name, netname, type, scope).replace('_', '-')
                zone.addRecord(record)

        return super().configure(emulator)

    @property
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return ReverseDomainNameServer.softwareDeps
    