from __future__ import annotations
from abc import ABCMeta, abstractmethod
from sys import stderr
from .Logger import get_logger

class Mergeable(metaclass=ABCMeta):
    """!
    @brief Mergeable base class
    """

    @abstractmethod
    def getTypeName(self) -> str:
        """!
        @brief Get type name of the current object. 

        @returns type name.
        """
        raise NotImplementedError("getTypeName not implemented.")

    @abstractmethod
    def shouldMerge(self, other: Mergeable) -> bool:
        """!
        @brief Test if two object should be merged, or treated as different
        objects. This is called when merging two object with the same type.
        emulator.

        @param other the other object.

        @returns true if should merge.
        """
        raise NotImplementedError("equals not implemented.")


class Merger(metaclass=ABCMeta):
    """!
    @brief Merger base class. 

    When merging, merger are invoked to do the merge.
    """

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def getName(self) -> str:
        """!
        @brief get name of the mergeable object.

        @returns name.
        """
        return self.__class__.__name__

    @abstractmethod
    def getTargetType(self) -> str:
        """!
        @brief Get the type name of objects that this merger can handle.

        @returns type name.
        """
        raise NotImplementedError("getTargetType not implemented.")

    @abstractmethod
    def doMerge(self, objectA: Mergeable, objectB: Mergeable) -> Mergeable:
        """!
        @brief Do merging.

        @param objectA first object.
        @param objectB second object.
        @returns merged object.
        """
        raise NotImplementedError("doMerge not implemented.")
