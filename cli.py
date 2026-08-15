import asyncio
import click
from rich.console import Console
from rich.table import Table

from scraper.pipeline import ScraperPipeline
from scraper.storage.repository import JsonRepository

console = Console()

@click.group()
def cli():
    """Universal E-Commerce Scraper CLI"""
    pass

@cli.command()
@click.argument('url')
@click.option('--limit', default=None, type=int, help='Límite de productos a extraer')
def scrape(url, limit):
    """Scrapea todos los productos de una tienda online."""
    console.print(f"[bold blue]Iniciando scraping en: {url}[/bold blue]")
    
    # Run the async pipeline
    try:
        result = asyncio.run(ScraperPipeline.scrape(url, limit=limit))
        
        console.print("\n[bold green][SUCCESS] Scraping finalizado con éxito[/bold green]")
        console.print(f"Dominio: {result.site_domain}")
        console.print(f"Plataforma: {result.platform.upper()}")
        console.print(f"Productos extraídos: {result.total_extracted}")
        
    except Exception as e:
        console.print(f"[bold red][ERROR] Error durante el scraping: {e}[/bold red]")


@cli.command()
@click.argument('domain')
def stats(domain):
    """Muestra estadísticas de un sitio scrapeado."""
    stats_data = JsonRepository.get_stats(domain)
    
    if stats_data["total_products"] == 0:
        console.print(f"[yellow]No se encontraron datos para {domain}[/yellow]")
        return
        
    table = Table(title=f"Estadísticas para {domain}")
    table.add_column("Métrica", justify="right", style="cyan")
    table.add_column("Valor", style="magenta")
    
    table.add_row("Total Productos", str(stats_data["total_products"]))
    
    console.print(table)

@cli.command()
@click.argument('query')
@click.option('--domain', required=True, help='Dominio objetivo (ej. zooroyal.de)')
@click.option('--limit', default=5, type=int, help='Resultados máximos a mostrar')
def search(query, domain, limit):
    """Busca productos similares semánticamente en un dominio."""
    async def do_search():
        from scraper.embeddings.generator import EmbeddingGenerator
        from scraper.repositories.neon_repo import NeonRepository
        
        console.print(f"[cyan]Generando embedding para: '{query}'...[/cyan]")
        embed_gen = EmbeddingGenerator()
        vector = await embed_gen.generate(query)
        if not vector:
            console.print("[red]No se pudo generar el vector.[/red]")
            return
            
        console.print(f"[cyan]Buscando en {domain}...[/cyan]")
        repo = NeonRepository()
        results = await repo.search_similar(domain, vector, limit=limit)
        await repo.close()
        
        if not results:
            console.print(f"[bold yellow]No se encontraron productos similares en {domain}. ¡Oportunidad de Venta! (Market Gap)[/bold yellow]")
            return
            
        table = Table(title=f"Resultados de Búsqueda Semántica: '{query}'")
        table.add_column("Similitud", justify="right", style="green")
        table.add_column("Producto", style="magenta")
        table.add_column("Precio", style="cyan")
        table.add_column("URL")
        
        for r in results:
            sim = f"{r['similarity']:.2f}"
            price = str(r['price']) if r['price'] else "N/A"
            table.add_row(sim, r['name'], price, r['source_url'])
            
        console.print(table)
        
        # Check gap
        best_sim = results[0]['similarity']
        if best_sim < 0.70:
            console.print("\n[bold yellow]Conclusión: Los productos encontrados no son idénticos. Posible oportunidad de venta (Market Gap).[/bold yellow]")
        else:
            console.print("\n[bold red]Conclusión: El competidor ya vende este producto (o uno casi idéntico).[/bold red]")
            
    asyncio.run(do_search())

