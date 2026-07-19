"""Central LocalAgent configuration. Everything overridable via environment variable."""
import os

# --- Endpoints (all on your LAN, zero cloud) ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CORPUS_URL = os.getenv("CORPUS_URL", "http://localhost:5099/api")  # optional: your own corpus/RAG server
CORPUS_KEY = os.getenv("CORPUS_KEY", "dev-only-key-cambiar-en-prod")
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
# Optional extra OpenAI-compatible backend (e.g. llama.cpp's llama-server). Its models are
# listed alongside ollama's and chatted with via /v1/chat/completions. Empty = disabled.
LLAMACPP_URL = os.getenv("LLAMACPP_URL", "http://localhost:8080/v1")
VAULT_DIR = os.getenv("VAULT_DIR", "/mnt/c/Sites/Data")  # physical Obsidian vault (git repo)
# Root where the model can create projects/scripts (C:\Sites from Windows).
# To isolate from your existing repos, point to a subfolder, e.g.: /mnt/c/Sites/localagent-projects
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/mnt/c/Sites")

# --- VRAM limit (set VRAM_GB to your GPU). Models > this threshold spill to CPU. ---
VRAM_BYTES = int(float(os.getenv("VRAM_GB", "12")) * 1024**3)
# margin: leave ~1 GB for the runtime; only show models that fit comfortably
FIT_BYTES = int(VRAM_BYTES * 0.92)

# Models that are NOT chat models (embeddings/vision are listed separately)
EMBED_HINT = ("embed", "nomic")
VISION_HINT = ("vl", "llava", "vision")

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.2")  # the UI auto-picks the first available if you don't have it
DEFAULT_TOPK = int(os.getenv("RAG_TOPK", "6"))
