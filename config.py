"""Configuración central de LocalAgent. Todo override por variable de entorno."""
import os

# --- Endpoints (todo en tu LAN, cero nube) ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CORPUS_URL = os.getenv("CORPUS_URL", "http://localhost:5099/api")  # opcional: servidor de corpus/RAG propio
CORPUS_KEY = os.getenv("CORPUS_KEY", "dev-only-key-cambiar-en-prod")
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
VAULT_DIR = os.getenv("VAULT_DIR", "/mnt/c/Sites/Data")  # vault físico de Obsidian (repo git)
# Raíz donde el modelo puede crear proyectos/scripts (C:\Sites desde Windows).
# Para aislar de tus repos existentes, apuntá a una subcarpeta, ej: /mnt/c/Sites/localagent-projects
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/mnt/c/Sites")

# --- Límite de VRAM (ajustá VRAM_GB a tu GPU). Modelos > este umbral se parten a CPU. ---
VRAM_BYTES = int(float(os.getenv("VRAM_GB", "12")) * 1024**3)
# margen: dejamos ~1 GB para el runtime; solo mostramos modelos que entran holgados
FIT_BYTES = int(VRAM_BYTES * 0.92)

# Modelos que NO son de chat (embeddings/visión se listan aparte)
EMBED_HINT = ("embed", "nomic")
VISION_HINT = ("vl", "llava", "vision")

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.2")  # la UI auto-elige el primero disponible si no lo tenés
DEFAULT_TOPK = int(os.getenv("RAG_TOPK", "6"))
