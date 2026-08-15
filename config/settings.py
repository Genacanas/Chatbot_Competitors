import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Rutas base
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data")

# Crear carpeta de datos si no existe
DATA_DIR.mkdir(parents=True, exist_ok=True)

# LLM
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Scraper Settings
DEFAULT_REQUEST_DELAY = float(os.getenv("DEFAULT_REQUEST_DELAY", "1.5"))
MAX_PRODUCTS_PER_SITE = int(os.getenv("MAX_PRODUCTS_PER_SITE", "10000"))
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
