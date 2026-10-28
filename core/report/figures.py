"""Figuras del reporte (matplotlib, backend Agg: sin display, sin red).

Se guardan como PNG a 180 dpi dentro de ``<out_dir>/assets``. Los tamaños están
pensados para el ancho útil de una A4 (≈ 17,4 cm) y para que el PDF supere de sobra
los 20 KB incluso con pocos candidatos.
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")  # antes de pyplot, siempre

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

VERDE = "#1f6f5c"
VERDE_CLARO = "#59a98f"
AMBAR = "#b45309"
GRIS = "#5b6770"
TINTA = "#1c2430"

plt.rcParams.update({
    "font.family": ["DejaVu Sans"],
    "font.size": 8.5,
    "axes.edgecolor": "#9aa5ad",
    "axes.labelcolor": TINTA,
    "axes.titlecolor": TINTA,
    "axes.titlesize": 9.5,
    "axes.titleweight": "bold",
    "xtick.color": GRIS,
    "ytick.color": GRIS,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "axes.unicode_minus": False,
})


def _save(fig, path: str) -> str:
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _empty(ax, msg: str) -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes,
            color=GRIS, fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def eficiencia_hist(series: Sequence[Tuple[str, Sequence[float]]], path: str) -> str:
    """Histograma del eje E (0..1). Una serie por corrida si hay más de una."""
    fig, ax = plt.subplots(figsize=(6.9, 2.85), constrained_layout=True)
    bins = [i / 10 for i in range(11)]

    series = [(label, [float(v) for v in values if v is not None])
              for label, values in series]
    total = sum(len(values) for _label, values in series)

    if not total:
        _empty(ax, "Sin candidatos para graficar")
        ax.set_title("Distribución de eficiencia (eje E)")
        return _save(fig, path)

    if len(series) == 1:
        label, values = series[0]
        ax.hist(values, bins=bins, color=VERDE_CLARO, edgecolor="white",
                linewidth=0.9, zorder=2)
        if values:
            mean = sum(values) / len(values)
            ax.axvline(mean, color=AMBAR, linestyle=(0, (4, 3)), linewidth=1.2,
                       zorder=3)
            ax.annotate(f"media {mean:.2f}".replace(".", ","),
                        xy=(mean, ax.get_ylim()[1] * 0.94),
                        xytext=(4, 0), textcoords="offset points",
                        color=AMBAR, fontsize=7.5, va="top")
    else:
        colors = [VERDE, "#2b6cb0", AMBAR, "#6b46c1", "#b83280", GRIS]
        for i, (label, values) in enumerate(series):
            ax.hist(values, bins=bins, histtype="step", linewidth=1.6,
                    color=colors[i % len(colors)], label=f"{label} (n={len(values)})")
        ax.legend(frameon=False, fontsize=6.8, loc="upper left")

    ax.set_xlim(0, 1)
    ax.set_xlabel("Valor del eje E (0 = sin señal, 1 = óptimo termodinámico)")
    ax.set_ylabel("Candidatos")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", color="#e3e8eb", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(f"Distribución de eficiencia (eje E) — {total} candidato(s)")
    return _save(fig, path)


def hits_por_panel(panels: Sequence[dict], path: str) -> str:
    """Barras horizontales apiladas: hits perfectos vs. con mismatches, por panel."""
    fig, ax = plt.subplots(figsize=(6.9, 2.6), constrained_layout=True)
    if not panels:
        _empty(ax, "Sin hits de off-target registrados en esta corrida")
        ax.set_title("Hits de off-target por panel")
        return _save(fig, path)

    labels = [_short(p["panel"], 30) for p in panels]
    perfect = [int(p["perfect"]) for p in panels]
    imperfect = [int(p["imperfect"]) for p in panels]
    y = list(range(len(panels)))

    ax.barh(y, perfect, color=VERDE, height=0.58, label="0 mismatches (hit perfecto)",
            zorder=2)
    ax.barh(y, imperfect, left=perfect, color=VERDE_CLARO, height=0.58,
            label="1–3 mismatches", zorder=2)

    top = max(perfect[i] + imperfect[i] for i in y) if y else 0
    for i in y:
        total = perfect[i] + imperfect[i]
        ax.text(total + max(0.15, top * 0.015), i, str(total), va="center",
                fontsize=7.5, color=TINTA)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlabel("Hits de off-target (filas siRNA–hit)")
    ax.set_xlim(0, max(1, top * 1.12))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="x", color="#e3e8eb", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=6.8, loc="lower right")
    ax.set_title("Hits de off-target por panel")
    return _save(fig, path)


def _short(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def figuras(runs, assets_dir: str) -> Dict[str, str]:
    """Genera las dos figuras y devuelve rutas relativas al out_dir."""
    os.makedirs(assets_dir, exist_ok=True)
    eff_path = os.path.join(assets_dir, "fig_eficiencia.png")
    panel_path = os.path.join(assets_dir, "fig_paneles.png")

    series = [(run.run_id, run.e_values) for run in runs]
    eficiencia_hist(series, eff_path)
    hits_por_panel(_merge_panels(runs), panel_path)

    return {
        "eficiencia": "assets/fig_eficiencia.png",
        "paneles": "assets/fig_paneles.png",
        "eficiencia_path": eff_path,
        "paneles_path": panel_path,
    }


def _merge_panels(runs) -> List[dict]:
    agg: Dict[str, dict] = {}
    for run in runs:
        for item in run.panels:
            target = agg.setdefault(item["panel"],
                                    {"panel": item["panel"], "perfect": 0, "imperfect": 0})
            target["perfect"] += item["perfect"]
            target["imperfect"] += item["imperfect"]
    rows = sorted(agg.values(), key=lambda x: (-(x["perfect"] + x["imperfect"]), x["panel"]))
    if len(rows) > 12:
        top = rows[:11]
        rest = rows[11:]
        top.append({"panel": f"otros ({len(rest)} paneles)",
                    "perfect": sum(p["perfect"] for p in rest),
                    "imperfect": sum(p["imperfect"] for p in rest)})
        return top
    return rows
