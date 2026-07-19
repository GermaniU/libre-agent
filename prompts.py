"""Loader for externalized natural-language prompts.

The code is in English but prompts stay in the product language (Spanish) and live as
plain files under ``prompts/`` so they can be edited without touching code and, later,
translated per language. Files are read fresh on each call (hot-reload friendly).
"""
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def load(name: str, default: str = "") -> str:
    """Return the contents of ``prompts/<name>`` stripped, or ``default`` if unreadable."""
    try:
        with open(os.path.join(_DIR, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default
