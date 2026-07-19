"""read_file tool — safe read-only access to workspace files.

The read-only counterpart of write_file. Verifies happy path, truncation,
path-traversal rejection, missing files, directory rejection, empty files,
subdirectory access, and that the tool is properly registered in SPECS/_IMPLS.
"""

import config
import tools


def test_read_file_devuelve_contenido(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "hola.txt").write_text("hola mundo", encoding="utf-8")
    assert tools.read_file("hola.txt") == "hola mundo"


def test_read_file_trunca_a_max_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "largo.txt").write_text("A" * 500, encoding="utf-8")
    result = tools.read_file("largo.txt", max_chars=10)
    assert len(result) == 10
    assert result == "A" * 10


def test_read_file_rechaza_traversal(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "secreto.txt").write_text("passwords", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(root))
    result = tools.read_file("../secreto.txt")
    assert "fuera del workspace" in result


def test_read_file_archivo_no_existente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    result = tools.read_file("no-existe.txt")
    assert "No existe" in result


def test_read_file_carpeta_no_es_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "carpeta").mkdir()
    result = tools.read_file("carpeta")
    assert "carpeta" in result.lower()


def test_read_file_archivo_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "vacio.txt").write_text("", encoding="utf-8")
    assert tools.read_file("vacio.txt") == "(archivo vacío)"


def test_read_file_subdirectorio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "main.py").write_text("print('hi')", encoding="utf-8")
    assert tools.read_file("src/main.py") == "print('hi')"


def test_read_file_default_max_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "ok.txt").write_text("B" * 100, encoding="utf-8")
    # default max_chars=10000 → no trunca contenido de 100 chars
    assert tools.read_file("ok.txt") == "B" * 100


def test_read_file_registrada_en_specs():
    names = [s["function"]["name"] for s in tools.SPECS]
    assert "read_file" in names


def test_read_file_registrada_en_impls():
    assert "read_file" in tools._IMPLS
    assert tools._IMPLS["read_file"] is tools.read_file


def test_execute_read_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "x.py").write_text("x = 1", encoding="utf-8")
    assert tools.execute("read_file", {"path": "x.py"}) == "x = 1"
