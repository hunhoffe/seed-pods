from abc import ABCMeta, abstractmethod
from sys import stderr

class Loggable(metaclass=ABCMeta):
    """!
    @brief Loggable class.

    Implement this abstract class for printing to stdout.
    """

    @abstractmethod
    def _log(self, message) -> None:
        """!
        @brief log to standard out.
        """
        raise NotImplementedError("loggable classes must implement the log method")
        

    def __log__(self, name, message) -> None:
        print('== {}: {}'.format(name, message), file=stderr)