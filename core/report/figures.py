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


def perfil_posicion(records, path: str) -> str:
    """Perfil por posición del transcrito: todos los siRNAs, los eficientes y las bandas
    de off-target perfecto. Es el gráfico que responde «¿por dónde corto?»: donde la curva
    verde sube y no hay banda roja, la ventana es buena."""
    fig, ax = plt.subplots(figsize=(6.9, 2.9), constrained_layout=True)

    total = [0] * 0
    series = []
    for rec in records:
        largo = int(rec.get("query_length") or 0)
        filas = rec.get("sirnas") or []
        if not largo:
            largo = max((int(r.get("sirna_position") or 0) for r in filas), default=0) + 21
        if largo <= 0:
            continue
        todos = [0] * largo
        eficientes = [0] * largo
        banda = [False] * largo
        for r in filas:
            pos = int(r.get("sirna_position") or 0) - 1
            if pos < 0:
                continue
            for i in range(pos, min(pos + 21, largo)):
                todos[i] += 1
                if r.get("is_efficient"):
                    eficientes[i] += 1
            if str(r.get("mismatches") or "").strip() in ("0", ""):
                if r.get("is_off_target"):
                    for i in range(pos, min(pos + 21, largo)):
                        banda[i] = True
        series.append((rec.get("query_name") or "query", todos, eficientes, banda, largo))

    if not series:
        _empty(ax, "Sin filas de siRNA para ubicar en el transcrito")
        ax.set_title("Perfil por posición")
        return _save(fig, path)

    nombre, todos, eficientes, banda, largo = series[0]
    for i, flag in enumerate(banda):
        if flag:
            ax.axvspan(i, i + 1, color="0.72", alpha=0.45, linewidth=0, zorder=1)

    ax.plot(range(largo), todos, color="#2b6cb0", linewidth=1.0, zorder=3,
            label="Todos los siRNAs")
    ax.plot(range(largo), eficientes, color=VERDE, linewidth=1.6, zorder=4,
            label="Eficientes (pasan los filtros)")

    ax.set_xlim(0, largo)
    ax.set_ylim(bottom=0)
    ax.set_xlabel(f"Posición sobre el transcrito ({nombre}, {largo} nt)")
    ax.set_ylabel("siRNAs por posición")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", color="#e3e8eb", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=6.8, loc="upper right")
    ax.set_title("Perfil por posición — dónde conviene cortar")
    # Marca la mejor zona: 40 nt con más eficientes y sin off-target perfecto
    mejor, mejor_val = None, 0
    ancho = 40
    for ini in range(0, max(1, largo - ancho), 5):
        if any(banda[ini:ini + ancho]):
            continue
        val = sum(eficientes[ini:ini + ancho])
        if val > mejor_val:
            mejor, mejor_val = ini, val
    if mejor is not None and mejor_val:
        ax.axvspan(mejor, mejor + ancho, color=AMBAR, alpha=0.18, linewidth=0, zorder=2)
        ax.annotate(f"mejor zona: {mejor + 1}-{mejor + ancho}",
                    xy=(mejor + ancho / 2, ax.get_ylim()[1] * 0.9),
                    ha="center", fontsize=7, color=AMBAR)
    return _save(fig, path)


def dispersion_especificidad_eficacia(candidates, path: str) -> str:
    """Dispersión eficiencia (E) × especificidad (S): el plano donde se elige una ventana.

    Arriba y a la derecha es lo bueno: muchos siRNAs eficientes y pocos off-targets. El punto
    de mejor score total queda marcado; la zona verde claro es la combinación deseable.
    """
    fig, ax = plt.subplots(figsize=(6.9, 3.4), constrained_layout=True)
    cands = [c for c in candidates if c.get("desglose")]
    if not cands:
        _empty(ax, "Sin candidatos puntuables")
        ax.set_title("Eficiencia contra especificidad")
        return _save(fig, path)

    # zona deseable
    ax.axvspan(0.66, 1.0, ymin=0.66, ymax=1.0, color=VERDE_CLARO, alpha=0.20,
               linewidth=0, zorder=0)
    colores = {"recomendado": VERDE, "revisar": AMBAR, "bajo": GRIS,
               "descartar": "#c53030"}
    grupos = {}
    for c in cands:
        grupos.setdefault(c.get("banda") or "revisar", []).append(c)
    orden = [b for b in ("recomendado", "revisar", "bajo", "descartar") if b in grupos]
    orden += [b for b in grupos if b not in orden]  # una banda nueva no puede quedar afuera
    for banda in orden:
        xs = [float(c["desglose"]["S"]["valor"]) for c in grupos[banda]]
        ys = [float(c["desglose"]["E"]["valor"]) for c in grupos[banda]]
        ax.scatter(xs, ys, s=16, color=colores.get(banda, GRIS), alpha=0.72,
                   linewidths=0, zorder=3, label=f"{banda} (n={len(xs)})")

    mejor = max(cands, key=lambda c: float(c.get("total") or 0))
    ax.scatter([float(mejor["desglose"]["S"]["valor"])],
               [float(mejor["desglose"]["E"]["valor"])],
               s=90, facecolors="none", edgecolors=TINTA, linewidths=1.2, zorder=4)
    ax.annotate(f"mejor score · {mejor.get('id')} · pos {mejor.get('pos')}",
                xy=(float(mejor["desglose"]["S"]["valor"]),
                    float(mejor["desglose"]["E"]["valor"])),
                xytext=(6, 6), textcoords="offset points", fontsize=7, color=TINTA)

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("Especificidad (eje S): 1 = sin off-targets")
    ax.set_ylabel("Eficiencia (eje E)")
    ax.grid(color="#e3e8eb", linewidth=0.6, zorder=1)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=6.8, loc="lower left")
    ax.set_title("Eficiencia contra especificidad — dónde está el compromiso")
    return _save(fig, path)


