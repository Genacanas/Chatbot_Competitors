import os
import json
import asyncio
import sys
from typing import List, Dict, Any, Optional
from openai import OpenAI

# Asegurar que la raíz del proyecto esté en sys.path para importar scraper
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scraper.repositories.neon_repo import NeonRepository
from scraper.embeddings.generator import EmbeddingGenerator

class ChatbotAgent:
    def __init__(self):
        # Synchronous client to avoid event loop blocking in Streamlit
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.last_usage = None
        self.last_cost = 0.0
        self.system_prompt = {
            "role": "system",
            "content": (
                "You are an expert competitive intelligence assistant for a pet e-commerce company. "
                "You have access to a PostgreSQL database (NeonDB) of pet products from multiple competitors. "
                "Table schema for `products`: "
                "id (UUID), site_domain (VARCHAR), source_url (TEXT), name (VARCHAR), brand (VARCHAR), "
                "sku (VARCHAR), price (NUMERIC), original_price (NUMERIC), currency (VARCHAR, default 'EUR'), "
                "description (TEXT), categories (TEXT[]), images (TEXT[]), scraped_at (TIMESTAMP).\n\n"
                "ROUTING INSTRUCTIONS:\n"
                "1. If the user asks for analytics, statistics, counts, or grouping (e.g. 'How many brands are there?', 'What is the average price of X?', 'List all domains'), use the `query_database_sql` tool. Write valid Postgres SQL (SELECT only).\n"
                "2. If the user asks to find specific products, compare prices, or find 'the cheapest' or 'the best' items (e.g. 'Find Royal Canin 2kg', 'What are the top 3 cheapest dog beds?'), ALWAYS use the `search_similar_products` tool. NEVER use SQL for product discovery, because categories and names are in multiple languages and SQL exact matching will fail.\n"
                "\nCRITICAL RULES FOR SEARCHING PRODUCTS:\n"
                "- When calling `search_similar_products`, you MUST provide a highly expanded `query`. Include synonyms, related terms, and translations (German and French) to ensure the vector semantic search captures the full meaning. Example: instead of 'dog bed', use 'dog bed, orthopedic cushion, sleeping mat, Hundebett, lit pour chien'.\n"
                "- After receiving the results from `search_similar_products`, YOU MUST ACT AS A SMART RE-RANKER AND FILTER. Read the `description`, `sku`, and `name` of each returned product VERY CAREFULLY.\n"
                "- The database search is fuzzy (vector-based). It WILL return products that are only tangentially related if it can't find an exact match.\n"
                "- Your job is to DISCARD any products that clearly do NOT match the user's intent (e.g., if they want a dog bed, and the result is a cat bed, discard it. If they want 10kg, and the result is 2kg, discard it).\n"
                "- However, be smart about names: 'Dog Collar Signature' is the same as 'Signature Dog Collar' or 'Doco Dog Collar Signature'. Do not discard valid products just because the word order or brand prefix is different.\n"
                "- Only show the user the products that are valid matches. If none of the returned products match, politely tell the user that we couldn't find matches in our catalog.\n"
                "\nCRITICAL RULES FOR IMAGES:\n"
                "- If the user uploads an image, assume it is an e-commerce product image. You MUST extract the brand, product name, and text from the packaging to identify it.\n"
                "- NEVER refuse to identify products in images. There are no people in these images. Identify the commercial product and immediately use the `search_similar_products` tool.\n"
                "\nAlways reply in English unless the user explicitly requests another language. When returning products, use Markdown links for source_url."
            )
        }
        
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_similar_products",
                    "description": "Searches the competitors' database for products matching the description. Uses hybrid search (semantic + exact text).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Highly expanded description of the product to search. MUST include synonyms and translations to German/French. E.g. 'cat tree, scratching post, arbre a chat, Kratzbaum'"
                            },
                            "min_price": {
                                "type": "number",
                                "description": "Minimum price filter (optional)"
                            },
                            "max_price": {
                                "type": "number",
                                "description": "Maximum price filter (optional)"
                            },
                            "brand": {
                                "type": "string",
                                "description": "Brand name filter (optional)"
                            },
                            "exact_keyword": {
                                "type": "string",
                                "description": "Use this ONLY if the user is looking for a VERY specific product, code (SKU), or specific word (e.g. 'DCO002XS04', 'Signature'). This will force the database to only return products containing this exact string in their name, sku, or description. Use with caution as it restricts semantic search."
                            },
                            "store": {
                                "type": "string",
                                "description": "Competitor store domain filter, e.g., 'fressnapf.de' (optional)"
                            }
                        },
                        "required": ["query"],
                    },
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_database_sql",
                    "description": "Executes a raw read-only SQL query against the PostgreSQL database to get analytics, counts, or exact aggregations.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "A valid PostgreSQL SELECT query using the `products` table."
                            }
                        },
                        "required": ["query"],
                    },
                }
            }
        ]

    async def _buscar_async(self, query: str, min_price: float = None, max_price: float = None, brand: str = None, store: str = None, exact_keyword: str = None) -> str:
        """Internal async function to interact with DB."""
        repo = NeonRepository()
        embed_gen = EmbeddingGenerator()
        
        try:
            # Imprimir seguro para la consola de Windows
            safe_query = query.encode("ascii", "replace").decode("ascii")
            print(f"[Agent] Generating embedding for query: '{safe_query}'")
            vector = await embed_gen.generate(query)
            if not vector:
                return json.dumps({"error": "Could not generate embedding for the query."})
                
            safe_brand = brand.encode("ascii", "replace").decode("ascii") if brand else None
            print(f"[Agent] Searching in NeonDB with filters (min_price={min_price}, max_price={max_price}, brand={safe_brand}, store={store}, exact_keyword={exact_keyword})...")
            resultados = await repo.search_similar_global(
                query_text=query,
                embedding=vector, 
                limit=15,
                min_price=min_price,
                max_price=max_price,
                brand=brand,
                store=store,
                exact_keyword=exact_keyword
            )
            
            cleaned_results = []
            for r in resultados:
                cleaned_results.append({
                    "name": r.get("name"),
                    "brand": r.get("brand"),
                    "sku": r.get("sku"),
                    "description": str(r.get("description", ""))[:600] + "..." if r.get("description") else "",
                    "price": float(r.get("price")) if r.get("price") else None,
                    "store_domain": r.get("site_domain"),
                    "url": r.get("source_url"),
                    "similarity": round(float(r.get("similarity", 0)), 3)
                })
                
            return json.dumps(cleaned_results, ensure_ascii=False)
        finally:
            await repo.close()

    def search_similar_products(self, query: str, min_price: float = None, max_price: float = None, brand: str = None, store: str = None, exact_keyword: str = None) -> str:
        """Sync wrapper to be called by the tool."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._buscar_async(query, min_price, max_price, brand, store, exact_keyword))
        finally:
            loop.close()

    async def _execute_sql_async(self, query: str) -> str:
        """Internal async function to execute readonly SQL."""
        repo = NeonRepository()
        try:
            print(f"[Agent] Executing SQL Query: {query}")
            resultados = await repo.execute_readonly_sql(query)
            
            # Format results for the LLM
            # Handle non-serializable objects like Decimal/datetime if necessary
            def default_serializer(obj):
                import datetime
                import decimal
                if isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                if isinstance(obj, decimal.Decimal):
                    return float(obj)
                return str(obj)
                
            return json.dumps(resultados, default=default_serializer, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            await repo.close()

    def query_database_sql(self, query: str) -> str:
        """Sync wrapper for SQL tool."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._execute_sql_async(query))
        finally:
            loop.close()

    def process_chat(self, messages: List[Dict[str, Any]], stream: bool = False, model: str = "gpt-4o"):
        full_messages = [self.system_prompt] + messages
        self.last_model_used = model
        
        print(f"[Agent] Querying OpenAI ({model})...")
        response = self.client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=self.tools,
            tool_choice="auto",
            stream=False # First call is never streamed because it might return tool calls
        )
        
        response_message = response.choices[0].message
        
        if response_message.tool_calls:
            print("[Agent] LLM decided to use a tool.")
            
            message_dict = response_message.model_dump(exclude_none=True)
            full_messages.append(message_dict)
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "search_similar_products":
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query")
                    min_price = args.get("min_price")
                    max_price = args.get("max_price")
                    brand = args.get("brand")
                    store = args.get("store")
                    exact_keyword = args.get("exact_keyword")
                    
                    function_result = self.search_similar_products(query, min_price, max_price, brand, store, exact_keyword)
                    
                    full_messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "search_similar_products",
                        "content": function_result,
                    })
                elif tool_call.function.name == "query_database_sql":
                    args = json.loads(tool_call.function.arguments)
                    sql_query = args.get("query")
                    
                    function_result = self.query_database_sql(sql_query)
                    
                    full_messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "query_database_sql",
                        "content": function_result,
                    })
            
            print("[Agent] Sending results back to LLM for final response...")
            if stream:
                def stream_wrapper():
                    self.last_usage = None
                    self.last_cost = 0.0
                    stream_obj = self.client.chat.completions.create(
                        model=model,
                        messages=full_messages,
                        stream=True,
                        stream_options={"include_usage": True}
                    )
                    for chunk in stream_obj:
                        if chunk.usage:
                            self.last_usage = {
                                "prompt_tokens": chunk.usage.prompt_tokens,
                                "completion_tokens": chunk.usage.completion_tokens,
                                "total_tokens": chunk.usage.total_tokens
                            }
                            # Calculate cost based on model
                            if model == "gpt-4o-mini":
                                self.last_cost = (chunk.usage.prompt_tokens * 0.150 / 1000000) + (chunk.usage.completion_tokens * 0.600 / 1000000)
                            else:
                                # gpt-4o pricing: $5.00 / 1M input, $15.00 / 1M output
                                self.last_cost = (chunk.usage.prompt_tokens * 5.00 / 1000000) + (chunk.usage.completion_tokens * 15.00 / 1000000)
                        if chunk.choices and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                return stream_wrapper()
            else:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    stream=False
                )
                if resp.usage:
                    self.last_usage = {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                        "total_tokens": resp.usage.total_tokens
                    }
                    self.last_cost = (resp.usage.prompt_tokens * 0.150 / 1000000) + (resp.usage.completion_tokens * 0.600 / 1000000)
                return resp.choices[0].message.content
        else:
            if response.usage:
                self.last_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
                self.last_cost = (response.usage.prompt_tokens * 0.150 / 1000000) + (response.usage.completion_tokens * 0.600 / 1000000)
            
            if stream:
                def string_streamer(s):
                    # Yield words to simulate streaming for cached/no-tool responses
                    words = s.split(" ")
                    for i, word in enumerate(words):
                        yield word + (" " if i < len(words)-1 else "")
                
                return string_streamer(response_message.content)
            else:
                return response_message.content
