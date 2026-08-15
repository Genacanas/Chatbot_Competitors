import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from dataclasses import dataclass, field, asdict


@dataclass
class ProductSchema:
    source_url: str
    site_domain: str
    name: str
    price: float
    # Identificación
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Datos opcionales del producto
    sku: str | None = None
    brand: str | None = None
    original_price: float | None = None
    currency: str = "EUR"
    
    # Contenido
    description: str | None = None
    images: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    
    # Estado
    in_stock: bool = True
    
    # Raw data (para debugging)
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    def model_dump(self):
        return asdict(self)


class ProductNormalizer:
    @staticmethod
    def extract_domain(url: str) -> str:
        """Extrae el dominio base de una URL."""
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    @staticmethod
    def normalize(data: dict) -> ProductSchema:
        """
        Normaliza un diccionario crudo en un ProductSchema validado.
        """
        if "site_domain" not in data and "source_url" in data:
            data["site_domain"] = ProductNormalizer.extract_domain(data["source_url"])
            
        # Limpiar data de llaves que no están en dataclass
        valid_keys = ProductSchema.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
            
        return ProductSchema(**filtered_data)
