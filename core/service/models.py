"""Modelos de la API de sifid (pydantic v2).

El pedido es la descripción *completa* de una corrida: si no está acá, no se puede
reproducir. Las rutas son del lado del servidor porque sifid es un servicio local
(127.0.0.1); la UI y el agente hablan con él, nunca con el filesystem.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["design", "offtarget"] = "design"

    # --- entrada: o un FASTA en disco, o el FASTA embebido (nunca los dos) ---
    query_path: Optional[str] = None
    query_fasta: Optional[str] = None

    # --- base de datos: o un panel del registro, o un índice bowtie directo ---
    panel_id: Optional[str] = None
    panel_version: Optional[str] = None
    db_dir: Optional[str] = None
    db_name: Optional[str] = None

    # --- parámetros del algoritmo (defaults = GUI original) ---
    sirna_size: int = Field(21, ge=3, le=200)
    mismatches: int = Field(0, ge=0, le=3)
    accessibility_window: Optional[int] = Field(None, ge=1)
    strand_check: Optional[bool] = None
    end_check: Optional[bool] = None
    accessibility_check: Optional[bool] = None
    terminal_check: Optional[bool] = None
    no_efficience: bool = False

    # --- selección de blanco principal ---
    main_targets: Optional[List[str]] = None
    main_target_mode: Literal["auto", "explicit"] = "auto"

    # --- binarios (si no, se descubren por env / vendor / PATH) ---
    bowtie: Optional[str] = None
    rnaplfold: Optional[str] = None

    extra_meta: Optional[Dict] = None


class CancelResponse(BaseModel):
    run_id: str
    status: str
    cancel_requested: bool
    detail: str
