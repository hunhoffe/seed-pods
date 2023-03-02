from __future__ import annotations
from seedemu.core.Emulator import Emulator
from seedemu.core import Node, NodeFile, NodeSoftware, Network, Compiler, BaseSystem
from seedemu.core.enums import NodeRole, NetworkType
from typing import Dict, Generator, List, Set, Tuple
from hashlib import md5
from os import mkdir, chdir
from re import sub
from ipaddress import IPv4Network, IPv4Address
import json
from .DockerImage import DockerImage

SEEDEMU_INTERNET_MAP_IMAGE='handsonsecurity/seedemu-map'
SEEDEMU_ETHER_VIEW_IMAGE='handsonsecurity/seedemu-etherview'

DockerCompilerFileTemplates: Dict[str, str] = {}

DockerCompilerFileTemplates['start_script'] = """\
#!/bin/bash
{startCommands}
echo "ready! run 'docker exec -it $HOSTNAME /bin/zsh' to attach to this node" >&2
for f in /proc/sys/net/ipv4/conf/*/rp_filter; do echo 0 > "$f"; done
tail -f /dev/null
"""

DockerCompilerFileTemplates['seedemu_sniffer'] = """\
#!/bin/bash
last_pid=0
while read -sr expr; do {
    [ "$last_pid" != 0 ] && kill $last_pid 2> /dev/null
    [ -z "$expr" ] && continue
    tcpdump -e -i any -nn -p -q "$expr" &
    last_pid=$!
}; done
[ "$last_pid" != 0 ] && kill $last_pid
"""

DockerCompilerFileTemplates['seedemu_worker'] = """\
#!/bin/bash

net() {
    [ "$1" = "status" ] && {
        ip -j link | jq -cr '.[] .operstate' | grep -q UP && echo "up" || echo "down"
        return
    }

    ip -j li | jq -cr '.[] .ifname' | while read -r ifname; do ip link set "$ifname" "$1"; done
}

bgp() {
    cmd="$1"
    peer="$2"
    [ "$cmd" = "bird_peer_down" ] && birdc dis "$2"
    [ "$cmd" = "bird_peer_up" ] && birdc en "$2"
}

while read -sr line; do {
    id="`cut -d ';' -f1 <<< "$line"`"
    cmd="`cut -d ';' -f2 <<< "$line"`"

    output="no such command."

    [ "$cmd" = "net_down" ] && output="`net down 2>&1`"
    [ "$cmd" = "net_up" ] && output="`net up 2>&1`"
    [ "$cmd" = "net_status" ] && output="`net status 2>&1`"
    [ "$cmd" = "bird_list_peer" ] && output="`birdc s p | grep --color=never BGP 2>&1`"

    [[ "$cmd" == "bird_peer_"* ]] && output="`bgp $cmd 2>&1`"

    printf '_BEGIN_RESULT_'
    jq -Mcr --arg id "$id" --arg return_value "$?" --arg output "$output" -n '{id: $id | tonumber, return_value: $return_value | tonumber, output: $output }'
    printf '_END_RESULT_'
}; done
"""

DockerCompilerFileTemplates['replace_address_script'] = '''\
#!/bin/bash
ip -j addr | jq -cr '.[]' | while read -r iface; do {
    ifname="`jq -cr '.ifname' <<< "$iface"`"
    jq -cr '.addr_info[]' <<< "$iface" | while read -r iaddr; do {
        addr="`jq -cr '"\(.local)/\(.prefixlen)"' <<< "$iaddr"`"
        line="`grep "$addr" < /dummy_addr_map.txt`"
        [ -z "$line" ] && continue
        new_addr="`cut -d, -f2 <<< "$line"`"
        ip addr del "$addr" dev "$ifname"
        ip addr add "$new_addr" dev "$ifname"
    }; done
}; done
'''

DockerCompilerFileTemplates['compose'] = """\
version: "3.4"
services:
{dummies}
{services}
networks:
{networks}
"""

DockerCompilerFileTemplates['compose_dummy'] = """\
    {imageDigest}:
        build:
            context: .
            dockerfile: dummies/{imageDigest}
        image: {imageDigest}
"""

