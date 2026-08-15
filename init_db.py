import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def init_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL no está definida en .env")
        return
        
    print(f"Conectando a {db_url.split('@')[1]}...")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        # 1. Crear extensión pgvector
        print("Creando extensión vector...")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # 2. Crear tabla products
        print("Creando tabla products...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                site_domain   TEXT NOT NULL,
                source_url    TEXT NOT NULL,
                name          TEXT NOT NULL,
                brand         TEXT,
                sku           TEXT,
                price         NUMERIC(10, 2),
                original_price NUMERIC(10, 2),
                currency      TEXT DEFAULT 'EUR',
                description   TEXT,
                categories    TEXT[],
                images        TEXT[],
                scraped_at    TIMESTAMPTZ DEFAULT NOW(),
                embedding     vector(768),
                UNIQUE(site_domain, source_url)
            );
        """)
        
        # 3. Crear tabla scraping_jobs
        print("Creando tabla scraping_jobs...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scraping_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                site_domain TEXT NOT NULL,
                platform TEXT,
                status TEXT DEFAULT 'pending',
                "limit" INT,
                total_urls_discovered INT DEFAULT 0,
                total_urls_queued INT DEFAULT 0,
                total_extracted INT DEFAULT 0,
                url_pattern TEXT,
                pattern_source TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            );
        """)
        
        # 3.1 Crear tabla scraping_queue
        print("Creando tabla scraping_queue...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scraping_queue (
                id BIGSERIAL PRIMARY KEY,
                job_id UUID REFERENCES scraping_jobs(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                attempts INT DEFAULT 0,
                error_message TEXT,
                processed_at TIMESTAMPTZ,
                UNIQUE(job_id, url)
            );
        """)
        
        # 4. Crear índice vectorial
        print("Creando índice vectorial IVFFlat (puede tardar un momento)...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS products_embedding_idx 
            ON products USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        
        print("✅ Base de datos inicializada correctamente.")
        await conn.close()
        
    except Exception as e:
        print(f"❌ Error al inicializar DB: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