@cli.command()
@click.option('--source', required=True, help='Archivo CSV con el catálogo del cliente')
@click.option('--target', required=True, help='Dominio competidor objetivo (ej. zooroyal.de)')
@click.option('--threshold', default=0.70, type=float, help='Umbral de similitud (debajo de esto es un GAP)')
def gaps(source, target, threshold):
    """Realiza un Análisis de Brechas de Mercado (Market Gap Analysis)."""
    import csv
    import os
    
    if not os.path.exists(source):
        console.print(f"[red]Error: No se encontró el archivo {source}[/red]")
        return
        
    async def do_analysis():
        from scraper.embeddings.generator import EmbeddingGenerator
        from scraper.repositories.neon_repo import NeonRepository
        
        console.print(f"[bold cyan]Iniciando Análisis de Brechas: Tu Catálogo vs {target}[/bold cyan]")
        
        embed_gen = EmbeddingGenerator()
        repo = NeonRepository()
        
        products = []
        with open(source, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                products.append(row)
                
        total_analyzed = len(products)
        gaps_found = []
        matches_found = []
        
        for p in products:
            name = p.get('name', '')
            brand = p.get('brand', '')
            desc = p.get('description', '')
            
            query = f"{name} {brand} {desc}".strip()
            vector = await embed_gen.generate(query)
            
            if not vector:
                continue
                
            results = await repo.search_similar(target, vector, limit=1)
            
            if not results:
                gaps_found.append({"product": p, "reason": "No hay datos en la DB"})
                continue
                
            best_match = results[0]
            sim = best_match['similarity']
            
            if sim < threshold:
                gaps_found.append({"product": p, "best_match": best_match})
            else:
                matches_found.append({"product": p, "best_match": best_match})
                
        await repo.close()
        
        # Reporte
        console.print("\n[bold]------------------------------------------------------[/bold]")
        console.print(f"[bold]     ANÁLISIS DE BRECHAS — {target} vs Tu Catálogo  [/bold]")
        console.print("[bold]------------------------------------------------------[/bold]")
        console.print(f"Total analizados:               {total_analyzed}")
        console.print(f"[green]Productos que SÍ tienen:        {len(matches_found)}[/green]")
        console.print(f"[yellow]OPORTUNIDADES (no los tienen):  {len(gaps_found)}[/yellow]")
        console.print("[bold]------------------------------------------------------[/bold]\n")
        
        if gaps_found:
            console.print("[bold yellow]TOP OPORTUNIDADES DE VENTA:[/bold yellow]")
            for i, gap in enumerate(gaps_found, 1):
                p_name = gap['product'].get('name', 'Unknown')
                if 'best_match' in gap:
                    sim = gap['best_match']['similarity']
                    closest = gap['best_match']['name']
                    console.print(f"{i}. [bold]{p_name}[/bold] — Score: {sim:.2f} (Lo más parecido que tienen es: {closest})")
                else:
                    console.print(f"{i}. [bold]{p_name}[/bold] — (No hay datos en la BD)")
                    
        # Exportar a CSV
        out_file = f"gaps_report_{target.replace('.', '_')}.csv"
        with open(out_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Tu Producto', 'Marca', 'Score Similitud', 'Lo mas parecido que tienen', 'URL Competidor', 'Es Oportunidad?'])
            
            for m in matches_found:
                writer.writerow([m['product'].get('name'), m['product'].get('brand'), f"{m['best_match']['similarity']:.2f}", m['best_match']['name'], m['best_match']['source_url'], 'NO'])
                
            for g in gaps_found:
                if 'best_match' in g:
                    writer.writerow([g['product'].get('name'), g['product'].get('brand'), f"{g['best_match']['similarity']:.2f}", g['best_match']['name'], g['best_match']['source_url'], 'SI (GAP)'])
                else:
                    writer.writerow([g['product'].get('name'), g['product'].get('brand'), "N/A", "N/A", "N/A", 'SI (GAP)'])
                    
        console.print(f"\n[bold green]Reporte completo exportado a: {out_file}[/bold green]")
        
    asyncio.run(do_analysis())

if __name__ == '__main__':
    cli()
