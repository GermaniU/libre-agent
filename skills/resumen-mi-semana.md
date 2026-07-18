---
name: resumen-mi-semana
description: Trae lo trabajado en el vault en los últimos días y arma un resumen accionable
---

# Skill: resumen de mi semana

Cuando el usuario pregunte "¿qué trabajé esta semana / últimos días?" o pida un repaso de su trabajo reciente:

1. **Traé lo nuevo**: `vault_pull` (para que el vault físico esté al día).
2. **Listá lo reciente**: `vault_recent` con los días que pida (default 7). Devuelve notas modificadas + las daily notes.
3. **Si una nota parece clave**, abrila con `vault_read` para tener el detalle.
4. **Armá el resumen** en prosa, agrupado por proyecto/tema. Para cada bloque: qué avanzó y qué quedó pendiente.
5. **Cerrá con 2-3 próximos pasos** concretos y accionables.

Reglas: apoyate en lo que dicen las notas, no inventes. Si algo no está en el vault, decilo. Si el usuario pide, ofrecé volcarlo a un `write_html`.
