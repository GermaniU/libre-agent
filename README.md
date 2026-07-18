# LibreAgent

**IA agéntica local, libre y para todos.** Un asistente/agente que corre **100% en tu
máquina** — chat multi-sesión con modelos locales (ollama), memoria persistente, tools,
RAG sobre tus notas y presencia en web + Telegram. Cero nube, cero API keys de pago.

> Software libre (MIT). El conocimiento se comparte: cloná, usá, modificá, compartí.

## Por qué

No busca competirle en features a los clientes grandes de Ollama. Su gracia es otra: es
**chico y legible** — un núcleo de agente en Python (~1.700 líneas) que podés leer,
entender y forkear en una tarde. Sin build step, sin cadena de JS, sin nube. El
anti-"caja negra": un repo donde un PR se entiende sin arqueología.

## Anatomía del agente

| Componente | Implementación |
|---|---|
| **Cerebro** (reasoning) | ollama local, selección de modelo por VRAM |
| **Alma** (soul) | `soul.md` — identidad, criterio, routing (se recarga en caliente) |
| **Memoria** | corto plazo en SQLite (`store.py`) + largo plazo semántico vía `mcp-memory` (opcional) |
| **Manos** (tools) | web, vault/RAG, filesystem, shell, HTML, puente MCP |
| **Skills** | procedimientos reutilizables en `skills/*.md`, invocables con `use_skill` |
| **Gateway** | UI Streamlit + bot de Telegram, sobre un núcleo común (`agent.py`) |

La lógica de un turno vive en `agent.py`, así **UI y bot no divergen**.

## Módulos

- `app.py` — UI Streamlit (chat, toggles, monitor de recursos, visor de trazas).
- `telegram_bot.py` — bot de Telegram (mismo núcleo y tools que la UI).
- `agent.py` — núcleo compartido: `build_system` + `finalize`.
- `clients.py` — cliente ollama (chat, streaming con tools, ventana de contexto) + corpus/RAG.
- `tools.py` — tools locales: web, vault, filesystem, shell (con guardas), HTML, skills.
- `memory.py` — memoria persistente sobre mcp-memory (auto-recall + auto-save).
- `mcp_bridge.py` — conecta MCP servers de `~/.claude.json` y expone sus tools.
- `skills.py` + `skills/` — procedimientos reutilizables.
- `store.py` — persistencia de conversaciones (SQLite).
- `trace.py` — trazabilidad (JSONL) de cada turno.
- `config.py` — endpoints y parámetros (todo override por env var).

## Correr

```bash
cp .env.example .env   # ajustá lo que uses (solo ollama es imprescindible)
./run.sh               # UI en http://localhost:8501
./run-bot.sh           # bot de Telegram (requiere .env con TELEGRAM_BOT_TOKEN)
```

Con solo tener **ollama** con un modelo de chat ya arranca; corpus/RAG, memoria, MCP y
Telegram son opcionales y degradan solos si no los configurás.

Config por variables de entorno (ver `.env.example` y `config.py`): `OLLAMA_URL`,
`DEFAULT_MODEL`, `VRAM_GB`, `CORPUS_URL`, `VAULT_DIR`, `WORKSPACE_DIR`.

## Personalizarlo

- **Personalidad:** editá `soul.md` (es el system prompt; se recarga en caliente).
- **Skills:** agregá un `.md` con frontmatter (`name`, `description`) en `skills/`.
- **Tema:** paleta en `.streamlit/config.toml` + la capa CSS en `app.py`.

## Seguridad

`run_cmd` bloquea patrones destructivos y corre confinado a `WORKSPACE_DIR`, pero **no es
un sandbox**: ejecuta comandos de dev que el modelo decide. Los secretos (token de
Telegram, etc.) viven en `.env` (git-ignored). Mantené criterio sobre lo que ejecuta,
sobre todo con entradas de terceros.

## Requisitos

- ollama con al menos un modelo de chat local.
- Python 3.12+, deps en `requirements.txt`.
- (Opcional) un servidor MCP de memoria y un corpus/RAG para el vault.

## Contribuir

Los PRs son bienvenidos. La idea es que el código siga siendo **legible**: cambios
chicos y enfocados, sin dependencias de más, en el mismo estilo del módulo que tocás.
Para algo grande, abrí un issue primero y lo charlamos.

## Licencia

[MIT](LICENSE) — libre para usar, modificar y compartir.

## Apoyar

Es gratis y libre. Si te sirve y podés, invitame un café ☕ →
[paypal.me/TU_USUARIO](https://paypal.me/TU_USUARIO) *(reemplazá por tu usuario)*.
