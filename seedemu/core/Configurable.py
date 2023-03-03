
from abc import ABCMeta
from .Emulator import Emulator

class Configurable(metaclass=ABCMeta):
    """!
    @brief Configurable class.

    Configurable classes are classes that need to be configure before rendering.
    """

    def configure(self, emulator: Emulator):
        """!
        @brief Configure the class.

        @param emulator emulator object to use.
        """
        return
