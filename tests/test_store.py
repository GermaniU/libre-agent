"""Round-trip de persistencia de sesiones (store.py) contra una DB temporal."""
import store


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", str(tmp_path / "test.db"))


def test_save_load_roundtrip(tmp_path, monkeypatch):
    _tmp_db(tmp_path, monkeypatch)
    sess = {"messages": [{"role": "user", "content": "hola"}], "tokens": 10}
    store.save_session("chat-1", sess)
    loaded = store.load_sessions()
    assert loaded["chat-1"]["messages"][0]["content"] == "hola"
    assert loaded["chat-1"]["tokens"] == 10


def test_delete(tmp_path, monkeypatch):
    _tmp_db(tmp_path, monkeypatch)
    store.save_session("a", {"messages": []})
    store.delete_session("a")
    assert "a" not in store.load_sessions()


def test_rename_ok(tmp_path, monkeypatch):
    _tmp_db(tmp_path, monkeypatch)
    store.save_session("viejo", {"messages": []})
    assert store.rename_session("viejo", "nuevo") is True
    sesiones = store.load_sessions()
    assert "nuevo" in sesiones and "viejo" not in sesiones


def test_rename_a_nombre_existente_falla(tmp_path, monkeypatch):
    # no debe pisar la sesión destino: devuelve False y deja ambas intactas
    _tmp_db(tmp_path, monkeypatch)
    store.save_session("a", {"messages": [{"role": "user", "content": "A"}]})
    store.save_session("b", {"messages": [{"role": "user", "content": "B"}]})
    assert store.rename_session("a", "b") is False
    sesiones = store.load_sessions()
    assert sesiones["b"]["messages"][0]["content"] == "B"  # intacta
    assert "a" in sesiones
