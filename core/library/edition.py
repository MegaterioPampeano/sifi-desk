"""Edición del producto: `stable` (default) o `dev`.

La biblioteca entera es una función de la edición **developer**: el buscador de papers,
las anotaciones y la descarga de PDFs no se ofrecen al usuario final. En `stable` el CLI
y la API tienen que contestar con un error legible, nunca con un traceback.

    SIFI_EDITION=dev python3 -m library.cli stats
"""
from __future__ import annotations

import os

STABLE = "stable"
DEV = "dev"
EDITIONS = (STABLE, DEV)
ENV_VAR = "SIFI_EDITION"

MESSAGE = "función de la edición developer (activar con SIFI_EDITION=dev)"


class EditionError(RuntimeError):
    """Se pidió una función de la biblioteca en la edición `stable`."""


def current() -> str:
    """Edición activa. Cualquier valor raro cae en `stable` (fail closed)."""
    raw = (os.environ.get(ENV_VAR) or "").strip().lower()
    return DEV if raw == DEV else STABLE


def is_dev() -> bool:
    return current() == DEV


def require_dev() -> None:
    """Levanta `EditionError` si no estamos en la edición developer."""
    if not is_dev():
        raise EditionError(MESSAGE)
