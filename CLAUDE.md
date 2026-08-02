# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run (pick one gateway)
./run-spa.sh              # FastAPI + vanilla-JS SPA on :8585 (primary UI)
./run.sh                  # Streamlit UI on :8501 (alternative)
./run-bot.sh              # Telegram bot (needs TELEGRAM_BOT_TOKEN in .env)
PORT=9000 ./run-spa.sh    # override port

# Tests
python -m pytest tests/ -v
python -m pytest tests/test_tools_guards.py -v             # one file
python -m pytest tests/test_tools_guards.py::test_name -v  # one test

# Lint / format (ruff)
uvx ruff check .
uvx ruff format .
```

Config: copy `.env.example` to `.env`. Only `OLLAMA_URL` matters to start — every other
integration (vault/RAG, MCP, Telegram, llama.cpp backend) degrades silently when unset.
`config.py` is the single source of truth for every override.

## Architecture

**One turn loop, three gateways.** `agent.run_turn` is the single place a conversational
turn is resolved: it assembles the system prompt (`build_system` = soul + skills catalog +
recalled memories), drives the model/tool loop, and does post-turn work (`finalize`: memory
auto-save + `trace.log`). `api.py` (SPA), `app.py` (Streamlit) and `telegram_bot.py` are thin
gateways that call `run_turn` and only handle their own transport/persistence — turn logic
never gets duplicated per-gateway; new turn behavior belongs in `agent.py`.

**Two inference backends, one call site.** `clients.py` talks to ollama's native API and, in
parallel, to an OpenAI-compatible backend (llama.cpp's `llama-server`, for MTP / exotic
quantizations) via `config.LLAMACPP_URL`. `_is_openai(model)` decides per-model which backend
handles a chat call, transparently to `agent.py`; `list_local_models()` merges both backends'
models into one list.

**Tools come from two places, merged into one spec list per call.** Native Python tools live
in `tools.py` (`SPECS`/`_IMPLS`, human descriptions externalized in `prompts/tools.es.json`):
web, vault (a git-backed notes directory at `VAULT_DIR`, works with Obsidian or any similar
setup), workspace filesystem/shell (confined to `WORKSPACE_DIR` via `_in_workspace()` /
`_BLOCKED_CMD`), HTML generation, skills. External MCP servers declared in `mcp.json` (same
shape as Claude's `mcpServers`) are connected by `mcp_bridge.MCPBridge`, which namespaces each
tool as `<server>__<tool>` to avoid collisions; its `.specs` are appended alongside the native
ones before every model call, and `.call()` is where tool execution routes when a name isn't a
native tool.

**Memory is delegated, not implemented here.** `memory.py` doesn't store facts itself — it's a
client of an external `mcp-memory` MCP server (recall before the turn, auto-save after). No
memory MCP configured/reachable → recall/save are silent no-ops, not errors.

**Everything is env-var configurable and degrades gracefully by design.** `config.py` holds
every endpoint/path (`OLLAMA_URL`, `LLAMACPP_URL`, `CORPUS_URL`, `VAULT_DIR`, `WORKSPACE_DIR`,
…), loaded from `.env` via a minimal built-in parser (no `python-dotenv` dependency). Each
integration point (vault search, MCP, memory) already treats "not configured" as a normal
case rather than an error — keep any new integration to that same pattern, and keep new tools
generic (driven by config, not by assumptions specific to one person's setup).

## Conventions (see CONTRIBUTING.md for the full flow)

- Conventional Commits (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`).
- One PR = one topic. Modules are kept short and read-as-prose on purpose — read a module
  fully before touching it. No new dependency without justification.
- Adding a tool → add a test in `tests/`. Touching `_in_workspace`/`_BLOCKED_CMD` → the
  existing guard tests in `tests/test_tools_guards.py` must stay green.
- AI-agent-authored PRs are accepted but must disclose the generating framework and name the
  human who reviewed/approved them.
