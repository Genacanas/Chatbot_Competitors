import re
import httpx
import gzip
from typing import Set

class SitemapCrawler:
    @staticmethod
    async def discover_product_urls(base_url: str, max_sitemaps: int = 5) -> tuple[list[str], bool]:
        print(f"[SitemapCrawler] Buscando sitemaps para {base_url}")
        
        sitemaps_to_visit = set()
        raw_urls: Set[str] = set()
        visited_sitemaps = set()
        has_explicit_product_sitemap = False
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
        
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            # 1. Leer robots.txt
            try:
                robots_res = await client.get(f"{base_url.rstrip('/')}/robots.txt")
                if robots_res.status_code == 200:
                    for line in robots_res.text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                sm = parts[1].strip()
                                sitemaps_to_visit.add(sm)
            except Exception as e:
                print(f"[SitemapCrawler] Error leyendo robots.txt: {e}")
                
            # Fallback
            if not sitemaps_to_visit:
                sitemaps_to_visit.add(f"{base_url.rstrip('/')}/sitemap.xml")
                
            print(f"[SitemapCrawler] Encontrados {len(sitemaps_to_visit)} sitemaps iniciales.")
            
            # 2. Recorrer sitemaps
            sitemaps_list = list(sitemaps_to_visit)
            sitemaps_processed = 0
            
            while sitemaps_list and sitemaps_processed < max_sitemaps:
                sm_url = sitemaps_list.pop(0)
                if sm_url in visited_sitemaps:
                    continue
                    
                visited_sitemaps.add(sm_url)
                print(f"[SitemapCrawler] Analizando sitemap: {sm_url}")
                
                if "product" in sm_url.lower():
                    has_explicit_product_sitemap = True
                
                try:
                    res = await client.get(sm_url)
                    if res.status_code != 200:
                        continue
                        
                    content = res.content
                    if sm_url.endswith(".gz"):
                        try:
                            content = gzip.decompress(content)
                        except:
                            pass
                            
                    text = content.decode('utf-8', errors='ignore')
                    
                    # Extraer todos los <loc>
                    locs = re.findall(r'<loc>\s*(.*?)\s*</loc>', text, re.IGNORECASE)
                    
                    # Distinguir si es sitemap index o sitemap de URLs
                    if "<sitemapindex" in text.lower() or "<sitemap>" in text.lower():
                        # Es un índice
                        product_sitemaps = [loc for loc in locs if any(kw in loc.lower() for kw in ['product', 'item', 'article', 'detail'])]
                        
                        if product_sitemaps:
                            print(f"[SitemapCrawler] Índice contiene sitemaps de productos explícitos. Ignorando el resto.")
                            locs = product_sitemaps
                        else:
                            print(f"[SitemapCrawler] Es un índice genérico. Agregando {len(locs)} sub-sitemaps a la cola.")
                            
                        # Insert at beginning to go deep
                        sitemaps_list = locs + sitemaps_list 
                    else:
                        # Son URLs finales
                        sitemaps_processed += 1
                        for loc in locs:
                            raw_urls.add(loc)
                        print(f"[SitemapCrawler] Encontradas {len(locs)} URLs crudas en este sitemap.")
                                
                except Exception as e:
                    print(f"[SitemapCrawler] Error parseando sitemap {sm_url}: {e}")
                    
        return list(raw_urls), has_explicit_product_sitemap
        
    @staticmethod
    def _is_product_url_heuristic(url: str) -> bool:
        """Heurística de fallback si el LLM no deriva patrón."""
        h = url.lower()
        if any(x in h for x in ["/p/", "/product/", "/item/", "/produkt/", "/artikel/"]):
            return True
        
        parts = [p for p in h.split("/") if p]
        last_part = parts[-1] if parts else ""
        if last_part.count("-") >= 3 or ("/" in h and re.search(r'\d{6,}', h)):
            return True
        if "/shop/" in h and len(parts) >= 3:
            return True
            
        return False
