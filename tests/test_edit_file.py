"""edit_file tool — exact-snippet replacement inside the workspace.

Verifies the single-match happy path, refusal of ambiguous/missing snippets, replace_all
(including booleans sent as strings), path-traversal rejection, and registration.
"""

import config
import tools


def _ws(tmp_path, monkeypatch, name="a.py", text="x = 1\ny = 2\n"):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def test_edit_file_reemplaza_fragmento_unico(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch)
    result = tools.edit_file("a.py", "y = 2", "y = 3")
    assert "1 reemplazo)" in result
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 3\n"


def test_edit_file_fragmento_inexistente_no_toca_nada(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch)
    result = tools.edit_file("a.py", "z = 9", "z = 0")
    assert "no aparece" in result
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 2\n"


def test_edit_file_ambiguo_se_rechaza(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch, text="a\na\n")
    result = tools.edit_file("a.py", "a", "b")
    assert "2 veces" in result
    assert f.read_text(encoding="utf-8") == "a\na\n"


def test_edit_file_replace_all(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch, text="a\na\n")
    result = tools.edit_file("a.py", "a", "b", replace_all=True)
    assert "2 reemplazos" in result
    assert f.read_text(encoding="utf-8") == "b\nb\n"


def test_edit_file_replace_all_como_string(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch, text="a\na\n")
    assert "2 veces" in tools.edit_file("a.py", "a", "b", replace_all="false")
    assert f.read_text(encoding="utf-8") == "a\na\n"  # "false" no es truthy
    tools.edit_file("a.py", "a", "b", replace_all="true")
    assert f.read_text(encoding="utf-8") == "b\nb\n"


def test_edit_file_new_vacio_borra(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch)
    tools.edit_file("a.py", "y = 2\n", "")
    assert f.read_text(encoding="utf-8") == "x = 1\n"


def test_edit_file_old_vacio_se_rechaza(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    assert "write_file" in tools.edit_file("a.py", "", "algo")


def test_edit_file_archivo_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    assert "No existe" in tools.edit_file("nada.py", "a", "b")


def test_edit_file_rechaza_traversal(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("clave=1", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(root))
    result = tools.edit_file("../secreto.txt", "clave=1", "clave=2")
    assert "fuera del workspace" in result
    assert secreto.read_text(encoding="utf-8") == "clave=1"


def test_edit_file_conserva_utf8(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch, name="n.md", text="año: 2025 — ñandú\n")
    tools.edit_file("n.md", "2025", "2026")
    assert f.read_text(encoding="utf-8") == "año: 2026 — ñandú\n"


def test_edit_file_registrada():
    spec = next(s for s in tools.SPECS if s["function"]["name"] == "edit_file")
    assert spec["function"]["parameters"]["required"] == ["path", "old", "new"]
    assert spec["function"]["description"]  # description loaded from tools.es.json
    assert tools._IMPLS["edit_file"] is tools.edit_file


def test_execute_edit_file(tmp_path, monkeypatch):
    f = _ws(tmp_path, monkeypatch)
    tools.execute("edit_file", {"path": "a.py", "old": "x = 1", "new": "x = 10"})
    assert f.read_text(encoding="utf-8").startswith("x = 10")


def test_edit_file_no_corrompe_binarios(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    f = tmp_path / "img.bin"
    f.write_bytes(b"\xff\xfe abc")
    assert "no es texto UTF-8" in tools.edit_file("img.bin", "abc", "xyz")
    assert f.read_bytes() == b"\xff\xfe abc"
