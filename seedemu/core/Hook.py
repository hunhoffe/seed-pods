from abc import ABCMeta, abstractmethod
from .Logger import get_logger
from .Emulator import Emulator
from .Registry import Registrable
from .Printable import Printable
from sys import stderr

class Hook(Registrable, Printable, metaclass=ABCMeta):
    """!
    @brief Hook into the rendering process.
    """

    def __init__(self):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__ + "Hook")

    @abstractmethod
    def getName(self) -> str:
        """!
        @brief Get the name of the hook.
        """
        raise NotImplementedError("getName not implemented.")
        
    @abstractmethod
    def getTargetLayer(self) -> str:
        """!
        @brief Get the name of layer to target.
        """
        raise NotImplementedError("getTargetLayer not implemented.")

    def preconfigure(self, emulator: Emulator):
        """!
        @brief pre-configure hook. This is called right before the specified is
        about to configured.

        @param emulator emulator.
        """
        pass

    def postconfigure(self, emulator: Emulator):
        """!
        @brief post-configure hook. This is called right after the specified
        finished configuring.

        @param emulator emulator.
        """
        pass

    def prerender(self, emulator: Emulator):
        """!
        @brief pre-render hook. This is called right before the specified is
        about to rendered.

        @param emulator emulator.
        """
        pass

    def postrender(self, emulator: Emulator):
        """!
        @brief post-render hook. This is called right after the specified
        finished rendering.

        @param emulator emulator.
        """
        pass

    def print(self, indent: int) -> str:
        return ' ' * indent + '{}Hook: targeting {}\n'.format(self.getName(), self.getTargetLayer())
