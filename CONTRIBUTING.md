# Contribuir a LocalAgent

¡Gracias por querer contribuir! Este proyecto es **software libre** y los PRs son
bienvenidos — tanto de humanos como de agentes autónomos.

---

## Principios

1. **Legibilidad ante todo.** El código debe poder leerse como prosa. Si un cambio
   requiere un párrafo de explicación en el PR, probablemente necesita ser más simple.
2. **Cambios chicos y enfocados.** Un PR = un tema. Si tocás dos cosas distintas, hacé
   dos PRs.
3. **Sin dependencias de más.** Cada `import` nuevo se justifica. Si se puede resolver
   con la stdlib o con lo que ya está, mejor.
4. **Mismo estilo del módulo que tocás.** No reformatear archivos que no son parte del
   cambio.

---

## Flujo de trabajo

```bash
# 1. Fork + clone (o clone directo si tenés acceso)
git clone https://github.com/GermaniU/libre-agent.git
cd libre-agent

# 2. Crear rama descriptiva
git checkout -b feat/mi-feature        # feat/, fix/, docs/, refactor/

# 3. Instalar dependencias
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Hacer los cambios — mantener el estilo existente

# 5. Correr los tests
python -m pytest tests/ -v

# 6. Commit con mensaje convencional
git commit -m "feat(tools): agregar tool X para hacer Y"

# 7. Push y abrir PR contra main
git push origin feat/mi-feature
```

### Convención de commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

| Prefijo      | Cuándo                                           |
|-------------|--------------------------------------------------|
| `feat`      | Nueva funcionalidad                               |
| `fix`       | Corrección de bug                                 |
| `docs`      | Solo documentación                                |
| `refactor`  | Cambio interno sin alterar comportamiento         |
| `test`      | Agregar o corregir tests                          |
| `chore`     | Mantenimiento (deps, CI, configs)                 |

---

## Tests

Antes de abrir un PR, asegurate de que la suite pase:

```bash
python -m pytest tests/ -v
```

Si tu cambio agrega una tool nueva, agregá un test en `tests/`. Si toca guardas de
seguridad (`_in_workspace`, `_BLOCKED_CMD`), verificá que los tests existentes sigan
pasando.

---

## Estructura del proyecto

```
agent.py        ← núcleo compartido (run_turn, build_system)
api.py          ← backend FastAPI (SPA)
app.py          ← UI Streamlit (alternativa)
telegram_bot.py ← bot de Telegram
clients.py      ← clientes de inferencia (ollama, llama.cpp)
tools.py        ← tools locales + specs
memory.py       ← memoria persistente (mcp-memory)
mcp_bridge.py   ← puente a servidores MCP
config.py       ← configuración central (env vars)
store.py        ← persistencia SQLite de conversaciones
prompts/        ← prompts externalizados (soul, memory, tools)
skills/         ← skills reutilizables (.md)
web/            ← frontend SPA (vanilla JS)
tests/          ← pytest suite
```

Antes de tocar un módulo, leelo completo. Son archivos cortos a propósito.

---

## Contribuciones de agentes IA 🤖

Este proyecto acepta PRs generados por agentes autónomos (Hermes, Claude, Cursor,
Copilot, etc.) bajo estas condiciones:

1. **Atribución clara.** El PR debe indicar en su descripción:
   - Que fue generado por un agente.
   - Qué framework/plataforma lo generó (ej: *"Generado por Hermes Agent — framework
     de agentes de @GermaniU"*).
   - Quién es el humano responsable que lo revisó/aprobó.

2. **Misma calidad.** Un PR de agente se evalúa con los mismos criterios que uno humano:
   tests pasan, código legible, cambio enfocado.

3. **Sin PRs de relleno.** No se aceptan contribuciones cosméticas vacías (reformateo
   masivo, comentarios obvios, cambios que no aportan). Aplica igual para humanos.

4. **El humano responsable revisa.** Aunque el agente generó el código, un humano debe
   haberlo leído y aprobado antes de hacer merge.

---

## ¿Algo grande? Abrí un issue primero

Si tu cambio es una feature nueva significativa, un refactor de arquitectura o una
dependencia pesada, abrí un issue antes de codear. Lo charlamos y nos ponemos de acuerdo
en el approach.

---

## Licencia

Al contribuir aceptás que tu código se publica bajo la misma [licencia MIT](LICENSE) del
proyecto.

---

Hecho con ❤️ por la comunidad de LocalAgent.
