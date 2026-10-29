"""``dossier``: figuras A–D para elegir un blanco de dsRNA (informe de 12 ventanas).

Cuatro figuras, cada una con su propia pregunta:

A. mapa de evidencia de expresión por tejido (matriz genes × tejidos)
B. especificidad: % de siRNAs de cada ventana que conservan la semilla contra cada panel
C. eficacia prevista (índice 0-100) con IC 95 % por bootstrap
D. priorización: evidencia funcional (x) contra índice de riesgo (y)

Todo se calcula acá, sin estado global: las cifras de B salen de blastn-short contra los
FASTA de los paneles registrados en el servicio (no de archivos sueltos en /tmp), y las de
C de las propiedades termodinámicas por siRNA (semilla, asimetría, accesibilidad).
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

VERDE = "#0d3b2e"
ORO = "#c8a24a"
GRIS = "#e8e5df"
TINTA = "#1d1d1b"
ROJO = "#b03a2e"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": "#8a8a8a", "axes.labelcolor": TINTA,
    "text.color": TINTA, "xtick.color": TINTA, "ytick.color": TINTA,
    "savefig.facecolor": "white",
})

# Tejidos del mapa A y evidencia cargada a mano (0 sin dato, 1 ortología, 2 dato directo).
TEJIDOS = ["Intestino", "Bacteriocito", "Ovario", "Glánd. salival", "Cuerpo entero"]
EVIDENCIA_BASE = {
    # inferencias documentadas en pulgón (ApGLNT1, ApAAT1) o en Drosophila: NO verificadas
    # en D. maidis. Se dibujan rayadas a propósito.
    "SNAT11": [0, 1, 0, 0, 2],
    "YLAT2": [0, 1, 0, 0, 2],
    "B0AT1": [0, 1, 0, 0, 2],
    "DMGLU": [1, 0, 0, 0, 2],
    "PAT": [1, 0, 0, 0, 2],
    "BicC": [0, 0, 1, 0, 2],
}

# Rúbrica de evidencia funcional (eje x de D). 0 sólo ortología … 4 bioensayo propio.
EVIDENCIA_FUNCIONAL = {
    "SNAT11": 1.5, "YLAT2": 1.4, "B0AT1": 1.2, "CAT": 1.0, "DMGLU": 1.2, "PAT": 1.0,
    "Sec23": 1.0, "Arf1": 1.0, "kkv": 2.0, "Mdr49": 0.6, "RpS13": 0.8, "BicC": 2.0,
}

ETIQUETAS = {
    "SNAT11": "SNAT11 (SLC38)", "YLAT2": "Y+L (SLC7)", "CAT": "CAT (SLC7)",
    "DMGLU": "DMGLU", "B0AT1": "b(0,+) (SLC7)", "PAT": "PAT (SLC36)",
    "Sec23": "Sec23", "Arf1": "Arf1", "kkv": "kkv (quitina sintasa)",
    "Mdr49": "Mdr49 (ABC)", "RpS13": "RpS13", "BicC": "BicC (KH, ovario)",
}


# --------------------------------------------------------------------------- datos

def cargar_ventanas(ruta: str) -> List[dict]:
    with open(ruta, encoding="utf-8") as fh:
        datos = json.load(fh)
    ventanas = datos["ventanas"] if isinstance(datos, dict) else datos
    for v in ventanas:
        if len(v.get("secuencia") or "") < 21:
            raise ValueError(f"la ventana {v.get('ventana')} no tiene secuencia utilizable")
    return ventanas


def _sirnas(seq: str, k: int = 21) -> List[str]:
    return [seq[i:i + k] for i in range(len(seq) - k + 1)]


def _complemento(seq: str) -> str:
    return seq.translate(str.maketrans("ACGTacgtNn", "TGCAtgcaNn"))[::-1]


def _escribir_consultas(ventanas: Sequence[dict], ruta: str, k: int = 21) -> List[str]:
    """FASTA con los siRNAs de cada ventana en los dos sentidos; devuelve los ids."""
    ids = []
    with open(ruta, "w", encoding="utf-8") as fh:
        for v in ventanas:
            for i, s in enumerate(_sirnas(v["secuencia"], k)):
                for sentido, sec in (("f", s), ("r", _complemento(s))):
                    qid = f"{v['ventana']}|{i}|{sentido}"
                    ids.append(qid)
                    fh.write(f">{qid}\n{sec}\n")
    return ids


def _clase(mm: int, largo: int, posiciones: Iterable[int], cubre_semilla: bool) -> int:
    """Clase de un hit: 3 exacto, 2 semilla tocada, 1 cobertura sin semilla, 0 resto."""
    posiciones = list(posiciones)
    if mm == 0 and largo == 21:
        return 3
    if largo == 21 and mm == 1:
        return 2 if posiciones and 2 <= posiciones[0] <= 8 else 1
    if largo == 21 and mm == 2:
        return 2 if any(2 <= p <= 8 for p in posiciones) else 0
    if mm == 0 and cubre_semilla:
        return 1
    if mm <= 1 and cubre_semilla:
        return 2
    return 0


def contar_semilla(ventanas: Sequence[dict], paneles: Dict[str, str], k: int = 21,
                   blastn: str = "blastn", hilos: int = 8,
                   tmpdir: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """% de siRNAs de cada ventana con la semilla tocada, por panel.

    ``paneles``: {nombre: ruta al FASTA del panel}. Regla de conteo: se toma el peor hit
    de cada siRNA en cada panel y se cuenta si llega a clase 2 (semilla, posiciones 2-8).
    """
    tmpdir = tmpdir or tempfile.mkdtemp(prefix="dossier_")
    consultas = os.path.join(tmpdir, "queries.fa")
    ids = _escribir_consultas(ventanas, consultas, k)
    ventana_de = {qid: v["ventana"] for qid, v in
                  ((f"{v['ventana']}|{i}|{s}", v) for v in ventanas
                   for i in range(len(v["secuencia"]) - k + 1) for s in ("f", "r"))}
    salida: Dict[str, Dict[str, int]] = {v["ventana"]: {} for v in ventanas}
    por_ventana = {v["ventana"]: len(_sirnas(v["secuencia"], k)) for v in ventanas}

    for nombre, fasta in paneles.items():
        crudo = os.path.join(tmpdir, f"hits_{nombre}.tsv")
        cmd = [blastn, "-task", "blastn-short", "-query", consultas, "-subject", fasta,
               "-word_size", "9", "-evalue", "10", "-dust", "no",
               "-max_target_seqs", "500", "-num_threads", str(hilos),
               "-outfmt", "6 qseqid length mismatch qstart qend qseq sseq"]
        with open(crudo, "w", encoding="utf-8") as fh:
            subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, check=True)
        peor: Dict[str, int] = {}
        with open(crudo, encoding="utf-8") as fh:
            for linea in fh:
                f = linea.rstrip("\n").split("\t")
                if len(f) < 7:
                    continue
                qid, largo, mm = f[0], int(f[1]), int(f[2])
                if largo < 19:
                    continue
                qs, qe, qseq, sseq = int(f[3]), int(f[4]), f[5].upper(), f[6].upper()
                pos = [qs + i for i, (a, b) in enumerate(zip(qseq, sseq))
                       if a != b and a != "-" and b != "-"]
                cubre = any(2 <= p <= 8 for p in range(qs, qe + 1))
                c = _clase(mm, largo, pos, cubre)
                if c > peor.get(qid, -1):
                    peor[qid] = c
        conteo: Dict[str, int] = {v["ventana"]: 0 for v in ventanas}
        for qid, c in peor.items():
            if c >= 2:
                conteo[ventana_de[qid]] += 1
        for vid, n in conteo.items():
            salida[vid][nombre] = 100.0 * n / por_ventana[vid]
    return salida


# ---------------------------------------------------------------- eficacia (índice C)

def _gc(seq: str) -> float:
    seq = seq.upper()
    return 100.0 * sum(1 for b in seq if b in "GC") / max(1, len(seq))


def _componentes(gc: float, seed_gc: float, asimetria: float, acceso: float,
                 homopolimero: int) -> float:
    gc_c = 100.0 if 40 <= gc <= 55 else (
        max(0.0, 100 - (40 - gc) * 9) if gc < 40 else max(0.0, 100 - (gc - 55) * 9))
    seed_c = max(0.0, 100 - abs(seed_gc - 50) * 3)
    asim_c = max(0.0, min(100.0, 50 + 25 * asimetria))
    acc_c = 100.0 * acceso
    return max(0.0, min(100.0, 0.30 * gc_c + 0.25 * seed_c + 0.25 * asim_c
                        + 0.20 * acc_c - (0 if homopolimero <= 5 else 25)))


def eficacia_ic(ventana: dict, n: int = 4000) -> Tuple[float, float, float]:
    """Media e IC 95 % (bootstrap) del índice de eficacia de la ventana."""
    termo = ventana.get("termo")
    if not termo or not os.path.isfile(termo):
        return (float("nan"),) * 3
    with open(termo, encoding="utf-8") as fh:
        datos = {x["id"]: x for x in json.load(fh)["ventanas"]}
    t = datos.get(ventana["ventana"])
    if not t:
        return (float("nan"),) * 3
    gc = float(ventana.get("gc") or _gc(ventana["secuencia"]))
    hom = int(ventana.get("homopolimero") or 0)
    filas = t["sirnas"]
    punto = _componentes(gc, t["seed_gc_medio"], t["asimetria_media"],
                         t["accesibilidad_media"], hom)
    rnd = random.Random(11)
    vals = []
    for _ in range(n):
        m = [filas[rnd.randrange(len(filas))] for _ in range(len(filas))]
        sg = sum(r["seed_gc"] for r in m) / len(m)
        a = sum(r["asimetria"] for r in m) / len(m)
        ac = sum(r["accesibilidad"] for r in m) / len(m)
        vals.append(_componentes(gc, sg, a, ac, hom))
    vals.sort()
    return punto, vals[int(0.025 * n)], vals[int(0.975 * n)]


# ------------------------------------------------------------------------ figuras

def _guardar(fig, ruta: str) -> str:
    fig.savefig(ruta, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return ruta


def fig_a(ventanas: Sequence[dict], ruta: str) -> str:
    genes = [v["gen"] for v in ventanas]
    ev = {g: list(EVIDENCIA_BASE.get(g, [0, 0, 0, 0, 2])) for g in genes}
    fig, ax = plt.subplots(figsize=(7.4, 3.6 + 0.3 * len(genes)), constrained_layout=True)
    for i, g in enumerate(genes):
        for j in range(len(TEJIDOS)):
            v = ev[g][j]
            if v == 0:
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor=GRIS, edgecolor="white", lw=1.4))
                ax.text(j + .5, i + .5, "—", ha="center", va="center", color="#9b9b9b", fontsize=9)
            elif v == 1:
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor="#f3e6c6", edgecolor="white",
                                       lw=1.4, hatch="////"))
                ax.text(j + .5, i + .5, "o", ha="center", va="center", color="#8a6a1f",
                        fontsize=8, weight="bold")
            else:
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor=VERDE, edgecolor="white", lw=1.4))
                ax.text(j + .5, i + .5, "●", ha="center", va="center", color="white", fontsize=9)
    ax.set_xlim(0, len(TEJIDOS)); ax.set_ylim(0, len(genes))
    ax.set_xticks(np.arange(len(TEJIDOS)) + .5); ax.set_xticklabels(TEJIDOS, fontsize=8.4)
    ax.set_yticks(np.arange(len(genes)) + .5)
    ax.set_yticklabels([ETIQUETAS.get(g, g) for g in genes], fontsize=8.6)
    ax.invert_yaxis()
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("A · Dónde hay evidencia de expresión", loc="left", fontsize=11,
                 color=VERDE, weight="bold", pad=10)
    ax.legend(handles=[Patch(facecolor=VERDE, label="dato directo"),
                       Patch(facecolor="#f3e6c6", hatch="////", label="inferencia por ortología"),
                       Patch(facecolor=GRIS, label="sin dato")],
              loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=3, frameon=False, fontsize=8)
    return _guardar(fig, ruta)


def fig_b(ventanas: Sequence[dict], conteo: Dict[str, Dict[str, int]], ruta: str) -> str:
    genes = [v["gen"] for v in ventanas]
    paneles = [p for p in ("maiz", "polinizador", "humano", "simbionte")
               if any(p in conteo.get(v["ventana"], {}) for v in ventanas)]
    corto = {"maiz": "Maíz", "polinizador": "Abeja", "humano": "Humano", "simbionte": "Sulcia"}
    M = np.array([[conteo.get(v["ventana"], {}).get(p, 0.0) for p in paneles] for v in ventanas],
                 dtype=float)
    fig, ax = plt.subplots(figsize=(6.6, 4.6), constrained_layout=True)
    im = ax.imshow(M, cmap="OrRd", vmin=0, vmax=max(2.0, float(M.max()) if M.size else 9),
                   aspect="auto")
    for i in range(len(genes)):
        for j in range(len(paneles)):
            v = M[i, j]
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7.6,
                    color="white" if v > 0.6 * im.norm.vmax else TINTA)
    ax.set_xticks(range(len(paneles)))
    ax.set_xticklabels([corto.get(p, p) for p in paneles], fontsize=8.4)
    ax.set_yticks(range(len(genes)))
    ax.set_yticklabels([ETIQUETAS.get(g, g) for g in genes], fontsize=8.6)
    ax.set_xticks(np.arange(-.5, len(paneles), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(genes), 1), minor=True)
    ax.grid(which="minor", color="white", lw=1.6); ax.tick_params(which="minor", length=0)
    ax.set_title("B · Carga off-target por panel (% de siRNAs con la semilla tocada)",
                 loc="left", fontsize=10.2, color=VERDE, weight="bold", pad=10)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("% de siRNAs de la ventana", fontsize=7.6); cb.ax.tick_params(labelsize=7)
    return _guardar(fig, ruta)


def fig_c(datos: Sequence[Tuple[str, float, float, float]], ruta: str) -> str:
    orden = sorted(datos, key=lambda d: (d[1] if d[1] == d[1] else -1))
    fig, ax = plt.subplots(figsize=(7.2, 4.4), constrained_layout=True)
    for i, (g, m, lo, hi) in enumerate(orden):
        if m != m:
            ax.text(50, i, "sin datos termodinámicos", fontsize=7.6, color=ROJO)
            continue
        col = VERDE if lo >= 70 else (ORO if lo >= 55 else ROJO)
        ax.plot([lo, hi], [i, i], color=col, lw=3, solid_capstyle="round", alpha=.85)
        ax.plot(m, i, "o", color=col, ms=6.5, zorder=3)
    ax.axvline(70, color=VERDE, ls="--", lw=1, alpha=.8)
    ax.axvline(55, color=ROJO, ls=":", lw=1, alpha=.8)
    ax.set_ylim(-0.8, len(orden) - 0.2)
    ax.legend(handles=[Line2D([0], [0], color=VERDE, ls="--", lw=1, label="umbral fuerte (70)"),
                       Line2D([0], [0], color=ROJO, ls=":", lw=1, label="mínimo aceptable (55)")],
              loc="lower right", frameon=False, fontsize=7.2)
    ax.set_yticks(range(len(orden)))
    ax.set_yticklabels([ETIQUETAS.get(g, g) for g, *_ in orden], fontsize=8.6)
    ax.set_xlim(48, 84)
    ax.set_xlabel("Eficacia prevista (media e IC 95 % bootstrap)", labelpad=14)
    ax.set_title("C · Eficacia prevista con su incertidumbre", loc="left", fontsize=10.6,
                 color=VERDE, weight="bold", pad=10)
    ax.grid(axis="x", color="#e5e2db", lw=.8); ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _guardar(fig, ruta)


def fig_d(datos: Sequence[Tuple[str, float, float, float]], ruta: str) -> str:
    """x: evidencia funcional 0-4; y: índice de riesgo (tejido + IC + off-target)."""
    fig, ax = plt.subplots(figsize=(7.6, 5.6), constrained_layout=True)
    ax.add_patch(Rectangle((0, 0), 2, 3.2, facecolor="#eef4ef", zorder=0))
    ax.add_patch(Rectangle((2, 0), 2.4, 3.2, facecolor="#e6f0e8", zorder=0))
    ax.add_patch(Rectangle((0, 3.2), 2, 3.0, facecolor="#fbf3e2", zorder=0))
    ax.add_patch(Rectangle((2, 3.2), 2.4, 3.0, facecolor="#f7e3dd", zorder=0))
    ax.text(0.07, 6.1, "interesante pero frágil", fontsize=8, color="#9a6b1f", style="italic", va="top")
    ax.text(4.33, 6.1, "prioridad baja", fontsize=8, color="#a4462f", style="italic", ha="right", va="top")
    ax.text(0.07, 0.12, "listo para ensayo", fontsize=8, color="#2f6b4f", style="italic", va="bottom")
    ax.text(4.33, 0.12, "sólido pero menor", fontsize=8, color="#2f6b4f", style="italic", ha="right", va="bottom")
    puntos = []
    for g, x, riesgo, _frac in datos:
        if riesgo != riesgo:
            continue
        col = VERDE if riesgo <= 3.2 else (ORO if riesgo <= 4.3 else ROJO)
        ax.scatter(x, riesgo, s=95, color=col, edgecolor="white", lw=1.2, zorder=3)
        puntos.append((g, x, riesgo))
    ax.set_xlim(0, 4.4); ax.set_ylim(0, 6.4)
    ax.set_xlabel("Calidad de la evidencia funcional (0 = sólo ortología, 4 = bioensayo propio)",
                  labelpad=12, fontsize=8.4)
    ax.set_ylabel("Índice de riesgo (tejido desconocido + amplitud del IC + off-target)",
                  labelpad=12, fontsize=8.4)
    ax.set_title("D · Priorización de candidatos", loc="left", fontsize=11, color=VERDE,
                 weight="bold", pad=10)
    ax.grid(color="white", lw=1.2); ax.set_axisbelow(False); ax.tick_params(labelsize=8)

    fig.canvas.draw(); r = fig.canvas.get_renderer()
    ocupados = [t.get_window_extent(r) for t in ax.texts]
    for g, x, y in sorted(puntos, key=lambda p: (p[1], p[2])):
        for dx, dy in [(7, 5), (7, -12), (-46, 5), (-46, -12), (7, 16), (7, -22)]:
            t = ax.annotate(ETIQUETAS.get(g, g), (x, y), xytext=(dx, dy),
                            textcoords="offset points", fontsize=7.6, zorder=4)
            bb = t.get_window_extent(r)
            if not any(bb.overlaps(o) for o in ocupados):
                ocupados.append(bb)
                break
            t.remove()
        else:
            ocupados.append(ax.annotate(ETIQUETAS.get(g, g), (x, y), xytext=(7, 5),
                                        textcoords="offset points", fontsize=7.6,
                                        zorder=4).get_window_extent(r))
    return _guardar(fig, ruta)


# -------------------------------------------------------------------------- build

def build(ventanas_json: str, paneles: Dict[str, str], out_dir: str, blastn: str = "blastn",
          hilos: int = 8, bootstrap: int = 4000) -> Dict[str, Any]:
    """Genera A, B, C y D y devuelve las rutas y los números que las respaldan."""
    os.makedirs(out_dir, exist_ok=True)
    ventanas = cargar_ventanas(ventanas_json)
    conteo = contar_semilla(ventanas, paneles, blastn=blastn, hilos=hilos)

    datos_c: List[Tuple[str, float, float, float]] = []
    for v in ventanas:
        m, lo, hi = eficacia_ic(v, n=bootstrap)
        datos_c.append((v["gen"], m, lo, hi))
    datos_d = []
    for (g, m, lo, hi), v in zip(datos_c, ventanas):
        semilla = max(conteo.get(v["ventana"], {}).values() or [0.0])
        riesgo = 1.0 + ((hi - lo) / 2 if lo == lo else 0.0) + semilla / 3
        datos_d.append((g, EVIDENCIA_FUNCIONAL.get(g, 0.0), riesgo, semilla))

    rutas = {
        "A": fig_a(ventanas, os.path.join(out_dir, "fig_A_evidencia.png")),
        "B": fig_b(ventanas, conteo, os.path.join(out_dir, "fig_B_especificidad.png")),
        "C": fig_c(datos_c, os.path.join(out_dir, "fig_C_eficacia.png")),
        "D": fig_d(datos_d, os.path.join(out_dir, "fig_D_priorizacion.png")),
    }
    resumen = {
        "ventanas": [v["ventana"] for v in ventanas],
        "paneles": list(paneles),
        "semilla_pct": conteo,
        "eficacia": {g: {"media": m, "ic95": [lo, hi]} for g, m, lo, hi in datos_c},
        "priorizacion": {g: {"evidencia": x, "riesgo": r, "semilla": s}
                         for g, x, r, s in datos_d},
        "figuras": rutas,
    }
    with open(os.path.join(out_dir, "dossier.json"), "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)
    return resumen


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Figuras A-D del dossier de blancos")
    ap.add_argument("ventanas", help="JSON con las ventanas (id, gen, secuencia, gc, termo)")
    ap.add_argument("out", help="directorio de salida")
    ap.add_argument("--panel", action="append", default=[],
                    metavar="NOMBRE=RUTA", help="panel a evaluar (repetible)")
    ap.add_argument("--blastn", default=shutil.which("blastn") or "blastn")
    ap.add_argument("--hilos", type=int, default=8)
    args = ap.parse_args(argv)
    paneles = {}
    for p in args.panel:
        nombre, _, ruta = p.partition("=")
        paneles[nombre] = ruta
    resumen = build(args.ventanas, paneles, args.out, blastn=args.blastn, hilos=args.hilos)
    print(json.dumps({k: v for k, v in resumen.items() if k != "semilla_pct"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------- PDF

LECTURA = {
    "A": ("Dónde hay evidencia de expresión",
          "Punto lleno: medición directa en D. maidis (sólo cuerpo entero, la TSA). "
          "Rayado: ortólogo descrito en ese tejido en otro insecto —hipótesis, no dato del "
          "vector—. Guión: no hay ni medición ni ortólogo caracterizado.",
          "La ortología no conserva el patrón de expresión y expresión no es esencialidad: "
          "esta figura no puede decir si el gen hace falta para vivir."),
    "B": ("Cuánto se parece la ventana a otros genomas",
          "Porcentaje de los 280 siRNAs de cada ventana que conservan la semilla (posiciones "
          "2-8) contra cada panel. Es la medida de riesgo off-target: cuanto más bajo, mejor.",
          "Mide parecido de secuencia, no silenciamiento: un hit de semilla no implica que "
          "el gen ajeno se apague, y no dice nada de dosis ni de entrega."),
    "C": ("Qué eficacia se espera y con cuánta incertidumbre",
          "Índice 0-100 (GC, GC de semilla, asimetría de extremos y accesibilidad) con IC 95 % "
          "por bootstrap sobre los 280 siRNAs de la ventana.",
          "Es una predicción termodinámica. No reemplaza el bioensayo: ninguna figura de este "
          "dossier mide mortalidad, desarrollo ni carga del simbionte."),
    "D": ("Qué candidato conviene mover primero",
          "Eje x: calidad de la evidencia funcional (0 sólo ortología, 4 bioensayo propio). "
          "Eje y: índice de riesgo (tejido desconocido + amplitud del IC + off-target).",
          "Ordena el trabajo, no decide: un punto en «listo para ensayo» sigue necesitando "
          "el ensayo. La rúbrica del eje x es juicio experto, no una medición."),
}


def to_pdf(resumen: Dict[str, Any], out_pdf: str, titulo: str = "Cuatro gráficos para elegir el blanco",
           subtitulo: str = "Transportadores de aminoácidos de Dalbulus maidis") -> str:
    """Arma el PDF del dossier: portada con la tabla de candidatos y una página por figura."""
    import base64
    from weasyprint import HTML

    figuras = resumen["figuras"]
    filas = []
    for v in resumen["ventanas"]:
        gen = next((g for g in resumen["eficacia"] if resumen["eficacia"][g] is not None
                    and v.startswith(g)), v.split("_")[0])
        ef = resumen["eficacia"].get(gen, {})
        sem = resumen["semilla_pct"].get(v, {})
        peor = max(sem.values()) if sem else 0.0
        filas.append((ETIQUETAS.get(gen, gen), v, peor, ef.get("media"),
                      ef.get("ic95", [None, None])))
    trs = "\n".join(
        f"<tr><td>{g}</td><td class='mono'>{w}</td>"
        f"<td class='num'>{p:.1f}</td>"
        f"<td class='num'>{('%.1f' % m) if m == m and m is not None else '—'}</td>"
        f"<td class='num'>{('%.1f–%.1f' % (lo, hi)) if lo == lo and lo is not None else '—'}</td></tr>"
        for g, w, p, m, (lo, hi) in filas)

    paginas = []
    for clave in ("A", "B", "C", "D"):
        tit, que, no = LECTURA[clave]
        with open(figuras[clave], "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        paginas.append(f"""
        <section class="fig">
          <div class="kicker">{clave}</div>
          <h2>{tit}</h2>
          <img src="data:image/png;base64,{b64}">
          <p class="cap"><b>Qué muestra.</b> {que}</p>
          <p class="cap"><b>Qué no permite concluir.</b> {no}</p>
        </section>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: A4; margin: 18mm 16mm; @bottom-center {{
        content: counter(page) " / " counter(pages); font-size: 8pt; color: #888; }} }}
      body {{ font-family: 'DejaVu Sans', sans-serif; color: {TINTA}; font-size: 9.5pt; }}
      h1 {{ font-size: 21pt; color: {VERDE}; margin: 0 0 4pt 0; line-height: 1.15; }}
      .sub {{ color: #555; font-size: 11pt; margin-bottom: 22pt; }}
      .fig {{ page-break-after: always; }}
      .kicker {{ font-size: 30pt; color: {ORO}; font-weight: bold; line-height: 1; }}
      h2 {{ font-size: 14pt; color: {VERDE}; margin: 2pt 0 10pt 0; }}
      img {{ width: 100%; margin: 6pt 0 10pt 0; }}
      .cap {{ font-size: 8.8pt; color: #333; margin: 3pt 0; text-align: justify; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 8.4pt; margin-top: 10pt; }}
      th {{ text-align: left; font-size: 7.4pt; text-transform: uppercase; letter-spacing: .04em;
            color: #666; border-bottom: 1px solid {VERDE}; padding: 4pt 3pt; }}
      td {{ padding: 3.2pt 3pt; border-bottom: .5pt solid #e3e0d8; }}
      td.num, th.num {{ text-align: right; }} .mono {{ font-family: 'DejaVu Sans Mono', monospace;
        font-size: 7.6pt; color: #555; }}
      .nota {{ font-size: 7.8pt; color: #666; margin-top: 12pt; text-align: justify;
               border-left: 2pt solid {ORO}; padding-left: 8pt; }}
    </style></head><body>
      <h1>{titulo}</h1><div class="sub">{subtitulo}</div>
      <p class="cap">Doce candidatos, cada uno con una ventana de 300 nt. Las cifras de B y C se
      calculan acá, sobre los paneles cargados en el servicio (maíz B73, abeja, humano y Sulcia),
      y no se copian de corridas anteriores.</p>
      <table><tr><th>Gen</th><th>Ventana</th><th class="num">Semilla %</th>
      <th class="num">Eficacia</th><th class="num">IC 95 %</th></tr>{trs}</table>
      <p class="nota">Semilla %: el peor panel de la ventana (cuántos de sus 280 siRNAs conservan
      las posiciones 2-8 en maíz, abeja, humano o Sulcia). Eficacia: índice 0-100 con IC 95 % por
      bootstrap sobre los 280 siRNAs. Ninguna de las cuatro figuras mide fenotipo.</p>
      {"".join(paginas)}
    </body></html>"""
    HTML(string=html).write_pdf(out_pdf)
    return out_pdf
