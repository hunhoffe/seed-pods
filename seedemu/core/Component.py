from abc import ABCMeta, abstractmethod

from seedemu.core import Emulator
from typing import List

class Component(metaclass=ABCMeta):
    """!
    @brief Component interface.
    """

    @abstractmethod
    def get(self) -> Emulator:
        """!
        @brief get the emulator with component.
        """
        raise NotImplementedError('get not iImplemented.')

    def getVirtualNodes(self) -> List[str]:
        """!
        @brief get list of virtual nodes.
        """
        return []