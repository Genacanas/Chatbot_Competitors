import os
import random
import re
from openai import AsyncOpenAI

class UrlPatternAnalyzer:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.client = AsyncOpenAI(api_key=api_key)
            self.model = "gpt-4o"
        else:
            self.client = None
            
        self.total_tokens_used = 0

    async def derive_pattern(self, domain: str, raw_urls: list[str]) -> str | None:
        """
        Toma una lista de URLs, extrae una muestra estratégica y le pide al LLM
        que devuelva un REGEX en Python que matchee las URLs de productos.
        """
        if not self.client or not raw_urls:
            return None
            
        # Tomar muestra: 100 de inicio, 100 del medio, 100 del final
        sample_size = min(100, max(1, len(raw_urls) // 3))
        sample_urls = []
        
        if len(raw_urls) <= 300:
            sample_urls = raw_urls
        else:
            sample_urls.extend(raw_urls[:sample_size])
            mid_start = len(raw_urls) // 2 - sample_size // 2
            sample_urls.extend(raw_urls[mid_start:mid_start + sample_size])
            sample_urls.extend(raw_urls[-sample_size:])
            
        # Mezclar un poco para evitar sesgos
        random.shuffle(sample_urls)
        
        urls_text = "\n".join(sample_urls[:300]) # Cap at 300
        
        prompt = f"""
Eres un experto en scraping web. Aquí tienes una muestra representativa de URLs extraídas del sitemap de {domain}.
Tu tarea es encontrar el patrón (o patrones) que identifican a las URLs que corresponden a páginas de productos individuales, diferenciándolas de categorías, blogs, políticas, inicio, etc.

Muestra de URLs:
{urls_text}

Analiza las URLs y devuelve ÚNICAMENTE una expresión regular (regex) válida en Python que matchee las URLs de productos en este sitio. 
NO incluyas explicaciones, NO incluyas backticks (```), SOLO el texto puro de la expresión regular.
Si no puedes deducir un patrón claro, devuelve la palabra NONE.
"""
        try:
            print(f"[UrlPatternAnalyzer] Analizando patrón para {domain} con {len(sample_urls[:300])} URLs...")
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            if response.usage:
                self.total_tokens_used += response.usage.total_tokens
                
            pattern = response.choices[0].message.content.strip()
            
            # Limpiar posible formato markdown si el modelo no hizo caso
            pattern = pattern.replace('```regex', '').replace('```python', '').replace('```', '').strip()
            
            if pattern.upper() == "NONE":
                return None
                
            # Validar que el regex compila
            re.compile(pattern, re.IGNORECASE)
            
            print(f"[UrlPatternAnalyzer] Patrón derivado exitosamente: {pattern}")
            return pattern
            
        except Exception as e:
            print(f"[UrlPatternAnalyzer] Error derivando patrón: {e}")
            return None
            
    def filter_urls(self, raw_urls: list[str], pattern: str) -> list[str]:
        """Filtra la lista de URLs usando el patrón regex."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            filtered = [url for url in raw_urls if regex.search(url)]
            print(f"[UrlPatternAnalyzer] Filtro aplicado: {len(raw_urls)} -> {len(filtered)} URLs")
            return filtered
        except Exception as e:
            print(f"[UrlPatternAnalyzer] Error aplicando regex: {e}")
            return raw_urls
