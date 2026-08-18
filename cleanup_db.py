import asyncio
from dotenv import load_dotenv
load_dotenv()
from scraper.repositories.neon_repo import NeonRepository

async def cleanup():
    print("Iniciando limpieza de la base de datos...")
    repo = NeonRepository()
    await repo._init_pool()
    
    # Dominios válidos a preservar
    valid_domains = ['kika.lt', 'mustijamirri.fi']
    
    async with repo.pool.acquire() as conn:
        to_delete = await conn.fetchval(
            "SELECT count(*) FROM products WHERE site_domain != ALL($1)",
            valid_domains
        )
        print(f"Productos que NO son {valid_domains} y serán borrados: {to_delete}")
        
        if to_delete > 0:
            result = await conn.execute(
                "DELETE FROM products WHERE site_domain != ALL($1)",
                valid_domains
            )
            print(f"Resultado del borrado: {result}")
        else:
            print("Nada que borrar.")
        
    await repo.close()
    print("Limpieza finalizada.")

if __name__ == '__main__':
    asyncio.run(cleanup())
