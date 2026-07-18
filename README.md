<div align="center">

<img src="web/favicon.svg" width="84" alt="LocalAgent">

# LocalAgent

**Agente de IA local, libre y para todos.**

Chat multi-sesión con modelos locales (ollama), memoria persistente por MCP,
tools (web, vault/RAG, filesystem, HTML) y presencia en web + Telegram.
**Cero nube, cero API keys de pago.**

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![Ollama](https://img.shields.io/badge/LLM-ollama-black)
![MCP](https://img.shields.io/badge/protocol-MCP-purple)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

<img src="docs/screenshots/01-chat.png" width="820" alt="LocalAgent — interfaz web">

</div>

> Software libre (MIT). El conocimiento se comparte: cloná, usá, modificá, compartí.

---

## 📸 Capturas

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/02-mcp.png" alt="Configuración de MCPs"><br><sub><b>Config → MCPs</b> — ver/editar servidores, alta y baja desde la UI</sub></td>
    <td width="50%"><img src="docs/screenshots/03-advanced-light.png" alt="Panel avanzado (tema claro)"><br><sub><b>Panel Avanzado</b> — sampling y system prompt, con tema claro</sub></td>
  </tr>
</table>

---

## 📖 Cómo funciona

Documentación técnica: arquitectura, ciclo de un turno, MCP, memoria, seguridad y buenas
prácticas.

- 📄 **[Leer en GitHub (markdown)](docs/como-funciona.md)** — se lee directo, sin descargar nada.
- 🖥️ **[Versión interactiva (HTML)](docs/como-funciona.html)** — misma info con acordeón y
  nav; descargala y abrila en el navegador (GitHub no renderiza HTML, muestra el fuente).

> Ambas versiones tienen el **mismo contenido**; elegí la que te resulte más cómoda.

## 💡 Por qué existe

No busca competirle en features a los clientes grandes de Ollama. Su gracia es otra: es
**chico y legible** — un núcleo de agente en Python que podés leer, entender y forkear en
una tarde. Sin build step, sin cadena de JS, sin nube. El anti-"caja negra": un repo
donde un PR se entiende sin arqueología.

Tres principios, los mismos que [mcp-memory](https://github.com/GermaniU/mcp-memory):

- **Todo en tu máquina** — el modelo, las conversaciones y la memoria; nada sale de tu LAN.
- **Una conexión, muchas piezas** — se arma con servidores MCP estándar que también usan
  otros clientes (Claude Code, Cursor, …). Lo que conectás acá sirve en todos.
- **Config sin sobrecarga** — con solo tener ollama ya arranca; lo demás es opcional y
  degrada solo si no lo configurás.

---

## ⚡ Quickstart

```bash
cp .env.example .env   # ajustá lo que uses (solo OLLAMA_URL es imprescindible)
./run-spa.sh           # UI web (SPA) en http://localhost:8585
```

Otros modos de arranque:

```bash
./run.sh               # UI clásica en Streamlit  → http://localhost:8501
./run-bot.sh           # bot de Telegram (requiere TELEGRAM_BOT_TOKEN en .env)
PORT=9000 ./run-spa.sh # SPA en otro puerto
```

Con solo tener **ollama** con un modelo de chat ya funciona. Memoria (MCP), vault/RAG y
Telegram son opcionales.

---

## 🧠 Memoria persistente — combinar con mcp-memory

LocalAgent **no reinventa la memoria**: la delega en un servidor MCP dedicado. El default
es [**mcp-memory**](https://github.com/GermaniU/mcp-memory) — memoria local con búsqueda
semántica (Ollama embeddings + Qdrant) que corre en tu máquina o en otra de tu LAN.

Así se combinan: mcp-memory expone las tools (`memory_save`, `memory_search`, `memory_recent`,
…) y LocalAgent es uno de sus **clientes**. El modelo local decide cuándo guardar un hecho
y cuándo recuperarlo, sin que vos toques nada.

```jsonc
// mcp.json  (en la raíz del proyecto — mismo formato que Claude)
{
  "mcpServers": {
    "agentic-memory-mcp": {
      "type": "http",
      "url": "http://localhost:8765/mcp"   // o la IP de la máquina donde corre mcp-memory
    }
  }
}
```

Levantá mcp-memory (ver su [Quickstart](https://github.com/GermaniU/mcp-memory)), apuntá
la URL en `mcp.json`, y en la UI **Config → MCPs** vas a ver el server: podés
activarlo/desactivarlo por chat, y **ver/editar su configuración** desde ahí mismo.

---

## 🔌 Conectar más servidores MCP

LocalAgent usa un `mcp.json` **propio del proyecto** (no hereda el de Claude). Sin archivo
= ningún MCP. Se puede editar a mano o todo desde la UI (**Config → MCPs**):

- **Agregar**: nombre + destino. Una URL `http(s)://…` crea un server HTTP; cualquier otra
  cosa se toma como comando stdio (`comando arg1 arg2`).
- **Ver / editar**: cada server muestra su tipo y destino; el lápiz abre la config para
  editarla (las variables de entorno con secretos se preservan y nunca se muestran).
- **Activar por chat**: un toggle decide si sus tools se ofrecen al modelo.

Formato (idéntico al `mcpServers` de Claude), con override por `MCP_CONFIG`:

```jsonc
{
  "mcpServers": {
    "remoto":  { "type": "http", "url": "http://host:puerto/mcp" },
    "local":   { "command": "python", "args": ["-m", "mi_server"], "env": { "API_KEY": "…" } }
  }
}
```

Ver `mcp.json.example`. El `mcp.json` está git-ignored (puede llevar claves en `env`).

---

## 🛠 Capacidades

| Capacidad | Qué habilita |
|---|---|
| **Web** | buscar en la web y leer páginas (`web_search` / `web_fetch`) |
| **Vault** | buscar y leer tus notas de Obsidian por RAG (`vault_search`) |
| **HTML** | generar documentos/páginas HTML (`write_html`) |
| **Thinking** | razonamiento extendido (solo en modelos que lo soportan) |
| **Memoria** | recordar hechos entre chats vía mcp-memory (auto-recall + auto-save) |
| **MCP** | cualquier tool de los servidores declarados en `mcp.json` |
| **Filesystem / Shell** | crear proyectos y correr comandos, confinado a `WORKSPACE_DIR` |

Cada capacidad se prende/apaga por chat desde el compositor.

---

## 🎯 Alcance actual

**Lo que hace** ✅
- Chat multi-sesión en streaming con modelos locales, selección por VRAM.
- Memoria persistente semántica (vía mcp-memory) y RAG sobre tus notas.
- Tools locales con guardas + puente a cualquier servidor MCP.
- Dos frentes: UI web (SPA) y bot de Telegram, sobre el mismo núcleo.

**Lo que NO hace (todavía)** ❌
- No es un sandbox: `run_cmd` corre comandos de dev que el modelo decide.
- No sincroniza sesiones entre máquinas (SQLite local).
- No multi-usuario / multi-tenant.

---

## 🧱 Arquitectura

```
┌─────────────┐   ┌──────────────┐
│  UI web SPA │   │  bot Telegram │        gateways (mismo núcleo)
│   :8585     │   │              │
└──────┬──────┘   └──────┬───────┘
       └────────┬────────┘
                ▼
        ┌───────────────┐   agent.py = build_system + finalize
        │  núcleo agente │   (un turno se resuelve igual en todos)
        └───────┬───────┘
     ┌──────────┼──────────────┬──────────────┐
     ▼          ▼              ▼              ▼
 ┌────────┐ ┌────────┐  ┌────────────┐  ┌──────────┐
 │ ollama │ │ tools  │  │ mcp_bridge │  │  vault   │
 │ (chat) │ │ locales│  │  (mcp.json)│  │  (RAG)   │
 └────────┘ └────────┘  └─────┬──────┘  └──────────┘
                              ▼
                     ┌──────────────────┐
                     │  mcp-memory      │  memoria semántica
                     │  (otra máquina)  │  Ollama emb + Qdrant
                     └──────────────────┘
```

La lógica de un turno vive en `agent.py`, así **UI y bot no divergen**.

---

## 🖥 Módulos

- `api.py` — backend FastAPI que sirve la SPA (`web/`) y expone el agente por HTTP.
- `web/` — frontend SPA en JS vanilla (sin build): `app.js`, `index.html`, `style.css`.
- `app.py` — UI clásica en Streamlit (alternativa a la SPA).
- `telegram_bot.py` — bot de Telegram (mismo núcleo y tools).
- `agent.py` — núcleo compartido: `build_system` + `finalize`.
- `clients.py` — cliente ollama (chat, streaming con tools, ventana de contexto) + corpus/RAG.
- `tools.py` — tools locales: web, vault, filesystem, shell (con guardas), HTML, skills.
- `memory.py` — memoria persistente sobre mcp-memory (auto-recall + auto-save).
- `mcp_bridge.py` — conecta los servers de `mcp.json` y expone sus tools.
- `skills.py` + `skills/` — procedimientos reutilizables (`use_skill`).
- `store.py` — persistencia de conversaciones (SQLite).
- `trace.py` — trazabilidad (JSONL) de cada turno.
- `config.py` — endpoints y parámetros (todo override por env var).

---

## 🎨 Personalizar

- **Personalidad:** editá `soul.md` (es el system prompt; se recarga en caliente). También
  desde la UI en **Config → Agente**.
- **Skills:** agregá un `.md` con frontmatter (`name`, `description`) en `skills/`.
- **Parámetros:** temperatura, top-p, máx. tokens, contexto y system prompt desde el panel
  **Avanzado** de la UI.
- **Tema:** claro/oscuro desde la UI; tokens de color en `web/style.css`.

---

## 🔒 Seguridad

`run_cmd` bloquea patrones destructivos y corre confinado a `WORKSPACE_DIR`, pero **no es
un sandbox**: ejecuta comandos de dev que el modelo decide. Los secretos (token de Telegram,
`env` de MCP servers, etc.) viven en `.env` / `mcp.json`, ambos git-ignored. Mantené criterio
sobre lo que ejecuta, sobre todo con entradas de terceros. El backend restringe CORS a
localhost y valida el path de los estáticos.

---

## 🩹 Troubleshooting

- **La UI tarda en cargar** → algún servicio opcional (MCP remoto) no responde. Los MCP se
  conectan al iniciar cada chat; desactivá el que esté caído en **Config → MCPs**.
- **El modelo escupe el tool call como texto en vez de ejecutarlo** → ese modelo no maneja
  bien tools. Probá con `gemma4:12b` u otro que soporte function-calling.
- **La memoria no guarda nada** → verificá que mcp-memory esté arriba y la URL de `mcp.json`
  sea alcanzable (`curl http://host:8765/mcp`), y que el server esté activo en la UI.
- **Respuestas cortadas** → subí "Máx. tokens" en el panel Avanzado.

---

## 📋 Requisitos

- ollama con al menos un modelo de chat local.
- Python 3.12+, deps en `requirements.txt`.
- (Opcional) [mcp-memory](https://github.com/GermaniU/mcp-memory) para memoria persistente,
  y un corpus/RAG para el vault.

---

## 🤝 Contribuir

Los PRs son bienvenidos. La idea es que el código siga siendo **legible**: cambios chicos y
enfocados, sin dependencias de más, en el mismo estilo del módulo que tocás. Para algo
grande, abrí un issue primero y lo charlamos.

---

## ☕ Apoyar

Es gratis y libre. Si te sirve y podés, invitame un café:

[![PayPal](https://img.shields.io/badge/☕_Invitame_un_café-PayPal-0070ba?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/GermaniUicab)

→ **[paypal.me/GermaniUicab](https://paypal.me/GermaniUicab)**

## 📄 Licencia

[MIT](LICENSE) — libre para usar, modificar y compartir.

Hecho por [@GermaniU](https://github.com/GermaniU). Si te sirve, dale una ⭐ y reportá issues.
