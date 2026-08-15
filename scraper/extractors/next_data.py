import json
import asyncio
from typing import Any
import httpx
from bs4 import BeautifulSoup
import re

from .base import BaseExtractor


class NextDataExtractor(BaseExtractor):
    """
    Extractor para sitios Next.js (como zooroyal.de).
    Busca <script id="__NEXT_DATA__"> y extrae información.
    """
    
    async def discover_products(self) -> list[str]:
        # Para Zooroyal / Next.js requeriría navegar por categorías
        # Por simplicidad del prototipo, probaremos con la home buscando links
        base_url = self.fingerprint.base_url
        urls = set()
        
        print(f"[NextDataExtractor] Descubriendo productos en {base_url}")
        
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(base_url)
                soup = BeautifulSoup(response.text, "html.parser")
                
                for a in soup.find_all("a", href=True):
                    link = a["href"]
                    if link.startswith("/"):
                        link = f"{base_url.rstrip('/')}{link}"
                    elif not link.startswith("http"):
                        continue
                        
                    if base_url not in link:
                        continue
                        
                    h = link.lower()
                    is_prod = False
                    if any(x in h for x in ["/p/", "/product/", "/item/", "/produkt/", "/artikel/"]):
                        is_prod = True
                    else:
                        parts = [p for p in h.split("/") if p]
                        last_part = parts[-1] if parts else ""
                        if last_part.count("-") >= 3 or ("/" in link and re.search(r'\d{6,}', link)):
                            is_prod = True
                        elif "/shop/" in h and len(parts) >= 3:
                            is_prod = True
                            
                    if is_prod:
                        urls.add(link)
                    
            if len(urls) < 5:
                print(f"[NextDataExtractor] Pocas URLs encontradas, intentando con Playwright fallback en {base_url}")
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(base_url, wait_until="networkidle", timeout=30000)
                    # Scroll to trigger lazy loads
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)
                    
                    hrefs = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a'))
                            .map(a => a.href)
                            .filter(href => {
                                if (!href.startsWith(window.location.origin)) return false;
                                const h = href.toLowerCase();
                                if (h.includes('/p/') || h.includes('/product/') || h.includes('/item/') || h.includes('/produkt/') || h.includes('/artikel/')) return true;
                                const parts = h.split('/').filter(Boolean);
                                const lastPart = parts[parts.length - 1] || '';
                                if (lastPart.split('-').length - 1 >= 3) return true;
                                if (/\\d{6,}/.test(h)) return true;
                                if (h.includes('/shop/') && parts.length >= 3) return true;
                                return false;
                            })
                    }''')
                    for href in hrefs:
                        urls.add(href)
                    await browser.close()
                    
        except Exception as e:
            print(f"[NextDataExtractor] Error en discovery: {e}")
            
        print(f"[NextDataExtractor] Encontradas {len(urls)} URLs potenciales")
        return list(urls)

    async def _extract_single_product(self, client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        try:
            response = await client.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Intentar primero con __NEXT_DATA__ si existe
            next_data_script = soup.find("script", id="__NEXT_DATA__")
            if next_data_script and next_data_script.string:
                try:
                    data = json.loads(next_data_script.string)
                    # Lógica específica de Zooroyal Commercetools si existiera
                except:
                    pass
                    
            # Fallback a JSON-LD schema.org (universal para Next.js y otros SSR)
            schema_scripts = soup.find_all("script", type="application/ld+json")
            for script in schema_scripts:
                if not script.string:
                    continue
                try:
                    schema = json.loads(script.string)
                    if isinstance(schema, list):
                        schemas = schema
                    else:
                        schemas = [schema]
                        
                    for s in schemas:
                        if s.get("@type") in ["Product", "ProductGroup"]:
                            # Encontramos el producto o grupo de productos!
                            target = s
                            
                            # Si es ProductGroup, la info útil (name, image, description) 
                            # suele estar dentro del primer 'hasVariant'
                            if target.get("@type") == "ProductGroup" and target.get("hasVariant"):
                                variants = target.get("hasVariant")
                                if isinstance(variants, list) and len(variants) > 0:
                                    # Usamos la primera variante como fuente de datos base
                                    variant = variants[0]
                                    
                                    t_name = target.get("name", "")
                                    if not t_name or t_name.startswith("ProductGroup"):
                                        target["name"] = variant.get("name", "")
                                        
                                    t_desc = target.get("description", "")
                                    if not t_desc:
                                        target["description"] = variant.get("description", "")
                                        
                                    t_img = target.get("image", [])
                                    if not t_img:
                                        target["image"] = variant.get("image", [])
                                        
                                    t_brand = target.get("brand", "")
                                    if not t_brand:
                                        target["brand"] = variant.get("brand", "")
                                    
                            name = target.get("name", "")
                            description = target.get("description", "")
                            
                            raw_images = target.get("image", [])
                            if isinstance(raw_images, str):
                                raw_images = [raw_images]
                            elif not isinstance(raw_images, list):
                                raw_images = [raw_images]
                            
                            images = []
                            for img in raw_images:
                                if isinstance(img, str):
                                    images.append(img)
                                elif isinstance(img, dict):
                                    # Podría ser ImageObject de schema.org
                                    img_url = img.get("url") or img.get("contentUrl")
                                    if img_url and isinstance(img_url, str):
                                        images.append(img_url)
                                        
                            sku = target.get("sku", target.get("productGroupID", ""))
                            brand = target.get("brand", {}).get("name", "") if isinstance(target.get("brand"), dict) else target.get("brand", "")
                            
                            offers = target.get("offers", {})
                            if isinstance(offers, dict) and "offers" in offers:
                                offers = offers["offers"]
                                
                            if isinstance(offers, list) and len(offers) > 0:
                                offers = offers[0]
                                
                            price = float(offers.get("price", 0.0)) if isinstance(offers, dict) else 0.0
                            currency = offers.get("priceCurrency", "EUR") if isinstance(offers, dict) else "EUR"
                            
                            if price == 0.0 and target.get("hasVariant"):
                                variants = target.get("hasVariant")
                                if isinstance(variants, list) and len(variants) > 0:
                                    v_offers = variants[0].get("offers", {})
                                    if isinstance(v_offers, dict) and "offers" in v_offers:
                                        v_offers = v_offers["offers"]
                                    if isinstance(v_offers, list) and len(v_offers) > 0:
                                        v_offers = v_offers[0]
                                    if isinstance(v_offers, dict):
                                        price = float(v_offers.get("price", 0.0))
                                        currency = v_offers.get("priceCurrency", "EUR")
                            
                            # Limpiar nombre si es necesario
                            if not name and target.get("productGroupID"):
                                name = f"ProductGroup {target.get('productGroupID')}"
                                
                            return {
                                "source_url": url,
                                "name": name,
                                "description": description,
                                "price": price,
                                "currency": currency,
                                "sku": sku,
                                "brand": brand,
                                "images": images,
                                "raw_data": {"schema_org": target}
                            }
                except json.JSONDecodeError:
                    continue
                        
        except Exception as e:
            print(f"[NextDataExtractor] Error scrapeando {url}: {e}")
            
        return None

    async def extract_all(self, product_urls: list[str], limit: int = None) -> list[dict[str, Any]]:
        products = []
        urls_to_process = product_urls[:limit] if limit else product_urls
        semaphore = asyncio.Semaphore(10)
        
        async def process_url(client, url, idx, total):
            async with semaphore:
                print(f"[NextDataExtractor] Procesando {idx}/{total}: {url}")
                await asyncio.sleep(0.5) # Pequeño delay para no saturar
                try:
                    return await self._extract_single_product(client, url)
                except Exception as e:
                    print(f"[NextDataExtractor] Error inesperado en {url}: {e}")
                    return None

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            tasks = [
                process_url(client, url, i+1, len(urls_to_process)) 
                for i, url in enumerate(urls_to_process)
            ]
            results = await asyncio.gather(*tasks)
            
            for prod in results:
                if prod:
                    products.append(prod)
                
        return products
