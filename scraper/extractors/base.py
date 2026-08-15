from abc import ABC, abstractmethod
from typing import Any

from ..detector.site_detector import SiteFingerprint


class BaseExtractor(ABC):
    def __init__(self, fingerprint: SiteFingerprint):
        self.fingerprint = fingerprint

    @abstractmethod
    async def discover_products(self) -> list[str]:
        """
        Descubre las URLs (o identificadores) de los productos del sitio.
        """
        pass

    @abstractmethod
    async def extract_all(self, product_urls: list[str], limit: int = None) -> list[dict[str, Any]]:
        """
        Extrae la data en bruto (diccionarios crudos) dado una lista de URLs/IDs.
        El pipeline luego pasará esto por el normalizador.
        """
        pass
