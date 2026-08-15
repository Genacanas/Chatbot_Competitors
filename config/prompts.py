"""LLM Prompts."""

PRODUCT_EXTRACTION_PROMPT = """
Eres un extractor experto de datos de e-commerce.
Dado el siguiente código HTML de una página de producto, extrae los datos del producto en formato JSON.

Campos a extraer:
- name: nombre completo del producto (string)
- price: precio numérico (float, solo número, usa punto para decimales)
- currency: código de moneda de 3 letras (ej: EUR, USD) (string)
- sku: código de referencia del producto (string)
- brand: marca del producto (string)
- description: descripción del producto (string, texto limpio, sin tags HTML)
- images: lista de URLs de imágenes del producto (lista de strings)
- in_stock: true si el producto está en stock, false si está agotado (boolean)
- categories: lista de categorías o breadcrumbs a las que pertenece el producto (lista de strings)

REGLAS MUY IMPORTANTES:
1. Responde SOLO con el objeto JSON válido. NO incluyas backticks (```json), NI saludos, NI explicaciones.
2. Si un campo no se puede encontrar o inferir del HTML, asígnale el valor `null` (excepto listas que deben ser `[]`).
3. Asegúrate de parsear correctamente el precio a número (ej. "49,99 €" -> 49.99).
4. El output debe poder ser parseado directamente por `json.loads()` en Python.
5. TRADUCCIÓN OBLIGATORIA: Traduce TODOS los campos de texto (name, brand, description, categories) al INGLÉS (English). El JSON devuelto debe estar completamente en inglés.

HTML a analizar:
{html_content}
"""
