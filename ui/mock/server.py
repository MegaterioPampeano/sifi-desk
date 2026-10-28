#!/usr/bin/env python3
"""Servidor de maqueta de siFi Desk (sólo biblioteca estándar).

Sirve el frontend estático de ``ui/`` y responde el mismo contrato HTTP que va a
exponer ``sifid`` (ver docs/STREAMS.md, frente ventana):

    GET  /health
    GET  /panels
    GET  /runs
    POST /runs                {query_path, panel_ids[], mode, mismatches, main_target}
    GET  /runs/{id}
    POST /runs/{id}/cancel
    GET  /runs/{id}/results

Extensión propia de la maqueta (no está en el contrato del servicio):

    POST /agent/chat          {mensaje, run_id?}  → respuesta del agente simulado

Los datos salen de ``ui/mock/data/mock_data.json``, generado por
``ui/mock/gen_data.py`` a partir de ``tests/data/results_fixture.json`` y del scoring
real del core. Acá no se calcula nada: la UI es una vista y esta maqueta imita al
servicio, no al motor científico.

    python3 ui/mock/server.py --port 8765

Sin dependencias, sin red, sin credenciales.
"""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import posixpath
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UI_ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA_PATH = os.environ.get("SIFI_MOCK_DATA") or os.path.join(HERE, "data", "mock_data.json.gz")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(HERE, "data", "mock_data.json")

with (gzip.open(DATA_PATH, "rt", encoding="utf-8") if DATA_PATH.endswith(".gz")
      else open(DATA_PATH, encoding="utf-8")) as _fh:
    DATA = json.load(_fh)

PANELES = DATA["paneles"]
PANELES_POR_ID = {p["id"]: p for p in PANELES}
GENES = DATA["genes"]
VARIANTES = DATA["variantes"]
NARRATIVA = DATA["narrativa"]

MAX_BODY = 8 * 1024 * 1024
RUN_RE = re.compile(r"^/runs/([0-9a-f]{6,32})(/(cancel|results))?$")


# --------------------------------------------------------------------------- #
# estado de las corridas (en memoria: la maqueta no persiste)
# --------------------------------------------------------------------------- #

class Run:
    def __init__(self, run_id: str, body: dict):
        self.id = run_id
        self.query_path = str(body.get("query_path") or "consulta.fa")
        self.panel_ids = [p for p in (body.get("panel_ids") or []) if p in PANELES_POR_ID]
        self.mode = body.get("mode") or "design"
        self.mismatches = int(body.get("mismatches", 2))
        self.main_target = body.get("main_target") or None
        self.status = "queued"
        self.progress = {"done": 0, "total": 1, "pct": 0}
        self.stage = "en cola"
        self.started_at = None
        self.finished_at = None
        self.error = None
        self.log = []
        self.result = None
        self.cancelado = threading.Event()
        self.variant_key = elegir_variante(self.panel_ids, self.query_path)
        self.genes = [r["query_name"] for r in VARIANTES[self.variant_key]["records"]]

    # -- vistas ----------------------------------------------------------- #
    def to_dict(self, con_log: bool = False) -> dict:
        d = {
            "id": self.id,
            "run_id": self.id,
            "status": self.status,
            "query_path": self.query_path,
            "panel_ids": self.panel_ids,
            "panels": [PANELES_POR_ID[p]["nombre"] for p in self.panel_ids],
            "mode": self.mode,
            "mismatches": self.mismatches,
            "main_target": self.main_target,
            "stage": self.stage,
            "progress": self.progress,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "n_genes": len(self.genes),
            "genes": self.genes,
        }
        if con_log:
            d["log"] = self.log[-200:]
        return d

    def add_log(self, texto: str) -> None:
        self.log.append({"t": _now_iso(), "linea": texto})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def elegir_variante(panel_ids: list, query_path: str) -> str:
    """Busca la variante más parecida a la elección del usuario.

    La maqueta pre-genera un conjunto curado de combinaciones de paneles (ver
    gen_data.py). Si la combinación pedida no está, se usa la que comparte más
    paneles y, en segundo término, la que menos sobra.
    """
    genes_sel = "all"
    pistas = (query_path or "").lower()
    for g in GENES:
        if g["id"].lower() in pistas:
            genes_sel = "only_" + g["id"]
            break
    pedidos = set(panel_ids)
    mejor, mejor_puntaje = None, None
    for key in VARIANTES:
        paneles_key, genes_key = key.split("|", 1)
        if genes_key != genes_sel:
            continue
        sel = set(paneles_key.split(","))
        comunes = len(sel & pedidos)
        sobran = len(sel - pedidos)
        faltan = len(pedidos - sel)
        puntaje = (comunes, -sobran, -faltan)
        if mejor_puntaje is None or puntaje > mejor_puntaje:
            mejor, mejor_puntaje = key, puntaje
    if mejor is None:
        mejor = ",".join(p["id"] for p in PANELES) + "|all"
    return mejor


