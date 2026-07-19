"""Central LocalAgent configuration. Everything overridable via environment variable."""
import os


def _load_dotenv():
    """Load .env (never committed) so local config/secrets reach the app. Minimal loader,
    no dependency: KEY=VALUE lines, '#' comments ignored, real env vars win."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

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
# Fallback context window when the backend can't report one (e.g. llama.cpp models,
# unknown to ollama). The A3B server runs at 32k, so that's a sane default.
DEFAULT_CTX = int(os.getenv("DEFAULT_CTX", "32768"))
DEFAULT_TOPK = int(os.getenv("RAG_TOPK", "6"))

# Max chars per MCP tool description sent to the model. Lower it (e.g. 250) to shrink the
# prompt when large MCPs (many tools) are active — faster prompt eval, slightly less guidance.
MCP_TOOL_DESC_MAX = int(os.getenv("MCP_TOOL_DESC_MAX", "900"))
