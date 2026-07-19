# Backend llama.cpp (modelos MTP / cuantizaciones exóticas)

LocalAgent habla con **ollama** por defecto, pero también puede usar modelos servidos por
**llama.cpp** (`llama-server`) como un backend extra. Sirve para modelos que ollama no
empaqueta bien: cuantizaciones agresivas (IQ1/IQ2), **MTP** (multi-token prediction /
speculative decoding), o forks específicos (PrismML).

> ollama corre *sobre* llama.cpp, así que la velocidad base es la misma; llama-server te da
> control fino (elegir el GGUF exacto, `-ngl` para repartir GPU+RAM, KV cache q4_0, MTP).

## Requisitos (ya instalados en esta máquina)

- Prebuilt del fork PrismML en `~/llama.cpp-bin/llama-prism-*/` (tiene soporte MTP).
- Libs CUDA prestadas de ollama (`/usr/local/lib/ollama/cuda_v12`) — el launcher las apunta.
- Launcher: `~/llama.cpp-bin/run-llama.sh`.

Para reinstalar el binario: bajar el prebuilt `bin-linux-cuda-12.4` de
`github.com/PrismML-Eng/llama.cpp/releases` y extraerlo en `~/llama.cpp-bin/`.

## Arrancar el server

```bash
# desde un archivo .gguf local:
~/llama.cpp-bin/run-llama.sh /ruta/al/modelo.gguf

# o descargando de HuggingFace (baja solo el GGUF la primera vez):
~/llama.cpp-bin/run-llama.sh unsloth/Qwen3.6-35B-A3B-MTP-GGUF:UD-IQ1_M
```

Deja un endpoint **OpenAI-compatible + web UI** en **http://localhost:8080**. La web UI de
llama.cpp funciona sola ahí; LocalAgent lo usa vía la API.

## Elegir el modelo / la cuantización

El nombre `repo:quant`. El quant define **calidad vs tamaño**. Para una **RTX 3060 (12 GB)**:

| Quant | Tamaño | Notas |
|---|---|---|
| `UD-IQ1_M` | ~11.4 GB | Entra en GPU (justo). Lo más rápido, calidad más baja. |
| `UD-IQ3_XXS` | ~14 GB | Mejor calidad; reparte GPU + RAM (ok por el MoE). |
| `UD-Q3_K_M` | ~17 GB | Aún mejor; más RAM, más lento. |
| `UD-Q4_K_M` | ~22 GB | No entra sin bastante RAM. |

**"A3B" = 3B parámetros activos por token** (arquitectura MoE de 35B totales). Eso NO se
configura: es del modelo. Para "más nivel" se sube el **quant**, no los parámetros activos.

## Config del server (flags)

Se editan en `~/llama.cpp-bin/run-llama.sh`:
- `--ctx-size 32768` — ventana de contexto (más = más VRAM).
- `--n-gpu-layers all` + `--fit off` — todo a GPU (si da OOM, `--fit on` o bajar `--ctx-size`).
- `--cache-type-k q4_0 --cache-type-v q4_0` — KV cache cuantizado (ahorra VRAM).
- `--spec-type draft-mtp --spec-draft-n-max 2` — **MTP** (acelera 1.4–2.2×).
- `--reasoning on` — razonamiento del modelo (LocalAgent lo desactiva por request salvo que prendas "Thinking").
- `--temp 0.6 --top-p 0.95 --top-k 20` — sampling.

## Integración con LocalAgent

- `config.LLAMACPP_URL` (default `http://localhost:8080/v1`, vacío = deshabilitado).
- Si el server está arriba, sus modelos **aparecen en el selector** de LocalAgent junto a los
  de ollama (etiquetados `llama.cpp`).
- LocalAgent rutea el chat a `/v1/chat/completions` (streaming) cuando elegís ese modelo.
- **ollama no se ve afectado**: sigue con sus tools, memoria, etc.
- **Limitación actual**: por el backend llama.cpp es **solo chat de texto** (sin tools/MCP).
  Las tools siguen en los modelos de ollama. (Tools por llama.cpp = pendiente a futuro.)
