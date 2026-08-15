"""
Benchmark: Gemini 2.5 Flash (Kie.ai) vs gpt-4o-mini (OpenAI)
Extrae 15 productos de fressnapf.de con ambos modelos y compara:
  - Calidad (campos extraídos vs nulos)
  - Costo (tokens × tarifa)
  - Velocidad (tiempo total)
"""
import asyncio
import json
import time
import os
from typing import Any
from dotenv import load_dotenv
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

load_dotenv()

# 15 URLs de producto de Fressnapf conocidas
TEST_URLS = [
    "https://www.fressnapf.de/p/trixie-kletterleiter-zur-wandmontage-1368032/",
    "https://www.fressnapf.de/p/max--molly-multifunktionseine-sailor-s-1871010/",
    "https://www.fressnapf.de/p/dog-sport-hunter-ergonomisches-hundehalsband-arvika-cognac-m-2410824/",
    "https://www.fressnapf.de/p/tierlando-lilly-flauschige-haustier---plueschdecke-hellbraun-xl-2129512/",
    "https://www.fressnapf.de/p/doog-walkie-belt-2033128/",
    "https://www.fressnapf.de/p/alphazoo-magenruhe-bachblueten-globuli-fuer-hunde-und-katzen-1701984/",
    "https://www.fressnapf.de/p/jr-farm-dottergelb-maker-100-g-1343844/",
    "https://www.fressnapf.de/p/aniforte-gruenlippmuschelpulver-vollfettqualitaet-250-g-1337238/",
    "https://www.fressnapf.de/p/wolfsbacher-natur-ruhe--relax-leckerli-4-2078196/",
    "https://www.fressnapf.de/p/wildfang--nassfutter-huhn-pur-barf-6x400-g-1951764/",
    "https://www.fressnapf.de/p/anione-snack-ball-6-cm-lavender-1520926/",
    "https://www.fressnapf.de/p/select-gold-sensitive-trockenfutter-hund-mini-seidenraupenprotein-1-kg-2068115/",
    "https://www.fressnapf.de/p/multifit-nassfutter-hund-pastete-gefluegel-48x150-g-1954846/",
    "https://www.fressnapf.de/p/hunter-verstellbare-fuehrleine-solid-education-oliv-13-cm-25-m-1326978/",
    "https://www.fressnapf.de/p/district-70-hundebett-classic-dunkelgrau-m-1867003/",
]

PROMPT_TEMPLATE = """You are an expert e-commerce data extractor.
Given the following HTML from a product page, extract the product data as JSON.

Fields to extract:
- name: full product name (string, in English)
- price: numeric price (float, number only, use dot for decimals)
- currency: 3-letter currency code (e.g. EUR, USD) (string)
- sku: product reference code (string)
- brand: product brand (string)
- description: product description (string, clean text, no HTML tags, in English)
- images: list of product image URLs (list of strings)
- in_stock: true if in stock, false if out of stock (boolean)
- categories: list of categories or breadcrumbs (list of strings, in English)

IMPORTANT RULES:
1. Respond ONLY with a valid JSON object. NO backticks, NO greetings, NO explanations.
2. If a field cannot be found, assign null (except lists which must be []).
3. Parse the price correctly to a number (e.g. "49,99 €" -> 49.99).
4. Output must be directly parseable by json.loads() in Python.
5. Translate all text fields (name, description, brand, categories) to English.

HTML to analyze:
{html_content}
"""

SCORE_FIELDS = ["name", "price", "currency", "sku", "brand", "description", "images", "in_stock", "categories"]

# Pricing per 1M tokens
COST_GEMINI_PER_1M = 0.075   # Kie.ai Gemini 2.5 Flash
COST_GPT4O_MINI_PER_1M = 0.075  # gpt-4o-mini input (approx)
COST_GPT4O_MINI_BATCH_PER_1M = 0.0375  # 50% discount via Batch API


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "path", "nav", "footer", "header", "aside"]):
        tag.decompose()
    for selector in ['main', 'article', '#product', '.product', '#content', '.content']:
        found = soup.select_one(selector)
        if found:
            soup = found
            break
    clean = str(soup)
    if len(clean) > 25000:
        clean = clean[:25000]
    return clean


def score_product(product: dict | None) -> dict:
    if product is None:
        return {"score": 0, "max": len(SCORE_FIELDS), "fields": {f: False for f in SCORE_FIELDS}}
    
    field_results = {}
    for f in SCORE_FIELDS:
        val = product.get(f)
        if val is None:
            field_results[f] = False
        elif isinstance(val, list):
            field_results[f] = len(val) > 0
        elif isinstance(val, bool):
            field_results[f] = True  # bool is always "present" even if False
        else:
            field_results[f] = bool(val)
    
    score = sum(field_results.values())
    return {"score": score, "max": len(SCORE_FIELDS), "fields": field_results}


