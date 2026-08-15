import asyncio
import csv
import time
from collections import defaultdict
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv
load_dotenv()

from scraper.pipeline import ScraperPipeline
from scraper.repositories.neon_repo import NeonRepository

console = Console()

DOMAINS = [
    "zoomalia.com",
    "maxizoo.fr",
    "wanimo.com",
    "vetostore.com",
    "animalis.com",
    "lacompagniedesanimaux.com",
    "croquetteland.com",
    "entrenous.fr",
    "brekz.fr"
]

LIMIT_PER_DOMAIN = 600

async def run_massive_test():
    console.print(f"[bold cyan]Iniciando Extraccion Masiva FR (Limite {LIMIT_PER_DOMAIN} por dominio)[/bold cyan]")
    
    # Initialize DB (wake it up)
    repo = NeonRepository()
    try:
        await repo._init_pool()
        console.print("[green]Conexion a Neon DB establecida exitosamente.[/green]")
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
            res = await ScraperPipeline.scrape(url, limit=LIMIT_PER_DOMAIN)
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
    
    # --- TABLA 1: DOMINIOS ---
    console.print("\n[bold green]=== BALANCE FINAL POR DOMINIO ===[/bold green]")
    table = Table(title=f"Resultados de Extraccion (T. Total: {total_time/60:.2f} mins)")
    table.add_column("Dominio")
    table.add_column("Plataforma")
    table.add_column("Extraidos", justify="right")
    table.add_column("Tiempo (s)", justify="right")
    table.add_column("Tokens LLM", justify="right")
    table.add_column("Costo USD", justify="right", style="magenta")
    table.add_column("Estado")
    
    for r in results:
        table.add_row(
            r["Domain"],
            r["Platform"],
            str(r["Extracted"]),
            str(r["Time_sec"]),
            str(r["LLM_Tokens"]),
            f"${r['Cost_USD']:.5f}",
            r["Status"]
        )
    console.print(table)
    
    # --- TABLA 2: AGREGADOS POR PLATAFORMA ---
    console.print("\n[bold green]=== ESTADISTICAS POR TECNOLOGIA ===[/bold green]")
    agg = defaultdict(lambda: {"count": 0, "extracted": 0, "llm_tokens": 0, "cost": 0.0, "time": 0.0})
    
    for r in results:
        plat = r["Platform"]
        agg[plat]["count"] += 1
        agg[plat]["extracted"] += r["Extracted"]
        agg[plat]["llm_tokens"] += r["LLM_Tokens"]
        agg[plat]["cost"] += r["Cost_USD"]
        agg[plat]["time"] += r["Time_sec"]
        
    agg_table = Table(title="Comparativa de Rendimiento y Costo")
    agg_table.add_column("Plataforma")
    agg_table.add_column("Tiendas")
    agg_table.add_column("Total Productos", justify="right")
    agg_table.add_column("Tokens LLM", justify="right")
    agg_table.add_column("Costo Total", justify="right", style="magenta")
    agg_table.add_column("Tiempo Total (s)", justify="right")
    
    for plat, data in agg.items():
        agg_table.add_row(
            plat.upper(),
            str(data["count"]),
            str(data["extracted"]),
            str(data["llm_tokens"]),
            f"${data['cost']:.5f}",
            f"{data['time']:.2f}"
        )
        
    console.print(agg_table)
    
    # Exportar a CSV
    with open('report_fr_massive.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Domain", "Platform", "Extracted", "Time_sec", "LLM_Tokens", "Emb_Tokens", "Cost_USD", "Status"])
        writer.writeheader()
        writer.writerows(results)
        
    console.print("\n[bold cyan]Resultados guardados en report_fr_massive.csv[/bold cyan]")

if __name__ == '__main__':
    asyncio.run(run_massive_test())
