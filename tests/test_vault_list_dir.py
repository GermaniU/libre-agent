"""vault_list_dir tool — browse the vault's folder structure by name.

Mirrors the guards already covered for list_dir/read_file, but scoped to VAULT_DIR
instead of WORKSPACE_DIR. Added after a model burned its whole tool-round budget trying
to list vault folders with list_dir (which is confined to WORKSPACE_DIR, a different
directory) while vault_search was unavailable.
"""

import config
import tools


def test_vault_list_dir_lista_entradas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", str(tmp_path))
    (tmp_path / "nota.md").write_text("hola", encoding="utf-8")
    (tmp_path / "Carpeta").mkdir()
    result = tools.vault_list_dir("")
    assert "nota.md" in result
    assert "Carpeta" in result


def test_vault_list_dir_subcarpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", str(tmp_path))
    sub = tmp_path / "01 - Empresas"
    sub.mkdir()
    (sub / "nota.md").write_text("x", encoding="utf-8")
    result = tools.vault_list_dir("01 - Empresas")
    assert "nota.md" in result


def test_vault_list_dir_rechaza_traversal(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    (tmp_path / "fuera.md").write_text("secreto", encoding="utf-8")
    monkeypatch.setattr(config, "VAULT_DIR", str(root))
    result = tools.vault_list_dir("../fuera.md")
    assert "fuera del vault" in result


def test_vault_list_dir_ruta_no_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", str(tmp_path))
    result = tools.vault_list_dir("no-existe")
    assert "No es una carpeta" in result


def test_vault_list_dir_carpeta_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", str(tmp_path))
    result = tools.vault_list_dir("")
    assert result == "(carpeta vacía)"


def test_vault_list_dir_registrada_en_specs():
    names = [s["function"]["name"] for s in tools.SPECS]
    assert "vault_list_dir" in names


def test_vault_list_dir_registrada_en_impls():
    assert "vault_list_dir" in tools._IMPLS
    assert tools._IMPLS["vault_list_dir"] is tools.vault_list_dir


def test_execute_vault_list_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", str(tmp_path))
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    assert "a.md" in tools.execute("vault_list_dir", {"path": ""})
