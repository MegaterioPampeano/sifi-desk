"""Parámetros y rutas de herramientas del núcleo siFi.

Los valores por defecto replican EXACTAMENTE los del GUI original
(siFi21/main.py: set_design_settings / set_offtarget_settings).
No cambiar sin actualizar tests/golden.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


@dataclass
class ToolPaths:
    """Rutas a los binarios externos. No se buscan en PATH a propósito:
    la fidelidad exige saber qué binario exacto se usó (se registra el hash)."""

    bowtie: str
    rnaplfold: str
    bowtie_build: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: (str(v) if v is not None else None) for k, v in asdict(self).items()}


@dataclass
class SifiParams:
    # --- comunes ---
    sirna_size: int = 21
    mismatches: int = 0            # GUI: comboBox_miss index 0 == "0"
    mode: str = "design"           # "design" | "offtarget"

    # --- controles de eficiencia ---
    strand_check: bool = True
    end_check: bool = True
    accessibility_check: bool = True
    terminal_check: bool = True
    no_efficience: bool = False

    accessibility_window: int = 8        # columna de _lunp (u)
    end_stability_threshold: float = 1.0
    target_site_accessibility_threshold: float = 0.1

    # --- constantes del algoritmo (siFi21/sifi_pipeline.py: __init__) ---
    winsize: int = 80
    span: int = 40
    temperature: float = 22.0      # el original usa 22, no 37
    overhang: int = 2
    end_nucleotides: int = 3
    sirna_start_position: int = 0

    def __post_init__(self) -> None:
        if self.mode not in ("design", "offtarget"):
            raise ValueError(f"mode inválido: {self.mode!r} (usar 'design' u 'offtarget')")
        if self.sirna_size < 3:
            raise ValueError("sirna_size debe ser >= 3")
        if not (1 <= self.accessibility_window <= self.sirna_size):
            raise ValueError("accessibility_window fuera de rango (1..sirna_size)")
        if self.mismatches < 0 or self.mismatches > 3:
            raise ValueError("mismatches debe estar entre 0 y 3 (límite del GUI)")

    @property
    def mode_code(self) -> int:
        """El original usa 0=design, 1=off-target."""
        return 0 if self.mode == "design" else 1

    @classmethod
    def offtarget_defaults(cls, **kw) -> "SifiParams":
        """Defaults del GUI en modo off-target: strand+terminal, sin end/access."""
        base = dict(end_check=False, accessibility_check=False)
        base.update(kw)
        return cls(mode="offtarget", **base)

    def as_dict(self) -> dict:
        return asdict(self)
