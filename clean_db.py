import asyncio
import time
from scraper.repositories.neon_repo import NeonRepository

async def clean_db():
    print("Conectando a la base de datos (con reintentos)...")
    repo = NeonRepository()
    
    for attempt in range(15):
        try:
            await repo._init_pool()
            await repo.pool.execute("DELETE FROM products;")
            print("Exito: ¡Todos los datos corruptos han sido eliminados de la tabla 'products'!")
            await repo.close()
            return
        except Exception as e:
            print(f"Intento {attempt+1} fallido: {e}. Reintentando en 4 segundos...")
            await asyncio.sleep(4)
            
    print("No se pudo conectar después de múltiples intentos.")

if __name__ == "__main__":
    asyncio.run(clean_db())
