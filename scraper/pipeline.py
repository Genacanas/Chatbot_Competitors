from dataclasses import dataclass
import time
from typing import Any

from .detector.site_detector import SiteDetector
from .extractors.shopify import ShopifyExtractor
from .extractors.next_data import NextDataExtractor
from .extractors.browser import BrowserExtractor
from .normalizer.product_normalizer import ProductNormalizer
from .repositories.neon_repo import NeonRepository
from .embeddings.generator import EmbeddingGenerator
from .discovery.url_pattern_analyzer import UrlPatternAnalyzer
from .crawlers.sitemap_crawler import SitemapCrawler

@dataclass
class ScrapingResult:
    total_extracted: int
    site_domain: str
    platform: str
    execution_time_seconds: float = 0.0
    llm_tokens_used: int = 0
    embedding_tokens_used: int = 0
    estimated_cost_usd: float = 0.0

class ScraperPipeline:
    @staticmethod
    async def scrape(url: str, limit: int = None, batch_size: int = 50) -> ScrapingResult:
        start_time = time.time()
        print(f"\n[Pipeline] Iniciando scraping para: {url}")
        
        domain = ProductNormalizer.extract_domain(url)
        repo = NeonRepository()
        
        # 1. Detectar plataforma
        fingerprint = await SiteDetector.analyze(url)
        print(f"[Pipeline] Plataforma detectada: {fingerprint.platform.upper()}")
        
        # 2. Inicializar o Recuperar Job
        job = await repo.get_resumable_job(domain)
        if job:
            job_id = job['id']
            print(f"[Pipeline] Reanudando job existente: {job_id}")
            # limit could be updated but we keep the original job's limit for consistency
            if job['limit']: limit = job['limit']
        else:
            job_id = await repo.create_job(domain, fingerprint.platform, limit)
            print(f"[Pipeline] Nuevo job creado: {job_id}")
            job = {'status': 'pending', 'total_extracted': 0, 'limit': limit}

        # 3. Descubrir y Encolar URLs (si es un job nuevo)
        if job['status'] == 'pending':
            print("[Pipeline] Fase de descubrimiento...")
            if fingerprint.platform == "shopify":
                extractor = ShopifyExtractor(fingerprint)
                product_urls = await extractor.discover_products()
                await repo.set_total_urls_discovered(job_id, len(product_urls))
                await repo.enqueue_urls(job_id, product_urls)
            else:
                raw_urls, has_explicit = await SitemapCrawler.discover_product_urls(fingerprint.base_url)
                await repo.set_total_urls_discovered(job_id, len(raw_urls))
                
                urls_to_queue = raw_urls
                if has_explicit:
                    print("[Pipeline] Sitemap explícito de productos detectado. Encolando URLs.")
                    await repo.update_job_pattern(job_id, "EXPLICIT_SITEMAP", "heuristic")
                else:
                    analyzer = UrlPatternAnalyzer()
                    pattern = await analyzer.derive_pattern(domain, raw_urls)
                    if pattern:
                        urls_to_queue = analyzer.filter_urls(raw_urls, pattern)
                        await repo.update_job_pattern(job_id, pattern, "llm")
                    else:
                        print("[Pipeline] Fallback a heurística estándar.")
                        urls_to_queue = [u for u in raw_urls if SitemapCrawler._is_product_url_heuristic(u)]
                        await repo.update_job_pattern(job_id, "HEURISTIC", "heuristic")
                        
                if not urls_to_queue:
                    print("[Pipeline] No se encontraron URLs después del filtro. Abortando.")
                    await repo.complete_job(job_id, failed=True)
                    await repo.close()
                    return ScrapingResult(0, domain, fingerprint.platform, execution_time_seconds=time.time() - start_time)
                
                await repo.enqueue_urls(job_id, urls_to_queue)
                
        # 4. Seleccionar extractor
        if fingerprint.platform == "shopify":
            extractor = ShopifyExtractor(fingerprint)
        elif fingerprint.platform == "nextjs":
            extractor = NextDataExtractor(fingerprint)
        else:
            extractor = BrowserExtractor(fingerprint)

        embed_gen = EmbeddingGenerator()
        total_extracted = job.get('total_extracted', 0)
        
        # 5. Loop de procesamiento de colas
        while True:
            # Check limit globally
            if limit and total_extracted >= limit:
                print(f"[Pipeline] Límite global alcanzado ({limit}).")
                break
                
            batch_urls = await repo.claim_pending_urls(job_id, limit=batch_size)
            if not batch_urls:
                print("[Pipeline] No hay más URLs pendientes en la cola.")
                break
                
            print(f"\n[Pipeline] Procesando batch de {len(batch_urls)} URLs...")
            
            # Extraer
            raw_products = await extractor.extract_all(batch_urls, limit=None)
            
            successful_urls = set()
            normalized_products = []
            
            # Normalizar
            for p in raw_products:
                if not p: continue
                source_url = p.get('source_url')
                
                # Check for valid name before processing
                if not p.get('name') or str(p.get('name')).strip() == "":
                    print(f"[Pipeline] Descartando producto sin nombre: {source_url}")
                    # No lo marcamos como exitoso
                    continue
                    
                successful_urls.add(source_url)
                
                if "site_domain" not in p:
                    p["site_domain"] = domain
                try:
                    norm_p = ProductNormalizer.normalize(p)
                    normalized_products.append(norm_p)
                except Exception as e:
                    print(f"[Pipeline] Error normalizando producto {source_url}: {e}")
                    successful_urls.discard(source_url)
                    
            from dataclasses import asdict
            dict_products = [asdict(p) for p in normalized_products]
            
            # Batch Embeddings
            if embed_gen.client and dict_products:
                texts = [embed_gen.prepare_text(p) for p in dict_products]
                vectors = await embed_gen.generate_batch(texts)
                if vectors:
                    for p, vec in zip(dict_products, vectors):
                        p["embedding"] = vec

            # Guardar en DB
            if dict_products:
                await repo.save_products(dict_products, domain)
            
            # Actualizar estados en cola
            for url in batch_urls:
                if url in successful_urls:
                    await repo.mark_url_done(job_id, url)
                    total_extracted += 1
                else:
                    await repo.mark_url_failed(job_id, url, "Extracción fallida o producto vacío.")
                    
        # 6. Finalizar Job
        await repo.complete_job(job_id)
        
        llm_tokens = getattr(extractor, 'total_tokens_used', 0)
        embedding_tokens = embed_gen.total_tokens_used
        
        cost_emb = (embedding_tokens / 1_000_000.0) * 0.02
        cost_llm = (llm_tokens / 1_000_000.0) * 0.075
        
        await repo.close()
        
        return ScrapingResult(
            total_extracted=total_extracted,
            site_domain=domain,
            platform=fingerprint.platform,
            execution_time_seconds=time.time() - start_time,
            llm_tokens_used=llm_tokens,
            embedding_tokens_used=embedding_tokens,
            estimated_cost_usd=cost_emb + cost_llm
        )