async def fetch_html_batch(urls: list[str]) -> dict[str, str]:
    """Obtiene el HTML limpio de todas las URLs usando Playwright con concurrencia."""
    htmls = {}
    semaphore = asyncio.Semaphore(3)
    
    async def fetch_one(browser, url):
        async with semaphore:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
                raw = await page.content()
                return url, clean_html(raw)
            except Exception as e:
                print(f"  [Playwright] Error en {url}: {e}")
                return url, None
            finally:
                await page.close()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tasks = [fetch_one(browser, url) for url in urls]
        results = await asyncio.gather(*tasks)
        await browser.close()
    
    for url, html in results:
        htmls[url] = html
    return htmls


async def run_model(name: str, client: AsyncOpenAI, model_id: str, htmls: dict[str, str]) -> dict:
    """Corre la extracción con un modelo dado sobre los HTMLs precargados."""
    print(f"\n{'='*60}")
    print(f"  Modelo: {name}")
    print(f"{'='*60}")
    
    semaphore = asyncio.Semaphore(5)
    total_tokens = 0
    products = []
    
    async def extract_one(url, html):
        nonlocal total_tokens
        if not html:
            print(f"  [{name}] Sin HTML para {url}")
            return None
        
        async with semaphore:
            prompt = PROMPT_TEMPLATE.format(html_content=html)
            try:
                response = await client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                
                if hasattr(response, 'usage') and response.usage:
                    total_tokens += response.usage.total_tokens
                    
                text = response.choices[0].message.content.strip()
                if text.startswith("```json"): text = text[7:]
                if text.startswith("```"): text = text[3:]
                if text.endswith("```"): text = text[:-3]
                
                data = json.loads(text.strip())
                data["source_url"] = url
                print(f"  [{name}] OK: {url.split('/')[-2][:50]}")
                return data
            except json.JSONDecodeError as e:
                print(f"  [{name}] JSON parse error en {url}: {e}")
                return None
            except Exception as e:
                print(f"  [{name}] Error en {url}: {e}")
                return None
    
    start = time.time()
    tasks = [extract_one(url, html) for url, html in htmls.items()]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start
    
    products = [r for r in results if r is not None]
    failed = len(results) - len(products)
    
    return {
        "model": name,
        "elapsed_seconds": round(elapsed, 2),
        "total_tokens": total_tokens,
        "products_ok": len(products),
        "products_failed": failed,
        "products": products,
    }


