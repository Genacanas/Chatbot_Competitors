import httpx
import asyncio
from typing import Any

from .base import BaseExtractor


class ShopifyExtractor(BaseExtractor):
    """
    Extractor para sitios Shopify. 
    Usa la API pública /products.json para extraer productos rápidamente sin scrapeo visual.
    """
    
    async def discover_products(self) -> list[str]:
        # Para Shopify, devolvemos un string especial indicando que extraemos todo paginado
        # O podemos devolver los números de páginas
        return ["API_PAGINATION_JOB"]

    async def extract_all(self, product_urls: list[str], limit: int = None) -> list[dict[str, Any]]:
        # En Shopify ignoramos las URLs ya que extraemos todo via API
        api_base = self.fingerprint.api_base
        if not api_base:
            api_base = f"{self.fingerprint.base_url}/products.json"
        
        base_url = self.fingerprint.base_url
        print(f"[ShopifyExtractor] Iniciando extracción vía API para {base_url}")
        
        products = []
        page = 1
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while True:
                if limit and len(products) >= limit:
                    break
                    
                url = f"{api_base}?limit=250&page={page}"
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    
                    batch = data.get("products", [])
                    if not batch:
                        break
                        
                    for sp in batch:
                        if limit and len(products) >= limit:
                            break
                            
                        # Convertir modelo crudo Shopify a dict crudo normalizable
                        # Tomar el precio de la primera variante como default
                        price = 0.0
                        if sp.get("variants") and len(sp["variants"]) > 0:
                            price_str = sp["variants"][0].get("price", "0.0")
                            try:
                                price = float(price_str)
                            except ValueError:
                                price = 0.0
                        
                        images = [img.get("src") for img in sp.get("images", []) if img.get("src")]
                        
                        raw_dict = {
                            "source_url": f"{self.fingerprint.base_url}/products/{sp.get('handle')}",
                            "name": sp.get("title", ""),
                            "description": sp.get("body_html", ""),
                            "price": price,
                            "currency": "EUR", # Shopify API no siempre da la moneda en endpoint /products.json
                            "brand": sp.get("vendor", ""),
                            "images": images,
                            "tags": sp.get("tags", []),
                            "raw_data": sp
                        }
                        products.append(raw_dict)
                    
                    print(f"[ShopifyExtractor] Página {page} - {len(batch)} productos (Total: {len(products)})")
                    page += 1
                    
                    # Pequeña pausa para no saturar la API
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    print(f"[ShopifyExtractor] Error en página {page}: {e}")
                    break
        if products:
            products = await self._translate_products_batch(products)
            
        return products

    async def _translate_products_batch(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Traduce los textos de los productos extraídos al inglés usando LLM (gpt-4o-mini) en lotes."""
        import os
        import json
        from openai import AsyncOpenAI
        from bs4 import BeautifulSoup
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[ShopifyExtractor] No OPENAI_API_KEY, saltando traducción.")
            return products
            
        client = AsyncOpenAI(api_key=api_key)
        
        # Limpiar HTML del body_html antes de enviar para no gastar tokens
        def clean_desc(html_str):
            if not html_str: return ""
            soup = BeautifulSoup(html_str, "html.parser")
            return soup.get_text(separator=" ").strip()[:1000] # Solo 1000 chars

        # Armar el batch
        batch_size = 20
        translated_products = []
        
        print(f"[ShopifyExtractor] Traduciendo {len(products)} productos al inglés...")
        
        for i in range(0, len(products), batch_size):
            chunk = products[i:i+batch_size]
            
            # Payload mínimo
            payload = []
            for idx, p in enumerate(chunk):
                payload.append({
                    "id": idx,
                    "name": p["name"],
                    "brand": p["brand"],
                    "description": clean_desc(p["description"]),
                    "tags": p["tags"]
                })
                
            prompt = f"""You are a translator. Translate the following JSON list of products to English.
Only translate 'name', 'brand', 'description', and 'tags'. Keep the structure exactly the same.
Return ONLY valid JSON array.

{json.dumps(payload, ensure_ascii=False)}"""

            try:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                
                if hasattr(response, 'usage') and response.usage:
                    if not hasattr(self, 'total_tokens_used'):
                        self.total_tokens_used = 0
                    self.total_tokens_used += response.usage.total_tokens
                
                res_text = response.choices[0].message.content.strip()
                if res_text.startswith("```json"): res_text = res_text[7:]
                if res_text.startswith("```"): res_text = res_text[3:]
                if res_text.endswith("```"): res_text = res_text[:-3]
                
                translated_chunk = json.loads(res_text.strip())
                
                # Merge back
                for t_item in translated_chunk:
                    idx = t_item.get("id")
                    if idx is not None and 0 <= idx < len(chunk):
                        orig = chunk[idx]
                        orig["name"] = t_item.get("name", orig["name"])
                        orig["brand"] = t_item.get("brand", orig["brand"])
                        orig["description"] = t_item.get("description", orig["description"])
                        orig["tags"] = t_item.get("tags", orig["tags"])
                        
            except Exception as e:
                print(f"[ShopifyExtractor] Error traduciendo batch {i}: {e}")
                
            translated_products.extend(chunk)
            
        return translated_products
