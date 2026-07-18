"""Parseo de skills (frontmatter opcional)."""
import skills


def test_parse_con_frontmatter():
    text = "---\nname: mi-skill\ndescription: hace algo\n---\nPaso 1\nPaso 2\n"
    name, desc, body = skills._parse(text)
    assert name == "mi-skill"
    assert desc == "hace algo"
    assert body == "Paso 1\nPaso 2"


def test_parse_sin_frontmatter():
    text = "Solo el procedimiento, sin metadata.\n"
    name, desc, body = skills._parse(text)
    assert name is None
    assert desc is None
    assert body == "Solo el procedimiento, sin metadata."


def test_parse_frontmatter_parcial():
    text = "---\nname: solo-nombre\n---\ncuerpo\n"
    name, desc, body = skills._parse(text)
    assert name == "solo-nombre"
    assert desc is None
    assert body == "cuerpo"
