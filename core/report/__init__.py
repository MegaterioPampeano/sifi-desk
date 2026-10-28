"""Reportes PDF/HTML de una corrida de siFi-Desk.

El módulo no recalcula nada: toma el manifest ``sifi.results/1`` que escribe
``sifi.run.run_once``, lo puntúa con ``sifi.scoring`` (el mismo scoring del producto)
y arma un documento A4 imprimible con portada, parámetros/versiones, tabla de
candidatos con desglose E/R/S/T/D, figuras, limitaciones y metodología.

Uso programático::

    from report import render
    pdf = render(["out/results.json"], "out/reporte", fmt="pdf")

Uso por línea de comandos (desde ``core/``)::

    python3 -m report.cli --results out/results.json --out reporte.pdf
"""
from __future__ import annotations

from .render import REPORT_VERSION, render

__all__ = ["render", "REPORT_VERSION"]
