from __future__ import annotations
from seedemu.core.Emulator import Emulator
from seedemu.core import Node, NodeFile, NodeSoftware, Network, Compiler
from seedemu.core.enums import NodeRole, NetworkType
from typing import Dict, Generator, List, Set, Tuple
from hashlib import md5
from os import mkdir, chdir
from re import sub
from ipaddress import IPv4Network, IPv4Address
from shutil import copyfile
import json

SEEDEMU_CLIENT_IMAGE='handsonsecurity/seedemu-map'

DockerCompilerFileTemplates: Dict[str, str] = {}

DockerCompilerFileTemplates['dockerfile'] = """\
ARG DEBIAN_FRONTEND=noninteractive
RUN echo 'exec zsh' > /root/.bashrc
"""

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

DockerCompilerFileTemplates['seedemu_client'] = """\
    seedemu-client:
        image: {clientImage}
        container_name: seedemu_client
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        ports:
            - {clientPort}:8080/tcp
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

class DockerImage(object):
    """!
    @brief The DockerImage class.

    This class repersents a candidate image for docker compiler.
    """
    __software: List[NodeSoftware]
    __name: str
    __local: bool
    __dirName: str
    __baseImage: DockerImage
    __packageInstallTiers:  List[List[NodeSoftware]]

    def __init__(self, name: str, software: List[NodeSoftware], local: bool = False, dirName: str = None, baseImage: DockerImage = None) -> None:
        """!
        @brief create a new docker image.

        @param name name of the image. Can be name of a local image, image on
        dockerhub, or image in private repo.
        @param software set of software pre-installed in the image, so the
        docker compiler can skip them when compiling.
        @param local (optional) set this image as a local image. A local image
        is built locally instead of pulled from the docker hub. Default to False.
        @param dirName (optional) directory name of the local image (when local
        is True). Default to None. None means use the name of the image.
        @param baseImage (optional) Name of image to build on top of
        """
        if not local:
            assert baseImage is None, "Remote images cannot have a base image"

        super().__init__()

        self.__name = name
        self.__software = []
        self.__local = local
        self.__dirName = dirName if dirName != None else name
        self.__baseImage = baseImage
        self.__packageInstallTiers = None

        for soft in software:
            self.__software.append(soft)

    def getName(self) -> str:
        """!
        @brief get the name of this image.

        @returns name.
        """
        return self.__name

    def getSoftware(self) -> List[NodeSoftware]:
        """!
        @brief get set of software installed on this image.
        
        @return set.
        """
        return self.__software
    
    def addSoftware(self, soft: NodeSoftware) -> DockerImage:
        """!
        @brief add to the set of software installed on this image.
        
        @returns self, for chaining api calls.
        """
        self.__software.append(soft)
        return self

    def getDirName(self) -> str:
        """!
        @brief returns the directory name of this image.

        @return directory name.
        """
        return self.__dirName
    
    def isLocal(self) -> bool:
        """!
        @brief returns True if this image is local.

        @return True if this image is local.
        """
        return self.__local

    def setSoftwareInstallTiers(self, tiers: List[List[NodeSoftware]]) -> DockerImage:
        """!
        @brief returns Groupings for software installed with a package installer

        @returns self, for chaining api calls.
        """
        self.__packageInstallTiers = tiers
        return self

    def generateDockerFile(self) -> str:
        """!
        @brief Generate a docker file for the current docker image

        @returns dockerfile contents
        """
        dockerfile = ""

        # Create from base image, if has base image
        if self.__baseImage:
            dockerfile += "# The base image of the DockerImage\n"
            if not self.__baseImage.isLocal():
                # Use dummy name for remote images
                dockerfile += f"FROM {md5(self.__baseImage.getName().encode('utf-8')).hexdigest()}\n"
            else:
                # Use actual name for local images
                dockerfile += f"FROM {self.__baseImage.getName()}\n"

        dockerfile += '\n# Default dockerfile commands used for all SEED docker images\n'
        dockerfile += DockerCompilerFileTemplates['dockerfile']

        # Install software via package manager
        softPackages = set([s.name for s in self.__software if s.usePackageManager()])
        if len(softPackages) > 0:
            use_software_tiers = not (self.__packageInstallTiers is None)
            dockerfile += f"\n# Installing software with package manager (software_tiers={use_software_tiers})\n"
            if use_software_tiers:
                installedSoft = set()
                for tier in self.__packageInstallTiers:
                    packages = [pkg.name for pkg in tier]
                    dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(set(packages))))
                    installedSoft |= set(packages)
                toInstall = [s for s in softPackages if not (s in installedSoft)]
                if len(toInstall) > 0:
                    dockerfile += '\n# Installing leftover software packages after installing all tiers\n'
                    dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(set(toInstall))))
            else:
                dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(softPackages)))

        # Install software that is installed via script
        softScripts = [s for s in self.__software if not s.usePackageManager()]
        if len(softScripts) > 0:
            dockerfile += "\n# Installing software via script\n"
            for s in softScripts:
                dockerfile += self.__runFile(s.installScript)

        # If parent image has cmd, it's okay - docker will override it and use this.
        dockerfile += '\n# Command that runs when a container based on this image is instantiated\n'
        dockerfile += 'CMD ["/start.sh"]\n'
        return dockerfile

    def rebaseImage(self, baseImage: DockerImage) -> DockerImage:
        """!
        @brief Create a new docker image with FROM baseImage with any additional dependencies (software, files) from self added. 

        @param baseImage the new base for the docker image

        @returns rebasedImage the new docker image.
        """
        rebasedImage = DockerImage(self.getName(), [], local=True, dirName=self.getDirName(), baseImage=baseImage)

        # Go through all fields and add anything not included in self.
        for s in self.getSoftware():
            if not (s in baseImage.getSoftware()):
                rebasedImage.addSoftware(s)
        
        # Only include tiers that install software the new rebased image needs
        if self.__packageInstallTiers:
            tiers = []
            for tier in self.__packageInstallTiers:
                new_tier = tier.intersection(rebasedImage.getSoftware())
                if len(new_tier) > 0:
                    tiers.append(tier)
        rebasedImage.setSoftwareInstallTiers(tiers)

        return rebasedImage

    def __runFile(cls, file: NodeFile) -> str:
        """!
        @brief Add the file to docker and add related commands to dockerfile string.

        @param file the file to add to the container image
        @param executeFile whether the execute the file or not (e.g., as in a script)

        @returns dockerfile commands.
        """
        stagedPath = md5(file.getPath().encode('utf-8')).hexdigest()
        if not (file.getHostPath() is None):
            copyfile(file.getHostPath(), stagedPath)
        else:
            content = file.getContent()
            if content is None:
                content = ''
            print(content, file=open(stagedPath, 'w'))

        dockerfile = f'COPY {stagedPath} {file.getPath()}\n'
        dockerfile += f'RUN chmod +x {file.getPath()}\n'
        dockerfile += f'RUN .{file.getPath()}\n'
        return dockerfile

    def __str__(self) -> str:
        base_image_name = None
        if self.__baseImage:
            base_image_name = self.__baseImage.getName()
        return f'DockerImage name={self.getName()}, local={self.isLocal()}, dirName={self.getDirName()} ' \
            f'baseImage={base_image_name}\ninstallTiers={self.__packageInstallTiers}\nsoftware={self.getSoftware()}'

DefaultImages: List[DockerImage] = []

DefaultImages.append(DockerImage('ubuntu:20.04', [], local=False))

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

    __client_enabled: bool
    __client_port: int

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
        clientEnabled: bool = False,
        clientPort: int = 8080,
        clientHideServiceNet: bool = True
    ):
        """!
        @brief Docker compiler constructor.

        @param namingScheme (optional) node naming scheme. Avaliable variables
        are: {asn}, {role} (r - router, h - host, rs - route server), {name},
        {primaryIp} and {displayName}. {displayName} will automaically fall
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
        @param clientEnabled (optional) set if seedemu client should be enabled.
        Default to False. Note that the seedemu client allows unauthenticated
        access to all nodes, which can potentially allow root access to the
        emulator host. Only enable seedemu in a trusted network.
        @param clientPort (optional) set seedemu client port. Default to 8080.
        @param clientHideServiceNet (optional) hide service network for the
        client map by not adding metadata on the net. Default to True.
        """
        self.__networks = ""
        self.__services = ""
        self.__naming_scheme = namingScheme
        self.__self_managed_network = selfManagedNetwork
        self.__dummy_network_pool = IPv4Network(dummyNetworksPool).subnets(new_prefix = dummyNetworksMask)

        self.__client_enabled = clientEnabled
        self.__client_port = clientPort

        self.__client_hide_svcnet = clientHideServiceNet

        self.__images = {}
        self.__forced_image = None
        self.__disable_images = False
        self._used_images = set()
        self.__image_per_node_list = {}

        for image in DefaultImages:
            self.addImage(image)

    def addImage(self, image: DockerImage, priority: int = 0) -> Docker:
        """!
        @brief add an candidate image to the compiler.

        @param image image to add.
        @param priority (optional) priority of this image. Used when one or more
        images with same number of missing software exist. The one with highest
        priority wins. If two or more images with same priority and same number
        of missing software exist, the one added the last will be used. All
        built-in images has priority of 0. Default to 0.

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
        everything from scratch. Set to False to disable the behavior.

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

        return self

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

            for soft in node.getSoftware():
                # Grouping only matters when using package manager, so ignore other software items.
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
        nodeFiles = node.getFiles()

        nodeImage = DockerImage(nodeName, node.getSoftware(), local=True, dirName=None, baseImage=DefaultImages[0])

        if node.hasAttribute('__soft_install_tiers'):
            nodeImage.setSoftwareInstallTiers(node.getAttribute('__soft_install_tiers'))
        return nodeImage

    def _selectImageFor(self, node: Node) -> Tuple[DockerImage]:
        """!
        @brief select image for the given node.

        @param node node.

        @returns tuple of selected image and set of missinge software.
        """
        nodeSoft = node.getSoftware()
        nodeKey = (node.getAsn(), node.getName())

        if nodeKey in self.__image_per_node_list:
            image_name = self.__image_per_node_list[nodeKey]

            assert image_name in self.__images, 'image-per-node configured, but image {} does not exist.'.format(image_name)

            (image, _) = self.__images[image_name]

            self._log('image-per-node configured, using {}'.format(image.getName()))

            return image

        if self.__disable_images:
            self._log('disable-images configured, using base image.')
            (image, _) = self.__images['ubuntu:20.04']

            return image

        if self.__forced_image != None:
            assert self.__forced_image in self.__images, 'forced-image configured, but image {} does not exist.'.format(self.__forced_image)

            (image, _) = self.__images[self.__forced_image]

            self._log('force-image configured, using image: {}'.format(image.getName()))

            return image
        
        candidates: List[Tuple[DockerImage, int]] = []
        minMissing = len(nodeSoft)

        for (image, prio) in self.__images.values():
            missing = len(set(nodeSoft) - set(image.getSoftware()))

            if missing < minMissing:
                candidates = []
                minMissing = missing

            if missing <= minMissing: 
                candidates.append((image, prio))

        assert len(candidates) > 0, '_selectImageFor ended w/ no images?'

        (selected, maxPiro) = candidates[0]

        for (candidate, prio) in candidates:
            if prio >= maxPiro:
                selected = candidate

        return image


    def _getNetMeta(self, net: Network) -> str: 
        """!
        @brief get net metadata lables.

        @param net net object.

        @returns metadata lables string.
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
        @brief get node metadata lables.

        @param node node object.

        @returns metadata lables string.
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
        assert False, 'unknow node role {}'.format(role)

    def _contextToPrefix(self, scope: str, type: str) -> str:
        """!
        @brief Convert context to prefix.

        @param scope scope.
        @param type type.

        @returns prefix string.
        """
        return '{}_{}_'.format(type, scope)

    def _addFile(self, file: NodeFile) -> str:
        """!
        @brief Stage file to local folder and return Dockerfile command.

        @param file the node file

        @returns self, for chaining api calls. 
        """
        staged_path = md5(file.getPath().encode('utf-8')).hexdigest()
        host_path = file.getHostPath()
        if host_path:
            copyfile(host_path, staged_path)
        else:
            print(file.getContent(), file=open(staged_path, 'w'))
        return self

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
            self._addFile(NodeFile('/replace_address.sh', DockerCompilerFileTemplates['replace_address_script'], isExecutable=True))
            self._addFile(NodeFile('/dummy_addr_map.txt', dummy_addr_map))
            self._addFile(NodeFile('/root/.zshrc.pre', DockerCompilerFileTemplates['zshrc_pre']))

        for (cmd, fork) in node.getStartCommands():
            start_commands += '{}{}\n'.format(cmd, ' &' if fork else '')

        self._addFile(NodeFile('/start.sh', DockerCompilerFileTemplates['start_script'].format(
            startCommands = start_commands
        ), isExecutable=True))

        self._addFile(NodeFile('/seedemu_sniffer', DockerCompilerFileTemplates['seedemu_sniffer'], isExecutable=True))
        self._addFile(NodeFile('/seedemu_worker', DockerCompilerFileTemplates['seedemu_worker'], isExecutable=True))

        for f in node.getFiles():
            self._addFile(f)

        dockerfile = nodeImage.generateDockerFile()
        print(dockerfile, file=open('Dockerfile', 'w'))

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
            # We don't need dummies for local images.
            if image.isLocal():
                continue

            self._log(f'adding dummy service for image {image.getName()}...')

            imageDigest = md5(image.getName().encode('utf-8')).hexdigest()
            
            dummies += DockerCompilerFileTemplates['compose_dummy'].format(
                imageDigest = imageDigest
            )

            dockerfile = f'FROM {image.getName()}\n'
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

        if self.__client_enabled:
            self._log('enabling seedemu-client...')

            self.__services += DockerCompilerFileTemplates['seedemu_client'].format(
                clientImage = SEEDEMU_CLIENT_IMAGE,
                clientPort = self.__client_port
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
