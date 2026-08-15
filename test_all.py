import asyncio
import csv
import time
from rich.console import Console
from rich.table import Table
from scraper.pipeline import ScraperPipeline
from scraper.repositories.neon_repo import NeonRepository

console = Console()

DOMAINS = [
    "alphazoo.de",
    "aniforte.de",
    "bitiba.de",
    "dehner.de",
    "fressnapf.de",
    "futterhaus.de",
    "kika.lt",
    "koelle-zoo.de",
    "petsdeli.de",
    "tiierisch.de",
    "vet-concept.com",
    "zooplus.de",
    "zooroyal.de"
]

async def run_massive_test():
    console.print("[bold cyan]Iniciando Prueba Masiva de 13 Dominios (Límite 50)[/bold cyan]")
    
    # Initialize DB (wake it up)
    repo = NeonRepository()
    try:
        await repo._init_pool()
        console.print("[green]Conexión a Neon DB establecida exitosamente.[/green]")
        # Limpiar la DB para que sea una prueba limpia (opcional, pero útil)
        async with repo.pool.acquire() as conn:
            await conn.execute("DELETE FROM products;")
        console.print("[green]Base de datos vaciada para la prueba.[/green]")
    except Exception as e:
        console.print(f"[red]Error conectando a la BD: {e}[/red]")
        return
    finally:
        await repo.close()

    results = []
    total_start = time.time()
    
    for i, domain in enumerate(DOMAINS, 1):
        url = f"https://www.{domain}"
        console.print(f"\n[bold yellow]({i}/{len(DOMAINS)}) Procesando {url}...[/bold yellow]")
        
        try:
            res = await ScraperPipeline.scrape(url, limit=50)
            results.append({
                "Domain": domain,
                "Platform": res.platform,
                "Extracted": res.total_extracted,
                "Time_sec": round(res.execution_time_seconds, 2),
                "LLM_Tokens": res.llm_tokens_used,
                "Emb_Tokens": res.embedding_tokens_used,
                "Cost_USD": round(res.estimated_cost_usd, 5),
                "Status": "OK" if res.total_extracted > 0 else "NO_PRODUCTS"
            })
        except Exception as e:
            console.print(f"[bold red]Error con {domain}: {e}[/bold red]")
            results.append({
                "Domain": domain,
                "Platform": "ERROR",
                "Extracted": 0,
                "Time_sec": 0,
                "LLM_Tokens": 0,
                "Emb_Tokens": 0,
                "Cost_USD": 0.0,
                "Status": f"ERROR: {str(e)[:50]}"
            })
            
    total_time = time.time() - total_start
    
    # Imprimir Tabla Final
    console.print("\n[bold green]=== BALANCE FINAL ===[/bold green]")
    table = Table(title=f"Resultados de Prueba Masiva (T. Total: {total_time/60:.2f} mins)")
    table.add_column("Dominio")
    table.add_column("Plataforma")
    table.add_column("Extraídos", justify="right")
    table.add_column("Tiempo (s)", justify="right")
    table.add_column("Tokens LLM", justify="right")
    table.add_column("Tokens Emb", justify="right")
    table.add_column("Costo USD", justify="right", style="magenta")
    table.add_column("Estado")
    
    total_ext = 0
    total_cost = 0.0
    total_llm = 0
    total_emb = 0
    
    for r in results:
        table.add_row(
            r["Domain"],
            r["Platform"],
            str(r["Extracted"]),
            str(r["Time_sec"]),
            str(r["LLM_Tokens"]),
            str(r["Emb_Tokens"]),
            f"${r['Cost_USD']:.5f}",
            r["Status"]
        )
        total_ext += r["Extracted"]
        total_cost += r["Cost_USD"]
        total_llm += r["LLM_Tokens"]
        total_emb += r["Emb_Tokens"]
        
    table.add_row(
        "[bold]TOTAL[/bold]", "-", f"[bold]{total_ext}[/bold]", "-", 
        f"[bold]{total_llm}[/bold]", f"[bold]{total_emb}[/bold]", 
        f"[bold]${total_cost:.5f}[/bold]", "-"
    )
    
    console.print(table)
    
    # Exportar a CSV
    with open('test_results.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Domain", "Platform", "Extracted", "Time_sec", "LLM_Tokens", "Emb_Tokens", "Cost_USD", "Status"])
        writer.writeheader()
        writer.writerows(results)
        
    console.print("\n[bold cyan]Resultados guardados en test_results.csv[/bold cyan]")

if __name__ == '__main__':
    asyncio.run(run_massive_test())
