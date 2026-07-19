# Golden evals — LocalAgent

**Modelo:** `gemma4:12b`  ·  **Resultado:** 10/11 (90%)  ·  **Tiempo:** 131s

| Caso | ✓ | Tools | Motivo de fallo |
|------|---|-------|-----------------|
| `route-web` | ✅ | web_search |  |
| `route-vault` | ✅ | vault_pull, vault_recent |  |
| `route-html` | ❌ | ∅ | esperaba tool 'write_html', llamó ∅ |
| `no-tool-knowledge` | ✅ | ∅ |  |
| `no-tool-opinion` | ✅ | ∅ |  |
| `no-leak-web` | ✅ | web_search |  |
| `lang-neutral-greeting` | ✅ | ∅ |  |
| `lang-neutral-instruction` | ✅ | ∅ |  |
| `route-vault-recent` | ✅ | vault_pull, vault_recent |  |
| `code-direct` | ✅ | ∅ |  |
| `ambiguous-prefers-direct` | ✅ | ∅ |  |

_Generado el eval; tools stubbeadas, memoria desactivada._
