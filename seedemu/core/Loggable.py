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
        """!
        @brief helper function with common log format. Can be used by implementors of _log.
        @param name the name of the class
        @param message the message to log
        """
        print('== {}: {}'.format(name, message), file=stderr)