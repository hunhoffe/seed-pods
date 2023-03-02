from __future__ import annotations
from .Printable import Printable
from typing import Tuple

class NodeFile(Printable):
    """!
    @brief NodeFile class.
    This class represents a file on a node.
    """

    __content: str
    __path: str
    __host_path: str
    __is_executable: bool

    def __init__(self, path: str, content: str = None, hostPath: str = None, isExecutable: bool = False):
        """!
        @brief NodeFile constructor.
        Put a file onto a node.
        @param path path of the file.
        @param content content of the file. Only one of content and hostPath must be specified.
        @param hostPath host path of the file. Only one of content and hostPath must be specified.
        @param isExecutable when the file should have executable permissions
        """
        assert (content is None) or (hostPath is None), "Content and hostPath cannot both be specified"
        self.__path = path
        self.__content = content
        self.__host_path = hostPath
        self.__is_executable = isExecutable

    def setPath(self, path: str) -> NodeFile:
        """!
        @brief Update file path.
        @param path new path.
        @returns self, for chaining API calls.
        """
        self.__path = path
        return self

    def getPath(self) -> str:
        """!
        @brief Get file path.
        @returns path of the file
        """
        return self.__path

    def getHostPath(self) -> str:
        """!
        @brief Get the host file path.
        @returns host path of the file
        """
        return self.__host_path

    def getContent(self) -> str:
        """!
        @brief Return the file contents.
        @returns content of the file.
        """
        return self.__content

    def hasContent(self) -> bool:
        """!
        @brief Returns if the file has contents
        @returns True if file has contents
        """
        return not ((self.__content is None) or (self.__content == ''))

    def appendContent(self, content: str) -> NodeFile:
        """!
        @brief Append to file.
        @param content content.
        @returns self, for chaining API calls.
        """
        assert self.__host_path is None, "Host path and content may not both be specified"
        if self.__content is None:
            self.__content = content
        else:
            self.__content += content

        return self

    def isExecutable(self) -> bool:
        """!
        @brief Whether the file should have executable privilege.
        @returns True is executable.
        """
        return self.__is_executable

    def print(self, indent: int) -> str:
        out = ' ' * indent
        out += "{} (hostPath={}):\n".format(self.__path, self.__host_path)
        indent += 4
        content = self.getContent()
        if (content is None) and self.__host_path:
            with open(self.__host_path, 'r') as f:
                content = f.read()
        if content:
            for line in content.splitlines():
                out += ' ' * indent
                out += '> '
                out += line
                out += '\n'
        return out

    def __eq__(self, obj):
        return isinstance(obj, NodeFile) and \
            obj.__path == self.__path and \
            obj.__is_executable == self.__is_executable and \
            obj.__host_path == self.__host_path and \
            obj.__content == self.__content
