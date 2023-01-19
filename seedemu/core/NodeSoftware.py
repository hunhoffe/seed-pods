from abc import ABCMeta, abstractmethod
from typing import Set

class NodeSoftware(object):
    """!
    @brief The NodeSoftware class

    This class repersents software to be installed on a Node
    """

    __name: str
    __installScript: str

    def __init__(self, name: str, installScript: str = None) -> None:
        """!
        @brief create a new software dependency to be installed on a Node.

        @param name name of the software, if no installScript is provided, this name will be given to the package manager
        @param installScript (optional) instead of running the apt package manager, use an install script to install.
        """
        self.__name = name
        self.__installScript = installScript

    def getName(self) -> str:
        """!
        @brief get the name of this software.

        @returns name.
        """
        return self.__name

    def usePackageManager(self) -> bool:
        """!
        @brief whether to use the install script or use the package manager.

        @returns True if the software should be installed via package manager.
        """
        return self.__installScript is None

    def getInstallScript(self) -> str:
        """!
        @brief returns the contents of the installScript.

        @return returns the contents of the installScript
        """
        return self.__installScript

    def __repr__(self) -> str:
        return f"Software(\"{self.__name}\", usPackageManager={self.usePackageManager()})"

    def __eq__(self, obj):
        return isinstance(obj, NodeSoftware) and obj.__name == self.__name and obj.__installScript == self.__installScript

    def __gt__(self, obj):
        return self.__name > obj.__name

    def __hash__(self):
        return hash(self.__name + str(self.__installScript))

class NodeSoftwareInstaller(metaclass=ABCMeta):
    """!
    @brief SoftwareInstaller class.

    Implement this abstract class for bookkeeping for software installed on nodes.
    """

    @property
    @abstractmethod
    def softwareDeps(cls) -> Set[NodeSoftware]:
        """!
        @brief get the set of ALL software this component is dependent on (i.e., may install on a node.)

        @returns set of software this component may install on a node.
        """
        raise NotImplementedError("softwareDeps not implemented.")
