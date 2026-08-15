import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional

@dataclass
class SiteFingerprint:
    platform: str          # "shopify" | "nextjs" | "woocommerce" | "unknown"
    base_url: str          # "https://kika.lt"
    catalog_urls: list[str] # URLs de categorías/colecciones detectadas
    pagination_type: str   # "page_param" | "infinite_scroll" | "cursor"
    api_base: Optional[str] = None   # Si tiene API conocida: "https://kika.lt/products.json"


class SiteDetector:
    @staticmethod
    async def analyze(url: str) -> SiteFingerprint:
        """
        Analiza una URL para determinar la plataforma de e-commerce subyacente.
        """
        # Asegurar que url no termine en slash
        base_url = url.rstrip('/')

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                html = response.text
                headers = response.headers
                
                soup = BeautifulSoup(html, "html.parser")
                
                # 1. Chequear Shopify
                # Shopify headers o JS objects
                if "X-Shopify-Stage" in headers or "Shopify.shop" in html or "window.Shopify" in html:
                    return SiteFingerprint(
                        platform="shopify",
                        base_url=base_url,
                        catalog_urls=[f"{base_url}/collections/all"],
                        pagination_type="page_param",
                        api_base=f"{base_url}/products.json"
                    )

                # 2. Chequear Next.js
                if soup.find("script", id="__NEXT_DATA__") or "/_next/" in html:
                    return SiteFingerprint(
                        platform="nextjs",
                        base_url=base_url,
                        catalog_urls=[base_url], # En Next.js requeriría navegar o parsear menús
                        pagination_type="unknown",
                        api_base=None
                    )

                # TODO: Agregar más detecciones (WooCommerce, Magento, etc.)

                # Fallback: Unknown
                return SiteFingerprint(
                    platform="unknown",
                    base_url=base_url,
                    catalog_urls=[base_url],
                    pagination_type="unknown",
                    api_base=None
                )

        except Exception as e:
            print(f"Error analizando {url}: {e}")
            # Retornar unknown si falla para intentar browser mode
            return SiteFingerprint(
                platform="unknown",
                base_url=base_url,
                catalog_urls=[base_url],
                pagination_type="unknown"
            )
