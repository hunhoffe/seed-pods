from abc import ABCMeta, abstractmethod

class Printable(metaclass=ABCMeta):
    """!
    @brief Printable class.

    Implement this abstract class for indentable print.
    """

    @abstractmethod
    def print(self, indentation: int = 0) -> str:
        """!
        @brief get printable string.

        @param indentation indentation.

        @returns printable string.
        """

        raise NotImplementedError("print not implemented.")

    def __str__(self) -> str:
        """!
        @brief convert to string.

        alias to print(0).
        """
        return self.print(0)