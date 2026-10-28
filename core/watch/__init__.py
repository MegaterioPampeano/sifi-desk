"""Vigilante de novedades (frente M7).

Busca papers nuevos sobre RNAi/dsRNA/siRNA en insectos y fitopatógenos, y versiones
nuevas del upstream siFi, sin que el usuario tenga que buscar nada.

Uso típico (desde `core/`):

    python3 -m watch.cli run --since 7d --out novedades.json
    python3 -m watch.cli run --since 7d --offline --out novedades.json

Módulos:

* `sources` — consultas a Crossref, PubMed (E-utilities), bioRxiv y releases de GitHub,
  con User-Agent identificable, timeout, backoff exponencial y caché en disco.
* `store`   — `inventory.json` con los ids ya vistos y `diff()` que devuelve sólo lo nuevo.
* `digest`  — resumen corto en texto por ítem.
* `cli`     — el comando de arriba.

Nada de esto aplica cambios ni descarga bases: sólo informa. La decisión es del usuario.
"""
__all__ = ["sources", "store", "digest", "cli"]
__version__ = "0.1.0"