RUNS = {}
RUNS_LOCK = threading.Lock()


def crear_corrida(body: dict) -> Run:
    run_id = os.urandom(8).hex()
    run = Run(run_id, body)
    with RUNS_LOCK:
        RUNS[run_id] = run
    hilo = threading.Thread(target=_simular, args=(run,), daemon=True)
    hilo.start()
    return run


ETAPAS_GEN = [
    ("validando la consulta", "Se normalizó {gen}: un registro, sin caracteres inválidos."),
    ("cortando ventanas", "{gen}: ventanas de {size} nt generadas."),
    ("plegando ARN (RNAplfold)", "{gen}: accesibilidad calculada con W=80, span=40, T=37,0 °C."),
    ("buscando off-target (bowtie -v {mm})", "{gen}: barrido contra {n_paneles} panel(es): {paneles}."),
    ("puntuando candidatos (scoring v2)", "{gen}: desglose E/R/S/T/D calculado."),
]


def _simular(run: Run) -> None:
    total = max(1, len(run.genes))
    run.status = "running"
    run.started_at = _now_iso()
    run.progress = {"done": 0, "total": total, "pct": 0}
    n_paneles = len(run.panel_ids) or len(PANELES)
    paneles_nombres = ", ".join(PANELES_POR_ID[p]["nombre"] for p in run.panel_ids) or "todos"
    cands = sum(len(r["candidates"]) for r in VARIANTES[run.variant_key]["records"])
    try:
        for gi, gen in enumerate(run.genes):
            for stage, plantilla in ETAPAS_GEN:
                if run.cancelado.is_set():
                    _cancelar(run)
                    return
                run.stage = "%s · %s" % (stage, gen)
                run.add_log(plantilla.format(
                    gen=gen, size=21, mm=run.mismatches, n_paneles=n_paneles,
                    paneles=paneles_nombres,
                ))
                time.sleep(0.42)
            run.progress = {
                "done": gi + 1,
                "total": total,
                "pct": round(100.0 * (gi + 1) / total),
            }
        if run.cancelado.is_set():
            _cancelar(run)
            return
        run.stage = "cerrando la corrida"
        run.add_log("Escribiendo el manifest con run_id=%s." % run.id)
        time.sleep(0.55)
        if run.cancelado.is_set():
            _cancelar(run)
            return
        run.result = construir_resultado(run)
        run.status = "done"
        run.stage = "terminada"
        run.finished_at = _now_iso()
        run.progress = {"done": total, "total": total, "pct": 100}
        run.add_log("Corrida terminada: %d candidato(s) en %d gen(es)." % (cands, len(run.genes)))
    except Exception as exc:  # pragma: no cover - sólo maqueta
        run.status = "error"
        run.error = str(exc)
        run.finished_at = _now_iso()
        run.add_log("Error: %s" % exc)


def _cancelar(run: Run) -> None:
    run.status = "cancelled"
    run.stage = "cancelada"
    run.finished_at = _now_iso()
    run.add_log("Cancelada por el usuario; se descartaron los artefactos parciales.")


def construir_resultado(run: Run) -> dict:
    base = json.loads(json.dumps(VARIANTES[run.variant_key]))
    base["run_id"] = run.id
    base["generated_at"] = run.finished_at or _now_iso()
    base["query"] = {"id": os.path.basename(run.query_path), "path": run.query_path}
    base["params"] = {
        "sirna_size": 21,
        "mismatches": run.mismatches,
        "mode": run.mode,
        "main_target": run.main_target,
        "rnaplfold": {"W": 80, "span": 40, "T": 37.0},
    }
    base["core"] = {"version": "0.1.0", "vendor_commit": "sifi21-port", "bowtie": "1.3.1", "viennarna": "2.7.2"}
    return base


