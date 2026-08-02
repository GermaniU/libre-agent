"""vault_search's degrade path when the corpus/RAG server is unreachable or erroring.

Added after a code review flagged that catching only requests.exceptions.ConnectionError
missed HTTPError (corpus up but returning 5xx) and Timeout — neither is a ConnectionError
subclass, so they used to propagate as raw exceptions instead of degrading gracefully.
"""
import requests

import clients
import tools


def _raise(exc):
    def fake(query, limit=6):
        raise exc

    return fake


def test_degrada_en_connection_error(monkeypatch):
    monkeypatch.setattr(clients, "corpus_search", _raise(requests.exceptions.ConnectionError()))
    result = tools.vault_search("algo")
    assert "no disponible" in result
    assert "vault_list_dir" in result


def test_degrada_en_http_error(monkeypatch):
    monkeypatch.setattr(clients, "corpus_search", _raise(requests.exceptions.HTTPError()))
    result = tools.vault_search("algo")
    assert "no disponible" in result


def test_degrada_en_timeout(monkeypatch):
    monkeypatch.setattr(clients, "corpus_search", _raise(requests.exceptions.Timeout()))
    result = tools.vault_search("algo")
    assert "no disponible" in result


def test_sin_hits_mensaje_normal(monkeypatch):
    monkeypatch.setattr(clients, "corpus_search", lambda query, limit=6: [])
    assert tools.vault_search("algo") == "Sin pasajes relevantes en el vault."
