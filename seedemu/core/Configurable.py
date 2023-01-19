from abc import ABCMeta, abstractmethod
from .Emulator import Emulator

class Configurable(metaclass=ABCMeta):
    """!
    @brief Configurable class.

    Configurable classs are classes that need to be configured before rendering.
    """

    def configure(self, emulator: Emulator):
        """!
        @brief Configure the class.

        @param emulator emulator object to use.
        """
        return