DockerCompilerFileTemplates['compose_service'] = """\
    {nodeId}:
        build: ./{nodeId}
        container_name: {nodeName}
        cap_add:
            - ALL
        sysctls:
            - net.ipv4.ip_forward=1
            - net.ipv4.conf.default.rp_filter=0
            - net.ipv4.conf.all.rp_filter=0
        privileged: true
        networks:
{networks}{ports}{volumes}
        labels:
{labelList}
"""

DockerCompilerFileTemplates['compose_label_meta'] = """\
            org.seedsecuritylabs.seedemu.meta.{key}: "{value}"
"""

DockerCompilerFileTemplates['compose_ports'] = """\
        ports:
{portList}
"""

DockerCompilerFileTemplates['compose_port'] = """\
            - {hostPort}:{nodePort}/{proto}
"""

DockerCompilerFileTemplates['compose_volumes'] = """\
        volumes:
{volumeList}
"""

DockerCompilerFileTemplates['compose_volume'] = """\
            - type: bind
              source: {hostPath}
              target: {nodePath}
"""

DockerCompilerFileTemplates['compose_storage'] = """\
            - {nodePath}
"""

DockerCompilerFileTemplates['compose_service_network'] = """\
            {netId}:
{address}
"""

DockerCompilerFileTemplates['compose_service_network_address'] = """\
                ipv4_address: {address}
"""

DockerCompilerFileTemplates['compose_network'] = """\
    {netId}:
        driver_opts:
            com.docker.network.driver.mtu: {mtu}
        ipam:
            config:
                - subnet: {prefix}
        labels:
{labelList}
"""

DockerCompilerFileTemplates['seedemu_internet_map'] = """\
    seedemu-internet-client:
        image: {clientImage}
        container_name: seedemu_internet_map
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        ports:
            - {clientPort}:8080/tcp
"""

DockerCompilerFileTemplates['seedemu_ether_view'] = """\
    seedemu-ether-client:
        image: {clientImage}
        container_name: seedemu_ether_view
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        ports:
            - {clientPort}:5000/tcp
"""

DockerCompilerFileTemplates['zshrc_pre'] = """\
export NOPRECMD=1
alias st=set_title
"""

DockerCompilerFileTemplates['local_image'] = """\
    {imageName}:
        build:
            context: {dirName}
        image: {imageName}
"""

BaseSystemImageMapping: Dict = {}
# BaseSystemImageMapping['virtual-name'] = (DockerImage('image name'), [software...])
BaseSystemImageMapping[BaseSystem.UBUNTU_20_04] = (DockerImage('ubuntu:20.04', []))
BaseSystemImageMapping[BaseSystem.SEEDEMU_ETHEREUM] = (DockerImage('handsonsecurity/seedemu-ethereum', []))