def print_report(gemini_result: dict, openai_result: dict):
    print("\n\n" + "="*70)
    print("  BENCHMARK REPORT: Gemini 2.5 Flash vs gpt-4o-mini")
    print("="*70)
    
    # Puntajes de calidad
    gemini_scores = [score_product(p) for p in gemini_result["products"]]
    openai_scores = [score_product(p) for p in openai_result["products"]]
    
    gemini_avg = sum(s["score"] for s in gemini_scores) / len(gemini_scores) if gemini_scores else 0
    openai_avg = sum(s["score"] for s in openai_scores) / len(openai_scores) if openai_scores else 0
    max_score = len(SCORE_FIELDS)
    
    # Costos
    g_tokens = gemini_result["total_tokens"]
    o_tokens = openai_result["total_tokens"]
    
    g_cost = (g_tokens / 1_000_000) * COST_GEMINI_PER_1M
    o_cost = (o_tokens / 1_000_000) * COST_GPT4O_MINI_PER_1M
    o_cost_batch = (o_tokens / 1_000_000) * COST_GPT4O_MINI_BATCH_PER_1M
    
    print(f"\n{'Métrica':<35} {'Gemini 2.5 Flash':>18} {'gpt-4o-mini':>18}")
    print("-"*70)
    print(f"{'Productos extraídos':<35} {gemini_result['products_ok']:>18} {openai_result['products_ok']:>18}")
    print(f"{'Productos fallidos':<35} {gemini_result['products_failed']:>18} {openai_result['products_failed']:>18}")
    print(f"{'Score calidad promedio':<35} {f'{gemini_avg:.2f}/{max_score}':>18} {f'{openai_avg:.2f}/{max_score}':>18}")
    print(f"{'Tiempo de extracción (s)':<35} {gemini_result['elapsed_seconds']:>18.2f} {openai_result['elapsed_seconds']:>18.2f}")
    print(f"{'Tokens totales':<35} {g_tokens:>18,} {o_tokens:>18,}")
    print(f"{'Costo real (15 prods)':<35} {'${:.4f}'.format(g_cost):>18} {'${:.4f}'.format(o_cost):>18}")
    print(f"{'Costo Batch API estimado':<35} {'N/A':>18} {'${:.4f}'.format(o_cost_batch):>18}")
    
    # Proyección a 10,000 productos
    factor = 10000 / 15
    print(f"\n{'--- Proyección a 10,000 productos ---'}")
    print(f"{'Costo proyectado (real-time)':<35} {'${:.2f}'.format(g_cost * factor):>18} {'${:.2f}'.format(o_cost * factor):>18}")
    print(f"{'Costo proyectado (batch)':<35} {'N/A':>18} {'${:.2f}'.format(o_cost_batch * factor):>18}")
    
    # Desglose por campo
    print(f"\n{'--- Calidad por campo (% extraídos correctamente) ---'}")
    print(f"{'Campo':<20} {'Gemini':>10} {'gpt-4o-mini':>12}")
    print("-"*45)
    for field in SCORE_FIELDS:
        g_ok = sum(1 for s in gemini_scores if s["fields"].get(field)) / max(len(gemini_scores), 1) * 100
        o_ok = sum(1 for s in openai_scores if s["fields"].get(field)) / max(len(openai_scores), 1) * 100
        print(f"  {field:<18} {f'{g_ok:.0f}%':>10} {f'{o_ok:.0f}%':>12}")
    
    # Conclusión
    print("\n--- CONCLUSIÓN ---")
    if openai_avg >= gemini_avg * 0.95:
        print("[OK] gpt-4o-mini tiene calidad equivalente o mejor a Gemini.")
        print("   RECOMENDACION: Migrar a gpt-4o-mini + Batch API para ahorrar 50%.")
    elif openai_avg >= gemini_avg * 0.85:
        print("[~]  gpt-4o-mini tiene calidad ligeramente inferior (~85-95% de Gemini).")
        print("   RECOMENDACION: Evaluar si el ahorro de costos justifica la diferencia.")
    else:
        print("[X]  gpt-4o-mini tiene calidad notablemente inferior a Gemini.")
        print("   RECOMENDACION: Mantener Gemini para extraccion. Usar Batch solo para traduccion.")
    
    # Guardar resultados
    output = {
        "gemini": {**gemini_result, "avg_quality_score": gemini_avg, "cost_usd": g_cost},
        "gpt4o_mini": {**openai_result, "avg_quality_score": openai_avg, "cost_usd": o_cost, "cost_batch_usd": o_cost_batch},
    }
    with open("benchmark_model_comparison.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print("\n=== Resultados guardados en benchmark_model_comparison.json ===")


async def main():
    print("="*60)
    print("  Mini-Benchmark: Gemini vs gpt-4o-mini")
    print(f"  URLs a probar: {len(TEST_URLS)}")
    print("="*60)
    
    # Configurar clientes
    kie_api_key = os.getenv("KIE_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not kie_api_key:
        print("ERROR: KIE_API_KEY no encontrada en .env")
        return
    if not openai_api_key:
        print("ERROR: OPENAI_API_KEY no encontrada en .env")
        return
    
    gemini_client = AsyncOpenAI(api_key=kie_api_key, base_url="https://api.kie.ai/gemini-2.5-flash/v1")
    openai_client = AsyncOpenAI(api_key=openai_api_key)
    
    # 1. Obtener HTMLs UNA SOLA VEZ con Playwright (así el tiempo de red no sesga el resultado)
    print(f"\n[1/3] Cargando {len(TEST_URLS)} páginas con Playwright (compartido por ambos modelos)...")
    start_playwright = time.time()
    htmls = await fetch_html_batch(TEST_URLS)
    print(f"  HTMLs cargados en {time.time() - start_playwright:.1f}s")
    
    valid_htmls = {k: v for k, v in htmls.items() if v}
    print(f"  {len(valid_htmls)}/{len(TEST_URLS)} páginas cargadas correctamente.")
    
    # 2. Modo A: Gemini 2.5 Flash
    print(f"\n[2/3] Extrayendo con Gemini 2.5 Flash (Kie.ai)...")
    gemini_result = await run_model("Gemini 2.5 Flash", gemini_client, "google/gemini-2.5-flash", valid_htmls)
    
    # 3. Modo B: gpt-4o-mini
    print(f"\n[3/3] Extrayendo con gpt-4o-mini (OpenAI)...")
    openai_result = await run_model("gpt-4o-mini", openai_client, "gpt-4o-mini", valid_htmls)
    
    # 4. Reporte
    print_report(gemini_result, openai_result)


if __name__ == "__main__":
    asyncio.run(main())
