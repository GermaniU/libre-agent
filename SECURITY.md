# Política de Seguridad

## Modelo de amenaza

LocalAgent corre **en tu máquina**, habla con modelos **locales** (ollama / llama.cpp) y
no envía datos a ninguna nube. El perímetro de seguridad es tu LAN.

Dicho esto, el agente ejecuta acciones que el modelo decide (tools, shell, filesystem),
así que hay superficies que importa conocer:

| Superficie          | Mitigación actual                                                     |
|---------------------|-----------------------------------------------------------------------|
| `run_cmd`           | Denylist de patrones destructivos (`_BLOCKED_CMD`), confinado a `WORKSPACE_DIR` |
| Filesystem          | Todas las operaciones pasan por `_in_workspace()` — anti-traversal    |
| MCP servers         | Cada server se conecta explícitamente (`mcp.json`); secretos en `env` nunca se exponen en la UI |
| API (`api.py`)      | CORS restringido a localhost; paths de estáticos validados            |
| Secretos            | `.env` y `mcp.json` están en `.gitignore`                            |

### Lo que NO es un sandbox

`run_cmd` **no** corre en contenedor ni en VM. Los patrones bloqueados cubren lo
claramente destructivo, pero un modelo puede generar comandos inesperados. No expongas
el agente a entradas no confiables de terceros sin supervisión.

---

## Reportar una vulnerabilidad

Si encontrás un problema de seguridad (bypass de `_in_workspace`, evasión de la denylist,
exposición de secretos, etc.):

1. **No abras un issue público.** Escribí directo a [@GermaniU](https://github.com/GermaniU)
   por mensaje privado en GitHub o al correo que figure en su perfil.
2. Describí el problema, cómo reproducirlo, y qué impacto tiene.
3. Te responderemos dentro de **72 horas** con un plan de acción.
4. Si es un fix, lo aplicamos primero y después publicamos el advisory.

---

## Buenas prácticas para usuarios

- **No apuntes `WORKSPACE_DIR` a `/` o a tu home.** Usá un directorio acotado.
- **Revisá `mcp.json`** — no conectes servers MCP que no conozcas.
- **Mantené ollama actualizado** — las vulnerabilidades del modelo son upstream.
- **Si exponés el puerto de la SPA fuera de localhost**, agregá autenticación (reverse
  proxy con auth básica, por ejemplo).

---

## Alcance del programa

Consideramos en alcance:

- Bypass de las guardas de filesystem (`_in_workspace`).
- Evasión de `_BLOCKED_CMD` con comandos destructivos.
- Exposición de secretos (`.env`, `mcp.json` keys) vía la API o la UI.
- SSRF o acceso a recursos internos no intencionados desde `web_fetch`.
- XSS persistente en `write_html` que afecte al usuario.

**Fuera de alcance:** bugs en ollama, en modelos LLM, o en servers MCP de terceros.

---

Gracias por ayudar a mantener LocalAgent seguro. 🛡️
