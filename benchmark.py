import asyncio
import time
import json
import argparse
from dotenv import load_dotenv
load_dotenv()

from scraper.crawlers.sitemap_crawler import SitemapCrawler
from scraper.discovery.url_pattern_analyzer import UrlPatternAnalyzer
from scraper.extractors.browser import BrowserExtractor

async def run_benchmark(domain: str, use_smart_filter: bool, limit: int = 50, workers: int = 3, max_attempts: int = 150):
    print(f"=== INICIANDO BENCHMARK: {domain} ===")
    print(f"Modo: {'Smart Filter (B)' if use_smart_filter else 'No Filter (A)'}")
    
    start_time = time.time()
    
    # 1. Discovery
    print("\n--- Fase 1: Discovery ---")
    base_url = f"https://www.{domain}"
    raw_urls, has_explicit = await SitemapCrawler.discover_product_urls(base_url)
    
    print(f"URLs descubiertas en sitemaps: {len(raw_urls)}")
    
    urls_to_process = raw_urls
    pattern_derived = None
    
    # 2. Smart Filter (Si aplica)
    if use_smart_filter:
        print("\n--- Fase 2: Smart Filter ---")
        if has_explicit:
            print("Sitemap explícito detectado. Confiando 100% en las URLs (saltando LLM).")
        else:
            analyzer = UrlPatternAnalyzer()
            pattern = await analyzer.derive_pattern(domain, raw_urls)
            if pattern:
                pattern_derived = pattern
                urls_to_process = analyzer.filter_urls(raw_urls, pattern)
            else:
                print("Fallback a heurística...")
                urls_to_process = [u for u in raw_urls if SitemapCrawler._is_product_url_heuristic(u)]
    else:
        # Modo A: usar heurística vieja para no mandarle 34k URLs al extractor
        print("Aplicando heurística vieja (Modo A)...")
        urls_to_process = [u for u in raw_urls if SitemapCrawler._is_product_url_heuristic(u)]
        
    print(f"URLs a procesar después del filtro: {len(urls_to_process)}")
    
    # 3. Extracción
    print("\n--- Fase 3: Extracción ---")
    extractor = BrowserExtractor("benchmark_fp")
    
    # Override max_attempts in extractor logic
    # In browser.py, max_attempts is (limit * 3). We want to cap it to max_attempts.
    # To avoid changing browser.py just for benchmark, we pass limit, and browser.py uses limit*3.
    # For limit=50, limit*3 = 150.
    products = await extractor.extract_all(urls_to_process, limit=limit)
    
    end_time = time.time()
    exec_time = end_time - start_time
    
    print(f"\nExtracción completada. {len(products)} productos obtenidos.")
    
    # 4. Guardar resultados
    mode_name = "B_smart_filter" if use_smart_filter else "A_no_filter"
    
    stats = {
        "mode": mode_name,
        "domain": domain,
        "config": {
            "limit": limit,
            "browser_workers": workers,
            "html_max_chars": 25000
        },
        "sitemap_stats": {
            "total_urls_discovered": len(raw_urls),
            "urls_after_filter": len(urls_to_process),
            "pattern_derived": pattern_derived,
            "pattern_cost_usd": 0.0005 if pattern_derived else 0.0
        },
        "extraction_stats": {
            "urls_attempted": 150 if len(products) < limit else "unknown", # Approximation
            "urls_successful": len(products),
            "total_llm_tokens": extractor.total_tokens_used,
            "total_llm_cost_usd": (extractor.total_tokens_used / 1_000_000) * 0.075,
            "execution_time_seconds": exec_time
        },
        "products_preview": products[:2] # Guardar solo los 2 primeros para no inflar el json
    }
    
    filename = f"benchmark_{domain.replace('.', '_')}_{mode_name}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)
        
    print(f"=== RESULTADOS GUARDADOS EN {filename} ===")
    print(f"Tiempo total: {exec_time:.2f}s")
    print(f"Tokens: {extractor.total_tokens_used}")
    print(f"Costo extra estimado: ${stats['extraction_stats']['total_llm_cost_usd']:.4f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", type=str, default="fressnapf.de")
    parser.add_argument("--smart", action="store_true", help="Usar Smart Filter")
    args = parser.parse_args()
    
    asyncio.run(run_benchmark(args.domain, args.smart))
