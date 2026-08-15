import json
import os
from typing import Any

from config.settings import DATA_DIR
from ..normalizer.product_normalizer import ProductSchema

class JsonRepository:
    """
    Repositorio simple basado en archivos JSON para desarrollo/pruebas.
    Guarda los datos en data/{dominio}.json
    """
    
    @staticmethod
    def _get_file_path(domain: str) -> str:
        # Asegurar que el dominio sea seguro para usar como nombre de archivo
        safe_domain = "".join([c if c.isalnum() else "_" for c in domain])
        return os.path.join(DATA_DIR, f"{safe_domain}.json")

    @staticmethod
    async def upsert_many(domain: str, products: list[ProductSchema]) -> None:
        """
        Guarda o actualiza múltiples productos.
        En esta versión simple con JSON, simplemente sobrescribe o hace un merge básico.
        """
        file_path = JsonRepository._get_file_path(domain)
        
        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data_list = json.load(f)
                    for p in data_list:
                        # Usar URL como llave principal si no hay SKU
                        key = p.get('source_url')
                        if key:
                            existing_data[key] = p
            except Exception as e:
                print(f"[JsonRepository] Error leyendo {file_path}: {e}")

        # Actualizar con los nuevos
        for p in products:
            p_dict = p.model_dump()
            # Convertir datetime a string ISO para JSON
            p_dict['scraped_at'] = p_dict['scraped_at'].isoformat()
            
            key = p_dict['source_url']
            existing_data[key] = p_dict
            
        # Guardar
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(list(existing_data.values()), f, indent=2, ensure_ascii=False)
            print(f"[JsonRepository] Guardados {len(products)} productos para {domain}. Total histórico: {len(existing_data)}")
        except Exception as e:
            print(f"[JsonRepository] Error escribiendo {file_path}: {e}")

    @staticmethod
    def get_stats(domain: str) -> dict[str, Any]:
        file_path = JsonRepository._get_file_path(domain)
        if not os.path.exists(file_path):
            return {"total_products": 0}
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {"total_products": len(data)}
        except:
            return {"total_products": 0}
