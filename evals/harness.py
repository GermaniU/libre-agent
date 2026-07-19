"""Golden-set eval harness for LocalAgent.

Runs a fixed set of behavioural cases (evals/golden.jsonl) against a real local
model through ``agent.run_turn`` and scores each one. It measures the MODEL's
decisions — which tool it picks, whether it leaks a raw ``<tool_call>`` into the
reply, and whether it answers in neutral LATAM Spanish — not the tools' output.

To keep runs deterministic and offline, local tools are stubbed with canned
results and memory recall/auto-save are disabled. The only moving part is the
model, so this doubles as a regression test: change a prompt or swap a model and
compare the pass rate.

Usage:
    python -m evals.harness --model gemma4:12b
    python -m evals.harness --model gemma4:12b --report evals/report.md
    python -m evals.harness --only route-web,no-leak-web
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import tools

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.jsonl")

# Canned tool outputs so the tool loop can continue without network/disk/MCP.
_STUB_RESULTS = {
    "web_search": "Resultados web (stub): 1. Nota de ejemplo. 2. Otra fuente de ejemplo.",
    "web_fetch": "Contenido de página (stub): texto de ejemplo para el eval.",
    "vault_search": "Nota del vault (stub): 'Semana' — apunte de ejemplo relevante.",
    "vault_recent": "Notas recientes (stub): 'Idea A', 'Idea B', 'Pendiente C'.",
    "write_html": "Página guardada en static/demo.html → http://localhost:8585/demo.html",
    "run_cmd": "exit 0\n(salida de ejemplo)",
    "list_dir": "archivo1.py\narchivo2.py",
    "use_skill": "PROCEDIMIENTO (stub): paso 1, paso 2, paso 3.",
}

# Argentine-Spanish markers: any hit fails the `lang_neutral` assertion.
# Only the ACCENTED voseo variants — never a char class like [áa] that would also
# match the correct neutral form (e.g. "usa"/"busca"/"responde" are fine).
_VOSEO = re.compile(
    r"\b(podés|querés|tenés|sabés|necesitás|hacés|ponés|decís|sos|conectás|conectá|"
    r"enviás|usá|editá|activá|elegí|seguí|probá|dejá|sumá|tocá|agregá|resumí|generá|"
    r"buscá|preguntá|pegá|copiá|mandá|respondé|mantené|extraé|abrí|dudás|limpiá|"
    r"compartí|modificá|migrás|desactivá|verificá|acá|allá|dejalo|subilo|decilo|vos)\b",
    re.IGNORECASE,
)


def _stub_execute(name, args):
    """Deterministic replacement for tools.execute during evals."""
    base = name.split("__")[-1]
    return _STUB_RESULTS.get(base, f"(stub) resultado de {name}")


def run_case(case, model):
    """Run one case and return the observed behaviour (tools + reply + timing)."""
    prompt = case["prompt"]
    history = [{"role": "user", "content": prompt}]
    called, reply = [], ""
    t0 = time.time()
    for ev in agent.run_turn(
        model, history, prompt, soul=agent.load_soul(),
        channel="eval", use_tools=True, use_memory=False,
        think=False, bridge=None, stream=True,
    ):
        if ev["type"] == "tool":
            called.append(ev["name"].split("__")[-1])
        elif ev["type"] == "done":
            reply = ev.get("reply") or ""
        elif ev["type"] == "error":
            reply = ev.get("text") or reply
    return {"tools": called, "reply": reply, "secs": round(time.time() - t0, 1)}


def check(expect, obs):
    """Evaluate a case's assertions. Returns (passed, [failure_reasons])."""
    fails = []
    tools_called, reply = obs["tools"], obs["reply"]
    low = reply.lower()

    if "tool" in expect and expect["tool"] not in tools_called:
        fails.append(f"esperaba tool '{expect['tool']}', llamó {tools_called or '∅'}")
    if "tools_any" in expect and not any(t in tools_called for t in expect["tools_any"]):
        fails.append(f"esperaba alguna de {expect['tools_any']}, llamó {tools_called or '∅'}")
    if expect.get("no_tools") and tools_called:
        fails.append(f"no debía usar tools, llamó {tools_called}")
    if "not_tool" in expect and expect["not_tool"] in tools_called:
        fails.append(f"no debía llamar '{expect['not_tool']}'")
    for sub in expect.get("reply_contains", []):
        if sub.lower() not in low:
            fails.append(f"la respuesta no contiene '{sub}'")
    for sub in expect.get("reply_excludes", []):
        if sub.lower() in low:
            fails.append(f"la respuesta contiene lo prohibido '{sub}'")
    if expect.get("lang_neutral"):
        hits = sorted(set(m.group().lower() for m in _VOSEO.finditer(reply)))
        if hits:
            fails.append(f"argentinismos: {hits}")
    if "min_chars" in expect and len(reply.strip()) < expect["min_chars"]:
        fails.append(f"respuesta corta ({len(reply.strip())} < {expect['min_chars']} chars)")

    return (not fails), fails


def load_cases(only=None):
    cases = []
    with open(GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def render_report(model, results, elapsed):
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    lines = [
        f"# Golden evals — LocalAgent",
        "",
        f"**Modelo:** `{model}`  ·  **Resultado:** {passed}/{total} "
        f"({100*passed//total if total else 0}%)  ·  **Tiempo:** {elapsed:.0f}s",
        "",
        "| Caso | ✓ | Tools | Motivo de fallo |",
        "|------|---|-------|-----------------|",
    ]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        why = "" if r["ok"] else "; ".join(r["fails"])
        tl = ", ".join(r["obs"]["tools"]) or "∅"
        lines.append(f"| `{r['id']}` | {mark} | {tl} | {why} |")
    lines += ["", f"_Generado el eval; tools stubbeadas, memoria desactivada._", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Golden-set evals para LocalAgent")
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL", "gemma4:12b"))
    ap.add_argument("--report", default=None, help="Ruta para guardar el reporte .md")
    ap.add_argument("--only", default=None, help="IDs separados por coma")
    ap.add_argument("--no-stub", action="store_true", help="Ejecutar tools de verdad")
    args = ap.parse_args()

    if not args.no_stub:
        tools.execute = _stub_execute  # deterministic, offline

    cases = load_cases(args.only)
    print(f"▶ {len(cases)} casos contra {args.model}\n")
    results = []
    t0 = time.time()
    for c in cases:
        obs = run_case(c, args.model)
        ok, fails = check(c["expect"], obs)
        results.append({"id": c["id"], "ok": ok, "fails": fails, "obs": obs})
        mark = "✅" if ok else "❌"
        detail = "" if ok else "  → " + "; ".join(fails)
        print(f"{mark} {c['id']:24} [{', '.join(obs['tools']) or '∅':<22}] {obs['secs']}s{detail}")
    elapsed = time.time() - t0

    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} pasaron ({100*passed//len(results) if results else 0}%) en {elapsed:.0f}s")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(render_report(args.model, results, elapsed))
        print(f"📄 reporte: {args.report}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
