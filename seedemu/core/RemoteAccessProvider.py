from __future__ import annotations
from abc import ABCMeta, abstractmethod
from .Loggable import Loggable
from .NodeSoftware import NodeSoftwareInstaller

class RemoteAccessProvider(Loggable, NodeSoftwareInstaller, metaclass=ABCMeta):
    """!
    @brief Implements logic for provide remote access to emulated network.
    """

    def _log(self, message: str) -> None:
        """!
        @brief Log to stderr.

        @param message message.
        """
        super().__log__("{}RemoteAccessProvider".format(self.getName()), message)

    @abstractmethod
    def configureRemoteAccess(self, emulator: Emulator, netObject: Network, brNode: Node, brNet: Network):
        """!
        @brief configure remote access on a given network at given AS.

        @param emulator emulator object reference.
        @param netObject network object reference.
        @param brNode reference to a service node that is not part of the
        emulation. This node can be used to run software (like VPN server) for
        remote access. The configureRemoteAccess method will join the
        brNet/netObject networks. Do not join them manually on the brNode.
        @param brNet reference to a network that is not part of the emulation.
        This network will have access NAT to the real internet. 
        """
        raise NotImplementedError("configureRemoteAccess not implemented.")

    def getName(self) -> str:
        """!
        @brief Get the name of the provider.

        @returns name.
        """
        return self.__class__.__name__