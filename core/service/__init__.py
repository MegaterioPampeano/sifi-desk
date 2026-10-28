"""sifid — servicio local de siFi-Desk (FastAPI + cola SQLite + worker único).

El servicio **no** corre el pipeline adentro del proceso web: encola la corrida y un
worker la ejecuta en un proceso aparte (`python3 -m service.runner`), para que el
servidor pueda cancelarla, matarla sin dejar huérfanos y sobrevivir a sus errores.
"""
from __future__ import annotations

__version__ = "0.1.0"

SERVICE_NAME = "sifid"

__all__ = ["__version__", "SERVICE_NAME"]
