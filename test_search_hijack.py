import asyncio
from playwright.async_api import async_playwright

async def test_search_hijack():
    print("[Test] Lanzando navegador Playwright para espiar el tráfico de red...")
    async with async_playwright() as p:
        # Iniciamos en modo headless (invisible)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Función que se ejecuta cada vez que la página recibe un archivo/dato
        async def handle_response(response):
            # Solo nos interesan llamadas a APIs (fetch / xhr)
            if response.request.resource_type in ["fetch", "xhr"]:
                url = response.url.lower()
                # Filtramos URLs que parezcan de búsqueda o autocompletado
                if "search" in url or "api" in url or "query" in url or "autocomplete" in url or "suggest" in url:
                    print(f"\n[INTERCEPTADO] Llamada oculta detectada a: {response.url}")
                    try:
                        # Intentamos leer la respuesta como JSON
                        json_data = await response.json()
                        print(f"--> ¡ÉXITO! Respuesta JSON interceptada. Llaves principales: {list(json_data.keys())}")
                        # Si encontramos un array de resultados, imprimimos el conteo
                        for k, v in json_data.items():
                            if isinstance(v, list) and len(v) > 0:
                                print(f"--> Parece contener {len(v)} resultados en la llave '{k}'")
                    except Exception:
                        print("--> La respuesta no es un JSON estructurado o no se pudo leer.")

        # Conectar el "espía" a la página
        page.on("response", handle_response)
        
        print("[Test] Entrando a https://www.zoomalia.com...")
        try:
            await page.goto("https://www.zoomalia.com", wait_until="domcontentloaded", timeout=30000)
            
            # Esperar un poco a que cargue
            await asyncio.sleep(2)
            
            print("[Test] Simulando usuario: Escribiendo 'croquettes' en la barra de búsqueda...")
            
            # Tomar captura para ver qué bloquea
            await page.screenshot(path="zoomalia_debug.png")
            
            # Forzar el tipeado usando JS para evitar bloqueos de banners
            await page.evaluate("""
                const input = document.querySelector('input[type="text"], input[type="search"]');
                if (input) {
                    input.value = "croquettes";
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 's' }));
                }
            """)
            
            print("[Test] Texto escrito vía JS. Esperando 5 segundos a que la página haga peticiones AJAX ocultas...")
            await asyncio.sleep(5)
                
        except Exception as e:
            print(f"[Test] Error durante la navegación: {e}")
            
        finally:
            print("\n[Test] Cerrando navegador.")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_search_hijack())
