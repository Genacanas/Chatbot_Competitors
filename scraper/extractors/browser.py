import json
import asyncio
from typing import Any
import os
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from openai import AsyncOpenAI

from .base import BaseExtractor
from config.prompts import PRODUCT_EXTRACTION_PROMPT

class BrowserExtractor(BaseExtractor):
    """
    Extractor universal usando Playwright y Gemini 2.5 Flash a través de Kie.ai
    """
    
    def __init__(self, fingerprint):
        super().__init__(fingerprint)
        api_key = os.getenv("KIE_API_KEY")
        if api_key:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.kie.ai/gemini-2.5-flash/v1",
            )
            # El identificador de modelo puede variar en Kie.ai, probaremos con gemini-2.5-flash
            self.model = "gemini-2.5-flash"
        else:
            self.client = None
            
        self.total_tokens_used = 0

    async def discover_products(self) -> list[str]:
        base_url = self.fingerprint.base_url
        urls = set()
        
        print(f"[BrowserExtractor] Descubriendo productos en {base_url} vía Playwright")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(base_url, wait_until="networkidle", timeout=30000)
                
                # Extraer todos los links usando JS para mayor rapidez
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
                    
            except Exception as e:
                print(f"[BrowserExtractor] Error en discovery: {e}")
            finally:
                await browser.close()
                
        print(f"[BrowserExtractor] Encontradas {len(urls)} URLs potenciales")
        return list(urls)

    def _clean_html(self, html: str) -> str:
        """Remueve tags no útiles y extrae solo el contenedor del producto para ahorrar tokens."""
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Eliminar tags ruidosos en todo el documento por si falla el paso 2
        for tag in soup(["script", "style", "noscript", "svg", "path", "nav", "footer", "header", "aside"]):
            tag.decompose()
            
        # 2. Intentar encontrar el contenedor principal del producto
        main_content = None
        for selector in ['main', 'article', '#product', '.product', '#content', '.content']:
            found = soup.select_one(selector)
            if found:
                main_content = found
                break
                
        if main_content:
            soup = main_content
            
        # 3. Serializar y limitar a 25,000 caracteres
        clean_text = str(soup)
        if len(clean_text) > 25000:
            clean_text = clean_text[:25000]
            
        return clean_text

    async def _extract_single_product(self, browser, url: str) -> dict[str, Any] | None:
        if not self.client:
            print("[BrowserExtractor] Error: KIE_API_KEY no configurada.")
            return None
            
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Scroll para forzar lazy loading de imágenes
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            
            raw_html = await page.content()
            clean_html = self._clean_html(raw_html)
            
            prompt = PRODUCT_EXTRACTION_PROMPT.format(html_content=clean_html)
            
            print(f"[BrowserExtractor] Enviando HTML a Gemini vía Kie.ai (longitud: {len(clean_html)} chars)")
            
            response = await self.client.chat.completions.create(
                model="google/gemini-2.5-flash", # Intentar formato largo para proxys multimodelo
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            
            if not response.choices or not response.choices[0].message.content:
                print(f"[BrowserExtractor] Respuesta vacía o error del LLM: {response}")
                return None
                
            if hasattr(response, 'usage') and response.usage:
                self.total_tokens_used += response.usage.total_tokens
                
            result_text = response.choices[0].message.content.strip()
            # Limpiar posible markdown block
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            data = json.loads(result_text.strip())
            
            data["source_url"] = url
            return data
            
        except json.JSONDecodeError as e:
            print(f"[BrowserExtractor] Error parseando respuesta LLM para {url}: {e}\nRaw: {result_text}")
        except Exception as e:
            print(f"[BrowserExtractor] Error scrapeando {url}: {e}")
        finally:
            await page.close()
            
        return None

    async def extract_all(self, product_urls: list[str], limit: int = None) -> list[dict[str, Any]]:
        products = []
        urls_to_process = product_urls[:limit] if limit else product_urls
        semaphore = asyncio.Semaphore(3) # Límite conservador de 3 browsers paralelos
        
        async def process_url(browser, url, idx, total):
            async with semaphore:
                print(f"[BrowserExtractor] Procesando {idx}/{total}: {url}")
                try:
                    return await self._extract_single_product(browser, url)
                except Exception as e:
                    print(f"[BrowserExtractor] Error inesperado en {url}: {e}")
                    return None
                    
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            tasks = [
                process_url(browser, url, i+1, len(urls_to_process))
                for i, url in enumerate(urls_to_process)
            ]
            
            results = await asyncio.gather(*tasks)
            
            for prod in results:
                if prod:
                    products.append(prod)
                    
            await browser.close()
                
        return products
