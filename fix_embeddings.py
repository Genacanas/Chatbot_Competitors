import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from scraper.repositories.neon_repo import NeonRepository
from scraper.embeddings.generator import EmbeddingGenerator

async def fix_missing_embeddings():
    repo = NeonRepository()
    embed_gen = EmbeddingGenerator()
    
    await repo._init_pool()
    
    print("Buscando productos sin embeddings en la base de datos...")
    
    # Obtener los productos que no tienen embedding
    query = "SELECT id, name, brand, categories, description FROM products WHERE embedding IS NULL"
    
    async with repo.pool.acquire() as conn:
        records = await conn.fetch(query)
        
    if not records:
        print("No se encontraron productos con embeddings faltantes. Todo está perfecto.")
        await repo.close()
        return
        
    print(f"Se encontraron {len(records)} productos sin embeddings. Iniciando proceso de vectorización...")
    
    # Procesar en lotes de 500 para ser seguros con la memoria
    batch_size = 500
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        print(f"Procesando lote {i} a {i + len(batch)}...")
        
        # Preparar los textos
        texts = []
        ids = []
        for r in batch:
            # Recrear el diccionario que espera prepare_text
            p_dict = {
                'name': r['name'],
                'brand': r['brand'],
                'categories': r['categories'],
                'description': r['description']
            }
            texts.append(embed_gen.prepare_text(p_dict))
            ids.append(r['id'])
            
        # Generar embeddings (ya incluye el chunking por debajo gracias a nuestra corrección)
        embeddings = await embed_gen.generate_batch(texts)
        
        if embeddings:
            # Actualizar en la DB
            async with repo.pool.acquire() as conn:
                async with conn.transaction():
                    for product_id, emb in zip(ids, embeddings):
                        await conn.execute("UPDATE products SET embedding = $1 WHERE id = $2", emb, product_id)
            print(f"Lote guardado exitosamente.")
        else:
            print(f"Error generando embeddings para este lote.")
            
    print("¡Proceso de vectorización completado!")
    await repo.close()

if __name__ == "__main__":
    asyncio.run(fix_missing_embeddings())
