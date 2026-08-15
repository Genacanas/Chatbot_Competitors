import os
import json
import asyncpg
from pgvector.asyncpg import register_vector
from typing import List, Dict

class NeonRepository:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.pool = None

    async def _init_pool(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.db_url)
            # Register pgvector type
            async with self.pool.acquire() as conn:
                await register_vector(conn)

    async def save_products(self, products: List[Dict], domain: str) -> None:
        if not products:
            return
            
        await self._init_pool()
        
        async with self.pool.acquire() as conn:
            # Upsert logic (insert or update on conflict)
            for p in products:
                # Convert list to array for asyncpg
                categories = p.get("categories", [])
                images = p.get("images", [])
                embedding = p.get("embedding")
                
                await conn.execute("""
                    INSERT INTO products (
                        site_domain, source_url, name, brand, sku, 
                        price, original_price, currency, description, 
                        categories, images, embedding
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                    ) ON CONFLICT (site_domain, source_url) DO UPDATE SET
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        original_price = EXCLUDED.original_price,
                        description = EXCLUDED.description,
                        embedding = EXCLUDED.embedding,
                        scraped_at = NOW()
                """, 
                domain, p.get("source_url"), p.get("name"), p.get("brand"), p.get("sku"),
                p.get("price"), p.get("original_price"), p.get("currency", "EUR"), 
                p.get("description"), categories, images, embedding)
                
        print(f"[NeonRepository] Guardados/Actualizados {len(products)} productos para {domain}.")

    async def get_resumable_job(self, domain: str) -> Dict | None:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM scraping_jobs 
                WHERE site_domain = $1 AND status IN ('pending', 'running')
                ORDER BY created_at DESC LIMIT 1
            """, domain)
            if row:
                # Si había un job running, marcamos las processing como pending de nuevo
                if row['status'] == 'running':
                    await conn.execute("""
                        UPDATE scraping_queue SET status = 'pending'
                        WHERE job_id = $1 AND status = 'processing'
                    """, row['id'])
                return dict(row)
            return None

    async def create_job(self, domain: str, platform: str, limit: int = None) -> str:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            job_id = await conn.fetchval("""
                INSERT INTO scraping_jobs (site_domain, platform, "limit")
                VALUES ($1, $2, $3) RETURNING id
            """, domain, platform, limit)
            return str(job_id)

    async def update_job_pattern(self, job_id: str, pattern: str, source: str) -> None:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_jobs SET url_pattern = $1, pattern_source = $2
                WHERE id = $3
            """, pattern, source, job_id)

    async def enqueue_urls(self, job_id: str, urls: List[str]) -> None:
        if not urls: return
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_jobs 
                SET total_urls_queued = total_urls_queued + $1,
                    status = 'running',
                    started_at = COALESCE(started_at, NOW())
                WHERE id = $2
            """, len(urls), job_id)
            
            # Insert urls efficiently using executemany
            data = [(job_id, u) for u in urls]
            await conn.executemany("""
                INSERT INTO scraping_queue (job_id, url)
                VALUES ($1, $2)
                ON CONFLICT (job_id, url) DO NOTHING
            """, data)

    async def set_total_urls_discovered(self, job_id: str, total: int) -> None:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_jobs SET total_urls_discovered = $1 WHERE id = $2
            """, total, job_id)

    async def claim_pending_urls(self, job_id: str, limit: int = 10) -> List[str]:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                WITH claimed AS (
                    SELECT id FROM scraping_queue
                    WHERE job_id = $1 AND status = 'pending' AND attempts < 3
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT $2
                )
                UPDATE scraping_queue sq
                SET status = 'processing',
                    attempts = sq.attempts + 1,
                    processed_at = NOW()
                FROM claimed
                WHERE sq.id = claimed.id
                RETURNING sq.url
            """, job_id, limit)
            return [r['url'] for r in rows]

    async def mark_url_done(self, job_id: str, url: str) -> None:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_queue SET status = 'done', processed_at = NOW()
                WHERE job_id = $1 AND url = $2
            """, job_id, url)
            
            await conn.execute("""
                UPDATE scraping_jobs SET total_extracted = total_extracted + 1
                WHERE id = $1
            """, job_id)

    async def mark_url_failed(self, job_id: str, url: str, error_msg: str) -> None:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_queue SET status = 'failed', error_message = $1, processed_at = NOW()
                WHERE job_id = $2 AND url = $3
            """, str(error_msg)[:500], job_id, url)

    async def complete_job(self, job_id: str, failed: bool = False) -> None:
        status = 'failed' if failed else 'completed'
        await self._init_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraping_jobs SET status = $1, completed_at = NOW()
                WHERE id = $2
            """, status, job_id)
            
    async def search_similar(self, domain: str, embedding: List[float], limit: int = 5) -> List[Dict]:
        await self._init_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, brand, source_url, price, site_domain, (1 - (embedding <=> $1::vector)) as similarity
                FROM products
                WHERE site_domain = $2
                ORDER BY embedding <=> $1::vector ASC
                LIMIT $3
            """, embedding, domain, limit)
            
            return [dict(r) for r in rows]

    async def search_similar_global(self, embedding: List[float], limit: int = 10, min_price: float = None, max_price: float = None, brand: str = None, store: str = None) -> List[Dict]:
        await self._init_pool()
        
        conditions = ["1=1"]
        args = [embedding, limit]
        arg_idx = 3
        
        if min_price is not None:
            conditions.append(f"price >= ${arg_idx}")
            args.append(min_price)
            arg_idx += 1
            
        if max_price is not None:
            conditions.append(f"price <= ${arg_idx}")
            args.append(max_price)
            arg_idx += 1
            
        if brand:
            conditions.append(f"brand ILIKE ${arg_idx}")
            args.append(f"%{brand}%")
            arg_idx += 1
            
        if store:
            conditions.append(f"site_domain = ${arg_idx}")
            args.append(store)
            arg_idx += 1
            
        where_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT name, brand, source_url, price, site_domain, (1 - (embedding <=> $1::vector)) as similarity
            FROM products
            WHERE {where_clause}
            ORDER BY embedding <=> $1::vector ASC
            LIMIT $2
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]

    async def execute_readonly_sql(self, query: str) -> List[Dict]:
        """Ejecuta una consulta SQL de solo lectura de forma segura."""
        clean_query = query.strip()
        # Eliminar bloques de código markdown si el LLM los envía
        if clean_query.lower().startswith("```sql"):
            clean_query = clean_query[6:]
        elif clean_query.startswith("```"):
            clean_query = clean_query[3:]
        if clean_query.endswith("```"):
            clean_query = clean_query[:-3]
            
        clean_query = clean_query.strip()
        
        if not clean_query.upper().startswith("SELECT") and not clean_query.upper().startswith("WITH"):
            raise ValueError("Por seguridad, el chatbot solo puede ejecutar consultas SELECT o WITH.")
            
        await self._init_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(clean_query)
            return [dict(r) for r in rows]

    async def close(self):
        if self.pool:
            await self.pool.close()