# --------------------------------------------------------------------------- #
# agente simulado
# --------------------------------------------------------------------------- #

def _mejores(result: dict, n: int = 3) -> list:
    filas = []
    for rec in result["records"]:
        for c in rec["candidates"]:
            filas.append((c["total"], rec["query_name"], c))
    filas.sort(key=lambda x: (-x[0], x[1], x[2]["pos"]))
    return filas[:n]


def respuesta_agente(mensaje: str, run_id: str | None) -> dict:
    texto = (mensaje or "").lower()
    run = RUNS.get(run_id or "")
    result = run.result if run and run.result else VARIANTES["dalbulus_maidis,maiz|all"]
    genes = ", ".join(r["query_name"] for r in result["records"])
    mejores = _mejores(result)
    top = mejores[0] if mejores else None

    if any(k in texto for k in ("correr", "corrida", "lanzar", "empezar", "iniciar")):
        return {
            "texto": (
                "Podés lanzar la corrida desde el paso 4 del asistente. Para esta maqueta "
                "elegí los paneles y la secuencia y usá «Iniciar corrida»; el progreso se "
                "actualiza cada segundo contra GET /runs/{id}.\n\n"
                "Cuando termine te muestro el ranking y te ayudo a leer los off-target."
            ),
            "tools": [{"nombre": "sifi_panels", "args": {}, "resultado": "5 paneles disponibles"}],
            "sugerencias": ["¿Qué paneles elijo?", "¿Cómo leo el desglose E/R/S/T/D?"],
        }
    if any(k in texto for k in ("panel", "paneles", "base", "bases")):
        return {
            "texto": (
                "Hay %d paneles cargados. Para una primera pasada alcanza con el panel "
                "blanco (Dalbulus maidis) y maíz como no-blanco: es la combinación más "
                "informativa por minuto de cómputo. Sulcia suma ruido A+T y humano es "
                "control de especificidad; conviene agregarlos antes de sintetizar."
                % len(PANELES)
            ),
            "tools": [{"nombre": "sifi_list_panels", "args": {}, "resultado": "%d paneles" % len(PANELES)}],
            "sugerencias": ["¿Qué rol cumple cada panel?", "¿Por qué humano es control?"],
        }
    if "banda" in texto:
        return {
            "texto": (
                "Las bandas resumen el total en cuatro tramos operativos:\n\n"
                "· recomendado: total ≥ 75 y sin hits con 0-1 mismatch en paneles sensibles.\n"
                "· revisar: 55-75, o buen total con algún hit dudoso.\n"
                "· bajo: 35-55; sirve como respaldo si falla el resto.\n"
                "· descartar: < 35 o hit perfecto en no-blanco/control.\n\n"
                "La banda no reemplaza el desglose: dos candidatos con el mismo total pueden "
                "diferir en por qué llegaron ahí."
            ),
            "tools": [{"nombre": "sifi_score_bands", "args": {}, "resultado": "4 bandas"}],
            "sugerencias": ["¿Cuál es el mejor candidato?", "¿Qué candidatos tienen off-target?"],
        }
    if any(k in texto for k in ("off-target", "offtarget", "riesgo", "especificidad", "hit")):
        con_hits = [c for _, _, c in [(0, 0, c) for rec in result["records"] for c in rec["candidates"]] if c["n_hits"]]
        con_hits.sort(key=lambda c: c["desglose"]["R"]["valor"])
        if con_hits:
            peor = con_hits[0]
            return {
                "texto": (
                    "%d de %d candidatos tienen al menos un hit fuera del panel blanco. El más "
                    "comprometido es %s: R=%.2f, %d hit(s), banda «%s». Ojo: un hit con 0 o 1 "
                    "mismatch en maíz o humano no se compensa con eficiencia, aunque el total "
                    "siga alto.\n\nEsto es predicción in silico; la validación es en bioensayo."
                    % (len(con_hits), sum(len(r["candidates"]) for r in result["records"]),
                       peor["id"], peor["desglose"]["R"]["valor"], peor["n_hits"], peor["banda"])
                ),
                "tools": [{"nombre": "sifi_offtarget", "args": {"run_id": run_id}, "resultado": "%d con hits" % len(con_hits)}],
                "sugerencias": ["¿Cuál descartarías?", "¿Qué significa hit_perfecto?"],
            }
    if any(k in texto for k in ("score", "scoring", "desglose", "e/r/s", "puntaje", "ranking", "mejor", "candidato")):
        if top:
            _, gen, c = top
            return {
                "texto": (
                    "El score va de 0 a 100 y es la suma de cinco aportes: E eficiencia (40), "
                    "R riesgo (15, más alto = más seguro), S especificidad (15), T consenso con "
                    "siFi (15) y D calidad de diseño (15).\n\n"
                    "En esta corrida el mejor es %s (posición %d, %s), con %.1f puntos y banda "
                    "«%s». Su E es %.2f y su R es %.2f; los detalles están en el panel de "
                    "detalle al hacer clic en la fila."
                    % (c["id"], c["pos"], gen, c["total"], c["banda"],
                       c["desglose"]["E"]["valor"], c["desglose"]["R"]["valor"])
                ),
                "tools": [{"nombre": "sifi_score", "args": {"run_id": run_id}, "resultado": "mejor=%s" % c["id"]}],
                "sugerencias": ["¿Por qué R pesa 15?", "Mostrame los candidatos con riesgo alto"],
            }
        return {"texto": "Todavía no hay resultados para puntuar en esta corrida.", "tools": [], "sugerencias": []}
    if any(k in texto for k in ("informe", "reporte", "pdf", "exportar")):
        return {
            "texto": (
                "El informe se arma desde el manifest de la corrida (" + genes + "). En el "
                "producto final el botón «Exportar» llama a POST /reports y devuelve el PDF "
                "renderizado con WeasyPrint. En esta maqueta el botón está deshabilitado: el "
                "frente de reportes todavía no expone el endpoint."
            ),
            "tools": [{"nombre": "sifi_report", "args": {"run_id": run_id, "formato": "pdf"}, "resultado": "no disponible en la maqueta"}],
            "sugerencias": ["¿Qué secciones tendría el PDF?", "¿Qué límites hay que declarar?"],
        }
    if any(k in texto for k in ("secuencia", "gen", "genes", "fasta")):
        return {
            "texto": (
                "En esta corrida hay %d gen(es): %s. Podés pegar FASTA o una secuencia pelada "
                "en el paso 2; si pegás varias entradas, el motor las procesa por separado y "
                "el ranking muestra un selector de gen."
                % (len(result["records"]), genes)
            ),
            "tools": [{"nombre": "sifi_status", "args": {"run_id": run_id}, "resultado": "%d registros" % len(result["records"])}],
            "sugerencias": ["¿Cuántas ventanas genera un gen de 780 nt?"],
        }
    return {
        "texto": (
            "Puedo ayudarte con el diseño (sifi_design), los off-target (sifi_offtarget), "
            "el scoring, los paneles y el informe. Todo lo que digo sale del manifest de la "
            "corrida; no invento resultados y siempre cito el run_id. ¿Qué querés revisar?"
        ),
        "tools": [],
        "sugerencias": ["¿Cuál es el mejor candidato?", "¿Qué paneles tiene la corrida?"],
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "sifi-mock/0.1"

    def log_message(self, fmt, *args):  # silencio: la UI ya muestra el estado
        if os.environ.get("SIFI_MOCK_VERBOSE"):
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------- #
    def _json(self, code: int, payload) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, code: int, mensaje: str) -> None:
        self._json(code, {"error": mensaje, "status": code})

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("cuerpo demasiado grande")
        raw = self.rfile.read(n)
        if not raw.strip():
            return {}
        return json.loads(raw.decode("utf-8"))

    def _static(self, path: str) -> None:
        rel = urllib.parse.unquote(path.split("?", 1)[0])
        if rel in ("", "/"):
            rel = "/index.html"
        # normalización estricta: nada fuera de ui/
        rel = posixpath.normpath(rel)
        if rel.startswith("/..") or rel.startswith(".."):
            self._error(403, "ruta fuera de la raíz")
            return
        full = os.path.abspath(os.path.join(UI_ROOT, rel.lstrip("/")))
        if not full.startswith(UI_ROOT + os.sep) and full != UI_ROOT:
            self._error(403, "ruta fuera de la raíz")
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._error(404, "no existe %s" % rel)
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        elif full.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        with open(full, "rb") as fh:
            raw = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    # -- métodos ---------------------------------------------------------- #
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {
                "status": "ok",
                "servicio": "sifid-mock",
                "version": "0.1.0",
                "modo": "mock",
                "n_paneles": len(PANELES),
                "corridas": len(RUNS),
                "hora": _now_iso(),
            })
            return
        if path == "/panels":
            self._json(200, {"panels": PANELES})
            return
        if path == "/runs":
            with RUNS_LOCK:
                corridas = sorted(RUNS.values(), key=lambda r: r.started_at or "", reverse=True)
            self._json(200, {"runs": [r.to_dict() for r in corridas]})
            return
        if path == "/meta":
            self._json(200, {
                "schema": "sifi.results/1",
                "generado": DATA["generado"],
                "genes": DATA["genes"],
                "narrativa": NARRATIVA,
                "variantes": sorted(VARIANTES.keys()),
            })
            return
        m = RUN_RE.match(path)
        if m:
            run = RUNS.get(m.group(1))
            if not run:
                self._error(404, "corrida desconocida: %s" % m.group(1))
                return
            if m.group(3) == "results":
                if run.status != "done" or not run.result:
                    self._error(409, "la corrida está en estado %s" % run.status)
                    return
                self._json(200, run.result)
                return
            self._json(200, run.to_dict(con_log=True))
            return
        if path.startswith("/api/"):
            self._error(404, "endpoint desconocido")
            return
        self._static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._body()
        except Exception as exc:
            self._error(400, "JSON inválido: %s" % exc)
            return

        if path == "/runs":
            panel_ids = body.get("panel_ids") or []
            if not isinstance(panel_ids, list):
                self._error(422, "panel_ids debe ser una lista")
                return
            desconocidos = [p for p in panel_ids if p not in PANELES_POR_ID]
            if desconocidos:
                self._error(422, "paneles desconocidos: %s" % ", ".join(desconocidos))
                return
            if not panel_ids:
                self._error(422, "elegí al menos un panel")
                return
            try:
                mm = int(body.get("mismatches", 2))
            except (TypeError, ValueError):
                self._error(422, "mismatches debe ser un entero")
                return
            if not 0 <= mm <= 4:
                self._error(422, "mismatches fuera de rango (0..4)")
                return
            body["mismatches"] = mm
            run = crear_corrida(body)
            self._json(202, run.to_dict())
            return

        m = RUN_RE.match(path)
        if m and m.group(3) == "cancel":
            run = RUNS.get(m.group(1))
            if not run:
                self._error(404, "corrida desconocida")
                return
            if run.status in ("done", "error", "cancelled"):
                self._json(409, {"error": "la corrida ya terminó (%s)" % run.status, "run": run.to_dict()})
                return
            run.cancelado.set()
            self._json(202, run.to_dict())
            return

        if path == "/agent/chat":
            run_id = body.get("run_id")
            resp = respuesta_agente(body.get("mensaje") or body.get("message") or "", run_id)
            self._json(200, {
                "run_id": run_id,
                "respuesta": resp["texto"],
                "tools": resp["tools"],
                "sugerencias": resp.get("sugerencias", []),
                "agente": "sifi-agent (mock)",
            })
            return

        self._error(404, "endpoint desconocido")


def main() -> None:
    ap = argparse.ArgumentParser(description="Maqueta local de siFi Desk")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    # dos corridas históricas para que la lista no arranque vacía
    for paneles, mm, modo in (
        (["dalbulus_maidis", "maiz", "humano"], 2, "design"),
        (["dalbulus_maidis", "maiz"], 1, "offtarget"),
    ):
        run = Run(os.urandom(8).hex(), {"query_path": "ensayo_chicharrita.fa", "panel_ids": paneles,
                                        "mode": modo, "mismatches": mm})
        run.status = "done"
        run.stage = "terminada"
        run.started_at = _now_iso()
        run.finished_at = _now_iso()
        run.progress = {"done": max(1, len(run.genes)), "total": max(1, len(run.genes)), "pct": 100}
        run.add_log("Corrida histórica de ejemplo (%s, %d mismatch(es))." % (modo, mm))
        run.result = construir_resultado(run)
        RUNS[run.id] = run

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("siFi Desk — maqueta en http://%s:%d/  (Ctrl+C para cortar)" % (args.host, args.port))
    print("datos: %s" % DATA_PATH)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nchau")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
