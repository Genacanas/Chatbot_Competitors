import os
from typing import List, Optional
from openai import AsyncOpenAI
import numpy as np

class EmbeddingGenerator:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            print("[EmbeddingGenerator] Advertencia: OPENAI_API_KEY no definida. Se usarán vectores vacíos.")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.api_key)
            
        self.model = "text-embedding-3-small" # Fast, cheap, outputs 1536 dims by default. We can reduce to 768.
        self.total_tokens_used = 0

    async def generate_batch(self, texts: List[str], chunk_size: int = 2000) -> Optional[List[List[float]]]:
        if not self.client or not texts:
            return None
            
        all_embeddings = []
        try:
            for i in range(0, len(texts), chunk_size):
                chunk = texts[i:i + chunk_size]
                response = await self.client.embeddings.create(
                    input=chunk,
                    model=self.model,
                    dimensions=768
                )
                if hasattr(response, 'usage') and response.usage:
                    self.total_tokens_used += response.usage.total_tokens
                    
                all_embeddings.extend([data.embedding for data in response.data])
                
            return all_embeddings
        except Exception as e:
            print(f"[EmbeddingGenerator] Error generando embeddings en batch: {e}")
            return None

    async def generate(self, text: str) -> Optional[List[float]]:
        if not self.client:
            return None
            
        try:
            # We use text-embedding-3-small and specify dimensions=768 to save space
            # and match the pgvector schema.
            response = await self.client.embeddings.create(
                input=text,
                model=self.model,
                dimensions=768
            )
            if hasattr(response, 'usage') and response.usage:
                self.total_tokens_used += response.usage.total_tokens
                
            return response.data[0].embedding
        except Exception as e:
            print(f"[EmbeddingGenerator] Error generando embedding: {e}")
            return None
            
    def prepare_text(self, product_data: dict) -> str:
        """
        Combina los campos clave del producto en un solo texto rico en contexto
        para que el embedding capture el 'significado' del producto.
        """
        parts = []
        if product_data.get('name'):
            parts.append(product_data['name'])
        if product_data.get('brand'):
            parts.append(f"Marca: {product_data['brand']}")
        if product_data.get('categories'):
            parts.append(f"Categorías: {', '.join(product_data['categories'])}")
        if product_data.get('description'):
            # Take only first 300 chars to avoid noise
            desc = product_data['description'][:300].replace('\n', ' ')
            parts.append(f"Descripción: {desc}")
            
        return " | ".join(parts)
