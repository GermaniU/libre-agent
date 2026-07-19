"""Traducción de MCPs en api.py: target <-> config, y contención de estáticos."""
import os

import api


def test_target_http_a_config():
    s = api._mcp_server_from_target("http://host:8765/mcp")
    assert s == {"type": "http", "url": "http://host:8765/mcp"}


def test_target_stdio_a_config():
    s = api._mcp_server_from_target("python -m mi_server --flag")
    assert s == {"command": "python", "args": ["-m", "mi_server", "--flag"]}


def test_target_of_ida_y_vuelta():
    for target in ("https://x/mcp", "node build/index.js"):
        assert api._mcp_target_of(api._mcp_server_from_target(target)) == target


def test_view_env_keys_y_raw():
    # env_keys sigue siendo solo las claves (para el display colapsado); "raw" expone
    # la config completa (incluidos los valores de env) para poder editarla en el form
    # genérico — la app es local single-user, así que no hace falta ocultarlos.
    cfg = {"mcpServers": {"s": {"command": "x", "args": [], "env": {"TOKEN": "secreto"}}}}
    view = api._mcp_view(cfg)
    assert view[0]["env_keys"] == ["TOKEN"]
    assert view[0]["raw"] == {"command": "x", "args": [], "env": {"TOKEN": "secreto"}}


def test_safe_file_dentro_y_fuera(tmp_path):
    base = tmp_path / "web"
    base.mkdir()
    (base / "app.js").write_text("ok")
    (tmp_path / "secreto.env").write_text("KEY=1")
    assert api._safe_file(str(base), "app.js") == os.path.realpath(str(base / "app.js"))
    assert api._safe_file(str(base), "../secreto.env") is None
    assert api._safe_file(str(base), "no-existe.js") is None
