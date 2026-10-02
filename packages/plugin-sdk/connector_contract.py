from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable


class ConnectorPlugin(ABC):
    """Base contract for all connector plugins."""

    @abstractmethod
    def connect(self, configuration: Dict[str, Any]) -> Any:
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def sync(self) -> Iterable[Dict[str, Any]]:
        pass

    @abstractmethod
    def incremental_sync(self, cursor: str | None = None) -> Iterable[Dict[str, Any]]:
        pass

    @abstractmethod
    def map_metadata(self, item: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def map_permissions(self, item: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        pass
