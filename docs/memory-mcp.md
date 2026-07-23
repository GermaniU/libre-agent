# Memoria persistente vía MCP

LocalAgent guarda su memoria a largo plazo en un **servidor MCP que vos configurás** — no
trae almacenamiento propio. Así podés usar el backend que quieras (Qdrant, SQLite, un
servicio remoto…) siempre que exponga el contrato mínimo de abajo.

## Cómo se activa

1. Declará tu MCP de memoria en `mcp.json` (stdio o http), con la clave que quieras:
   ```json
   {
     "mcpServers": {
       "mcp-memory": { "type": "http", "url": "http://localhost:8765/mcp" }
     }
   }
   ```
2. Apuntá `MEMORY_MCP_SERVER` (en `.env`) a esa clave:
   ```
   MEMORY_MCP_SERVER=mcp-memory
   ```
3. Prendé el toggle **💾 Memoria persistente** en la UI.

Con eso, en cada turno:
- **Recall pasivo**: antes de responder, LocalAgent llama `memory_search` e inyecta los
  recuerdos relevantes en el system prompt.
- **Guardado automático**: tras responder, extrae hechos duraderos y los guarda con `memory_save`.
- **Tools activos para el modelo**: además, TODOS los tools del server se le pasan al modelo,
  así puede buscar/guardar/listar memoria por su cuenta a mitad de una tarea.

Si el server nombrado no está en `mcp.json`, la UI lo avisa y cae a solo recall pasivo.

## Contrato mínimo (obligatorio)

El server **debe** exponer estos dos tools. LocalAgent los llama con estos argumentos
(los nombres de tool se namespacean internamente como `<server>__<tool>`, vos exponés los
nombres cortos):

### `memory_search`
```
args:   { "query": string, "limit": int, "namespace": string }
return: JSON — un array de objetos, o { "result": [ ... ] }
        cada objeto: { "content": string, "score"?: number }
```
`score` es opcional; si viene, LocalAgent descarta los que estén por debajo de un umbral
(0.35 por defecto). `content` es el texto del recuerdo.

### `memory_save`
```
args:   { "content": string, "namespace": string, "tags": string[] }
return: cualquier cosa que NO empiece con "Error" (texto de éxito, JSON, id, etc.)
```

## Tools opcionales (recomendados)

Cualquier tool extra que exponga el server queda disponible **para el modelo** cuando la
memoria está activa. Los habituales del ecosistema `mcp-memory`:
`memory_recent`, `memory_list`, `memory_update`, `memory_delete`, `memory_stats`,
`memory_export`, `memory_import`. No son obligatorios, pero enriquecen lo que el modelo puede hacer.

## Namespace

LocalAgent usa el namespace **`localagent`** en todas las llamadas. Tu server debe respetar
el campo `namespace` para aislar la memoria de LocalAgent de otros clientes que compartan el
mismo backend.