class Docker(Compiler):
    """!
    @brief The Docker compiler class.

    Docker is one of the compiler driver. It compiles the lab to docker
    containers.
    """

    __services: str
    __networks: str
    __naming_scheme: str
    __self_managed_network: bool
    __dummy_network_pool: Generator[IPv4Network, None, None]

    __internet_map_enabled: bool
    __internet_map_port: int

    __ether_view_enabled: bool
    __ether_view_port: int

    __client_hide_svcnet: bool

    __images: Dict[str, Tuple[DockerImage, int]]
    __forced_image: str
    __disable_images: bool
    __image_per_node_list: Dict[Tuple[str, str], DockerImage]
    _used_images: Set[DockerImage]

    def __init__(
        self,
        namingScheme: str = "as{asn}{role}-{displayName}-{primaryIp}",
        selfManagedNetwork: bool = False,
        dummyNetworksPool: str = '10.128.0.0/9',
        dummyNetworksMask: int = 24,
        internetMapEnabled: bool = False,
        internetMapPort: int = 8080,
        etherViewEnabled: bool = False,
        etherViewPort: int = 5000,
        clientHideServiceNet: bool = True
    ):
        """!
        @brief Docker compiler constructor.

        @param namingScheme (optional) node naming scheme. Available variables
        are: {asn}, {role} (r - router, h - host, rs - route server), {name},
        {primaryIp} and {displayName}. {displayName} will automatically fall
        back to {name} if 
        Default to as{asn}{role}-{displayName}-{primaryIp}.
        @param selfManagedNetwork (optional) use self-managed network. Enable
        this to manage the network inside containers instead of using docker's
        network management. This works by first assigning "dummy" prefix and
        address to containers, then replace those address with "real" address
        when the containers start. This will allow the use of overlapping
        networks in the emulation and will allow the use of the ".1" address on
        nodes. Note this will break port forwarding (except for service nodes
        like real-world access node and remote access node.) Default to False.
        @param dummyNetworksPool (optional) dummy networks pool. This should not
        overlap with any "real" networks used in the emulation, including
        loopback IP addresses. Default to 10.128.0.0/9.
        @param dummyNetworksMask (optional) mask of dummy networks. Default to
        24.
        @param internetMapEnabled (optional) set if seedemu internetMap should be enabled.
        Default to False. Note that the seedemu internetMap allows unauthenticated
        access to all nodes, which can potentially allow root access to the
        emulator host. Only enable seedemu in a trusted network.
        @param internetMapPort (optional) set seedemu internetMap port. Default to 8080.
        @param etherViewEnabled (optional) set if seedemu EtherView should be enabled.
        Default to False. 
        @param etherViewPort (optional) set seedemu EtherView port. Default to 5000.
        @param clientHideServiceNet (optional) hide service network for the
        client map by not adding metadata on the net. Default to True.
        """
        self.__networks = ""
        self.__services = ""
        self.__naming_scheme = namingScheme
        self.__self_managed_network = selfManagedNetwork
        self.__dummy_network_pool = IPv4Network(dummyNetworksPool).subnets(new_prefix = dummyNetworksMask)

        self.__internet_map_enabled = internetMapEnabled
        self.__internet_map_port = internetMapPort

        self.__ether_view_enabled = etherViewEnabled
        self.__ether_view_port = etherViewPort

        self.__client_hide_svcnet = clientHideServiceNet

        self.__images = {}
        self.__forced_image = None
        self.__disable_images = False
        self._used_images = set()
        self.__image_per_node_list = {}

        for name, image in BaseSystemImageMapping.items():
            priority = 0
            if name == BaseSystem.DEFAULT:
                priority = 10
            self.addImage(image, priority=priority)

    def getName(self) -> str:
        return "Docker"

    def addImage(self, image: DockerImage, priority: int = -1) -> Docker:
        """!
        @brief add an candidate image to the compiler.

        @param image image to add.
        @param priority (optional) priority of this image. Used when one or more
        images with same number of missing software exist. The one with highest
        priority wins. If two or more images with same priority and same number
        of missing software exist, the one added the last will be used. All
        built-in images has priority of 0. Default to -1. All built-in images are
        prior to the added candidate image. To set a candidate image to a node, 
        use setImageOverride() method. 

        @returns self, for chaining api calls.
        """
        assert image.getName() not in self.__images, 'image with name {} already exists.'.format(image.getName())
            
        self.__images[image.getName()] = (image, priority)

        return self

    def getImages(self) -> List[Tuple[DockerImage, int]]:
        """!
        @brief get list of images configured.

        @returns list of tuple of images and priority.
        """

        return list(self.__images.values())

    def forceImage(self, imageName: str) -> Docker:
        """!
        @brief forces the docker compiler to use a image, identified by the
        imageName. Image with such name must be added to the docker compiler
        with the addImage method, or the docker compiler will fail at compile
        time. Set to None to disable the force behavior.

        @param imageName name of the image.

        @returns self, for chaining api calls.
        """
        self.__forced_image = imageName

        return self

    def disableImages(self, disabled: bool = True) -> Docker:
        """!
        @brief forces the docker compiler to not use any images and build
        everything for starch. Set to False to disable the behavior.

        @param disabled (option) disabled image if True. Default to True.

        @returns self, for chaining api calls.
        """
        self.__disable_images = disabled

        return self
    
    def setImageOverride(self, node:Node, imageName:str) -> Docker:
        """!
        @brief set the docker compiler to use a image on the specified Node.

        @param node target node to override image.
        @param imageName name of the image to use.

        @returns self, for chaining api calls.      
        """
        asn = node.getAsn()
        name = node.getName()
        self.__image_per_node_list[(asn, name)]=imageName

    def _groupSoftware(self, emulator: Emulator):
        """!
        @brief Group apt-get install calls to maximize docker cache. 

        @param emulator emulator to load nodes from.
        """

        registry = emulator.getRegistry()
        
        # { [imageName]: { [softwareRef]: [nodeRef] } }
        softGroups: Dict[str, Dict[NodeSoftware, List[Node]]] = {}

        # { [imageName]: useCount }
        groupIter: Dict[str, int] = {}

        for ((scope, type, name), obj) in registry.getAll().items():
            if type != 'rnode' and type != 'hnode' and type != 'snode' and type != 'rs' and type != 'snode': 
                continue

            node: Node = obj

            img = self._selectImageFor(node)
            imgName = img.getName()

            if not imgName in groupIter:
                groupIter[imgName] = 0

            groupIter[imgName] += 1

            if not imgName in softGroups:
                softGroups[imgName] = {}

            group = softGroups[imgName]

            # We only care about grouping software installed with the package manager.
            for soft in node.getSoftware():
                if soft.usePackageManager():
                    if soft not in group:
                        group[soft] = []
                    group[soft].append(node)

        for (key, val) in softGroups.items():
            maxIter = groupIter[key]
            self._log('grouping software for image "{}" - {} references.'.format(key, maxIter))
            step = 1

            for commRequired in range(maxIter, 0, -1):
                currentTier: Set[str] = set()
                currentTierNodes: Set[Node] = set()

                for (soft, nodes) in val.items():
                    if len(nodes) == commRequired:
                        currentTier.add(soft)
                        for node in nodes: currentTierNodes.add(node)
                
                for node in currentTierNodes:
                    if not node.hasAttribute('__soft_install_tiers'):
                        node.setAttribute('__soft_install_tiers', [])

                    node.getAttribute('__soft_install_tiers').append(currentTier)
                

                if len(currentTier) > 0:
                    self._log('the following software has been grouped together in step {}: {} since they are referenced by {} nodes.'.format(step, currentTier, len(currentTierNodes)))
                    step += 1
                
    def _imageFromNode(self, nodeName: str, node: Node) -> DockerImage:
        """!
        @brief creates a docker image definition from the node object

        @param node node.

        @returns the docker image
        """
        nodeFiles = node.getFiles()

        nodeImage = DockerImage(nodeName, node.getSoftware(), local=True, dirName=None, baseImage=BaseSystemImageMapping[node.getBaseSystem()])

        if node.hasAttribute('__soft_install_tiers'):
            nodeImage.setSoftwareInstallTiers(node.getAttribute('__soft_install_tiers'))
        return nodeImage

    def _selectImageFor(self, node: Node) -> DockerImage:
        """!
        @brief select image for the given node.

        @param node node.

        @returns the selected image.
        """
        nodeSoft = node.getSoftware()
        nodeKey = (node.getAsn(), node.getName())

        # #1 Highest Priority (User Custom Image)
        if nodeKey in self.__image_per_node_list:
            image_name = self.__image_per_node_list[nodeKey]

            assert image_name in self.__images, 'image-per-node configured, but image {} does not exist.'.format(image_name)

            (image, _) = self.__images[image_name]

            self._log('image-per-node configured, using {}'.format(image.getName()))
            return image

        # Should we keep this feature? 
        if self.__disable_images:
            self._log('disable-imaged configured, using base image.')
            (image, _) = self.__images['ubuntu:20.04']
            return image

        # Set Default Image for All Nodes 
        if self.__forced_image != None:
            assert self.__forced_image in self.__images, 'forced-image configured, but image {} does not exist.'.format(self.__forced_image)

            (image, _) = self.__images[self.__forced_image]

            self._log('force-image configured, using image: {}'.format(image.getName()))

            return image
        
        #############################################################
        if node.getBaseSystem().value != BaseSystem.DEFAULT.value:
            #Maintain a table : Virtual Image Name - Actual Image Name 
            image = BaseSystemImageMapping[node.getBaseSystem()]
            return image
        
        candidates: List[Tuple[DockerImage, int]] = []
        minMissing = len(nodeSoft)

        for (image, prio) in self.__images.values():
            missing = len(nodeSoft - image.getSoftware())

            if missing < minMissing:
                candidates = []
                minMissing = missing

            if missing <= minMissing: 
                candidates.append((image, prio))

        assert len(candidates) > 0, '_electImageFor ended w/ no images?'

        (selected, maxPrio) = candidates[0]

        for (candidate, prio) in candidates:
            if prio >= maxPrio:
                selected = candidate

        return selected


    def _getNetMeta(self, net: Network) -> str: 
        """!
        @brief get net metadata labels.

        @param net net object.

        @returns metadata labels string.
        """

        (scope, type, name) = net.getRegistryInfo()

        labels = ''

        if self.__client_hide_svcnet and scope == 'seedemu' and name == '000_svc':
            return DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'dummy',
                value = 'dummy label for hidden node/net'
            )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'type',
            value = 'global' if scope == 'ix' else 'local'
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'scope',
            value = scope
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'name',
            value = name
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'prefix',
            value = net.getPrefix()
        )

        if net.getDisplayName() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'displayname',
                value = net.getDisplayName()
            )
        
        if net.getDescription() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'description',
                value = net.getDescription()
            )

        return labels

    def _getNodeMeta(self, node: Node) -> str:
        """!
        @brief get node metadata labels.

        @param node node object.

        @returns metadata labels string.
        """
        (scope, type, name) = node.getRegistryInfo()

        labels = ''

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'asn',
            value = node.getAsn()
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'nodename',
            value = name
        )

        if type == 'hnode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Host'
            )

        if type == 'rnode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Router'
            )

        if type == 'snode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Emulator Service Worker'
            )

        if type == 'rs':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Route Server'
            )

        if node.getDisplayName() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'displayname',
                value = node.getDisplayName()
            )
        
        if node.getDescription() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'description',
                value = node.getDescription()
            )
        
        if len(node.getClasses()) > 0:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'class',
                value = json.dumps(node.getClasses()).replace("\"", "\\\"")
            )

        for key, value in node.getLabel().items():
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = key,
                value = value
            )
        n = 0
        for iface in node.getInterfaces():
            net = iface.getNet()

            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'net.{}.name'.format(n),
                value = net.getName()
            )

            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'net.{}.address'.format(n),
                value = '{}/{}'.format(iface.getAddress(), net.getPrefix().prefixlen)
            )

            n += 1

        return labels

    def _nodeRoleToString(self, role: NodeRole):
        """!
        @brief convert node role to prefix string

        @param role node role

        @returns prefix string
        """
        if role == NodeRole.Host: return 'h'
        if role == NodeRole.Router: return 'r'
        if role == NodeRole.RouteServer: return 'rs'
        assert False, 'unknown node role {}'.format(role)

    def _contextToPrefix(self, scope: str, type: str) -> str:
        """!
        @brief Convert context to prefix.

        @param scope scope.
        @param type type.

        @returns prefix string.
        """
        return '{}_{}_'.format(type, scope)

    def _compileNode(self, node: Node) -> str:
        """!
        @brief Compile a single node. Will create folder for node and the
        dockerfile.

        @param node node to compile.

        @returns docker-compose service string.
        """
        (scope, type, _) = node.getRegistryInfo()
        prefix = self._contextToPrefix(scope, type)
        real_nodename = '{}{}'.format(prefix, node.getName())
        node_nets = ''
        dummy_addr_map = ''

        for iface in node.getInterfaces():
            net = iface.getNet()
            (netscope, _, _) = net.getRegistryInfo()
            net_prefix = self._contextToPrefix(netscope, 'net') 
            if net.getType() == NetworkType.Bridge: net_prefix = ''
            real_netname = '{}{}'.format(net_prefix, net.getName())
            address = iface.getAddress()

            if self.__self_managed_network and net.getType() != NetworkType.Bridge:
                d_index: int = net.getAttribute('dummy_prefix_index')
                d_prefix: IPv4Network = net.getAttribute('dummy_prefix')
                d_address: IPv4Address = d_prefix[d_index]

                net.setAttribute('dummy_prefix_index', d_index + 1)

                dummy_addr_map += '{}/{},{}/{}\n'.format(
                    d_address, d_prefix.prefixlen,
                    iface.getAddress(), iface.getNet().getPrefix().prefixlen
                )

                address = d_address
                
                self._log('using self-managed network: using dummy address {}/{} for {}/{} on as{}/{}'.format(
                    d_address, d_prefix.prefixlen, iface.getAddress(), iface.getNet().getPrefix().prefixlen,
                    node.getAsn(), node.getName()
                ))

            if address == None:
                address = ""
            else:
                address = DockerCompilerFileTemplates['compose_service_network_address'].format(address = address)

            node_nets += DockerCompilerFileTemplates['compose_service_network'].format(
                netId = real_netname,
                address = address
            )
        
        _ports = node.getPorts()
        ports = ''
        if len(_ports) > 0:
            lst = ''
            for (h, n, p) in _ports:
                lst += DockerCompilerFileTemplates['compose_port'].format(
                    hostPort = h,
                    nodePort = n,
                    proto = p
                )
            ports = DockerCompilerFileTemplates['compose_ports'].format(
                portList = lst
            )
        
        _volumes = node.getSharedFolders()
        storages = node.getPersistentStorages()
        
        volumes = ''

        if len(_volumes) > 0 or len(storages) > 0:
            lst = ''

            for (nodePath, hostPath) in _volumes.items():
                lst += DockerCompilerFileTemplates['compose_volume'].format(
                    hostPath = hostPath,
                    nodePath = nodePath
                )
            
            for path in storages:
                lst += DockerCompilerFileTemplates['compose_storage'].format(
                    nodePath = path
                )

            volumes = DockerCompilerFileTemplates['compose_volumes'].format(
                volumeList = lst
            )

        mkdir(real_nodename)
        chdir(real_nodename)

        nodeImage = self._imageFromNode(real_nodename, node)
        baseImage = self._selectImageFor(node)
        self._used_images.add(baseImage)
        nodeImage = nodeImage.rebaseImage(baseImage)

        start_commands = ''

        if self.__self_managed_network:
            start_commands += '/replace_address.sh\n'
            nodeImage.addFile(NodeFile('/replace_address.sh', DockerCompilerFileTemplates['replace_address_script'], isExecutable=True))
            nodeImage.addFile(NodeFile('/dummy_addr_map.txt', dummy_addr_map))
            nodeImage.addFile(NodeFile('/root/.zshrc.pre', DockerCompilerFileTemplates['zshrc_pre']))

        for (cmd, fork) in node.getStartCommands():
            start_commands += '{}{}\n'.format(cmd, ' &' if fork else '')

        nodeImage.addFile(NodeFile('/start.sh', DockerCompilerFileTemplates['start_script'].format(
            startCommands = start_commands
        ), isExecutable=True))

        nodeImage.addFile(NodeFile('/seedemu_sniffer', DockerCompilerFileTemplates['seedemu_sniffer'], isExecutable=True))
        nodeImage.addFile(NodeFile('/seedemu_worker', DockerCompilerFileTemplates['seedemu_worker'], isExecutable=True))

        for f in node.getFiles():
            nodeImage.addFile(f)

        nodeImage.generateImageSetup()

        chdir('..')

        name = self.__naming_scheme.format(
            asn = node.getAsn(),
            role = self._nodeRoleToString(node.getRole()),
            name = node.getName(),
            displayName = node.getDisplayName() if node.getDisplayName() != None else node.getName(),
            primaryIp = node.getInterfaces()[0].getAddress()
        )

        name = sub(r'[^a-zA-Z0-9_.-]', '_', name)

        return DockerCompilerFileTemplates['compose_service'].format(
            nodeId = real_nodename,
            nodeName = name,
            networks = node_nets,
            # privileged = 'true' if node.isPrivileged() else 'false',
            ports = ports,
            labelList = self._getNodeMeta(node),
            volumes = volumes
        )

    def _compileNet(self, net: Network) -> str:
        """!
        @brief compile a network.

        @param net net object.

        @returns docker-compose network string.
        """
        (scope, _, _) = net.getRegistryInfo()
        if self.__self_managed_network and net.getType() != NetworkType.Bridge:
            pfx = next(self.__dummy_network_pool)
            net.setAttribute('dummy_prefix', pfx)
            net.setAttribute('dummy_prefix_index', 2)
            self._log('self-managed network: using dummy prefix {}'.format(pfx))

        net_prefix = self._contextToPrefix(scope, 'net')
        if net.getType() == NetworkType.Bridge: net_prefix = ''

        return DockerCompilerFileTemplates['compose_network'].format(
            netId = '{}{}'.format(net_prefix, net.getName()),
            prefix = net.getAttribute('dummy_prefix') if self.__self_managed_network and net.getType() != NetworkType.Bridge else net.getPrefix(),
            mtu = net.getMtu(),
            labelList = self._getNetMeta(net)
        )

    def _makeDummies(self) -> str:
        """!
        @brief create dummy services to get around docker pull limits.
        
        @returns docker-compose service string.
        """
        mkdir('dummies')
        chdir('dummies')

        dummies = ''

        for image in self._used_images:
            if image.isLocal():
                continue

            self._log('adding dummy service for image {}...'.format(image))
            imageDigest = md5(image.getName().encode('utf-8')).hexdigest()
            
            dummies += DockerCompilerFileTemplates['compose_dummy'].format(
                imageDigest = imageDigest
            )

            dockerfile = 'FROM {}\n'.format(image.getName())
            print(dockerfile, file=open(imageDigest, 'w'))

        chdir('..')

        return dummies

    def _doCompile(self, emulator: Emulator):
        registry = emulator.getRegistry()

        self._groupSoftware(emulator)

        for ((scope, type, name), obj) in registry.getAll().items():

            if type == 'net':
                self._log('creating network: {}/{}...'.format(scope, name))
                self.__networks += self._compileNet(obj)

        for ((scope, type, name), obj) in registry.getAll().items():
            if type == 'rnode':
                self._log('compiling router node {} for as{}...'.format(name, scope))
                self.__services += self._compileNode(obj)

            if type == 'hnode':
                self._log('compiling host node {} for as{}...'.format(name, scope))
                self.__services += self._compileNode(obj)

            if type == 'rs':
                self._log('compiling rs node for {}...'.format(name))
                self.__services += self._compileNode(obj)

            if type == 'snode':
                self._log('compiling service node {}...'.format(name))
                self.__services += self._compileNode(obj)

        if self.__internet_map_enabled:
            self._log('enabling seedemu-internet-map...')

            self.__services += DockerCompilerFileTemplates['seedemu_internet_map'].format(
                clientImage = SEEDEMU_INTERNET_MAP_IMAGE,
                clientPort = self.__internet_map_port
            )
        
        if self.__ether_view_enabled:
            self._log('enabling seedemu-ether-view...')

            self.__services += DockerCompilerFileTemplates['seedemu_ether_view'].format(
                clientImage = SEEDEMU_ETHER_VIEW_IMAGE,
                clientPort = self.__ether_view_port
            )

        local_images = ''

        for (image, _) in self.__images.values():
            if image not in self._used_images or not image.isLocal(): continue
            local_images += DockerCompilerFileTemplates['local_image'].format(
                imageName = image.getName(),
                dirName = image.getDirName()
            )

        self._log('creating docker-compose.yml...'.format(scope, name))
        print(DockerCompilerFileTemplates['compose'].format(
            services = self.__services,
            networks = self.__networks,
            dummies = local_images + self._makeDummies()
        ), file=open('docker-compose.yml', 'w'))