def perfil_por_gen(records, path: str, top: int = 5) -> str:
    """Perfil por posición para los genes más golpeados (todos vs eficientes).

    Equivale al «off target plot» del siFi original, pero con la estética del informe y sin
    la tabla: acá importa ver *dónde* pega cada gen, no cuántas filas suma.
    """
    from collections import Counter
    conteo: Counter = Counter()
    largo = 0
    for rec in records:
        largo = max(largo, int(rec.get("query_length") or 0))
        for r in rec.get("sirnas") or []:
            if r.get("hit_name"):
                conteo[str(r["hit_name"])] += 1
    if not conteo or not largo:
        fig, ax = plt.subplots(figsize=(6.9, 2.2), constrained_layout=True)
        _empty(ax, "Sin hits de off-target para desglosar")
        ax.set_title("Perfil por gen afectado")
        return _save(fig, path)

    elegidos = [h for h, _ in conteo.most_common(top)]
    filas_n = len(elegidos)
    fig, axes = plt.subplots(filas_n, 1, figsize=(6.9, 1.35 * filas_n + 0.5),
                             sharex=True, constrained_layout=True)
    if filas_n == 1:
        axes = [axes]

    for ax, hit in zip(axes, elegidos):
        todos = [0] * largo
        eff = [0] * largo
        for rec in records:
            for r in rec.get("sirnas") or []:
                if str(r.get("hit_name") or "") != hit:
                    continue
                pos = int(r.get("sirna_position") or 0) - 1
                if pos < 0:
                    continue
                for i in range(pos, min(pos + 21, largo)):
                    todos[i] += 1
                    if r.get("is_efficient"):
                        eff[i] += 1
        ax.fill_between(range(largo), todos, color="#2b6cb0", alpha=0.22, linewidth=0)
        ax.plot(range(largo), todos, color="#2b6cb0", linewidth=0.9)
        ax.plot(range(largo), eff, color=VERDE, linewidth=1.1)
        ax.set_xlim(0, largo)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("siRNAs", fontsize=7)
        ax.tick_params(labelsize=6.5)
        ax.grid(axis="y", color="#e3e8eb", linewidth=0.5)
        ax.set_axisbelow(True)
        ax.set_title(f"{hit} — {conteo[hit]} fila(s)", loc="left", fontsize=8)
    axes[-1].set_xlabel(f"Posición sobre el transcrito ({largo} nt)")
    fig.suptitle("Perfil por gen afectado (azul: todos · verde: eficientes)", fontsize=8.5)
    return _save(fig, path)


def figuras(runs, assets_dir: str) -> Dict[str, str]:
    """Genera las dos figuras y devuelve rutas relativas al out_dir."""
    os.makedirs(assets_dir, exist_ok=True)
    eff_path = os.path.join(assets_dir, "fig_eficiencia.png")
    panel_path = os.path.join(assets_dir, "fig_paneles.png")
    perfil_path = os.path.join(assets_dir, "fig_perfil.png")
    disp_path = os.path.join(assets_dir, "fig_dispersion.png")
    gen_path = os.path.join(assets_dir, "fig_por_gen.png")

    series = [(run.run_id, run.e_values) for run in runs]
    eficiencia_hist(series, eff_path)
    hits_por_panel(_merge_panels(runs), panel_path)
    perfil_posicion([rec for run in runs for rec in run.records], perfil_path)
    dispersion_especificidad_eficacia([c for run in runs for c in run.candidates], disp_path)
    perfil_por_gen([rec for run in runs for rec in run.records], gen_path)

    return {
        "eficiencia": "assets/fig_eficiencia.png",
        "paneles": "assets/fig_paneles.png",
        "perfil": "assets/fig_perfil.png",
        "dispersion": "assets/fig_dispersion.png",
        "por_gen": "assets/fig_por_gen.png",
        "eficiencia_path": eff_path,
        "paneles_path": panel_path,
        "perfil_path": perfil_path,
        "dispersion_path": disp_path,
        "por_gen_path": gen_path,
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
