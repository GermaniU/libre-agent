# Cómo funciona LocalAgent

Un agente de IA que corre 100% en tu máquina — arquitectura, ciclo de un turno, MCP,
memoria y las decisiones de diseño detrás del código.

> **TL;DR** — ollama pone el cerebro, `agent.py` orquesta el turno, las `tools` y el
> `mcp_bridge` ponen las manos, y SQLite + mcp-memory ponen la memoria.

> 💡 Esta es la versión markdown (legible directo en GitHub). Hay una versión
> **interactiva** en [`como-funciona.html`](como-funciona.html) — descargala y abrila
> en el navegador.

---

## 1. Visión general

**LocalAgent** es un asistente/agente que corre íntegramente en tu máquina: el modelo (vía
**ollama**), las conversaciones (SQLite) y la memoria (un servidor MCP). No hay nube ni API
keys de pago. Se opera desde una **UI web (SPA)** o un **bot de Telegram**, ambos sobre el
mismo núcleo.

**Tres principios de diseño:**

- **Legible sobre completo.** ~3.600 líneas que se entienden en una tarde; sin build step,
  sin cadena de JS, sin framework de frontend.
- **Un núcleo, muchos gateways.** La lógica de un turno vive en un solo lugar (`agent.py`),
  así la UI y el bot nunca divergen.
- **Estándar sobre custom.** Las capacidades externas (memoria, tools de terceros) entran
  por **MCP**, el mismo protocolo que usan Claude Code o Cursor: lo que conectás acá sirve
  en todos.

---

## 2. Arquitectura

Dos **gateways** (UI web y bot) hablan con un **núcleo** compartido. El núcleo delega en
ollama para el razonamiento, en las tools locales y el puente MCP para las acciones, y en
la capa de memoria para el contexto persistente.

```
┌──────────────┐   ┌───────────────┐
│  UI web SPA  │   │  bot Telegram │   gateways (mismo núcleo)
│   :8585      │   │               │
└──────┬───────┘   └──────┬────────┘
       └─────────┬────────┘
                 ▼
         ┌────────────────┐   agent.run_turn (un turno se resuelve igual en todos)
         │  núcleo agente │
         └───────┬────────┘
    ┌────────────┼───────────────┬───────────────┐
    ▼            ▼               ▼               ▼
┌──────────┐┌─────────┐   ┌────────────┐  ┌──────────┐
│ modelos  ││  tools  │   │ mcp_bridge │  │  vault   │
│          ││ locales │   │ (mcp.json) │  │  (RAG)   │
│ ollama   │└─────────┘   └─────┬──────┘  └──────────┘
│ llama.cpp│                    ▼
│ (:8080,  │           ┌──────────────────┐
│  OpenAI) │           │   mcp-memory     │  memoria semántica
└──────────┘           │  (otra máquina)  │  Ollama emb + Qdrant
                       └──────────────────┘
```

> **Por qué así** — Separar *gateway* de *núcleo* es lo que evita el bug clásico de "la UI
> hace una cosa y el bot otra". Un turno de chat es una función pura de orquestación; los
> gateways solo adaptan entrada/salida (HTTP streaming vs. mensajes de Telegram).

---

## 3. El ciclo de un turno

Cuando enviás un mensaje en la SPA, el backend abre un **stream NDJSON** (`POST /api/chat`)
y emite eventos en vivo. Recorrido real (`api.py` + `clients.chat_stream_with_tools`):

1. **Cargar sesión.** `store.load_sessions()` trae el historial; se agrega tu mensaje.
2. **Armar el system prompt.** `agent.build_system(soul, mensaje, use_memory)` combina
   `soul.md` con un *auto-recall* de memoria relevante. Emite evento `recall`.
3. **Conectar MCPs.** Si hay servidores activos, `mcp_bridge.MCPBridge` los levanta y suma
   sus `specs` a las tools locales.
