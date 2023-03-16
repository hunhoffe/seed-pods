from abc import ABCMeta, abstractmethod
from typing import List, Dict
from sys import stderr

class DataProvider(metaclass=ABCMeta):
    """!
    @brief data source for the topology generator.
    """

    def __init__(self):
        """!
        @brief Create a new RIS data provider.
        """
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def getName(self) -> str:
        """!
        @brief Get name of this data provider.

        @returns name of the layer.
        """
        raise NotImplementedError('getName not implemented')

    @abstractmethod
    def getPrefixes(self, asn: int) -> List[str]:
        """!
        @brief Get list of prefixes announced by the given ASN.
        @param asn asn.

        @returns list of prefixes.
        """
        raise NotImplementedError('getPrefixes not implemented.')

    @abstractmethod
    def getPeers(self, asn: int) -> Dict[int, str]:
        """!
        @brief Get a dict of peer ASNs of the given ASN.
        @param asn asn.

        @returns dict where key is asn and value is peering relationship.
        """
        raise NotImplementedError('getPeers not implemented.')

    @abstractmethod
    def getInternetExchanges(self, asn: int) -> List[int]:
        """!
        @brief Get list of internet exchanges joined by the given ASN.
        @param asn asn.

        @returns list of tuples of internet exchange ID. Use
        getInternetExchangeMembers to get other members.
        """
        raise NotImplementedError('getInternetExchanges not implemented.')

    @abstractmethod
    def getInternetExchangeMembers(self, id: int) -> Dict[int, str]:
        """!
        @brief Get internet exchange members for given IX ID.
        @param id internet exchange ID provided by getInternetExchanges.

        @returns dict where key is ASN and value is IP address in the exchange.
        Note that if an AS has multiple addresses in the IX, only one should be
        returned.
        """
        raise NotImplementedError('getInternetExchangeMembers not implemented.')

    @abstractmethod
    def getInternetExchangePrefix(self, id: int) -> str:
        """!
        @brief Get internet exchange peering lan prefix for given IX ID.
        @param id internet exchange ID provided by getInternetExchanges.

        @returns prefix in cidr format.
        """
        raise NotImplementedError('getInternetExchangeSubnet not implemented.')
