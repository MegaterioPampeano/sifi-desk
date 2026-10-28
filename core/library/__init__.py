"""Biblioteca de papers (frente M11, edición developer).

Guarda el **PDF real** de cada paper (tal cual lo publica el editor o PMC), lo indexa
para búsqueda de texto completo y permite anotar qué se puede extraer de cada uno.

Uso típico (desde `core/`):

    SIFI_EDITION=dev python3 -m library.cli search "dsRNA delivery" --tag entrega

Módulos:

* `edition` — interruptor `SIFI_EDITION=dev` (default `stable`).
* `store`   — SQLite: papers, tags, annotations y FTS5 (`papers_fts`).
* `fetch`   — resolución del PDF de acceso abierto (Europe PMC, Unpaywall, PMC OA,
  portada del editor) + descarga y verificación.
* `extract` — `pdftotext -layout` / `pdfinfo` y normalización de espacios.
* `search`  — traducción de la consulta del usuario a FTS5 (AND por defecto, frases, OR,
  prefijo `tag:`).
* `cli`     — el comando de arriba.
* `api`     — `APIRouter` de FastAPI para montar en `core/service/app.py`.

Regla de oro: **nunca** se genera un PDF con texto propio. Si no hay versión abierta, el
paper queda `status="sin_pdf"` con el motivo.
"""
from __future__ import annotations

__version__ = "0.1"