4. **Loop de rondas.** Se llama a ollama con `stream=True`. Los tokens del texto salen en
   vivo (evento `token`). Si el modelo pide una tool, se emite `tool`, se ejecuta
   (`tools.execute` o `bridge.call`), se agrega el resultado y se repite — hasta que no
   haya más tool calls o se llegue a `max_rounds`.
5. **Cerrar.** `agent.finalize()` hace *auto-save* de hechos nuevos a la memoria y escribe
   la traza (`trace.py`). Evento `done` con `reply`, `calls`, `usage` y `meta`.
6. **Persistir.** `store.save_session()` guarda la conversación actualizada en SQLite.

> **Degradación elegante** — Si el modelo elegido no soporta tools o *thinking*,
> `clients.py` lo detecta en el error de ollama, reintenta sin esa capacidad y sigue. El
> turno nunca se cae por elegir un modelo "chico".

---

## 4. Módulos

| Módulo | Líneas | Responsabilidad |
|---|---|---|
| `agent.py` | 43 | Núcleo compartido: `build_system` (prompt + recall) y `finalize` (save + trace). |
| `clients.py` | ~560 | Inferencia: ollama + backend OpenAI (llama.cpp, con tools) + corpus/RAG del vault. |
| `tools.py` | 376 | Tools locales: web, vault, filesystem, shell (con guardas), HTML, skills. |
| `api.py` | 417 | Backend FastAPI: sirve la SPA y expone el agente por HTTP (streaming NDJSON). |
| `app.py` | 345 | UI clásica en Streamlit (alternativa a la SPA). |
| `telegram_bot.py` | 289 | Bot de Telegram sobre el mismo núcleo y tools. |
| `mcp_bridge.py` | 104 | Conecta los servers de `mcp.json` (stdio/http) y expone sus tools namespaceadas. |
| `memory.py` | 107 | Memoria persistente sobre mcp-memory: auto-recall + auto-save. |
| `store.py` | 69 | Persistencia de conversaciones en SQLite. |
| `skills.py` | 69 | Procedimientos reutilizables (`skills/*.md`), invocables con `use_skill`. |
| `trace.py` | 33 | Trazabilidad JSONL de cada turno. |
| `config.py` | 24 | Endpoints y parámetros; todo override por variable de entorno. |
| `web/app.js` | 1426 | Frontend SPA en JS vanilla: estado, render, streaming, config. |

---

## 5. Tools y el loop de function-calling

Cada tool se declara con un *spec* (nombre, descripción, JSON Schema de parámetros) en
formato ollama/OpenAI. El modelo decide cuándo llamarlas; `clients.py` ejecuta la llamada,
le devuelve el resultado y deja que el modelo continúe.

| Tool | Qué hace |
|---|---|
| `web_search` / `web_fetch` | Buscar en la web (DuckDuckGo) y leer páginas. |
| `vault_search` | RAG semántico sobre tus notas de Obsidian (vía corpus/Qdrant). |
| `write_html` | Genera una página HTML autocontenida en `static/`. |
| `run_cmd` / filesystem | Crear proyectos y correr comandos de dev, confinado a `WORKSPACE_DIR`. |
| `use_skill` | Ejecuta un procedimiento definido en `skills/*.md`. |
| `<server>__<tool>` | Cualquier tool de un servidor MCP activo (ver sección MCP). |

Las tools se activan por chat desde el compositor (píldoras **Web**, **Vault**, **HTML**,
**Memoria**). Si están todas apagadas, el modelo responde sin herramientas.

---

## 6. MCP — Model Context Protocol

LocalAgent usa un `mcp.json` **propio del proyecto** (no hereda el de Claude). Sin archivo =
ningún MCP. El `mcp_bridge` los conecta al iniciar cada chat, soporta transporte **stdio** y
**http**, y namespacea cada tool como `<server>__<tool>` para que no choquen.

