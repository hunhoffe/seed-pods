from __future__ import annotations
from seedemu.core import NodeSoftware, NodeSoftwareInstaller, BaseSystem
from seedemu.services import *
from .DockerImage import DockerImage
from .Docker import BaseSystemImageMapping
from typing import Set

BASE_IMAGE=DockerImage('ubuntu:20.04', [], local=False)

def __get_software_deps(deps_acc, classes_to_check, checked_classes, excluded_classes) -> Set[NodeSoftware]:
    # Choose a class to explore
    cls = classes_to_check.pop()
    if cls not in excluded_classes:

        # Add software dependencies to our set of dependencies
        try:
            deps_acc |= cls.softwareDeps()
        except NotImplementedError:
            # This is for abstract classes without softwareDeps impl
            #print(f"Not implemented for: {cls}")
            pass
        except TypeError:
            # This is for abstract classes with softwareDeps impl
            try:
                deps_acc |= cls.softwareDeps(cls)
            except NotImplementedError:
                #print(f"Not implemented for: {cls}")
                pass

        # Do bookkeeping to make sure we don't explore a class more than once
        checked_classes.add(cls)

        # We need to check subclasses of the current class to see if they
        # have additional dependencies
        for subcls in cls.__subclasses__():
            if subcls not in checked_classes and subcls not in excluded_classes:
                classes_to_check.add(subcls)

    # If there are still classes to check, continue
    if len(classes_to_check) > 0:
        return __get_software_deps(deps_acc, classes_to_check, checked_classes, excluded_classes)
    else:
        return deps_acc

def get_seed_deps(excluded_classes=set()) -> Set[NodeSoftware]:
    # Note that excluded classes will automatically exclude their subclasses.
    return __get_software_deps(set(), {NodeSoftwareInstaller}, set(), excluded_classes)

def get_seedemu_image(image_owner) -> DockerImage:
    excluded_classes = {
        BotnetService, 
        BotnetClientService, 
        BotnetServer, 
        BotnetClientServer,

        TorServer, 
        TorService,

        BgpLookingGlassServer, 
        BgpLookingGlassService,

        EthereumService,
        EthereumServer,
    }
    return DockerImage(image_owner + '/seedemu', \
            get_seed_deps(excluded_classes=excluded_classes), \
            local=True, \
            baseImage=BaseSystemImageMapping[BaseSystem.UBUNTU_20_04].setLocal(True))

def get_seedemu_tor_image(image_owner) -> DockerImage:
    torSoftware = TorServer.softwareDeps() | TorService.softwareDeps()
    seedemu_image = get_seedemu_image(image_owner)
    return DockerImage(image_owner + '/seedemu-tor', torSoftware, local=True, baseImage=seedemu_image)

def get_seedemu_botnet_image(image_owner) -> DockerImage:
    botnetSoftware = BotnetServer.softwareDeps() | BotnetService.softwareDeps() | \
        BotnetClientServer.softwareDeps() | BotnetClientService.softwareDeps()
    seedemu_image = get_seedemu_image(image_owner)
    return DockerImage(image_owner + '/seedemu-botnet', botnetSoftware, local=True, baseImage=seedemu_image)

def get_seedemu_eth_image(image_owner) -> DockerImage:
    excluded_classes = {
        BotnetService,
        BotnetClientService,
        BotnetServer,
        BotnetClientServer,

        TorServer,
        TorService,

        BgpLookingGlassServer,
        BgpLookingGlassService,
    }
    return DockerImage(image_owner + '/seedemu-ethernet', \
            get_seed_deps(excluded_classes=excluded_classes), \
            local=True, baseImage=BaseSystemImageMapping[BaseSystem.SEEDEMU_ETHEREUM].setLocal(True))