```jsonc
{
  "mcpServers": {
    "agentic-memory-mcp": {
      "type": "http",
      "url": "http://192.168.68.138:8765/mcp"
    },
    "local": {
      "command": "python",
      "args": ["-m", "mi_server"],
      "env": { "API_KEY": "…" }
    }
  }
}
```

Todo el ciclo de vida se maneja desde la UI (**Config → MCPs**): alta, baja,
activar/desactivar por chat, y **ver/editar la config** de cada server. Las variables de
entorno con secretos se preservan y nunca se muestran al frontend.

> **Combinar con mcp-memory** — El default es
> [mcp-memory](https://github.com/GermaniU/mcp-memory): LocalAgent es uno de sus clientes.
> El servidor expone `memory_save`, `memory_search`, etc.; el modelo decide cuándo guardar
> y recuperar. Una conexión estándar, muchos clientes.

---

## 7. Memoria

**Corto plazo — la conversación.** `store.py` guarda cada sesión como un blob JSON en
SQLite (mensajes, tool calls, tokens). Sobrevive reinicios; es lo que ves en el sidebar
como "espacios".

**Largo plazo — memoria semántica.** `memory.py` se apoya en **mcp-memory** (Ollama
embeddings + Qdrant). Tiene dos caminos:

- **Automático** (píldora "Memoria"): `build_system` hace *recall* de hechos relevantes en
  cada turno, y `finalize` hace *save* de lo nuevo. No depende de que el modelo lo pida.
- **Explícito** (tools MCP): el modelo llama `agentic-memory-mcp__memory_search` /
  `__memory_save` cuando lo decide.

> **Ojo con el modelo** — El camino explícito depende de que el modelo *elija* llamar la
> tool. Modelos chicos a veces no la disparan con prompts vagos; para recall confiable,
> dejá prendida la píldora "Memoria" (auto-recall) o sé explícito ("buscá en tu memoria X").

---

## 8. Frontend SPA

La UI web es un único `web/app.js` (JS vanilla, sin framework ni bundler). Un objeto
`state` global + una función `render()` que reconstruye el HTML por template strings. Los
eventos se enganchan una sola vez con delegación (`data-action`).

- **Streaming.** `sendMessage()` lee el body como stream y parsea NDJSON línea por línea;
  `handleEvent()` pinta tokens con throttling por `requestAnimationFrame`.
- **Markdown ligero.** `mdToHtml` renderiza títulos, listas, tablas y bloques de código;
  todo texto se escapa (`esc`) y los links se filtran por esquema (anti-XSS).
- **Persistencia de UI.** Tema, modelo y toggles en `localStorage`; las sesiones van al
  backend.

> **Trade-off consciente** — Render por template strings = cero dependencias y todo el
> flujo visible en un archivo. El costo es un `app.js` grande; la mitigación es el escapado
> estricto y el enganche único de listeners.

---

## 9. Seguridad

| Área | Guarda |
|---|---|
| Shell (`run_cmd`) | Bloquea patrones destructivos y corre confinado a `WORKSPACE_DIR`. |
| Estáticos | `realpath` + contención de directorio (anti path-traversal). |
| CORS | Restringido a orígenes de localhost. |
| XSS | Escapado estricto en el render; links solo con esquema http/mailto/relativo. |
| Secretos | Token de Telegram y `env` de MCP en `.env` / `mcp.json`, ambos git-ignored. |

> **No es un sandbox** — `run_cmd` ejecuta comandos de dev que el modelo decide. Las guardas
> reducen el daño accidental, pero mantené criterio sobre lo que corre, sobre todo con
> entradas de terceros (prompt injection vía contenido web/vault).

---

## 10. Buenas prácticas y deuda técnica

Veredicto de una revisión senior del código: **buen nivel para un proyecto personal** —
docstrings que explican el *por qué*, XSS bien pensado en el front, secretos enmascarados y
deps pinneadas. Lo que lo separa de "profesional/mantenible" es la falta de red de
seguridad (tests, logging) y de disciplina de tooling.

**Lo que está bien:** intento real de **núcleo compartido** (`agent.py`), **docstrings**
abundantes y con criterio, manejo de **XSS** correcto en el frontend (`esc()` + href por
esquema), **secretos enmascarados** (`env_keys` nunca expone valores) y **dependencias
pinneadas** con política de actualización.

**Las 3 mejoras de mayor impacto:**

1. **Red de seguridad** *(tests ya agregados ✓)* — 17 tests con pytest sobre las superficies
   peligrosas: guardas de path (`_in_workspace`, `_safe_file`, incluido el caso de prefijo
   hermano), denylist de `run_cmd`, round-trip de `store.py`, parseo de skills y MCP config.
   Falta todavía introducir `logging` configurado (hoy los `except Exception: pass` tragan
   errores sin dejar rastro).
2. **Eliminar duplicación estructural** — Desacoplar `memory.py` de Streamlit y subir la
   orquestación del turno a `agent.py`: hoy el loop está casi duplicado entre `app.py`,
   `api.py` y `telegram_bot.py` — incluido `_soul()` definido 3 veces con fallbacks
   divergentes.
3. **Tooling y superficie de ataque** — `pyproject.toml` + **ruff** + pre-commit
   *(pyproject.toml ya agregado ✓)*, y endurecer `run_cmd` (opt-in de shell; la denylist
   regex es evadible con `shell=True`) y `web_fetch` (bloqueo de IPs privadas anti-SSRF).

> **Riesgos de seguridad concretos** — `run_cmd`: `subprocess.run(shell=True)` sobre
> comandos del modelo, confinado solo por `cwd` + denylist evadible → el confinamiento a
> `WORKSPACE_DIR` es ilusorio. `web_fetch`: SSRF hacia servicios internos. `vault_read`:
> chequeo de prefijo sin `os.sep`. `CORPUS_KEY`: default hardcodeado.

---

## 11. Correrlo

```bash
cp .env.example .env    # solo OLLAMA_URL es imprescindible
./run-spa.sh            # UI web (SPA) → http://localhost:8585

# opcionales
./run.sh                # UI clásica Streamlit → :8501
./run-bot.sh            # bot de Telegram (requiere TELEGRAM_BOT_TOKEN)
PORT=9000 ./run-spa.sh  # otro puerto
```

Con solo tener **ollama** y un modelo de chat ya funciona. Memoria (MCP), vault/RAG y
Telegram son opcionales y degradan solos si no los configurás.

---

# Fundamentos

Las secciones anteriores explican *qué hace* cada parte. Estas explican los **conceptos por
dentro** — el cómo y el porqué de un asistente local. Algunos valores numéricos (VRAM,
tokens) son ejemplos ilustrativos; ajustá a tu modelo y hardware.

## F1. Ollama, GGUF y cuantización

Para correr un LLM localmente hacen falta dos cosas: un **modelo** y un **runtime** que lo
ejecute. **Ollama** es ese runtime: un servidor local (puerto `11434`) que expone una API
REST. LocalAgent le habla por `POST /api/chat` con `stream=True` (`clients.py`).

Los modelos no se distribuyen en su formato original (pesarían cientos de GB): se comprimen
con **cuantización** en formato **GGUF**. La cuantización baja la precisión de los pesos
para reducir tamaño y VRAM, a costa de algo de calidad. La nomenclatura `Q2…Q8` indica los
bits por peso: más alto = más calidad y más peso.

| Cuantización | Tamaño (modelo 26B) | Calidad | VRAM aprox. |
|---|---|---|---|
| Q8_0 | ~28 GB | Casi idéntica | ~30 GB |
| Q5_K_M | ~19 GB | Excelente | ~20 GB |
| Q4_K_M | ~16 GB | Muy buena | ~17 GB |
| Q3_K_M | ~12 GB | Aceptable | ~13 GB |
| Q2_K | ~10 GB | Pérdida notable | ~11 GB |

Si la GPU no tiene VRAM suficiente, el modelo corre en **CPU** (funciona, pero más lento:
~10-15 tok/s vs 30-50 en GPU). Regla práctica: una **RTX 3060 (12 GB)** corre modelos hasta
~7B en GPU holgado. **LocalAgent hace esto automático**: con `VRAM_GB` en `config.py`
calcula qué modelos entran y marca con ⚠️ CPU los que no (`clients.list_local_models`).

| Modelo | Params | Fortaleza |
|---|---|---|
| Gemma 4 | 26B | Razonamiento + tools |
| Llama 3.1 | 8B | Versátil, rápido |
| Qwen 2.5 | 7B | Código + multilingüe |
| Phi-3 | 3.8B | Muy eficiente (CPU) |
| LLaVA / Qwen-VL | varía | Visión + lenguaje |

## F2. Embeddings y RAG

Un **embedding** convierte un texto en un **vector** (lista de números) que representa su
*significado*. Textos con significado parecido quedan cerca en el espacio vectorial, así se
puede buscar **por significado** y no por palabras exactas ("perro" y "can" caen cerca).

```
"Cómo configurar Ollama en Linux"
  → [modelo de embeddings] → [0.023, -0.451, 0.877, …] (p.ej. 768 dims)
  → buscar los vectores más cercanos en el índice
  → los N fragmentos más similares semánticamente
```

**Chunking:** no se busca sobre un documento entero; se lo parte en **chunks** de ~300-500
tokens con **overlap** (superposición) para no perder contexto en los bordes. Cada chunk se
convierte en embedding y se indexa.

| Modelo de embeddings | Dims | Nota |
|---|---|---|
| all-MiniLM-L6-v2 | 384 | Rápido, buen balance |
| nomic-embed-text | 768 | Optimizado para RAG |
| bge-m3 | 1024 | Multilingüe (español) |

**El pipeline RAG (dos fases):**

```
INDEXACIÓN (una vez, o al cambiar archivos):
  Vault (.md) → chunker → embeddings → índice vectorial

BÚSQUEDA (en cada pregunta):
  Pregunta → embedding → búsqueda top-K → inyectar los chunks en el prompt
```

> **En LocalAgent**: el RAG del vault (`vault_search`) usa un **corpus sobre Qdrant** (índice
> vectorial) en vez de FAISS; y la memoria de largo plazo (mcp-memory) también es Qdrant +
> embeddings de Ollama. El concepto es el mismo; cambia la pieza de almacenamiento.

## F3. Tool calling

El LLM **no ejecuta nada** por sí mismo: genera un **JSON estructurado** pidiendo llamar una
función; tu código la interpreta, ejecuta la función real y le devuelve el resultado para
que redacte la respuesta final. El modelo es el cerebro que decide; el código es el cuerpo
que ejecuta. **MCP** estandariza cómo se declaran y ejecutan esas tools (un "USB-C para AI
tools").

Formato de una tool (estilo ollama/OpenAI, el que consume LocalAgent):

```json
{
  "type": "function",
  "function": {
    "name": "vault_search",
    "description": "Busca semánticamente en las notas del vault del usuario.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Consulta de búsqueda"}
      },
      "required": ["query"]
    }
  }
}
```

El **loop** (el modelo puede encadenar varias tools antes de responder; hace falta un tope
de rondas — en LocalAgent `max_rounds`):

```python
messages = [{"role": "user", "content": user_input}]
for _ in range(MAX_ROUNDS):
    resp = call_model(messages, tools=specs)
    if resp.tool_calls:
        for tc in resp.tool_calls:
            result = execute_tool(tc.name, tc.arguments)
            messages.append(tc.message)                       # lo que pidió el modelo
            messages.append({"role": "tool", "content": result})  # lo que devolvió
    else:
        return resp.content                                   # respuesta final
```

> **En LocalAgent**: esto es exactamente `clients.chat_stream_with_tools` — resuelve las
> rondas en streaming, ejecuta con `tools.execute` (locales) o `bridge.call` (MCP), y corta
> por `max_rounds`.

## F4. Memoria persistente

Un LLM no recuerda nada entre conversaciones: cada chat empieza de cero. La memoria
persistente guarda datos clave del usuario y los reinyecta. Un "cuaderno de notas" que el
asistente lee antes de conversar.

```
FIN DE CONVERSACIÓN:
  Chat → prompt "extraé datos memorables" → hechos → guardar

INICIO DE CONVERSACIÓN:
  Memoria → filtrar relevantes → inyectar en el system prompt
```

Estructura de un recuerdo y **prompt de extracción**:

```json
{"category": "proyecto", "content": "Publicó el repo libre-agent en GitHub", "created": "2026-07-18"}
```

```
Analizá la conversación y extraé hechos memorables sobre el usuario. Solo lo que sirva a
futuro. Reglas: no repitas lo ya conocido; categorizá (negocio, tecnología, interés,
personal, proyecto); sé específico; ignorá saludos y datos temporales.
Salida JSON: [{"category": "...", "content": "..."}]  ·  Si no hay nada nuevo: []
```

**Estrategias de recall:** inyectar todo (simple, gasta tokens, ok con pocos hechos) ·
**embedding-based** (busca los hechos más relevantes a la pregunta — escalable) · por
categorías.

> **En LocalAgent**: usa la estrategia **embedding-based** vía mcp-memory (búsqueda
> semántica en Qdrant). `memory.py` hace *auto-recall* en `build_system` y *auto-save* en
> `finalize`; el modelo también puede llamar las tools `memory_*` explícitamente.

## F5. Contexto y tokens

Todo modelo tiene un **context window**: el máximo de texto por llamada (p.ej. 8k–32k
tokens). Conversión útil: **~4 caracteres ≈ 1 token** en español. Es la "memoria de trabajo"
del modelo; administrar ese presupuesto es trabajo del gateway.

```
SYSTEM PROMPT       ~800   instrucciones fijas
MEMORIA INYECTADA   ~200   hechos del usuario
TOOL DEFINITIONS    ~600   schemas de las tools
HISTORIAL           variable
MENSAJE ACTUAL      ~50
MARGEN DE SEGURIDAD ~1000
```

**Estrategias al acercarse al límite:**

| Estrategia | Cómo funciona | Trade-off |
|---|---|---|
| Sliding window | Borra los mensajes más viejos | Pierde contexto antiguo |
| Resumen | Un LLM chico resume lo viejo | Pierde detalle, agrega latencia |
| Truncar tool results | Corta resultados largos | Puede perder info |
| Tool defs dinámicas | Solo inyecta tools relevantes | El modelo no sabe de las otras |

> **En LocalAgent**: `clients.context_limit` lee el límite del modelo y `_ctx_estimate`
> estima el uso; la UI muestra la barra `N / Nk ctx` en el header. El contexto se elige por
> chat en el panel Avanzado (`num_ctx`).

## F6. Visión

La visión deja al asistente "ver" imágenes (screenshots, fotos de documentos, diagramas).
Se implementa mandando la imagen en **base64** dentro del mismo mensaje `user`, con `content`
como lista de partes.

| Modelo | Visión |
|---|---|
| Qwen 2.5-VL | Sí, nativa (multilingüe) |
| LLaVA | Sí, especializado |
| Gemma 4 | Sí, nativa |
| Llama 3.1 8B | No (solo texto) |

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "¿Qué muestra esta imagen?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo…"}}
  ]
}
```

**Prácticas:** una imagen de 1 MB en base64 puede consumir ~1.000-2.000 tokens →
**redimensioná** antes de enviar (máx ~1.200px). LocalAgent lista los modelos de visión
aparte (`qwen2.5vl`, `llava`, …) detectándolos por su `kind`.

---

*LocalAgent · agente de IA local, libre y para todos (MIT).*
[☕ Invitame un café](https://paypal.me/GermaniUicab)
